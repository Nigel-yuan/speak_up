import asyncio
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, UTC
from pathlib import Path
from time import monotonic
from uuid import uuid4

from fastapi import UploadFile, WebSocket

from app.schemas import (
    AckEvent,
    CoachPanelEvent,
    ClientMessage,
    ErrorEvent,
    InjectInsightRequest,
    InjectTranscriptRequest,
    LiveInsight,
    LiveInsightEvent,
    OmniDebugEvent,
    OmniDebugState,
    PongEvent,
    RealtimeSession,
    RealtimeStatusEvent,
    LanguageOption,
    ScenarioType,
    SessionStatus,
    TranscriptChunk,
    TranscriptFinalEvent,
    TranscriptPartialEvent,
)
from app.services.coach_panel_service import CoachPanelService
from app.services.debug_store import DebugStore
from app.services.omni_service import AliyunOmniCoachService, OmniCoachUpdate
from app.services.speech_analysis_service import SpeechAnalysisService
from app.services.stt_service import ProviderTranscriptResult, build_stt_service


@dataclass
class SessionRecord:
    session_id: str
    scenario_id: ScenarioType
    language: LanguageOption
    debug_enabled: bool = False
    status: SessionStatus = "created"
    transcript_count: int = 0
    insight_count: int = 0
    audio_chunk_count: int = 0
    video_frame_count: int = 0
    started_at_monotonic: float | None = None
    transcript_chunks: list[TranscriptChunk] = field(default_factory=list)
    omni_debug: OmniDebugState = field(
        default_factory=lambda: OmniDebugState(
            configured=False,
            connected=False,
            sessionUpdated=False,
        )
    )
    stream_task: asyncio.Task[None] | None = field(default=None, repr=False)
    sockets: list[WebSocket] = field(default_factory=list, repr=False)

    def to_schema(self) -> RealtimeSession:
        return RealtimeSession(
            sessionId=self.session_id,
            scenarioId=self.scenario_id,
            language=self.language,
            debugEnabled=self.debug_enabled,
            status=self.status,
            transcriptCount=self.transcript_count,
            insightCount=self.insight_count,
            audioChunkCount=self.audio_chunk_count,
            videoFrameCount=self.video_frame_count,
        )


class SessionManager:
    FILLER_TOKENS = {
        "zh": {"嗯", "啊", "额", "呃", "然后", "就是", "哦", "诶", "欸", "哎", "唉"},
        "en": {"um", "uh", "well", "so"},
    }

    def __init__(self) -> None:
        self.sessions: dict[str, SessionRecord] = {}
        self.stt_service = build_stt_service()
        self.omni_coach_service = AliyunOmniCoachService(analysis_scope="voice_content", turn_mode="vad")
        self.omni_body_service = AliyunOmniCoachService(analysis_scope="body_visual", turn_mode="manual")
        self.speech_analysis_service = SpeechAnalysisService()
        self.coach_panel_service = CoachPanelService()
        self.debug_store = DebugStore(Path(__file__).resolve().parents[2] / "debug")

    def create_session(self, scenario_id: ScenarioType, language: LanguageOption, debug_enabled: bool) -> SessionRecord:
        session_id = uuid4().hex
        session = SessionRecord(
            session_id=session_id,
            scenario_id=scenario_id,
            language=language,
            debug_enabled=debug_enabled,
        )
        session.omni_debug.configured = self.omni_coach_service.is_configured or self.omni_body_service.is_configured
        self.coach_panel_service.get_or_create_panel(session_id, language)
        self.sessions[session_id] = session
        if session.debug_enabled:
            self.debug_store.init_session(
                session_id,
                {
                    "sessionId": session_id,
                    "scenarioId": scenario_id,
                    "language": language,
                    "debugEnabled": debug_enabled,
                    "status": session.status,
                    "createdAt": datetime.now(UTC).isoformat(),
                },
            )
        return session

    def get_session(self, session_id: str) -> SessionRecord | None:
        return self.sessions.get(session_id)

    async def finish_session(self, session_id: str) -> SessionRecord | None:
        session = self.sessions.get(session_id)
        if session is None:
            return None

        try:
            await self.stt_service.finish_session(session_id)
        except Exception as error:
            await self._broadcast(session, ErrorEvent(message=f"结束实时转写时出错：{error}").model_dump())
            if session.debug_enabled:
                self.debug_store.append_event(
                    session_id,
                    {"type": "provider_finish_error", "provider": "aliyun-qwen-asr", "message": str(error)},
                )

        try:
            await self.omni_coach_service.finish_session(session_id)
        except Exception as error:
            if session.debug_enabled:
                self.debug_store.append_event(
                    session_id,
                    {"type": "provider_finish_error", "provider": "aliyun-omni-coach", "message": str(error)},
                )
        try:
            await self.omni_body_service.finish_session(session_id)
        except Exception as error:
            if session.debug_enabled:
                self.debug_store.append_event(
                    session_id,
                    {"type": "provider_finish_error", "provider": "aliyun-omni-body-coach", "message": str(error)},
                )

        session.status = "finished"
        session.stream_task = None
        self.speech_analysis_service.close_session(session_id)
        self.coach_panel_service.close_session(session_id)
        if session.debug_enabled:
            self.debug_store.append_event(session_id, {"type": "session_finished", "status": session.status})
        await self.broadcast_status(session)
        return session

    def get_replay(self, session_id: str) -> dict | None:
        session = self.sessions.get(session_id)
        if session is None:
            return None

        media_url = None
        media_type = None
        if session.debug_enabled:
            audio_dir = self.debug_store._session_dir(session_id) / "audio"
            for extension in ("webm", "wav", "mp3", "m4a", "ogg"):
                candidate = audio_dir / f"session_full.{extension}"
                if candidate.exists():
                    media_url = f"/api/session/{session_id}/media/audio"
                    media_type = "audio"
                    break

        return {
            "sessionId": session.session_id,
            "scenarioId": session.scenario_id,
            "language": session.language,
            "mediaUrl": media_url,
            "mediaType": media_type,
            "transcript": [chunk.model_dump() for chunk in session.transcript_chunks],
        }

    async def save_full_audio(
        self,
        session: SessionRecord,
        audio_file: UploadFile,
        reason: str,
        mime_type: str | None,
    ) -> tuple[str, int]:
        if not session.debug_enabled:
            return "", 0
        payload = await audio_file.read()
        return self.debug_store.save_full_audio(
            session.session_id,
            payload,
            mime_type or audio_file.content_type,
            reason,
        )

    async def connect(self, session: SessionRecord, websocket: WebSocket) -> None:
        await websocket.accept()
        session.sockets.append(websocket)
        await websocket.send_json(RealtimeStatusEvent(sessionId=session.session_id, status=session.status).model_dump())
        await websocket.send_json(
            CoachPanelEvent(
                coachPanel=self.coach_panel_service.get_or_create_panel(session.session_id, session.language)
            ).model_dump()
        )
        await websocket.send_json(OmniDebugEvent(omniDebug=session.omni_debug).model_dump())

    def disconnect(self, session: SessionRecord, websocket: WebSocket) -> None:
        if websocket in session.sockets:
            session.sockets.remove(websocket)
        if not session.sockets:
            session.stream_task = None
            self.speech_analysis_service.close_session(session.session_id)
            self.coach_panel_service.close_session(session.session_id)
            asyncio.create_task(self.stt_service.close_session(session.session_id))
            asyncio.create_task(self.omni_coach_service.close_session(session.session_id))
            asyncio.create_task(self.omni_body_service.close_session(session.session_id))

    @staticmethod
    def _is_debug_enabled(session: SessionRecord) -> bool:
        return session.debug_enabled

    def _build_provider_event_logger(
        self,
        session: SessionRecord,
        provider: str,
    ) -> Callable[[str, dict, dict | None], asyncio.Future | None]:
        async def log_event(stage: str, payload: dict, summary: dict | None = None) -> None:
            if not self._is_debug_enabled(session):
                return
            self.debug_store.append_provider_event(
                session.session_id,
                provider,
                stage,
                payload,
                summary,
            )

        return log_event

    def _build_omni_event_logger(
        self,
        session: SessionRecord,
        provider: str = "aliyun-omni-coach",
    ) -> Callable[[str, dict, dict | None], asyncio.Future | None]:
        async def log_event(stage: str, payload: dict, summary: dict | None = None) -> None:
            if self._is_debug_enabled(session):
                self.debug_store.append_provider_event(
                    session.session_id,
                    provider,
                    stage,
                    payload,
                    summary,
                )

            event_type = summary.get("eventType") if summary else None
            if stage == "session_created":
                session.omni_debug.connected = True
                session.omni_debug.lastError = None
            elif stage == "session_updated":
                session.omni_debug.connected = True
                session.omni_debug.sessionUpdated = True
                session.omni_debug.lastError = None
            elif stage in {"text_done", "response_done_fallback"}:
                session.omni_debug.responseCount += 1
                preview = summary.get("textPreview") if summary else None
                session.omni_debug.lastTextPreview = preview if isinstance(preview, str) else None
            elif stage == "error":
                message = summary.get("message") if summary else None
                session.omni_debug.lastError = message if isinstance(message, str) else "Omni coach 服务返回错误"
            elif stage == "session_finished":
                session.omni_debug.connected = False

            if event_type:
                session.omni_debug.lastEventType = str(event_type)
            session.omni_debug.lastStage = stage
            await self._broadcast(session, OmniDebugEvent(omniDebug=session.omni_debug).model_dump())

        return log_event

    async def handle_client_message(self, session: SessionRecord, message: ClientMessage, websocket: WebSocket) -> None:
        if self._is_debug_enabled(session):
            self.debug_store.append_event(
                session.session_id,
                {
                    "type": "client_message",
                    **message.model_dump(exclude={"payload", "image_base64"}),
                },
            )

        if message.type == "ping":
            await websocket.send_json(PongEvent().model_dump())
            return

        if message.type == "start_stream":
            if session.status == "streaming":
                await websocket.send_json(AckEvent(message="stream already started").model_dump())
                return

            try:
                await self.stt_service.connect_session(
                    session.session_id,
                    session.language,
                    on_partial=lambda text: self.broadcast_partial(session, text, source="aliyun-qwen-asr"),
                    on_final=lambda result: self._broadcast_provider_transcript(session, result),
                    on_error=lambda message: self._broadcast_provider_error(session, message),
                    on_event=self._build_provider_event_logger(session, "aliyun-qwen-asr"),
                )
            except Exception as error:
                await websocket.send_json(ErrorEvent(message=str(error)).model_dump())
                return

            try:
                await self.omni_coach_service.connect_session(
                    session.session_id,
                    session.scenario_id,
                    session.language,
                    on_insight=lambda update: self._broadcast_omni_update(session, update),
                    on_error=lambda message: self._record_omni_error(session, message),
                    on_event=self._build_omni_event_logger(session, "aliyun-omni-coach"),
                )
            except Exception as error:
                session.omni_debug.lastError = str(error)
                session.omni_debug.lastStage = "connect_error"
                await self._broadcast(session, OmniDebugEvent(omniDebug=session.omni_debug).model_dump())
                if self._is_debug_enabled(session):
                    self.debug_store.append_event(
                        session.session_id,
                        {
                            "type": "provider_connect_error",
                            "provider": "aliyun-omni-coach",
                            "message": str(error),
                        },
                    )
            try:
                await self.omni_body_service.connect_session(
                    session.session_id,
                    session.scenario_id,
                    session.language,
                    on_insight=lambda update: self._broadcast_omni_update(session, update),
                    on_error=lambda message: self._record_omni_error(session, message),
                    on_event=self._build_omni_event_logger(session, "aliyun-omni-body-coach"),
                )
            except Exception as error:
                session.omni_debug.lastError = str(error)
                session.omni_debug.lastStage = "connect_error"
                await self._broadcast(session, OmniDebugEvent(omniDebug=session.omni_debug).model_dump())
                if self._is_debug_enabled(session):
                    self.debug_store.append_event(
                        session.session_id,
                        {
                            "type": "provider_connect_error",
                            "provider": "aliyun-omni-body-coach",
                            "message": str(error),
                        },
                    )

            session.status = "streaming"
            session.started_at_monotonic = monotonic()
            await self.broadcast_status(session)
            return

        if message.type == "audio_chunk":
            session.audio_chunk_count += 1
            path = ""
            if self._is_debug_enabled(session):
                path = self.debug_store.save_audio_chunk(
                    session.session_id,
                    session.audio_chunk_count,
                    message.payload,
                    message.mime_type,
                )
            try:
                await self.stt_service.send_audio_chunk(session.session_id, message.payload)
            except Exception as error:
                await websocket.send_json(ErrorEvent(message=str(error)).model_dump())
                return

            try:
                await self.omni_coach_service.send_audio_chunk(session.session_id, message.payload)
            except Exception as error:
                await self._record_omni_error(session, f"发送音频到 Omni coach 失败：{error}")
            try:
                await self.omni_body_service.send_audio_chunk(session.session_id, message.payload)
            except Exception as error:
                await self._record_omni_error(session, f"发送音频到 Omni body coach 失败：{error}")

            if path:
                await websocket.send_json(AckEvent(message=f"audio chunk saved -> {path}").model_dump())
            return

        if message.type == "video_frame":
            session.video_frame_count += 1
            path = ""
            if self._is_debug_enabled(session):
                path = self.debug_store.save_video_frame(session.session_id, session.video_frame_count, message.image_base64)
            try:
                await self.omni_coach_service.send_video_frame(session.session_id, message.image_base64)
            except Exception as error:
                await self._record_omni_error(session, f"发送视频帧到 Omni coach 失败：{error}")
            try:
                await self.omni_body_service.send_video_frame(session.session_id, message.image_base64)
            except Exception as error:
                await self._record_omni_error(session, f"发送视频帧到 Omni body coach 失败：{error}")
            ack_message = f"video frame #{session.video_frame_count} received"
            if path:
                ack_message = f"{ack_message} -> {path}"
            await websocket.send_json(AckEvent(message=ack_message).model_dump())
            return

        if message.type == "inject_partial" and message.text:
            await self.broadcast_partial(session, message.text, source="websocket")
            return

        if message.type == "inject_transcript" and message.text and message.timestamp_label:
            chunk = TranscriptChunk(
                id=f"manual-transcript-{session.transcript_count + 1}",
                speaker="user",
                text=message.text,
                timestampLabel=message.timestamp_label,
                startMs=self._timestamp_label_to_ms(message.timestamp_label),
                endMs=self._timestamp_label_to_ms(message.timestamp_label) + 1000,
            )
            await self.broadcast_transcript(session, chunk, source="websocket")
            return

        if message.type == "inject_insight" and message.title and message.detail and message.tone:
            insight = LiveInsight(
                id=f"manual-insight-{session.insight_count + 1}",
                title=message.title,
                detail=message.detail,
                tone=message.tone,
                source="manual",
            )
            await self.broadcast_insight(session, insight, source="websocket")
            return

        await websocket.send_json(ErrorEvent(message="unsupported message type").model_dump())

    async def inject_transcript(self, session: SessionRecord, payload: InjectTranscriptRequest) -> None:
        chunk = TranscriptChunk(
            id=f"manual-transcript-{session.transcript_count + 1}",
            speaker=payload.speaker,
            text=payload.text,
            timestampLabel=payload.timestampLabel,
            startMs=self._timestamp_label_to_ms(payload.timestampLabel),
            endMs=self._timestamp_label_to_ms(payload.timestampLabel) + 1000,
        )
        await self.broadcast_transcript(session, chunk, source="rest")

    async def inject_insight(self, session: SessionRecord, payload: InjectInsightRequest) -> None:
        insight = LiveInsight(
            id=f"manual-insight-{session.insight_count + 1}",
            title=payload.title,
            detail=payload.detail,
            tone=payload.tone,
            source="manual",
        )
        await self.broadcast_insight(session, insight, source="rest")

    async def broadcast_status(self, session: SessionRecord) -> None:
        await self._broadcast(session, RealtimeStatusEvent(sessionId=session.session_id, status=session.status).model_dump())
        if self._is_debug_enabled(session):
            self.debug_store.append_event(session.session_id, {"type": "status_broadcast", "status": session.status})

    async def broadcast_partial(self, session: SessionRecord, text: str, source: str) -> None:
        await self._broadcast(session, TranscriptPartialEvent(text=text).model_dump())
        if self._is_debug_enabled(session):
            self.debug_store.append_event(
                session.session_id,
                {"type": "partial_broadcast", "source": source, "text": text},
            )

    async def broadcast_transcript(self, session: SessionRecord, chunk: TranscriptChunk, source: str) -> None:
        previous_chunk = session.transcript_chunks[-1] if session.transcript_chunks else None
        if previous_chunk and previous_chunk.speaker == chunk.speaker and self._is_filler_fragment(session.language, chunk.text):
            merged_chunk = self._merge_transcript_chunks(session.language, previous_chunk, chunk)
            session.transcript_chunks[-1] = merged_chunk
            await self._broadcast(session, TranscriptFinalEvent(chunk=merged_chunk, replacePrevious=True).model_dump())
            speech_update = self.speech_analysis_service.replace_last_chunk(
                session.session_id,
                session.language,
                merged_chunk,
            )
            coach_panel = self.coach_panel_service.update_from_speech(
                session.session_id,
                session.language,
                speech_update,
                merged_chunk.endMs,
            )
            if coach_panel is not None:
                await self._broadcast(session, CoachPanelEvent(coachPanel=coach_panel).model_dump())
            if self._is_debug_enabled(session):
                self.debug_store.save_transcript_merge(
                    session.session_id,
                    previous_chunk,
                    chunk,
                    merged_chunk,
                    ["filler_tail"],
                    source,
                )
            return

        session.transcript_count += 1
        session.transcript_chunks.append(chunk)
        await self._broadcast(session, TranscriptFinalEvent(chunk=chunk).model_dump())
        speech_update = self.speech_analysis_service.ingest_chunk(session.session_id, session.language, chunk)
        coach_panel = self.coach_panel_service.update_from_speech(
            session.session_id,
            session.language,
            speech_update,
            chunk.endMs,
        )
        if coach_panel is not None:
            await self._broadcast(session, CoachPanelEvent(coachPanel=coach_panel).model_dump())
        if self._is_debug_enabled(session):
            self.debug_store.save_transcript_injection(session.session_id, chunk, source)

    async def broadcast_insight(self, session: SessionRecord, insight: LiveInsight, source: str) -> None:
        session.insight_count += 1
        await self._broadcast(session, LiveInsightEvent(insight=insight).model_dump())
        if self._is_debug_enabled(session):
            self.debug_store.save_insight_injection(session.session_id, insight, source)

    async def _broadcast_provider_transcript(self, session: SessionRecord, result: ProviderTranscriptResult) -> None:
        start_ms = result.start_ms if result.start_ms is not None else self._build_elapsed_ms(session)
        end_ms = result.end_ms if result.end_ms is not None else start_ms
        if end_ms < start_ms:
            end_ms = start_ms
        if end_ms == start_ms:
            end_ms = start_ms + 1
        chunk = TranscriptChunk(
            id=f"realtime-transcript-{session.transcript_count + 1}",
            speaker="user",
            text=result.text,
            timestampLabel=self._format_timestamp_label(start_ms),
            startMs=start_ms,
            endMs=end_ms,
        )
        await self.broadcast_transcript(session, chunk, source="aliyun-qwen-asr")

    async def _broadcast_provider_error(self, session: SessionRecord, message: str) -> None:
        await self._broadcast(session, ErrorEvent(message=message).model_dump())
        if self._is_debug_enabled(session):
            self.debug_store.append_event(
                session.session_id,
                {"type": "provider_error", "provider": "aliyun-qwen-asr", "message": message},
            )

    async def _broadcast_omni_update(self, session: SessionRecord, update: OmniCoachUpdate) -> None:
        updated_at_ms = self._build_elapsed_ms(session)

        if update.patch is not None:
            coach_panel = self.coach_panel_service.update_from_omni_patch(
                session.session_id,
                session.language,
                update.patch,
                updated_at_ms,
            )
            if coach_panel is not None:
                await self._broadcast(session, CoachPanelEvent(coachPanel=coach_panel).model_dump())

        insight = update.insight
        if insight is None and update.patch is not None:
            insight = self.coach_panel_service.build_debug_insight_from_patch(
                update.patch,
                insight_id=f"omni-{session.session_id}-{updated_at_ms}",
            )

        if insight is None:
            return

        session.omni_debug.insightCount += 1
        session.omni_debug.lastInsightTitle = insight.title
        session.omni_debug.lastError = None
        session.omni_debug.lastStage = "insight_emitted"
        await self._broadcast(session, OmniDebugEvent(omniDebug=session.omni_debug).model_dump())
        await self.broadcast_insight(session, insight, source="omni-coach")

    async def _record_omni_error(self, session: SessionRecord, message: str) -> None:
        session.omni_debug.lastError = message
        session.omni_debug.lastStage = "runtime_error"
        await self._broadcast(session, OmniDebugEvent(omniDebug=session.omni_debug).model_dump())
        if self._is_debug_enabled(session):
            self.debug_store.append_event(
                session.session_id,
                {"type": "provider_error", "provider": "aliyun-omni-coach", "message": message},
            )

    async def _broadcast(self, session: SessionRecord, payload: dict) -> None:
        stale: list[WebSocket] = []
        for socket in session.sockets:
            try:
                await socket.send_json(payload)
            except RuntimeError:
                stale.append(socket)

        for socket in stale:
            self.disconnect(session, socket)

    @staticmethod
    def _format_timestamp_label(elapsed_ms: int) -> str:
        total_seconds = max(elapsed_ms // 1000, 0)
        minutes, seconds = divmod(total_seconds, 60)
        return f"{minutes:02d}:{seconds:02d}"

    @staticmethod
    def _build_elapsed_ms(session: SessionRecord) -> int:
        if session.started_at_monotonic is None:
            return 0

        return max(int((monotonic() - session.started_at_monotonic) * 1000), 0)

    def _merge_transcript_chunks(
        self,
        language: LanguageOption,
        previous_chunk: TranscriptChunk,
        current_chunk: TranscriptChunk,
    ) -> TranscriptChunk:
        return TranscriptChunk(
            id=previous_chunk.id,
            speaker=previous_chunk.speaker,
            text=self._append_filler_fragment(language, previous_chunk.text, current_chunk.text),
            timestampLabel=previous_chunk.timestampLabel,
            startMs=previous_chunk.startMs,
            endMs=max(previous_chunk.endMs, current_chunk.endMs),
        )

    def _append_filler_fragment(self, language: LanguageOption, previous_text: str, current_text: str) -> str:
        left = previous_text.rstrip()
        right = current_text.strip()

        if not left:
            return right
        if not right:
            return left

        if language == "zh":
            return f"{left}{right}"
        if re.search(r"[A-Za-z0-9]$", left) and re.match(r"^[A-Za-z0-9]", right):
            return f"{left} {right}"
        return f"{left}{right}"

    def _is_filler_fragment(self, language: LanguageOption, text: str) -> bool:
        normalized = re.sub(r"[\s,.!?，。！？、…:：;；\"'“”‘’（）()\-\u3000]+", "", text).lower()
        return normalized in self.FILLER_TOKENS[language]

    @staticmethod
    def _timestamp_label_to_ms(timestamp_label: str) -> int:
        try:
            minutes_text, seconds_text = timestamp_label.split(":", maxsplit=1)
            return (int(minutes_text) * 60 + int(seconds_text)) * 1000
        except ValueError:
            return 0


session_manager = SessionManager()
