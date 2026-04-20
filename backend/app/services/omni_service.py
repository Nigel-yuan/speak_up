import asyncio
import json
import os
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from time import monotonic
from typing import Any, Literal, cast
from urllib.parse import quote

import websockets
from websockets.exceptions import ConnectionClosed

from app.schemas import LanguageOption, ScenarioType
from app.schemas import CoachPanelPatch, CoachPanelPatchDimension


@dataclass(frozen=True)
class OmniCoachUpdate:
    patch: CoachPanelPatch | None = None


OmniInsightCallback = Callable[[OmniCoachUpdate], Awaitable[None]]
ErrorCallback = Callable[[str], Awaitable[None]]
ProviderEventCallback = Callable[[str, dict[str, Any], dict[str, Any] | None], Awaitable[None]]

LANGUAGE_LABELS: dict[LanguageOption, str] = {
    "zh": "Chinese",
    "en": "English",
}

SCENARIO_LABELS: dict[ScenarioType, str] = {
    "host": "主持人串场或主讲控场",
    "guest-sharing": "嘉宾分享或主题演讲",
    "standup": "脱口秀或高密度表达",
}

OmniAnalysisScope = Literal["voice_content", "body_visual"]
OMNI_ACCOUNT_ACCESS_DENIED_MARKER = "access denied, please make sure your account is in good standing"
OMNI_INTERNAL_SERVICE_ERROR_MARKER = "internal service error"
OMNI_BODY_BUFFER_TOO_SMALL_MARKER = "buffer too small, or have no audio"


def is_omni_account_access_denied(message: str) -> bool:
    return OMNI_ACCOUNT_ACCESS_DENIED_MARKER in message.lower()


def is_omni_internal_service_error(message: str) -> bool:
    return OMNI_INTERNAL_SERVICE_ERROR_MARKER in message.lower()


def is_omni_body_buffer_too_small_error(message: str) -> bool:
    return OMNI_BODY_BUFFER_TOO_SMALL_MARKER in message.lower()


@dataclass
class AliyunOmniCoachConnection:
    session_id: str
    language: LanguageOption
    scenario_id: ScenarioType
    websocket: Any
    on_insight: OmniInsightCallback
    on_error: ErrorCallback
    on_event: ProviderEventCallback | None = None
    event_counter: int = 0
    finish_sent: bool = False
    finished: asyncio.Event = field(default_factory=asyncio.Event)
    reader_task: asyncio.Task[None] | None = field(default=None, repr=False)
    has_received_audio: bool = False
    completed_response_ids: set[str] = field(default_factory=set)
    last_patch_signature: str | None = None
    last_emitted_at: float = 0.0
    visual_request_in_flight: bool = False
    pending_visual_refresh: bool = False
    buffered_audio_payloads: list[tuple[float, str]] = field(default_factory=list)
    latest_image_base64: str | None = None


class AliyunOmniCoachService:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        url: str | None = None,
        enabled: bool | None = None,
        analysis_scope: OmniAnalysisScope = "voice_content",
        turn_mode: Literal["vad", "manual"] = "vad",
    ) -> None:
        self.api_key = api_key or os.getenv("DASHSCOPE_API_KEY")
        self.model = model or os.getenv("ALIYUN_OMNI_COACH_MODEL", "qwen3.5-omni-flash-realtime")
        self.url = url or os.getenv("ALIYUN_OMNI_COACH_URL", "wss://dashscope.aliyuncs.com/api-ws/v1/realtime")
        self.analysis_scope = analysis_scope
        self.turn_mode = turn_mode
        configured_enabled = os.getenv("ALIYUN_OMNI_COACH_ENABLED")
        if enabled is not None:
            self.enabled = enabled
        elif configured_enabled is not None:
            self.enabled = configured_enabled.lower() not in {"0", "false", "no"}
        else:
            self.enabled = bool(self.api_key)
        self.vad_threshold = float(os.getenv("ALIYUN_OMNI_COACH_VAD_THRESHOLD", "0.0"))
        self.vad_silence_duration_ms = max(
            250,
            min(4000, int(os.getenv("ALIYUN_OMNI_COACH_SILENCE_DURATION_MS", "2000"))),
        )
        self.body_audio_window_ms = max(
            200,
            min(2000, int(os.getenv("ALIYUN_OMNI_BODY_AUDIO_WINDOW_MS", "500"))),
        )
        self.body_audio_min_payloads = max(
            2,
            int(os.getenv("ALIYUN_OMNI_BODY_MIN_AUDIO_PAYLOADS", "3")),
        )
        self.connections: dict[str, AliyunOmniCoachConnection] = {}

    @property
    def is_configured(self) -> bool:
        return self.enabled and bool(self.api_key)

    async def connect_session(
        self,
        session_id: str,
        scenario_id: ScenarioType,
        language: LanguageOption,
        on_insight: OmniInsightCallback,
        on_error: ErrorCallback,
        on_event: ProviderEventCallback | None = None,
    ) -> None:
        if not self.is_configured:
            return

        existing = self.connections.get(session_id)
        if existing is not None:
            return

        websocket = await websockets.connect(
            self._build_url(),
            additional_headers={"Authorization": f"bearer {self.api_key}"},
            max_size=2**22,
        )

        created_event = await self._receive_json(websocket)
        await self._emit_provider_event(on_event, "session_created", created_event)
        if created_event.get("type") == "error":
            await websocket.close()
            raise RuntimeError(self._extract_error_message(created_event))
        if created_event.get("type") != "session.created":
            await websocket.close()
            raise RuntimeError("Omni coach 连接失败：未收到 session.created")

        connection = AliyunOmniCoachConnection(
            session_id=session_id,
            scenario_id=scenario_id,
            language=language,
            websocket=websocket,
            on_insight=on_insight,
            on_error=on_error,
            on_event=on_event,
        )
        self.connections[session_id] = connection

        await self._send_json(
            connection,
            {
                "type": "session.update",
                "session": {
                    "modalities": ["text"],
                    "input_audio_format": "pcm",
                    "instructions": self._build_instructions(scenario_id, language),
                    "turn_detection": (
                        {
                            "type": "server_vad",
                            "threshold": self.vad_threshold,
                            "silence_duration_ms": self.vad_silence_duration_ms,
                        }
                        if self.turn_mode == "vad"
                        else None
                    ),
                },
            },
        )

        updated_event = await self._receive_json(websocket)
        await self._emit_provider_event(on_event, "session_updated", updated_event)
        if updated_event.get("type") == "error":
            await self.close_session(session_id)
            raise RuntimeError(self._extract_error_message(updated_event))
        if updated_event.get("type") != "session.updated":
            await self.close_session(session_id)
            raise RuntimeError("Omni coach 连接失败：未收到 session.updated")

        connection.reader_task = asyncio.create_task(self._reader_loop(connection))

    async def send_audio_chunk(self, session_id: str, payload: str | None) -> None:
        connection = self.connections.get(session_id)
        if connection is None or connection.finish_sent or not payload:
            return
        if self.analysis_scope == "body_visual":
            connection.has_received_audio = True
            self._buffer_body_audio_payload(connection, payload.split(",", 1)[-1])
            return

        await self._send_json(
            connection,
            {
                "type": "input_audio_buffer.append",
                "audio": payload.split(",", 1)[-1],
            },
        )
        connection.has_received_audio = True

    async def send_video_frame(self, session_id: str, image_base64: str | None) -> None:
        connection = self.connections.get(session_id)
        if connection is None or connection.finish_sent or not image_base64:
            return
        if self.analysis_scope != "body_visual":
            return
        connection.latest_image_base64 = image_base64.split(",", 1)[-1]
        if self.turn_mode == "manual":
            await self._maybe_request_visual_refresh(connection)

    async def finish_session(self, session_id: str) -> None:
        await self.close_session(session_id)

    async def close_session(self, session_id: str) -> None:
        connection = self.connections.pop(session_id, None)
        if connection is None:
            return

        connection.finish_sent = True
        connection.finished.set()

        if connection.reader_task is not None and connection.reader_task is not asyncio.current_task():
            connection.reader_task.cancel()
            await asyncio.gather(connection.reader_task, return_exceptions=True)

        try:
            await connection.websocket.close()
        except Exception:
            return

    async def _append_image(self, connection: AliyunOmniCoachConnection, image_base64: str) -> None:
        await self._send_json(
            connection,
            {
                "type": "input_image_buffer.append",
                "image": image_base64,
            },
        )

    async def _reader_loop(self, connection: AliyunOmniCoachConnection) -> None:
        try:
            async for raw_message in connection.websocket:
                event = json.loads(raw_message)
                event_type = event.get("type")
                await self._emit_provider_event(
                    connection.on_event,
                    "message",
                    event,
                    {"eventType": event_type},
                )

                if event_type == "response.text.delta":
                    await self._emit_provider_event(
                        connection.on_event,
                        "text_delta",
                        event,
                        {"responseId": event.get("response_id")},
                    )
                    continue

                if event_type == "response.text.done":
                    response_id = str(event.get("response_id", ""))
                    text = str(event.get("text", "")).strip()
                    if response_id:
                        connection.completed_response_ids.add(response_id)
                    await self._emit_provider_event(
                        connection.on_event,
                        "text_done",
                        event,
                        {"responseId": response_id, "textPreview": text[:120]},
                    )
                    await self._emit_text_as_insight(connection, text)
                    if self.turn_mode == "manual":
                        connection.visual_request_in_flight = False
                        await self._flush_pending_visual_refresh(connection)
                    continue

                if event_type == "response.done":
                    response = event.get("response", {})
                    response_id = str(response.get("id", ""))
                    if response_id and response_id in connection.completed_response_ids:
                        connection.visual_request_in_flight = False
                        await self._flush_pending_visual_refresh(connection)
                        continue

                    fallback_text = self._extract_text_from_response_done(response)
                    if fallback_text:
                        await self._emit_provider_event(
                            connection.on_event,
                            "response_done_fallback",
                            event,
                            {"responseId": response_id, "textPreview": fallback_text[:120]},
                        )
                        await self._emit_text_as_insight(connection, fallback_text)
                    connection.visual_request_in_flight = False
                    await self._flush_pending_visual_refresh(connection)
                    continue

                if event_type == "error":
                    connection.visual_request_in_flight = False
                    message = self._extract_error_message(event)
                    await self._emit_provider_event(
                        connection.on_event,
                        "error",
                        event,
                        {"message": message},
                    )
                    await connection.on_error(message)
                    continue

                if event_type == "session.finished":
                    connection.finished.set()
                    await self._emit_provider_event(connection.on_event, "session_finished", event)
                    continue
        except ConnectionClosed as error:
            connection.finished.set()
            if not connection.finish_sent:
                await connection.on_error(self._format_connection_closed_error(error))
        except asyncio.CancelledError:
            raise
        except Exception as error:
            await connection.on_error(f"Omni coach 连接异常：{error}")
            connection.finished.set()
        finally:
            if self.connections.get(connection.session_id) is connection:
                self.connections.pop(connection.session_id, None)

    async def _emit_text_as_insight(self, connection: AliyunOmniCoachConnection, text: str) -> None:
        update = self._parse_live_update(connection, text)
        if update is None:
            return
        await connection.on_insight(update)

    def _parse_live_update(self, connection: AliyunOmniCoachConnection, text: str) -> OmniCoachUpdate | None:
        payload = self._extract_json_payload(text)
        if not payload:
            return None

        should_emit = payload.get("should_emit")
        if isinstance(should_emit, str):
            should_emit = should_emit.lower() == "true"
        if should_emit is False:
            return None

        patch = self._parse_panel_patch(payload)
        if patch is not None:
            if self._should_drop_patch_duplicate(connection, patch):
                return None

            now = monotonic()
            connection.last_patch_signature = self._build_patch_signature(patch)
            connection.last_emitted_at = now

            return OmniCoachUpdate(patch=patch)

    def _should_drop_patch_duplicate(
        self,
        connection: AliyunOmniCoachConnection,
        patch: CoachPanelPatch,
    ) -> bool:
        signature = self._build_patch_signature(patch)
        return connection.last_patch_signature == signature

    @staticmethod
    def _build_patch_signature(patch: CoachPanelPatch) -> str:
        normalized_dimensions = [
            {
                "id": dimension.id,
                "status": dimension.status,
                "headline": AliyunOmniCoachService._normalize_text(dimension.headline),
                "detail": AliyunOmniCoachService._normalize_text(dimension.detail),
            }
            for dimension in patch.dimensions
        ]
        return json.dumps(normalized_dimensions, sort_keys=True, ensure_ascii=False)

    @staticmethod
    def _normalize_text(text: str) -> str:
        return re.sub(r"[\s,.!?，。！？、…:：;；\"'“”‘’（）()\-\u3000]+", "", text).lower()

    @staticmethod
    def _extract_json_payload(text: str) -> dict[str, Any] | None:
        stripped = text.strip()
        if stripped.startswith("```"):
            stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
            stripped = re.sub(r"\s*```$", "", stripped)

        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                pass

        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or start >= end:
            return None

        try:
            return json.loads(stripped[start : end + 1])
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _parse_panel_patch(payload: dict[str, Any]) -> CoachPanelPatch | None:
        dimensions_raw = payload.get("dimensions", payload)
        if not isinstance(dimensions_raw, dict):
            return None

        allowed_statuses = {"doing_well", "stable", "adjust_now", "analyzing"}
        dimension_ids = ("body_expression", "voice_pacing", "content_expression")
        dimensions: list[CoachPanelPatchDimension] = []

        for dimension_id in dimension_ids:
            raw_dimension = dimensions_raw.get(dimension_id)
            if not isinstance(raw_dimension, dict):
                continue

            status = str(raw_dimension.get("status", "")).strip().lower()
            headline = str(raw_dimension.get("headline", "")).strip()
            detail = str(raw_dimension.get("detail", "")).strip()

            if status not in allowed_statuses or not headline or not detail:
                continue

            dimensions.append(
                CoachPanelPatchDimension(
                    id=cast(Any, dimension_id),
                    status=cast(Any, status),
                    headline=headline,
                    detail=detail,
                )
            )

        if not dimensions:
            return None

        return CoachPanelPatch(dimensions=dimensions)


    @staticmethod
    def _extract_text_from_response_done(response: dict[str, Any]) -> str:
        output = response.get("output", [])
        for item in output:
            content = item.get("content", [])
            for part in content:
                text = part.get("text") or part.get("transcript")
                if isinstance(text, str) and text.strip():
                    return text.strip()
        return ""

    def _build_instructions(self, scenario_id: ScenarioType, language: LanguageOption) -> str:
        if self.analysis_scope == "body_visual":
            return self._build_body_instructions(scenario_id, language)
        return self._build_voice_content_instructions(scenario_id, language)

    def _build_voice_content_instructions(self, scenario_id: ScenarioType, language: LanguageOption) -> str:
        scenario_label = SCENARIO_LABELS.get(scenario_id, "通用演讲训练")
        language_label = LANGUAGE_LABELS.get(language, "Chinese")
        example = (
            '{"should_emit":true,"dimensions":{"voice_pacing":{"status":"adjust_now","headline":"减少重复起句","detail":"这句直接说完，别重起。"},"content_expression":{"status":"stable","headline":"先讲结论","detail":"结论再往前放一点。"}}}'
            if language == "zh"
            else '{"should_emit":true,"dimensions":{"voice_pacing":{"status":"adjust_now","headline":"Stop restarting the line","detail":"Finish the sentence instead of restarting."},"content_expression":{"status":"stable","headline":"Lead with the point","detail":"Move the conclusion a little earlier."}}}'
        )

        return (
            "You are the AI Live Coach for Speak Up. "
            f"The rehearsal scenario is: {scenario_label}. "
            f"Output language must be {language_label}. "
            "You will receive streaming user audio from the same speaking session. "
            "Your job is not to answer the content as an assistant. Your job is to coach the speaker's live delivery. "
            "Use the most recent speaking turn to update only two fixed dimensions: "
            "voice_pacing and content_expression. "
            "Do not return body_expression. Body delivery is handled by a separate visual pass. "
            "Always evaluate and return both dimensions whenever should_emit=true, even if one dimension is only stable or analyzing right now. "
            "Prioritize what is audible right now, not an earlier issue from several seconds ago. "
            "First infer the current delivery mode from the latest turn before judging problems: for example excited or celebratory, confident and assertive, reflective or questioning, serious and low-energy, or neutral. "
            "Use that delivery mode as context for judging pacing, emphasis, fluency, and emotional energy. Do not output the mode itself. "
            "For voice_pacing, evaluate seven sub-areas in this order: articulation clarity, projection, pace, pause placement, emphasis, intonation or emotional energy, and fluency. "
            "For articulation clarity, look for blurred words, swallowed endings, unclear consonants or vowels, and sentences that become hard to follow when the speaker speeds up. "
            "For projection, look for sustained weak projection, a voice that feels too small for the room, or a voice that sounds pressed or overly tight. "
            "For pace, look for a clearly sustained too-fast run, a clearly dragging run, or a pace shift caused by tension. "
            "For pause placement, look for key lines with no pause space, sentences pushed through without breathing room, or pauses inserted in the wrong place. "
            "For emphasis, look for key words being buried, sentence endings collapsing, or every line carrying the same weight. "
            "For intonation or emotional energy, look for flat delivery, fading energy, or clear tension. "
            "For fluency, look for repeated start-overs, frequent self-correction, searching for words, or stalled half-sentences. "
            "Do not treat intentional emphasis repetition as a fluency problem when it clearly supports excitement, confidence, or a key point and the sentence still keeps moving forward. "
            "Examples that should usually stay neutral or positive rather than be flagged as a restart include: 'very very nice', '太棒了太棒了', '真的真的很好'. "
            "If the latest turn is clearly excited, celebratory, or emotionally lifted, stronger emphasis, faster local energy, and short emphasis repetition may be appropriate rather than a problem. "
            "If the latest turn is clearly reflective, serious, or emotionally lowered, a calmer, lower-energy tone may still be appropriate as long as the line stays clear and intentional. "
            "Only escalate to adjust_now when the issue is clearly sustained in the latest stretch, not from one isolated moment. "
            "Do not treat a reflective, tentative, or questioning tone by itself as a problem. "
            "For content_expression, evaluate seven sub-areas in this order: concision, filler or redundancy, repetition or circularity, structure, point clarity, support, and progression. "
            "For concision, look for sentences carrying too many ideas, extra explanation layers, or a point taking too long to land. "
            "For filler or redundancy, look for many filler words, repeated setup phrases, or weak sentence openings that add no value. "
            "For repetition or circularity, look for the same idea being restated without new progress. "
            "For structure, look for missing layers, weak transitions, or a section that feels like piling up information without order. "
            "For point clarity, look for too much background before the actual stance or conclusion. "
            "For support, look for a claim with no example, no support, or a weak example that does not hold the point up. "
            "For progression, look for a section that does not move the listener forward or does not close one point before starting the next. "
            "Do not judge factual correctness. Judge clarity, directness, and whether the listener can follow the progression. "
            "Be conservative. Only use adjust_now when there is clear evidence in the most recent turn or latest frames. If the evidence is weak, use stable or analyzing instead. "
            "Do not tell the speaker to sound stronger, louder, or more powerful unless there is clear sustained evidence of low energy or weak projection in the latest turn. "
            "Do not use vague judgments such as '表达略显犹豫', '更有力量一点', '节奏不太自然', or '内容不够自然'. "
            "Instead, name the concrete signal and give one immediate action. "
            "Bad: '表达略显犹豫'. Good: '这句有重复起头，直接把后半句说完'. "
            "Bad: '语气更有力量一点'. Good: '重点句尾别收掉，把最后几个字讲完整'. "
            "Bad: '内容有点绕'. Good: '先讲结论，再补原因'. "
            "Bad: treating 'very very nice' as a restart. Good: treat it as positive emphasis when the line is still moving forward. "
            "Do not mention more than one issue per dimension in the same update. "
            "Choose the issue that is most visible to the listener right now and most fixable in the next sentence. "
            "If the speaker is only mildly imperfect but still understandable, prefer stable over adjust_now. "
            "For each dimension, choose the single most important observation right now instead of listing multiple issues. "
            "Headlines should be action-oriented or signal-oriented, not abstract personality judgments. "
            "Details should sound like a UI coaching cue, not a commentary paragraph. "
            "A good detail should tell the speaker exactly what to do next, such as: lead with the point, cut one layer of setup, finish the line without restarting, leave a short pause after the key line, or land the last few words fully. "
            "Do not mention JSON, frames, images, audio chunks, or model behavior. "
            "Do not ask follow-up questions. "
            "Do not produce multiple bullets. "
            "Return JSON only with this schema: "
            '{"should_emit":boolean,"dimensions":{"voice_pacing":{"status":"doing_well|stable|adjust_now|analyzing","headline":"string","detail":"string"},"content_expression":{"status":"doing_well|stable|adjust_now|analyzing","headline":"string","detail":"string"}}}. '
            "If there is no meaningful new coaching update, return should_emit=false with an empty dimensions object. "
            "Keep every headline very short, ideally within 12 Chinese characters or 24 English characters. "
            "Keep every detail to one concise sentence, ideally within 20 Chinese characters or 40 English characters. "
            f"Example: {example}"
        )

    def _build_body_instructions(self, scenario_id: ScenarioType, language: LanguageOption) -> str:
        scenario_label = SCENARIO_LABELS.get(scenario_id, "通用演讲训练")
        language_label = LANGUAGE_LABELS.get(language, "Chinese")
        example = (
            '{"should_emit":true,"dimensions":{"body_expression":{"status":"adjust_now","headline":"先把手离开脸","detail":"手先回到脸外。"}}}'
            if language == "zh"
            else '{"should_emit":true,"dimensions":{"body_expression":{"status":"adjust_now","headline":"Move your hand away","detail":"Keep your hand off your face."}}}'
        )
        return (
            "You are the body-expression lane of Speak Up AI Live Coach. "
            f"The rehearsal scenario is: {scenario_label}. "
            f"Output language must be {language_label}. "
            "You will receive streaming image frames and nearby microphone audio from the same speaking session. "
            "Focus only on the visible body delivery right now. "
            "Update only one fixed dimension: body_expression. "
            "Do not return voice_pacing or content_expression. "
            "Always evaluate and return body_expression whenever a response is created, even if the result is only stable or analyzing. "
            "Do not use should_emit=false just because the scene is stable. "
            "Prioritize the latest visible issue or the latest visible improvement, not an earlier posture from several seconds ago. "
            "Before judging body_expression, first infer the likely delivery mode from the nearby audio and the line's intent: for example excited or celebratory, confident and assertive, reflective or questioning, serious and low-energy, or neutral. "
            "Judge the body relative to that mode, not against one neutral baseline. Do not output the mode itself. "
            "Evaluate body_expression through six sub-areas: framing, alignment, openness or tension, gesture naturalness, movement or space use, and facial or eye engagement when visible. "
            "For framing, check whether the speaker is fully in frame, cut off, off-center, too far, too close, head-only, upper-body, or full-body. "
            "For alignment, check head tilt, shoulder tilt, upper-body lean, torso drift, and whether the speaker looks visibly slanted. "
            "For openness or tension, check whether the upper body looks open and settled, or tight, lifted, collapsed, closed, or overly guarded. "
            "For gesture naturalness, check whether gestures are missing, too frequent, too fragmented, unsynced with the point, blocking the face, or frozen. "
            "Do not treat a brief upward hand, upward fist, or lifted emphasis gesture as a problem when it clearly matches a strong positive line, a celebratory beat, or a confident emphasis point. "
            "Only warn about a raised hand when it stays too high for too long, blocks the face, becomes repetitive, or feels disconnected from the spoken point. "
            "When the nearby audio is clearly excited, upbeat, or celebratory, a bigger gesture, brighter face, stronger lift, or brief emphatic motion can be a good match rather than a problem. "
            "When the nearby audio is clearly serious, reflective, or emotionally lowered, a calmer, smaller, or lower-energy body state can still be appropriate if it looks intentional, stable, and engaged rather than collapsed or withdrawn. "
            "For movement or space use, only judge this when the frame is wide enough. Look for random swaying, pacing without purpose, or useful movement that supports the delivery. "
            "For facial or eye engagement, only judge this when the face is clear enough. Look for long downward gaze, obvious screen-checking, visible tension, very flat expression, or clear audience connection. "
            "Also watch for immediate bad habits: hand on face, holding an object in front of the face, long head-down posture, persistent head tilt, and clearly drifting out of frame. "
            "If only the head is visible but the face is still clear enough, you may still judge face-blocking, hand-on-face, downward gaze, head tilt, facial tension, and eye engagement. "
            "Use analyzing only when both upper-body and face evidence are too weak to support a reliable judgment. "
            "Be conservative. Only use adjust_now when there is clear visible evidence right now. "
            "If the speaker is covering the face with a hand or object for a sustained moment, use adjust_now instead of analyzing. "
            "If the head stays tilted, the gaze stays down, or the speaker stays visibly off-center for a sustained moment, use adjust_now instead of analyzing. "
            "Do not use vague body advice such as '别乱比划', '肢体不自然', or '状态不太对'. "
            "Instead, name the concrete visible issue and one immediate action. "
            "Bad: '手放下别乱比划'. Good: '手先离开脸，动作收回胸前'. "
            "Bad: '站姿不自然'. Good: '身体偏左，先回到镜头中间'. "
            "Bad: '手举太高了，放下来' for one short celebratory fist that supports the line. Good: keep it neutral or positive unless the hand stays high, blocks the face, or distracts from the point. "
            "Do not comment on full-body movement if the frame only shows the head or upper body. "
            "Do not jump to a strong posture claim from one weak frame. Prefer analyzing when the evidence is partial. "
            "Choose the single most important visible body issue right now and give the shortest action that can be done immediately. "
            "Choose the single most important body observation right now. "
            "Headlines should be short and specific. Details should be one concrete coaching cue, not a general comment. "
            "Do not mention JSON, frames, images, audio chunks, or model behavior. "
            "Do not ask follow-up questions. "
            "Do not produce multiple bullets. "
            "Return JSON only with this schema: "
            '{"should_emit":boolean,"dimensions":{"body_expression":{"status":"doing_well|stable|adjust_now|analyzing","headline":"string","detail":"string"}}}. '
            "If there is no meaningful new coaching update, return should_emit=false with an empty dimensions object. "
            "Keep every headline very short, ideally within 12 Chinese characters or 24 English characters. "
            "Keep every detail to one concise sentence, ideally within 20 Chinese characters or 40 English characters. "
            f"Example: {example}"
        )

    async def _maybe_request_visual_refresh(self, connection: AliyunOmniCoachConnection) -> None:
        if self.turn_mode != "manual":
            return
        if connection.finish_sent:
            return
        if self.analysis_scope == "body_visual":
            if not connection.latest_image_base64:
                return
            if connection.visual_request_in_flight:
                connection.pending_visual_refresh = True
                return
            audio_payloads = self._collect_recent_body_audio_payloads(connection)
            if len(audio_payloads) < self.body_audio_min_payloads:
                return

            image_base64 = connection.latest_image_base64
            connection.latest_image_base64 = None
            connection.visual_request_in_flight = True
            connection.pending_visual_refresh = False
            for audio_payload in audio_payloads:
                await self._send_json(
                    connection,
                    {
                        "type": "input_audio_buffer.append",
                        "audio": audio_payload,
                    },
                )
            await self._append_image(connection, image_base64)
            await self._send_json(connection, {"type": "input_audio_buffer.commit"})
            await self._send_json(connection, {"type": "response.create"})
            return
        if not connection.has_received_audio:
            return
        if connection.visual_request_in_flight:
            connection.pending_visual_refresh = True
            return

        connection.visual_request_in_flight = True
        connection.pending_visual_refresh = False
        await self._send_json(connection, {"type": "input_audio_buffer.commit"})
        await self._send_json(connection, {"type": "response.create"})

    async def _flush_pending_visual_refresh(self, connection: AliyunOmniCoachConnection) -> None:
        if not connection.pending_visual_refresh or connection.finish_sent:
            return
        await self._maybe_request_visual_refresh(connection)

    def _buffer_body_audio_payload(self, connection: AliyunOmniCoachConnection, payload: str) -> None:
        now = monotonic()
        cutoff = now - self.body_audio_window_ms / 1000
        connection.buffered_audio_payloads = [
            (timestamp, buffered_payload)
            for timestamp, buffered_payload in connection.buffered_audio_payloads
            if timestamp >= cutoff
        ]
        connection.buffered_audio_payloads.append((now, payload))

    def _collect_recent_body_audio_payloads(self, connection: AliyunOmniCoachConnection) -> list[str]:
        cutoff = monotonic() - self.body_audio_window_ms / 1000
        connection.buffered_audio_payloads = [
            (timestamp, payload)
            for timestamp, payload in connection.buffered_audio_payloads
            if timestamp >= cutoff
        ]
        return [payload for _, payload in connection.buffered_audio_payloads]

    def _build_url(self) -> str:
        encoded_model = quote(self.model, safe="")
        separator = "&" if "?" in self.url else "?"
        return f"{self.url}{separator}model={encoded_model}"

    async def _send_json(self, connection: AliyunOmniCoachConnection, payload: dict[str, Any]) -> None:
        connection.event_counter += 1
        message = {
            "event_id": f"{connection.session_id}-{connection.event_counter}",
            **payload,
        }
        await connection.websocket.send(json.dumps(message))
        await self._emit_provider_event(
            connection.on_event,
            "client_send",
            message,
            {"type": payload.get("type")},
        )

    @staticmethod
    async def _receive_json(websocket: Any) -> dict[str, Any]:
        raw_message = await websocket.recv()
        return json.loads(raw_message)

    @staticmethod
    def _extract_error_message(payload: dict[str, Any]) -> str:
        error = payload.get("error", {})
        message = error.get("message")
        if isinstance(message, str) and message.strip():
            return message
        return "Omni coach 服务返回错误"

    @staticmethod
    def _format_connection_closed_error(error: ConnectionClosed) -> str:
        reason = (error.reason or "").strip()
        if reason:
            return reason
        return str(error)

    @staticmethod
    async def _emit_provider_event(
        callback: ProviderEventCallback | None,
        stage: str,
        payload: dict[str, Any],
        summary: dict[str, Any] | None = None,
    ) -> None:
        if callback is None:
            return
        await callback(stage, payload, summary)
