import asyncio
import base64
import json
import os
import wave
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

import websockets
from websockets.exceptions import ConnectionClosed

from app.schemas import LanguageOption, ScenarioType
from app.services.voice_profile_service import VoiceProfileConfig


QAProviderEventCallback = Callable[[str, dict[str, Any], dict[str, Any] | None], Awaitable[None]]
QAErrorCallback = Callable[[str], Awaitable[None]]


@dataclass
class AliyunQAOmniConnection:
    session_id: str
    scenario_id: ScenarioType
    language: LanguageOption
    profile: VoiceProfileConfig
    websocket: Any
    on_event: QAProviderEventCallback
    on_error: QAErrorCallback
    event_counter: int = 0
    finish_sent: bool = False
    finished: asyncio.Event = field(default_factory=asyncio.Event)
    reader_task: asyncio.Task[None] | None = field(default=None, repr=False)
    assistant_turn_count: int = 0
    current_turn_id: str | None = None
    current_response_id: str | None = None
    current_transcript: str = ""
    current_audio_chunks: list[bytes] = field(default_factory=list)
    audio_stream_started: bool = False
    has_pending_user_audio: bool = False
    session_update_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    pending_session_update: asyncio.Future[dict[str, Any]] | None = field(default=None, repr=False)


class AliyunQAOmniRealtimeService:
    SAMPLE_RATE = 24000

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        url: str | None = None,
        output_root: str | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("DASHSCOPE_API_KEY")
        self.model = model or os.getenv("ALIYUN_QA_OMNI_MODEL", "qwen3.5-omni-plus-realtime")
        self.url = url or os.getenv("ALIYUN_QA_OMNI_URL", "wss://dashscope.aliyuncs.com/api-ws/v1/realtime")
        self.output_root = Path(output_root or os.getenv("QA_AUDIO_OUTPUT_ROOT", "output/qa_audio"))
        self.vad_threshold = float(os.getenv("ALIYUN_QA_OMNI_VAD_THRESHOLD", "0.4"))
        self.max_tokens = max(128, int(os.getenv("ALIYUN_QA_OMNI_MAX_TOKENS", "512")))
        self.temperature = max(0.0, min(1.5, float(os.getenv("ALIYUN_QA_OMNI_TEMPERATURE", "0.6"))))
        self.bootstrap_silence_ms = max(80, min(800, int(os.getenv("ALIYUN_QA_OMNI_BOOTSTRAP_SILENCE_MS", "240"))))
        self.connections: dict[str, AliyunQAOmniConnection] = {}

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def is_connected(self, session_id: str) -> bool:
        return session_id in self.connections

    def has_pending_user_audio(self, session_id: str) -> bool:
        connection = self.connections.get(session_id)
        return bool(connection and connection.has_pending_user_audio)

    async def connect_session(
        self,
        *,
        session_id: str,
        scenario_id: ScenarioType,
        language: LanguageOption,
        instructions: str,
        profile: VoiceProfileConfig,
        on_event: QAProviderEventCallback,
        on_error: QAErrorCallback,
    ) -> None:
        if not self.is_configured:
            raise RuntimeError("QA Omni Realtime 未配置")

        existing = self.connections.get(session_id)
        if existing is not None:
            return

        websocket = await websockets.connect(
            self._build_url(),
            additional_headers={"Authorization": f"bearer {self.api_key}"},
            max_size=2**22,
        )

        created_event = await self._receive_json(websocket)
        if created_event.get("type") == "error":
            await websocket.close()
            raise RuntimeError(self._extract_error_message(created_event))
        if created_event.get("type") != "session.created":
            await websocket.close()
            raise RuntimeError("QA Omni Realtime 连接失败：未收到 session.created")

        connection = AliyunQAOmniConnection(
            session_id=session_id,
            scenario_id=scenario_id,
            language=language,
            profile=profile,
            websocket=websocket,
            on_event=on_event,
            on_error=on_error,
        )
        self.connections[session_id] = connection

        connection.reader_task = asyncio.create_task(self._reader_loop(connection))
        await self._send_session_update(connection, instructions=instructions, profile=profile)

    async def update_session(
        self,
        *,
        session_id: str,
        instructions: str,
        profile: VoiceProfileConfig,
        wait_for_ack: bool = True,
    ) -> None:
        connection = self.connections.get(session_id)
        if connection is None or connection.finish_sent:
            return
        connection.profile = profile
        await self._send_session_update(
            connection,
            instructions=instructions,
            profile=profile,
            wait_for_ack=wait_for_ack,
        )

    async def send_audio_chunk(self, session_id: str, payload: str | None) -> None:
        connection = self.connections.get(session_id)
        if connection is None or connection.finish_sent or not payload:
            return

        await self._send_json(
            connection,
            {
                "type": "input_audio_buffer.append",
                "audio": payload.split(",", 1)[-1],
            },
        )
        connection.has_pending_user_audio = True

    async def bootstrap_first_question(self, session_id: str) -> bool:
        connection = self.connections.get(session_id)
        if connection is None or connection.finish_sent:
            return False

        return await self.commit_silent_user_turn(session_id)

    async def commit_silent_user_turn(self, session_id: str) -> bool:
        connection = self.connections.get(session_id)
        if connection is None or connection.finish_sent:
            return False

        await self._send_json(
            connection,
            {
                "type": "input_audio_buffer.append",
                "audio": self._build_silence_audio_payload(self.bootstrap_silence_ms),
            },
        )
        connection.has_pending_user_audio = True
        return await self.commit_user_turn(session_id)

    async def clear_input_audio_buffer(self, session_id: str) -> None:
        connection = self.connections.get(session_id)
        if connection is None or connection.finish_sent:
            return

        await self._send_json(connection, {"type": "input_audio_buffer.clear"})
        connection.has_pending_user_audio = False

    async def commit_user_turn(self, session_id: str) -> bool:
        connection = self.connections.get(session_id)
        if connection is None or connection.finish_sent or not connection.has_pending_user_audio:
            return False

        await self._send_json(connection, {"type": "input_audio_buffer.commit"})
        await self._send_json(connection, {"type": "response.create"})
        connection.has_pending_user_audio = False
        return True

    async def cancel_response(self, session_id: str) -> bool:
        connection = self.connections.get(session_id)
        if connection is None or connection.finish_sent or not connection.current_response_id:
            return False

        await self._send_json(connection, {"type": "response.cancel"})
        return True

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

    def build_audio_url(self, session_id: str, turn_id: str) -> str:
        return f"/api/session/{quote(session_id)}/qa/turns/{quote(turn_id)}/audio"

    def get_audio_path(self, session_id: str, turn_id: str) -> Path:
        return self.output_root / session_id / f"{turn_id}.wav"

    async def _send_session_update(
        self,
        connection: AliyunQAOmniConnection,
        *,
        instructions: str,
        profile: VoiceProfileConfig,
        wait_for_ack: bool = True,
    ) -> None:
        async with connection.session_update_lock:
            pending = connection.pending_session_update
            if pending is not None and not pending.done():
                if not wait_for_ack:
                    return
                await pending

            connection.pending_session_update = asyncio.get_running_loop().create_future()
            current_pending = connection.pending_session_update
            await self._send_json(
                connection,
                {
                    "type": "session.update",
                    "session": {
                        "modalities": ["text", "audio"],
                        "voice": profile.omni_voice_id,
                        "input_audio_format": "pcm",
                        "sample_rate": 16000,
                        "output_audio_format": "pcm",
                        "instructions": instructions,
                        "turn_detection": None,
                        "max_tokens": self.max_tokens,
                        "temperature": self.temperature,
                    },
                },
            )
            if not wait_for_ack:
                await self._emit_provider_event(
                    connection.on_event,
                    "session_update_enqueued",
                    {"type": "session.update"},
                    {"voiceProfileId": profile.profile.id},
                )
                return

            try:
                updated_event = await asyncio.wait_for(current_pending, timeout=10)
            finally:
                if connection.pending_session_update is current_pending:
                    if not current_pending.done():
                        current_pending.cancel()
                    connection.pending_session_update = None

            if updated_event.get("type") == "error":
                raise RuntimeError(self._extract_error_message(updated_event))
            if updated_event.get("type") != "session.updated":
                raise RuntimeError("QA Omni Realtime 连接失败：未收到 session.updated")

            await self._emit_provider_event(
                connection.on_event,
                "session_updated",
                updated_event,
                {"voiceProfileId": profile.profile.id},
            )

    async def _reader_loop(self, connection: AliyunQAOmniConnection) -> None:
        try:
            async for raw_message in connection.websocket:
                event = json.loads(raw_message)
                event_type = event.get("type")

                if event_type == "session.updated":
                    pending_update = connection.pending_session_update
                    if pending_update is not None and not pending_update.done():
                        pending_update.set_result(event)
                        continue

                if event_type == "error":
                    pending_update = connection.pending_session_update
                    if pending_update is not None and not pending_update.done():
                        pending_update.set_result(event)
                        continue

                if event_type == "response.created":
                    response = event.get("response", {})
                    connection.assistant_turn_count += 1
                    connection.current_turn_id = f"qa-turn-{connection.assistant_turn_count}"
                    connection.current_response_id = str(response.get("id", ""))
                    connection.current_transcript = ""
                    connection.current_audio_chunks = []
                    connection.audio_stream_started = False
                    await self._emit_provider_event(
                        connection.on_event,
                        "assistant_turn_started",
                        event,
                        {
                            "turnId": connection.current_turn_id,
                            "responseId": connection.current_response_id,
                            "voiceProfileId": connection.profile.profile.id,
                        },
                    )
                    continue

                if event_type == "response.audio_transcript.delta":
                    delta = str(event.get("delta", ""))
                    if connection.current_turn_id and delta:
                        connection.current_transcript += delta
                        await self._emit_provider_event(
                            connection.on_event,
                            "assistant_text_delta",
                            event,
                            {
                                "turnId": connection.current_turn_id,
                                "text": connection.current_transcript,
                            },
                        )
                    continue

                if event_type == "response.audio_transcript.done":
                    transcript = str(event.get("transcript", "")).strip()
                    if connection.current_turn_id and transcript:
                        connection.current_transcript = transcript
                        await self._emit_provider_event(
                            connection.on_event,
                            "assistant_text_done",
                            event,
                            {
                                "turnId": connection.current_turn_id,
                                "text": transcript,
                            },
                        )
                    continue

                if event_type == "response.audio.delta":
                    audio_base64 = str(event.get("delta", ""))
                    if connection.current_turn_id and audio_base64:
                        if not connection.audio_stream_started:
                            connection.audio_stream_started = True
                            await self._emit_provider_event(
                                connection.on_event,
                                "assistant_audio_start",
                                event,
                                {
                                    "turnId": connection.current_turn_id,
                                    "sampleRateHz": self.SAMPLE_RATE,
                                    "voiceProfileId": connection.profile.profile.id,
                                },
                            )
                        connection.current_audio_chunks.append(base64.b64decode(audio_base64))
                        await self._emit_provider_event(
                            connection.on_event,
                            "assistant_audio_delta",
                            event,
                            {
                                "turnId": connection.current_turn_id,
                                "audioBase64": audio_base64,
                                "sampleRateHz": self.SAMPLE_RATE,
                            },
                        )
                    continue

                if event_type == "response.audio.done":
                    if connection.current_turn_id:
                        duration_ms = self._write_current_audio_file(connection)
                        await self._emit_provider_event(
                            connection.on_event,
                            "assistant_audio_end",
                            event,
                            {
                                "turnId": connection.current_turn_id,
                                "audioUrl": self.build_audio_url(connection.session_id, connection.current_turn_id),
                                "durationMs": duration_ms,
                                "voiceProfileId": connection.profile.profile.id,
                            },
                        )
                    continue

                if event_type == "response.done":
                    response = event.get("response", {})
                    final_text = connection.current_transcript or self._extract_text_from_response_done(response)
                    if connection.current_turn_id:
                        await self._emit_provider_event(
                            connection.on_event,
                            "assistant_response_done",
                            event,
                            {
                                "turnId": connection.current_turn_id,
                                "responseId": connection.current_response_id,
                                "text": final_text,
                            },
                        )
                    connection.current_response_id = None
                    continue

                if event_type == "conversation.item.input_audio_transcription.completed":
                    transcript = str(event.get("transcript", "")).strip()
                    await self._emit_provider_event(
                        connection.on_event,
                        "user_transcript",
                        event,
                        {"transcript": transcript},
                    )
                    continue

                if event_type == "input_audio_buffer.committed":
                    await self._emit_provider_event(connection.on_event, "user_audio_committed", event, None)
                    continue

                if event_type == "input_audio_buffer.cleared":
                    await self._emit_provider_event(connection.on_event, "user_audio_cleared", event, None)
                    continue

                if event_type == "error":
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
                    pending_update = connection.pending_session_update
                    if pending_update is not None and not pending_update.done():
                        pending_update.set_exception(RuntimeError("QA Omni Realtime 会话已结束"))
                    await self._emit_provider_event(connection.on_event, "session_finished", event, None)
                    continue
        except ConnectionClosed as error:
            connection.finished.set()
            pending_update = connection.pending_session_update
            if pending_update is not None and not pending_update.done():
                pending_update.set_exception(RuntimeError(self._format_connection_closed_error(error)))
            if not connection.finish_sent:
                await connection.on_error(self._format_connection_closed_error(error))
        except asyncio.CancelledError:
            pending_update = connection.pending_session_update
            if pending_update is not None and not pending_update.done():
                pending_update.set_exception(RuntimeError("QA Omni Realtime reader 已取消"))
            raise
        except Exception as error:
            pending_update = connection.pending_session_update
            if pending_update is not None and not pending_update.done():
                pending_update.set_exception(RuntimeError(f"QA Omni Realtime 连接异常：{error}"))
            await connection.on_error(f"QA Omni Realtime 连接异常：{error}")
            connection.finished.set()
        finally:
            if self.connections.get(connection.session_id) is connection:
                self.connections.pop(connection.session_id, None)

    def _write_current_audio_file(self, connection: AliyunQAOmniConnection) -> int:
        if not connection.current_turn_id:
            return 1
        audio_bytes = b"".join(connection.current_audio_chunks)
        output_path = self.get_audio_path(connection.session_id, connection.current_turn_id)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(output_path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(self.SAMPLE_RATE)
            wav_file.writeframes(audio_bytes)
        return max(int(len(audio_bytes) / 2 / self.SAMPLE_RATE * 1000), 1)

    def _build_url(self) -> str:
        separator = "&" if "?" in self.url else "?"
        return f"{self.url}{separator}model={self.model}"

    @staticmethod
    async def _receive_json(websocket) -> dict[str, Any]:
        raw = await websocket.recv()
        return json.loads(raw)

    async def _send_json(self, connection: AliyunQAOmniConnection, payload: dict[str, Any]) -> None:
        connection.event_counter += 1
        message = {
            "event_id": f"event_{connection.session_id}_{connection.event_counter}",
            **payload,
        }
        await connection.websocket.send(json.dumps(message))

    @staticmethod
    async def _emit_provider_event(
        callback: QAProviderEventCallback,
        stage: str,
        event: dict[str, Any],
        metadata: dict[str, Any] | None,
    ) -> None:
        await callback(stage, event, metadata)

    @staticmethod
    def _extract_error_message(event: dict[str, Any]) -> str:
        error = event.get("error")
        if isinstance(error, dict):
            return str(error.get("message", "QA Omni Realtime 失败"))
        return "QA Omni Realtime 失败"

    @staticmethod
    def _extract_text_from_response_done(response: dict[str, Any]) -> str:
        output = response.get("output", [])
        for item in output:
            content = item.get("content", [])
            for part in content:
                transcript = part.get("transcript")
                if isinstance(transcript, str) and transcript.strip():
                    return transcript.strip()
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    return text.strip()
        return ""

    @staticmethod
    def _format_connection_closed_error(error: ConnectionClosed) -> str:
        return f"received {error.rcvd.code if error.rcvd else 'closed'} ({error})"

    @staticmethod
    def _build_silence_audio_payload(duration_ms: int) -> str:
        sample_count = max(1, int(AliyunQAOmniRealtimeService.SAMPLE_RATE * duration_ms / 1000))
        silence_bytes = b"\x00\x00" * sample_count
        return base64.b64encode(silence_bytes).decode("ascii")
