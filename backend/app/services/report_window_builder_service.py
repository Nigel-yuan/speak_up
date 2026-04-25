from __future__ import annotations

import asyncio
import logging

from app.schemas import LanguageOption, ReportWindowPack, ScenarioType
from app.services.report_artifact_service import ReportArtifactService
from app.services.report_brain_service import ReportBrainService
from app.services.report_repository import ReportRepository
from app.services.report_signal_service import ReportSignalService


logger = logging.getLogger("speak_up.session")


class ReportWindowBuilderService:
    def __init__(
        self,
        artifact_service: ReportArtifactService,
        signal_service: ReportSignalService,
        brain_service: ReportBrainService,
        repository: ReportRepository,
        window_size_ms: int,
        min_window_ms: int,
    ) -> None:
        self.artifact_service = artifact_service
        self.signal_service = signal_service
        self.brain_service = brain_service
        self.repository = repository
        self.window_size_ms = window_size_ms
        self.min_window_ms = min_window_ms
        self._session_locks: dict[str, asyncio.Lock] = {}

    async def build_available_windows(
        self,
        *,
        session_id: str,
        scenario_id: ScenarioType,
        language: LanguageOption,
        finalizing: bool = False,
    ) -> list[ReportWindowPack]:
        lock = self._session_locks.setdefault(session_id, asyncio.Lock())
        async with lock:
            return await self._build_available_windows_unlocked(
                session_id=session_id,
                scenario_id=scenario_id,
                language=language,
                finalizing=finalizing,
            )

    async def _build_available_windows_unlocked(
        self,
        *,
        session_id: str,
        scenario_id: ScenarioType,
        language: LanguageOption,
        finalizing: bool = False,
    ) -> list[ReportWindowPack]:
        state = await self.repository.get_state(session_id)
        if state is None:
            return []
        artifacts = await self.artifact_service.read_artifacts(session_id)
        if not artifacts:
            return []

        packs: list[ReportWindowPack] = []
        latest_timestamp_ms = max((artifact.timestampMs for artifact in artifacts), default=0)
        cursor_ms = state.lastCoveredMs
        while True:
            remaining_ms = latest_timestamp_ms - cursor_ms
            if remaining_ms <= 0:
                break
            if not finalizing and remaining_ms < self.window_size_ms:
                break
            if finalizing and remaining_ms < self.min_window_ms and state.windowCount > 0:
                break

            window_duration_ms = self.window_size_ms if remaining_ms >= self.window_size_ms else remaining_ms
            window_end_ms = cursor_ms + window_duration_ms
            if window_duration_ms < self.min_window_ms and not finalizing:
                break

            bundle = self.signal_service.build_bundle(
                language=language,
                artifacts=artifacts,
                after_ms=cursor_ms,
                end_ms=window_end_ms,
            )
            if not bundle.transcript_chunks and not bundle.qa_questions and not bundle.coach_signals:
                cursor_ms = window_end_ms
                await self.repository.update_state(session_id, lastCoveredMs=cursor_ms, latestArtifactMs=latest_timestamp_ms)
                continue

            next_window_index = state.windowCount + len(packs) + 1
            window_id = f"window-{next_window_index:04d}"
            logger.info(
                "report.window_build.begin session=%s window=%s start_ms=%s end_ms=%s transcript_chunks=%s qa_questions=%s coach_signals=%s",
                session_id,
                window_id,
                cursor_ms,
                window_end_ms,
                len(bundle.transcript_chunks),
                len(bundle.qa_questions),
                len(bundle.coach_signals),
            )
            pack = await self.brain_service.build_window_pack(
                session_id=session_id,
                scenario_id=scenario_id,
                language=language,
                window_id=window_id,
                window_start_ms=cursor_ms,
                window_end_ms=window_end_ms,
                bundle=bundle,
            )
            await self.repository.save_window_pack(session_id, pack)
            packs.append(pack)
            cursor_ms = window_end_ms
            logger.info(
                "report.window_build.done session=%s window=%s score_count=%s suggestion_count=%s",
                session_id,
                window_id,
                len(pack.topDimensionScores),
                len(pack.candidateSuggestions),
            )

        if packs:
            await self.repository.update_state(
                session_id,
                lastCoveredMs=cursor_ms,
                windowCount=state.windowCount + len(packs),
                latestArtifactMs=latest_timestamp_ms,
                status="processing",
                errorMessage=None,
            )
        elif latest_timestamp_ms > state.latestArtifactMs:
            await self.repository.update_state(session_id, latestArtifactMs=latest_timestamp_ms)
        return packs
