import base64
import json
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

from app.schemas import LiveInsight, TranscriptChunk


class DebugStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def init_session(self, session_id: str, metadata: dict[str, Any]) -> None:
        session_dir = self._session_dir(session_id)
        (session_dir / "audio").mkdir(parents=True, exist_ok=True)
        (session_dir / "frames").mkdir(parents=True, exist_ok=True)
        self._write_json(session_dir / "metadata.json", metadata)
        self.append_event(session_id, {"type": "session_created", **metadata})

    def append_event(self, session_id: str, event: dict[str, Any]) -> None:
        session_dir = self._session_dir(session_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            **event,
        }
        with (session_dir / "events.jsonl").open("a", encoding="utf-8") as file:
            file.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def save_audio_chunk(self, session_id: str, chunk_index: int, payload: str | None, mime_type: str | None) -> str:
        session_dir = self._session_dir(session_id) / "audio"
        session_dir.mkdir(parents=True, exist_ok=True)
        extension = self._audio_extension(mime_type)
        path = session_dir / f"audio_{chunk_index:04d}.{extension}"

        if payload:
            encoded = payload.split(",", 1)[-1]
            path.write_bytes(base64.b64decode(encoded))
        else:
            path.write_bytes(b"")

        self.append_event(
            session_id,
            {
                "type": "audio_chunk_saved",
                "path": str(path),
                "index": chunk_index,
                "mimeType": mime_type,
            },
        )
        return str(path)

    def save_video_frame(self, session_id: str, frame_index: int, image_base64: str | None) -> str:
        session_dir = self._session_dir(session_id) / "frames"
        session_dir.mkdir(parents=True, exist_ok=True)
        path = session_dir / f"frame_{frame_index:04d}.jpg"

        if image_base64:
            encoded = image_base64.split(",", 1)[-1]
            path.write_bytes(base64.b64decode(encoded))
        else:
            path.write_text("", encoding="utf-8")

        self.append_event(session_id, {"type": "video_frame_saved", "path": str(path), "index": frame_index})
        return str(path)

    def save_transcript_injection(self, session_id: str, chunk: TranscriptChunk, source: str) -> None:
        self.append_event(
            session_id,
            {"type": "transcript_injected", "source": source, "chunk": chunk.model_dump()},
        )

    def save_insight_injection(self, session_id: str, insight: LiveInsight, source: str) -> None:
        self.append_event(
            session_id,
            {"type": "insight_injected", "source": source, "insight": insight.model_dump()},
        )

    def _session_dir(self, session_id: str) -> Path:
        return self.root / session_id

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _audio_extension(mime_type: str | None) -> str:
        if not mime_type:
            return "bin"

        normalized = mime_type.split(";", 1)[0].strip().lower()

        if normalized == "audio/webm":
            return "webm"
        if normalized in {"audio/wav", "audio/wave", "audio/x-wav"}:
            return "wav"
        return "bin"
