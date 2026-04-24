from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass

from app.schemas import (
    CoachPanelPatch,
    CoachPanelState,
    LanguageOption,
    QAQuestion,
    ReportProgressState,
    ReportProgressStep,
    ReportSectionStatus,
    ReportWindowPack,
    ScenarioType,
    SessionReport,
    TranscriptChunk,
)
from app.services.report_artifact_service import ReportArtifactService
from app.services.report_brain_service import ReportBrainService
from app.services.report_repository import ReportRepository
from app.services.report_signal_service import ReportSignalBundle, ReportSignalService
from app.services.report_window_builder_service import ReportWindowBuilderService


logger = logging.getLogger("speak_up.session")

REPORT_PROGRESS_STEP_LABELS = {
    "collecting": "收集本轮素材",
    "structuring": "整理问答与教练信号",
    "generating": "生成整场分析报告",
    "finalizing": "写入最终结果",
}
REPORT_PROGRESS_STEP_ORDER = tuple(REPORT_PROGRESS_STEP_LABELS.keys())


@dataclass
class ReportJobContext:
    scenario_id: ScenarioType
    language: LanguageOption
    coach_profile_id: str | None = None
    finished: bool = False


class ReportJobService:
    def __init__(self) -> None:
        interval_seconds = max(60, int(os.getenv("REPORT_WINDOW_BUILD_INTERVAL_SECONDS", "120")))
        self.window_size_ms = interval_seconds * 1000
        self.min_window_ms = max(60000, int(os.getenv("REPORT_WINDOW_MIN_MS", "180000")))
        self.artifact_service = ReportArtifactService()
        self.signal_service = ReportSignalService()
        self.repository = ReportRepository()
        self.brain_service = ReportBrainService()
        self.window_builder_service = ReportWindowBuilderService(
            artifact_service=self.artifact_service,
            signal_service=self.signal_service,
            brain_service=self.brain_service,
            repository=self.repository,
            window_size_ms=self.window_size_ms,
            min_window_ms=self.min_window_ms,
        )
        self._contexts: dict[str, ReportJobContext] = {}
        self._window_tasks: dict[str, asyncio.Task[None]] = {}

    async def register_session(
        self,
        *,
        session_id: str,
        scenario_id: ScenarioType,
        language: LanguageOption,
        coach_profile_id: str | None = None,
    ) -> None:
        self._contexts[session_id] = ReportJobContext(
            scenario_id=scenario_id,
            language=language,
            coach_profile_id=coach_profile_id,
        )
        await self.artifact_service.init_session(
            session_id=session_id,
            scenario_id=scenario_id,
            language=language,
        )
        await self.repository.init_session(
            session_id=session_id,
            scenario_id=scenario_id,
            language=language,
            coach_profile_id=coach_profile_id,
        )

    async def update_coach_profile(self, session_id: str, coach_profile_id: str | None) -> None:
        context = self._contexts.get(session_id)
        if context is not None:
            context.coach_profile_id = coach_profile_id
        state = await self.repository.get_state(session_id)
        if state is None or state.coachProfileId == coach_profile_id:
            return
        await self.repository.save_state(state.model_copy(update={"coachProfileId": coach_profile_id}))

    def start_periodic_build(self, session_id: str) -> None:
        if session_id in self._window_tasks:
            return
        logger.info(
            "report.window_task.launch session=%s interval_s=%s",
            session_id,
            self.window_size_ms // 1000,
        )
        task = asyncio.create_task(self._run_periodic_window_build(session_id))
        self._window_tasks[session_id] = task
        task.add_done_callback(lambda finished_task, current_session_id=session_id: self._on_window_task_done(current_session_id, finished_task))

    async def record_transcript_chunk(self, session_id: str, chunk: TranscriptChunk, *, replace_previous: bool) -> None:
        artifact_type = "transcript_merged" if replace_previous else "transcript_final"
        await self.artifact_service.append_artifact(
            session_id=session_id,
            artifact_type=artifact_type,
            timestamp_ms=max(chunk.endMs, chunk.startMs),
            payload={
                "chunk": chunk.model_dump(),
                "replacePrevious": replace_previous,
            },
        )
        await self._update_latest_artifact_ms(session_id, max(chunk.endMs, chunk.startMs))

    async def record_qa_question(self, *, session_id: str, question: QAQuestion, timestamp_ms: int) -> None:
        question_text = question.questionText.strip()
        if not question_text or question.goal == "问答结束":
            return
        await self.artifact_service.append_artifact(
            session_id=session_id,
            artifact_type="qa_question",
            timestamp_ms=timestamp_ms,
            payload={
                "turnId": question.turnId,
                "questionText": question_text,
                "goal": question.goal,
                "followUp": question.followUp,
                "expectedPoints": question.expectedPoints,
            },
        )
        await self._update_latest_artifact_ms(session_id, timestamp_ms)

    async def record_coach_patch(
        self,
        *,
        session_id: str,
        patch: CoachPanelPatch,
        timestamp_ms: int,
        source: str,
    ) -> None:
        for dimension in patch.dimensions:
            await self.artifact_service.append_artifact(
                session_id=session_id,
                artifact_type="coach_signal",
                timestamp_ms=timestamp_ms,
                payload={
                    "dimensionId": dimension.id,
                    "status": dimension.status,
                    "headline": dimension.headline,
                    "detail": dimension.detail,
                    "subDimensionId": dimension.subDimensionId,
                    "signalPolarity": dimension.signalPolarity,
                    "severity": dimension.severity,
                    "confidence": dimension.confidence,
                    "evidenceText": dimension.evidenceText,
                    "source": source,
                },
            )
        await self._update_latest_artifact_ms(session_id, timestamp_ms)

    async def record_panel_snapshot(self, *, session_id: str, panel: CoachPanelState, timestamp_ms: int) -> None:
        await self.artifact_service.append_artifact(
            session_id=session_id,
            artifact_type="coach_panel_snapshot",
            timestamp_ms=timestamp_ms,
            payload={"coachPanel": panel.model_dump()},
        )
        await self._update_latest_artifact_ms(session_id, timestamp_ms)

    async def mark_session_finished(self, session_id: str, *, timestamp_ms: int) -> None:
        context = self._contexts.get(session_id)
        if context is None:
            return
        context.finished = True
        await self.artifact_service.append_artifact(
            session_id=session_id,
            artifact_type="session_finished",
            timestamp_ms=timestamp_ms,
            payload={"finished": True},
        )
        await self._update_latest_artifact_ms(session_id, timestamp_ms)
        self._cancel_window_task(session_id)
        await self.window_builder_service.build_available_windows(
            session_id=session_id,
            scenario_id=context.scenario_id,
            language=context.language,
            finalizing=True,
        )

    async def generate_final_report(self, session_id: str) -> SessionReport:
        context = await self._ensure_context(session_id)

        progress_key = "collecting"
        try:
            await self.repository.update_state(
                session_id,
                status="processing",
                errorMessage=None,
                progress=self._build_progress_state(
                    current_key="collecting",
                    detail="正在收集文字稿、问答提问和 AI Live Coach 信号。",
                ),
            )
            await self.window_builder_service.build_available_windows(
                session_id=session_id,
                scenario_id=context.scenario_id,
                language=context.language,
                finalizing=False,
            )
            state = await self.repository.get_state(session_id)
            artifacts = await self.artifact_service.read_artifacts(session_id)
            transcript_count = sum(1 for artifact in artifacts if artifact.type in {"transcript_final", "transcript_merged"})
            qa_question_count = sum(1 for artifact in artifacts if artifact.type == "qa_question")
            coach_signal_count = sum(1 for artifact in artifacts if artifact.type == "coach_signal")

            progress_key = "structuring"
            await self.repository.update_state(
                session_id,
                progress=self._build_progress_state(
                    current_key="structuring",
                    detail=(
                        f"已整理 {transcript_count} 段文字稿、"
                        f"{qa_question_count} 个问答问题、"
                        f"{coach_signal_count} 条教练信号。"
                    ),
                ),
            )

            tail_bundle: ReportSignalBundle | None = None
            if state is not None:
                tail_bundle = self.signal_service.build_bundle(
                    language=context.language,
                    artifacts=artifacts,
                    after_ms=state.lastCoveredMs,
                    end_ms=None,
                )
                if not tail_bundle.transcript_chunks and not tail_bundle.qa_questions and not tail_bundle.coach_signals:
                    tail_bundle = None

            window_packs = await self.repository.list_window_packs(session_id)
            logger.info(
                "report.final.begin session=%s windows=%s tail_chunks=%s tail_questions=%s tail_signals=%s",
                session_id,
                len(window_packs),
                len(tail_bundle.transcript_chunks) if tail_bundle else 0,
                len(tail_bundle.qa_questions) if tail_bundle else 0,
                len(tail_bundle.coach_signals) if tail_bundle else 0,
            )

            progress_key = "generating"
            await self.repository.update_state(
                session_id,
                progress=self._build_progress_state(
                    current_key="generating",
                    detail=f"已汇总 {len(window_packs)} 个时间窗口，正在生成完整报告。",
                ),
            )
            report = await self.brain_service.build_final_report(
                session_id=session_id,
                scenario_id=context.scenario_id,
                language=context.language,
                coach_profile_id=context.coach_profile_id,
                window_packs=window_packs,
                tail_bundle=tail_bundle,
            )

            progress_key = "finalizing"
            await self.repository.update_state(
                session_id,
                progress=self._build_progress_state(
                    current_key="finalizing",
                    detail="正在写入最终结果并刷新报告页面。",
                ),
            )
            report = report.model_copy(
                update={
                    "status": "ready",
                    "progress": self._build_progress_state(
                        current_key="finalizing",
                        detail="报告已生成完成。",
                        completed=True,
                    ),
                }
            )
            await self.repository.save_final_report(session_id, report)
            latest_covered_ms = state.lastCoveredMs if state is not None else 0
            if tail_bundle is not None:
                latest_covered_ms = max(latest_covered_ms, tail_bundle.latest_timestamp_ms)
            await self.repository.update_state(
                session_id,
                status="ready",
                finalGeneratedAt=report.generatedAt,
                finalCoveredMs=latest_covered_ms,
                errorMessage=None,
                progress=report.progress,
            )
            logger.info(
                "report.final.done session=%s overall_score=%s dimensions=%s",
                session_id,
                report.overallScore,
                len(report.dimensions),
            )
            return report
        except Exception as error:
            await self.repository.update_state(
                session_id,
                status="failed",
                errorMessage=str(error)[:500],
                progress=self._build_progress_state(
                    current_key=progress_key,
                    detail=f"生成失败：{str(error)[:120]}",
                    failed=True,
                ),
            )
            raise

    async def trigger_final_report(self, session_id: str) -> SessionReport | None:
        state = await self.repository.get_state(session_id)
        if state is None:
            return None
        return await self.generate_final_report(session_id)

    async def get_report(self, session_id: str) -> SessionReport | None:
        state = await self.repository.get_state(session_id)
        report = await self.repository.get_final_report(session_id)
        if report is not None:
            if state is not None and state.status == "failed" and report.status != "ready":
                return report.model_copy(update={"status": "failed"})
            if state is not None:
                return report.model_copy(update={"progress": state.progress})
            return report
        if state is None:
            return None
        await self._ensure_context(session_id, state=state)
        return self._build_placeholder_report(session_id, state)

    async def list_window_packs(self, session_id: str) -> list[ReportWindowPack]:
        return await self.repository.list_window_packs(session_id)

    async def list_artifacts(self, session_id: str) -> list[dict]:
        artifacts = await self.artifact_service.read_artifacts(session_id)
        return [artifact.model_dump() for artifact in artifacts]

    async def get_signals(self, session_id: str) -> dict | None:
        state = await self.repository.get_state(session_id)
        if state is None:
            return None
        context = await self._ensure_context(session_id, state=state)
        artifacts = await self.artifact_service.read_artifacts(session_id)
        bundle = self.signal_service.build_bundle(
            language=context.language,
            artifacts=artifacts,
        )
        return {
            "sessionId": session_id,
            "transcriptStats": bundle.transcript_stats,
            "qaQuestionCount": len(bundle.qa_questions),
            "coachSignalCount": len(bundle.coach_signals),
            "topDimensionMap": bundle.top_dimension_map,
            "latestTimestampMs": bundle.latest_timestamp_ms,
        }

    def _build_progress_state(
        self,
        *,
        current_key: str,
        detail: str | None = None,
        completed: bool = False,
        failed: bool = False,
    ) -> ReportProgressState:
        current_index = REPORT_PROGRESS_STEP_ORDER.index(current_key)
        steps: list[ReportProgressStep] = []
        for index, key in enumerate(REPORT_PROGRESS_STEP_ORDER):
            if completed:
                status = "done"
            elif failed:
                if index < current_index:
                    status = "done"
                elif index == current_index:
                    status = "failed"
                else:
                    status = "pending"
            else:
                if index < current_index:
                    status = "done"
                elif index == current_index:
                    status = "active"
                else:
                    status = "pending"
            step_detail = detail if index == current_index else None
            steps.append(
                ReportProgressStep(
                    key=key,
                    label=REPORT_PROGRESS_STEP_LABELS[key],
                    status=status,
                    detail=step_detail,
                )
            )
        return ReportProgressState(
            currentKey=current_key,
            currentLabel="报告已生成" if completed else REPORT_PROGRESS_STEP_LABELS[current_key],
            detail=detail,
            steps=steps,
        )

    def cancel_session(self, session_id: str) -> None:
        self._cancel_window_task(session_id)

    async def _run_periodic_window_build(self, session_id: str) -> None:
        try:
            while True:
                await asyncio.sleep(self.window_size_ms / 1000)
                context = self._contexts.get(session_id)
                if context is None or context.finished:
                    return
                await self.window_builder_service.build_available_windows(
                    session_id=session_id,
                    scenario_id=context.scenario_id,
                    language=context.language,
                    finalizing=False,
                )
        except asyncio.CancelledError:
            logger.info("report.window_task.cancelled session=%s", session_id)
            return
        except Exception as error:
            logger.exception("report.window_task.failed session=%s error=%s", session_id, error)
            await self.repository.mark_failed(session_id, str(error))

    async def _update_latest_artifact_ms(self, session_id: str, timestamp_ms: int) -> None:
        state = await self.repository.get_state(session_id)
        if state is None:
            return
        if timestamp_ms <= state.latestArtifactMs:
            return
        await self.repository.update_state(session_id, latestArtifactMs=timestamp_ms)

    def _cancel_window_task(self, session_id: str) -> None:
        task = self._window_tasks.pop(session_id, None)
        if task is not None:
            logger.info("report.window_task.cancel session=%s", session_id)
            task.cancel()

    def _on_window_task_done(self, session_id: str, task: asyncio.Task[None]) -> None:
        if self._window_tasks.get(session_id) is task:
            self._window_tasks.pop(session_id, None)

    async def _ensure_context(
        self,
        session_id: str,
        *,
        state=None,
    ) -> ReportJobContext:
        context = self._contexts.get(session_id)
        if context is not None:
            return context
        current_state = state or await self.repository.get_state(session_id)
        if current_state is None:
            raise FileNotFoundError(f"report session {session_id} not found")
        context = ReportJobContext(
            scenario_id=current_state.scenarioId,
            language=current_state.language,
            coach_profile_id=current_state.coachProfileId,
        )
        self._contexts[session_id] = context
        return context

    def _build_placeholder_report(self, session_id: str, state) -> SessionReport:
        is_processing = state.status == "processing"
        return SessionReport(
            sessionId=session_id,
            coachProfileId=state.coachProfileId,
            status=state.status,
            headline="AI 分析中..." if is_processing else "报告暂时不可用",
            encouragement="回放和文字稿已经可看，报告会逐步补全。" if is_processing else (state.errorMessage or "请稍后重试。"),
            summaryParagraph="当前还没有足够的分析结果，稍后会自动刷新。",
            generatedAt=state.finalGeneratedAt or "",
            sectionStatus=ReportSectionStatus(
                summary="processing" if is_processing else "ready",
                radar="processing" if is_processing else "ready",
                suggestions="processing" if is_processing else "ready",
            ),
            progress=state.progress,
        )
