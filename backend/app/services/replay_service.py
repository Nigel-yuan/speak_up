from __future__ import annotations

import asyncio
import json
import mimetypes
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from app.schemas import (
    CoachDimensionId,
    CoachSignalPolarity,
    CoachSignalSeverity,
    LanguageOption,
    ReplayCoachInsight,
    ReplayMediaUploadResponse,
    SessionReplay,
)
from app.services.report_artifact_service import ReportArtifactService
from app.services.report_repository import ReportRepository
from app.services.report_signal_service import ReportSignalService


DEFAULT_COACH_WINDOW_MS = 8000


@dataclass(frozen=True)
class ReplayMediaFile:
    path: Path
    media_type: str
    duration_ms: int
    content_type: str | None = None


class ReplayService:
    def __init__(
        self,
        *,
        artifact_service: ReportArtifactService,
        repository: ReportRepository,
        signal_service: ReportSignalService,
    ) -> None:
        self.artifact_service = artifact_service
        self.repository = repository
        self.signal_service = signal_service
        self.output_root = repository.output_root
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    def _session_dir(self, session_id: str) -> Path:
        return self.output_root / session_id

    def _media_meta_path(self, session_id: str) -> Path:
        return self._session_dir(session_id) / "replay_media.json"

    async def save_media(
        self,
        session_id: str,
        *,
        filename: str | None,
        content_type: str | None,
        data: bytes,
        duration_ms: int = 0,
    ) -> ReplayMediaUploadResponse:
        state = await self.repository.get_state(session_id)
        if state is None:
            raise FileNotFoundError(session_id)

        extension = self._resolve_extension(filename, content_type)
        media_type = self._resolve_media_type(extension, content_type)
        session_dir = self._session_dir(session_id)
        media_path = session_dir / f"replay_media{extension}"

        async with self._locks[session_id]:
            session_dir.mkdir(parents=True, exist_ok=True)
            for existing in session_dir.glob("replay_media.*"):
                if existing != media_path and existing.is_file():
                    existing.unlink(missing_ok=True)
            media_path.write_bytes(data)
            self._media_meta_path(session_id).write_text(
                json.dumps(
                    {
                        "fileName": media_path.name,
                        "mediaType": media_type,
                        "contentType": content_type,
                        "durationMs": max(0, int(duration_ms)),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

        return ReplayMediaUploadResponse(
            mediaUrl=f"/api/session/{session_id}/replay/media",
            mediaType=media_type,
            durationMs=max(0, int(duration_ms)),
        )

    async def get_media_file(self, session_id: str) -> ReplayMediaFile | None:
        meta_path = self._media_meta_path(session_id)
        if not meta_path.exists():
            return None

        async with self._locks[session_id]:
            payload = json.loads(meta_path.read_text(encoding="utf-8"))
            file_name = str(payload.get("fileName") or "").strip()
            if not file_name:
                return None
            media_path = self._session_dir(session_id) / file_name
            if not media_path.exists():
                return None

            content_type = payload.get("contentType")
            if not isinstance(content_type, str) or not content_type.strip():
                content_type = mimetypes.guess_type(media_path.name)[0] or None

            return ReplayMediaFile(
                path=media_path,
                media_type=str(payload.get("mediaType") or self._resolve_media_type(media_path.suffix, content_type)),
                duration_ms=max(0, int(payload.get("durationMs") or 0)),
                content_type=content_type,
            )

    async def build_replay(self, session_id: str) -> SessionReplay | None:
        state = await self.repository.get_state(session_id)
        if state is None:
            return None

        artifacts = await self.artifact_service.read_artifacts(session_id)
        bundle = self.signal_service.build_bundle(
            language=state.language,
            artifacts=artifacts,
        )
        media = await self.get_media_file(session_id)
        coach_insights = self._build_coach_insights(
            language=state.language,
            coach_signals=bundle.coach_signals,
            total_duration_ms=max(
                bundle.latest_timestamp_ms,
                max((chunk.endMs for chunk in bundle.transcript_chunks), default=0),
                media.duration_ms if media is not None else 0,
            ),
        )
        duration_ms = max(
            max((chunk.endMs for chunk in bundle.transcript_chunks), default=0),
            max((insight.endMs for insight in coach_insights), default=0),
            media.duration_ms if media is not None else 0,
        )

        return SessionReplay(
            sessionId=session_id,
            scenarioId=state.scenarioId,
            language=state.language,
            coachProfileId=state.coachProfileId,
            mediaUrl=f"/api/session/{session_id}/replay/media" if media is not None else None,
            mediaType=media.media_type if media is not None else None,
            durationMs=duration_ms,
            transcript=bundle.transcript_chunks,
            coachInsights=coach_insights,
        )

    def _build_coach_insights(
        self,
        *,
        language: LanguageOption,
        coach_signals: list[dict],
        total_duration_ms: int,
    ) -> list[ReplayCoachInsight]:
        ordered = sorted(coach_signals, key=lambda item: int(item.get("timestampMs", 0)))
        insights: list[ReplayCoachInsight] = []

        for index, signal in enumerate(ordered):
            start_ms = max(0, int(signal.get("timestampMs", 0)))
            next_start_ms = max(0, int(ordered[index + 1].get("timestampMs", 0))) if index + 1 < len(ordered) else 0
            capped_end_ms = start_ms + DEFAULT_COACH_WINDOW_MS
            if next_start_ms > start_ms:
                capped_end_ms = min(capped_end_ms, max(start_ms + 1200, next_start_ms - 1))
            if total_duration_ms > 0:
                capped_end_ms = min(capped_end_ms, max(start_ms + 1200, total_duration_ms))

            dimension_id = self._normalize_dimension_id(signal.get("dimensionId"))
            title = str(signal.get("headline") or self._default_title(language, dimension_id)).strip()
            message = str(signal.get("detail") or "").strip() or self._default_message(language, dimension_id)
            severity = self._normalize_severity(signal.get("severity"))
            polarity = self._normalize_polarity(signal.get("signalPolarity"), signal.get("status"))
            evidence_text = str(signal.get("evidenceText") or "").strip() or None

            if (
                insights
                and insights[-1].dimensionId == dimension_id
                and insights[-1].title == title
                and insights[-1].message == message
                and start_ms - insights[-1].endMs <= 2000
            ):
                insights[-1] = insights[-1].model_copy(update={"endMs": max(insights[-1].endMs, capped_end_ms)})
                continue

            insights.append(
                ReplayCoachInsight(
                    id=f"coach-{index + 1}",
                    startMs=start_ms,
                    endMs=max(start_ms + 1200, capped_end_ms),
                    dimensionId=dimension_id,
                    subDimensionId=str(signal.get("subDimensionId") or "").strip() or None,
                    severity=severity,
                    polarity=polarity,
                    title=title,
                    message=message,
                    evidenceText=evidence_text,
                )
            )

        return insights

    @staticmethod
    def _resolve_extension(filename: str | None, content_type: str | None) -> str:
        suffix = Path(filename or "").suffix.lower()
        if suffix in {".webm", ".mp4", ".mov", ".m4a", ".wav", ".mp3", ".ogg"}:
            return suffix
        if content_type == "video/mp4":
            return ".mp4"
        if content_type == "audio/wav":
            return ".wav"
        if content_type == "audio/mpeg":
            return ".mp3"
        if content_type == "audio/ogg":
            return ".ogg"
        return ".webm"

    @staticmethod
    def _resolve_media_type(extension: str, content_type: str | None) -> str:
        if content_type and content_type.startswith("audio/"):
            return "audio"
        if extension in {".wav", ".mp3", ".m4a", ".ogg"}:
            return "audio"
        return "video"

    @staticmethod
    def _normalize_dimension_id(value: object) -> CoachDimensionId:
        normalized = str(value or "").strip()
        if normalized in {"body_expression", "voice_pacing", "content_expression"}:
            return normalized
        return "content_expression"

    @staticmethod
    def _normalize_severity(value: object) -> CoachSignalSeverity:
        normalized = str(value or "").strip()
        if normalized in {"low", "medium", "high"}:
            return normalized
        return "medium"

    @staticmethod
    def _normalize_polarity(value: object, status: object) -> CoachSignalPolarity:
        normalized = str(value or "").strip()
        if normalized in {"positive", "neutral", "negative"}:
            return normalized

        status_text = str(status or "").strip()
        if status_text == "doing_well":
            return "positive"
        if status_text == "adjust_now":
            return "negative"
        return "neutral"

    @staticmethod
    def _default_title(language: LanguageOption, dimension_id: CoachDimensionId) -> str:
        if language == "en":
            return {
                "body_expression": "Body delivery update",
                "voice_pacing": "Voice pacing update",
                "content_expression": "Content expression update",
            }[dimension_id]
        return {
            "body_expression": "肢体与表情反馈",
            "voice_pacing": "语音语调与节奏反馈",
            "content_expression": "内容表达反馈",
        }[dimension_id]

    @staticmethod
    def _default_message(language: LanguageOption, dimension_id: CoachDimensionId) -> str:
        if language == "en":
            return {
                "body_expression": "Keep your gestures open and natural.",
                "voice_pacing": "Keep the pace stable and give key points a pause.",
                "content_expression": "Lead with the point, then expand with examples.",
            }[dimension_id]
        return {
            "body_expression": "保持肢体打开，动作自然一些。",
            "voice_pacing": "稳住节奏，重点前后留一点停顿。",
            "content_expression": "先讲结论，再补充展开和例子。",
        }[dimension_id]
