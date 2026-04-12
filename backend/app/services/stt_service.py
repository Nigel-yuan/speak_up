import asyncio
import json
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import websockets
from websockets.exceptions import ConnectionClosed

from app.schemas import LanguageOption


PartialTranscriptCallback = Callable[[str], Awaitable[None]]
ErrorCallback = Callable[[str], Awaitable[None]]
ProviderEventCallback = Callable[[str, dict[str, Any], dict[str, Any] | None], Awaitable[None]]

LANGUAGE_MAP: dict[LanguageOption, str] = {
    "zh": "zh",
    "en": "en",
}


@dataclass(frozen=True)
class ProviderTranscriptResult:
    text: str
    start_ms: int | None = None
    end_ms: int | None = None


FinalTranscriptCallback = Callable[[ProviderTranscriptResult], Awaitable[None]]


@dataclass
class AliyunRealtimeAsrConnection:
    session_id: str
    language: str
    websocket: Any
    on_partial: PartialTranscriptCallback
    on_final: FinalTranscriptCallback
    on_error: ErrorCallback
    on_event: ProviderEventCallback | None = None
    event_counter: int = 0
    finish_sent: bool = False
    finished: asyncio.Event = field(default_factory=asyncio.Event)
    current_speech_start_ms: int | None = None
    current_speech_end_ms: int | None = None
    reader_task: asyncio.Task[None] | None = field(default=None, repr=False)


class AliyunRealtimeAsrService:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        url: str | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("DASHSCOPE_API_KEY")
        self.model = model or os.getenv("ALIYUN_REALTIME_ASR_MODEL", "qwen3-asr-flash-realtime")
        self.url = url or os.getenv("ALIYUN_REALTIME_ASR_URL", "wss://dashscope.aliyuncs.com/api-ws/v1/realtime")
        self.vad_threshold = float(os.getenv("ALIYUN_REALTIME_ASR_VAD_THRESHOLD", "0.0"))
        self.vad_silence_duration_ms = max(
            200,
            min(6000, int(os.getenv("ALIYUN_REALTIME_ASR_SILENCE_DURATION_MS", "1200"))),
        )
        self.connections: dict[str, AliyunRealtimeAsrConnection] = {}

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def connect_session(
        self,
        session_id: str,
        language: LanguageOption,
        on_partial: PartialTranscriptCallback,
        on_final: FinalTranscriptCallback,
        on_error: ErrorCallback,
        on_event: ProviderEventCallback | None = None,
    ) -> None:
        if not self.is_configured:
            raise RuntimeError("阿里云实时转写未配置，请设置 DASHSCOPE_API_KEY 并重启后端")

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
            raise RuntimeError("阿里云实时转写连接失败：未收到 session.created")

        connection = AliyunRealtimeAsrConnection(
            session_id=session_id,
            language=LANGUAGE_MAP.get(language, "zh"),
            websocket=websocket,
            on_partial=on_partial,
            on_final=on_final,
            on_error=on_error,
            on_event=on_event,
        )
        self.connections[session_id] = connection

        await self._send_json(
            connection,
            {
                "type": "session.update",
                "session": {
                    "input_audio_format": "pcm",
                    "sample_rate": 16000,
                    "input_audio_transcription": {
                        "language": connection.language,
                    },
                    "turn_detection": {
                        "type": "server_vad",
                        "threshold": self.vad_threshold,
                        "silence_duration_ms": self.vad_silence_duration_ms,
                    },
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
            raise RuntimeError("阿里云实时转写连接失败：未收到 session.updated")

        connection.reader_task = asyncio.create_task(self._reader_loop(connection))

    async def send_audio_chunk(
        self,
        session_id: str,
        payload: str | None,
    ) -> None:
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

    async def finish_session(self, session_id: str) -> None:
        connection = self.connections.get(session_id)
        if connection is None:
            return

        if not connection.finish_sent:
            connection.finish_sent = True
            await self._send_json(connection, {"type": "session.finish"})

        try:
            await asyncio.wait_for(connection.finished.wait(), timeout=10)
        except TimeoutError:
            pass
        finally:
            await self.close_session(session_id)

    async def close_session(self, session_id: str) -> None:
        connection = self.connections.pop(session_id, None)
        if connection is None:
            return

        connection.finished.set()

        if connection.reader_task is not None and connection.reader_task is not asyncio.current_task():
            connection.reader_task.cancel()
            await asyncio.gather(connection.reader_task, return_exceptions=True)

        try:
            await connection.websocket.close()
        except Exception:
            return

    async def _reader_loop(self, connection: AliyunRealtimeAsrConnection) -> None:
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

                if event_type == "conversation.item.input_audio_transcription.text":
                    partial_text = f"{event.get('text', '')}{event.get('stash', '')}".strip()
                    if partial_text:
                        await self._emit_provider_event(
                            connection.on_event,
                            "partial",
                            event,
                            {"text": partial_text},
                        )
                        await connection.on_partial(partial_text)
                    continue

                if event_type == "input_audio_buffer.speech_started":
                    connection.current_speech_start_ms = self._coerce_millis(event.get("audio_start_ms"))
                    await self._emit_provider_event(
                        connection.on_event,
                        "speech_started",
                        event,
                        {"startMs": connection.current_speech_start_ms},
                    )
                    continue

                if event_type == "input_audio_buffer.speech_stopped":
                    connection.current_speech_end_ms = self._coerce_millis(event.get("audio_end_ms"))
                    await self._emit_provider_event(
                        connection.on_event,
                        "speech_stopped",
                        event,
                        {"endMs": connection.current_speech_end_ms},
                    )
                    continue

                if event_type == "conversation.item.input_audio_transcription.completed":
                    transcript = str(event.get("transcript", "")).strip()
                    if transcript:
                        result = ProviderTranscriptResult(
                            text=transcript,
                            start_ms=connection.current_speech_start_ms,
                            end_ms=connection.current_speech_end_ms,
                        )
                        await self._emit_provider_event(
                            connection.on_event,
                            "final",
                            event,
                            {"transcript": transcript, "startMs": result.start_ms, "endMs": result.end_ms},
                        )
                        await connection.on_final(result)
                    connection.current_speech_start_ms = None
                    connection.current_speech_end_ms = None
                    continue

                if event_type == "conversation.item.input_audio_transcription.failed":
                    error = event.get("error", {})
                    message = error.get("message", "阿里云实时转写失败")
                    await self._emit_provider_event(
                        connection.on_event,
                        "failed",
                        event,
                        {"message": message},
                    )
                    await connection.on_error(message)
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
                    await self._emit_provider_event(connection.on_event, "session_finished", event)
                    connection.finished.set()
                    break
        except ConnectionClosed:
            await self._emit_provider_event(
                connection.on_event,
                "connection_closed",
                {"type": "connection.closed"},
            )
            connection.finished.set()
        except asyncio.CancelledError:
            connection.finished.set()
            raise
        except Exception as error:
            await self._emit_provider_event(
                connection.on_event,
                "connection_error",
                {"type": "connection.error", "message": str(error)},
                {"message": str(error)},
            )
            connection.finished.set()
            await connection.on_error(f"阿里云实时转写连接异常：{error}")
        finally:
            self.connections.pop(connection.session_id, None)
            try:
                await connection.websocket.close()
            except Exception:
                return

    async def _send_json(self, connection: AliyunRealtimeAsrConnection, payload: dict[str, Any]) -> None:
        connection.event_counter += 1
        message = {
            "event_id": f"event_{connection.session_id}_{connection.event_counter}",
            **payload,
        }
        await connection.websocket.send(json.dumps(message))

    def _build_url(self) -> str:
        if "?model=" in self.url:
            return self.url
        separator = "&" if "?" in self.url else "?"
        return f"{self.url}{separator}model={quote(self.model)}"

    @staticmethod
    async def _receive_json(websocket: Any) -> dict[str, Any]:
        payload = await websocket.recv()
        return json.loads(payload)

    @staticmethod
    def _extract_error_message(event: dict[str, Any]) -> str:
        error = event.get("error", {})
        return error.get("message") or "阿里云实时转写请求失败"

    @staticmethod
    def _coerce_millis(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return max(int(value), 0)
        except (TypeError, ValueError):
            return None

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


class UnavailableRealtimeSttService:
    async def connect_session(
        self,
        session_id: str,
        language: LanguageOption,
        on_partial: PartialTranscriptCallback,
        on_final: FinalTranscriptCallback,
        on_error: ErrorCallback,
        on_event: ProviderEventCallback | None = None,
    ) -> None:
        raise RuntimeError("阿里云实时转写未配置，请设置 DASHSCOPE_API_KEY 并重启后端")

    async def send_audio_chunk(self, session_id: str, payload: str | None) -> None:
        return

    async def finish_session(self, session_id: str) -> None:
        return

    async def close_session(self, session_id: str) -> None:
        return


def build_stt_service() -> AliyunRealtimeAsrService | UnavailableRealtimeSttService:
    service = AliyunRealtimeAsrService()
    if service.is_configured:
        return service
    return UnavailableRealtimeSttService()
