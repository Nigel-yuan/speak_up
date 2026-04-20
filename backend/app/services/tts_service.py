import asyncio
import base64
import json
import os
import wave
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import websockets

from app.schemas import LanguageOption
from app.services.voice_profile_service import VoiceProfileConfig


@dataclass(frozen=True)
class TTSGenerationResult:
    file_path: Path
    duration_ms: int


TTSAudioDeltaCallback = Callable[[str], Awaitable[None]]


class AliyunRealtimeTTSService:
    SAMPLE_RATE = 24000

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        url: str | None = None,
        output_root: str | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("DASHSCOPE_API_KEY")
        self.model = model or os.getenv("ALIYUN_QA_TTS_MODEL", "qwen3-tts-instruct-flash-realtime")
        self.url = url or os.getenv("ALIYUN_QA_TTS_URL", "wss://dashscope.aliyuncs.com/api-ws/v1/realtime")
        self.output_root = Path(output_root or os.getenv("QA_AUDIO_OUTPUT_ROOT", "output/qa_audio"))

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def synthesize(
        self,
        *,
        session_id: str,
        turn_id: str,
        language: LanguageOption,
        text: str,
        profile: VoiceProfileConfig,
    ) -> TTSGenerationResult:
        output_path = self.output_root / session_id / f"{turn_id}.wav"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if not self.is_configured:
            self._write_silent_wav(output_path, duration_ms=1200)
            return TTSGenerationResult(file_path=output_path, duration_ms=1200)

        try:
            return await asyncio.wait_for(
                self._synthesize_remote(
                    session_id=session_id,
                    turn_id=turn_id,
                    language=language,
                    text=text,
                    profile=profile,
                    output_path=output_path,
                ),
                timeout=18,
            )
        except Exception:
            self._write_silent_wav(output_path, duration_ms=1200)
            return TTSGenerationResult(file_path=output_path, duration_ms=1200)

    async def synthesize_streaming(
        self,
        *,
        session_id: str,
        turn_id: str,
        language: LanguageOption,
        text: str,
        profile: VoiceProfileConfig,
        on_audio_delta: TTSAudioDeltaCallback,
    ) -> TTSGenerationResult:
        output_path = self.output_root / session_id / f"{turn_id}.wav"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if not self.is_configured:
            self._write_silent_wav(output_path, duration_ms=1200)
            return TTSGenerationResult(file_path=output_path, duration_ms=1200)

        try:
            return await asyncio.wait_for(
                self._synthesize_remote(
                    session_id=session_id,
                    turn_id=turn_id,
                    language=language,
                    text=text,
                    profile=profile,
                    output_path=output_path,
                    on_audio_delta=on_audio_delta,
                ),
                timeout=18,
            )
        except Exception:
            self._write_silent_wav(output_path, duration_ms=1200)
            return TTSGenerationResult(file_path=output_path, duration_ms=1200)

    async def _synthesize_remote(
        self,
        *,
        session_id: str,
        turn_id: str,
        language: LanguageOption,
        text: str,
        profile: VoiceProfileConfig,
        output_path: Path,
        on_audio_delta: TTSAudioDeltaCallback | None = None,
    ) -> TTSGenerationResult:
        del session_id

        audio_chunks: list[bytes] = []
        websocket = await websockets.connect(
            self._build_url(),
            additional_headers={"Authorization": f"Bearer {self.api_key}"},
            max_size=2**22,
        )

        try:
            created_event = await self._receive_json(websocket)
            if created_event.get("type") == "error":
                raise RuntimeError(self._extract_error_message(created_event))
            if created_event.get("type") != "session.created":
                raise RuntimeError("Qwen TTS 连接失败：未收到 session.created")

            await websocket.send(
                json.dumps(
                    {
                        "type": "session.update",
                        "event_id": f"event_{turn_id}_update",
                        "session": {
                            "mode": "commit",
                            "voice": profile.provider_voice_id,
                            "instructions": profile.instructions_for(language),
                            "optimize_instructions": True,
                            "language_type": "Chinese" if language == "zh" else "English",
                            "response_format": "pcm",
                            "sample_rate": self.SAMPLE_RATE,
                        },
                    }
                )
            )

            updated_event = await self._receive_json(websocket)
            if updated_event.get("type") == "error":
                raise RuntimeError(self._extract_error_message(updated_event))
            if updated_event.get("type") != "session.updated":
                raise RuntimeError("Qwen TTS 连接失败：未收到 session.updated")

            await websocket.send(
                json.dumps(
                    {
                        "type": "input_text_buffer.append",
                        "event_id": f"event_{turn_id}_append",
                        "text": text,
                    }
                )
            )
            await websocket.send(
                json.dumps(
                    {
                        "type": "input_text_buffer.commit",
                        "event_id": f"event_{turn_id}_commit",
                    }
                )
            )

            while True:
                event = await self._receive_json(websocket)
                event_type = event.get("type")
                if event_type == "response.audio.delta":
                    audio_base64 = str(event.get("delta", ""))
                    audio_chunks.append(base64.b64decode(audio_base64))
                    if on_audio_delta is not None and audio_base64:
                        await on_audio_delta(audio_base64)
                    continue
                if event_type == "error":
                    raise RuntimeError(self._extract_error_message(event))
                if event_type == "response.done":
                    break

            await websocket.send(
                json.dumps(
                    {
                        "type": "session.finish",
                        "event_id": f"event_{turn_id}_finish",
                    }
                )
            )
            await asyncio.wait_for(websocket.close(), timeout=5)
        finally:
            try:
                await websocket.close()
            except Exception:
                pass

        audio_bytes = b"".join(audio_chunks)
        if not audio_bytes:
            self._write_silent_wav(output_path, duration_ms=1200)
            return TTSGenerationResult(file_path=output_path, duration_ms=1200)

        duration_ms = max(int(len(audio_bytes) / 2 / self.SAMPLE_RATE * 1000), 1)
        with wave.open(str(output_path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(self.SAMPLE_RATE)
            wav_file.writeframes(audio_bytes)

        return TTSGenerationResult(file_path=output_path, duration_ms=duration_ms)

    def get_audio_path(self, session_id: str, turn_id: str) -> Path:
        return self.output_root / session_id / f"{turn_id}.wav"

    def build_audio_url(self, session_id: str, turn_id: str) -> str:
        return f"/api/session/{quote(session_id)}/qa/turns/{quote(turn_id)}/audio"

    @staticmethod
    def _extract_error_message(event: dict) -> str:
        error = event.get("error")
        if isinstance(error, dict):
            return str(error.get("message", "语音合成失败"))
        return "语音合成失败"

    def _build_url(self) -> str:
        separator = "&" if "?" in self.url else "?"
        return f"{self.url}{separator}model={self.model}"

    @staticmethod
    async def _receive_json(websocket) -> dict:
        raw = await websocket.recv()
        return json.loads(raw)

    def _write_silent_wav(self, file_path: Path, *, duration_ms: int) -> None:
        frame_count = max(int(self.SAMPLE_RATE * duration_ms / 1000), 1)
        silence = b"\x00\x00" * frame_count
        with wave.open(str(file_path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(self.SAMPLE_RATE)
            wav_file.writeframes(silence)
