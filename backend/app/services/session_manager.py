import asyncio
import logging
import os
import re
from dataclasses import dataclass, field
from time import monotonic
from uuid import uuid4

from fastapi import WebSocket

from app.schemas import (
    AckEvent,
    CoachPanelEvent,
    ClientMessage,
    ErrorEvent,
    PongEvent,
    QAAudioStreamDeltaEvent,
    QAAudioStreamEndEvent,
    QAAudioStreamStartEvent,
    QAQuestion,
    RealtimeSession,
    RealtimeStatusEvent,
    LanguageOption,
    ScenarioType,
    SessionStatus,
    TranscriptChunk,
    TranscriptFinalEvent,
    TranscriptPartialEvent,
    QAStateEvent,
)
from app.services.coach_panel_service import CoachPanelService
from app.services.omni_service import (
    AliyunOmniCoachService,
    OmniCoachUpdate,
    is_omni_account_access_denied,
    is_omni_body_append_image_before_audio_error,
    is_omni_body_buffer_too_small_error,
    is_omni_internal_service_error,
)
from app.services.qa_mode_orchestrator import QAModeOrchestrator
from app.services.report_job_service import ReportJobService
from app.services.speech_analysis_service import SpeechAnalysisService
from app.services.stt_service import ProviderTranscriptResult, build_stt_service

logger = logging.getLogger("speak_up.session")
logger.setLevel(logging.INFO)


@dataclass
class SessionRecord:
    session_id: str
    scenario_id: ScenarioType
    language: LanguageOption
    status: SessionStatus = "created"
    transcript_count: int = 0
    audio_chunk_count: int = 0
    video_frame_count: int = 0
    started_at_monotonic: float | None = None
    omni_coach_disabled_reason: str | None = None
    omni_body_disabled_reason: str | None = None
    body_lane_retry_after_monotonic: float = 0.0
    body_lane_internal_error_count: int = 0
    body_lane_last_error_at_monotonic: float = 0.0
    speech_preview_last_update_ms: int = 0
    transcript_chunks: list[TranscriptChunk] = field(default_factory=list)
    sockets: list[WebSocket] = field(default_factory=list, repr=False)

    def to_schema(self) -> RealtimeSession:
        return RealtimeSession(
            sessionId=self.session_id,
            scenarioId=self.scenario_id,
            language=self.language,
            status=self.status,
            transcriptCount=self.transcript_count,
            audioChunkCount=self.audio_chunk_count,
            videoFrameCount=self.video_frame_count,
        )


class SessionManager:
    FILLER_TOKENS = {
        "zh": {"嗯", "啊", "额", "呃", "然后", "就是", "哦", "诶", "欸", "哎", "唉", "hmm", "hm", "hmmm", "mhm", "mm", "uh", "um"},
        "en": {"um", "uh", "well", "so", "hmm", "hm", "hmmm", "mhm", "mm"},
    }
    QA_FALLBACK_FILLER_TOKENS = {
        "zh": {
            "嗯",
            "啊",
            "额",
            "呃",
            "哦",
            "诶",
            "欸",
            "哎",
            "唉",
            "好",
            "好的",
            "嗯嗯",
            "哦哦",
            "好的好",
            "收到",
            "hmm",
            "hm",
            "hmmm",
            "mhm",
            "mm",
            "uh",
            "um",
        },
        "en": {"um", "uh", "well", "so", "ok", "okay", "sure", "got it", "hmm", "hm", "hmmm", "mhm", "mm"},
    }

    def __init__(self) -> None:
        self.sessions: dict[str, SessionRecord] = {}
        self.qa_prewarm_tasks: dict[str, asyncio.Task[None]] = {}
        self.qa_prewarm_refresh_tasks: dict[str, asyncio.Task[None]] = {}
        self.qa_auto_advance_tasks: dict[str, asyncio.Task[None]] = {}
        self.qa_silence_fallback_tasks: dict[str, asyncio.Task[None]] = {}
        self.qa_active_audio_turns: dict[str, str] = {}
        self.qa_pending_response_done: dict[str, tuple[str, str]] = {}
        self.qa_response_done_grace_tasks: dict[str, asyncio.Task[None]] = {}
        self.qa_answer_audio_started_at_ms: dict[str, int] = {}
        self.qa_prewarm_interval_seconds = max(5, int(os.getenv("QA_PREWARM_INTERVAL_SECONDS", "20")))
        self.qa_prewarm_trigger_delay_seconds = max(
            0.0,
            float(os.getenv("QA_PREWARM_TRIGGER_DELAY_MS", "1500")) / 1000,
        )
        self.qa_auto_advance_delay_seconds = max(1.0, float(os.getenv("QA_AUTO_ADVANCE_DELAY_MS", "1200")) / 1000)
        self.qa_response_done_audio_grace_seconds = max(
            0.2,
            float(os.getenv("QA_RESPONSE_DONE_AUDIO_GRACE_MS", "1200")) / 1000,
        )
        self.qa_silence_fallback_delay_seconds = max(
            3.0,
            float(os.getenv("QA_SILENCE_FALLBACK_DELAY_MS", "10000")) / 1000,
        )
        self.body_lane_internal_error_disable_threshold = max(
            2,
            int(os.getenv("OMNI_BODY_INTERNAL_ERROR_DISABLE_THRESHOLD", "3")),
        )
        self.body_lane_internal_error_window_seconds = max(
            10.0,
            float(os.getenv("OMNI_BODY_INTERNAL_ERROR_WINDOW_SECONDS", "60")),
        )
        self.body_lane_internal_error_backoff_seconds = max(
            3.0,
            float(os.getenv("OMNI_BODY_INTERNAL_ERROR_BACKOFF_SECONDS", "5")),
        )
        self.stt_service = build_stt_service()
        self.omni_coach_service = AliyunOmniCoachService(analysis_scope="voice_content", turn_mode="vad")
        self.omni_body_service = AliyunOmniCoachService(analysis_scope="body_visual", turn_mode="manual")
        self.speech_analysis_service = SpeechAnalysisService()
        self.coach_panel_service = CoachPanelService()
        self.qa_mode_orchestrator = QAModeOrchestrator()
        self.report_job_service = ReportJobService()

    def create_session(self, scenario_id: ScenarioType, language: LanguageOption) -> SessionRecord:
        session_id = uuid4().hex
        session = SessionRecord(
            session_id=session_id,
            scenario_id=scenario_id,
            language=language,
        )
        self.coach_panel_service.get_or_create_panel(session_id, language)
        self.qa_mode_orchestrator.register_session(session_id, scenario_id, language)
        self.sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> SessionRecord | None:
        return self.sessions.get(session_id)

    async def finish_session(self, session_id: str) -> SessionRecord | None:
        session = self.sessions.get(session_id)
        if session is None:
            return None

        session.status = "finished"
        await self._mark_report_session_finished(session, self._build_elapsed_ms(session))

        try:
            await self.stt_service.finish_session(session_id)
        except Exception as error:
            await self._broadcast(session, ErrorEvent(message=f"结束实时转写时出错：{error}").model_dump())

        try:
            await self.omni_coach_service.finish_session(session_id)
        except Exception:
            pass
        try:
            await self.omni_body_service.finish_session(session_id)
        except Exception:
            pass
        try:
            await self.qa_mode_orchestrator.qa_omni_service.finish_session(session_id)
        except Exception:
            pass

        self._cancel_qa_prewarm_task(session_id)
        self._cancel_qa_prewarm_refresh_task(session_id)
        self._clear_qa_runtime_state(session_id)
        self.speech_analysis_service.close_session(session_id)
        self.coach_panel_service.close_session(session_id)
        self.qa_mode_orchestrator.close_session(session_id)
        await self.broadcast_status(session)
        return session

    def get_replay(self, session_id: str) -> dict | None:
        session = self.sessions.get(session_id)
        if session is None:
            return None

        return {
            "sessionId": session.session_id,
            "scenarioId": session.scenario_id,
            "language": session.language,
            "mediaUrl": None,
            "mediaType": None,
            "transcript": [chunk.model_dump() for chunk in session.transcript_chunks],
        }

    async def connect(self, session: SessionRecord, websocket: WebSocket) -> None:
        await websocket.accept()
        session.sockets.append(websocket)
        await websocket.send_json(RealtimeStatusEvent(sessionId=session.session_id, status=session.status).model_dump())
        await websocket.send_json(
            CoachPanelEvent(
                coachPanel=self.coach_panel_service.get_or_create_panel(session.session_id, session.language)
            ).model_dump()
        )
        await websocket.send_json(QAStateEvent(qaState=self.qa_mode_orchestrator.get_state(session.session_id)).model_dump())
        await websocket.send_json(self.qa_mode_orchestrator.build_voice_profiles_event().model_dump())

    def disconnect(self, session: SessionRecord, websocket: WebSocket) -> None:
        if websocket in session.sockets:
            session.sockets.remove(websocket)
        if not session.sockets:
            self._cancel_qa_prewarm_task(session.session_id)
            self._cancel_qa_prewarm_refresh_task(session.session_id)
            self._clear_qa_runtime_state(session.session_id)
            self.speech_analysis_service.close_session(session.session_id)
            self.coach_panel_service.close_session(session.session_id)
            self.qa_mode_orchestrator.close_session(session.session_id)
            if session.status != "finished":
                self.report_job_service.cancel_session(session.session_id)
            asyncio.create_task(self.stt_service.close_session(session.session_id))
            asyncio.create_task(self.omni_coach_service.close_session(session.session_id))
            asyncio.create_task(self.omni_body_service.close_session(session.session_id))
            asyncio.create_task(self.qa_mode_orchestrator.qa_omni_service.close_session(session.session_id))

    async def handle_client_message(self, session: SessionRecord, message: ClientMessage, websocket: WebSocket) -> None:
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
                    on_partial=lambda text: self.broadcast_partial(session, text),
                    on_final=lambda result: self._broadcast_provider_transcript(session, result),
                    on_error=lambda message: self._broadcast_provider_error(session, message),
                    on_event=lambda stage, event, meta=None: self._handle_stt_provider_event(
                        session.session_id,
                        stage,
                        event,
                        meta,
                    ),
                )
            except Exception as error:
                await websocket.send_json(ErrorEvent(message=str(error)).model_dump())
                return

            if session.omni_coach_disabled_reason is None:
                try:
                    await self.omni_coach_service.connect_session(
                        session.session_id,
                        session.scenario_id,
                        session.language,
                        on_insight=lambda update: self._broadcast_omni_update(session, update),
                        on_error=lambda message: self._handle_omni_provider_error(session, "coach", message),
                        on_event=None,
                    )
                except Exception as error:
                    await self._handle_omni_connect_failure(session, "coach", error)
            if session.omni_body_disabled_reason is None:
                try:
                    await self.omni_body_service.connect_session(
                        session.session_id,
                        session.scenario_id,
                        session.language,
                        on_insight=lambda update: self._broadcast_omni_update(session, update),
                        on_error=lambda message: self._handle_omni_provider_error(session, "body", message),
                        on_event=None,
                    )
                except Exception as error:
                    await self._handle_omni_connect_failure(session, "body", error)
                    session.body_lane_retry_after_monotonic = monotonic() + 2.0

            self.qa_mode_orchestrator.configure_prewarm_context(
                session_id=session.session_id,
                training_mode=message.training_mode or "free_speech",
                document_name=message.document_name,
                document_text=message.document_text,
                manual_text=message.manual_text,
            )
            session.status = "streaming"
            session.started_at_monotonic = monotonic()
            session.body_lane_retry_after_monotonic = 0.0
            self.report_job_service.start_periodic_build(session.session_id)
            self._launch_qa_prewarm_task(session)
            self._schedule_qa_prewarm_refresh(session.session_id, reason="stream_started", delay_seconds=0.0)
            await self.broadcast_status(session)
            return

        if message.type == "audio_chunk":
            session.audio_chunk_count += 1
            try:
                await self.stt_service.send_audio_chunk(session.session_id, message.payload)
            except Exception as error:
                await websocket.send_json(ErrorEvent(message=str(error)).model_dump())
                return

            if session.omni_coach_disabled_reason is None:
                try:
                    await self.omni_coach_service.send_audio_chunk(session.session_id, message.payload)
                except Exception as error:
                    await self._handle_omni_send_failure(session, "coach", f"发送音频到 Omni coach 失败：{error}")
            if session.omni_body_disabled_reason is None:
                try:
                    await self._ensure_body_lane_connected(session)
                    await self.omni_body_service.send_audio_chunk(session.session_id, message.payload)
                except Exception as error:
                    await self._handle_omni_send_failure(session, "body", f"发送音频到 Omni body coach 失败：{error}")
            if self.qa_mode_orchestrator.is_user_answering(session.session_id):
                try:
                    await self.qa_mode_orchestrator.qa_omni_service.send_audio_chunk(session.session_id, message.payload)
                except Exception as error:
                    await self._handle_qa_provider_error(
                        session.session_id,
                        f"发送音频到 QA Omni Realtime 失败：{error}",
                    )

            return

        if message.type == "video_frame":
            session.video_frame_count += 1
            if session.omni_body_disabled_reason is not None:
                return
            try:
                await self._ensure_body_lane_connected(session)
                await self.omni_body_service.send_video_frame(session.session_id, message.image_base64)
            except Exception as error:
                await self._handle_omni_send_failure(session, "body", f"发送视频帧到 Omni body coach 失败：{error}")
            return

        if message.type == "start_qa":
            logger.info(
                "qa.start_request session=%s mode=%s transcript_chunks=%s has_document=%s has_manual=%s",
                session.session_id,
                message.training_mode or "free_speech",
                len(session.transcript_chunks),
                bool(message.document_text),
                bool(message.manual_text),
            )
            self._clear_qa_runtime_state(session.session_id)
            events = self.qa_mode_orchestrator.prepare_start_qa(
                session_id=session.session_id,
                training_mode=message.training_mode or "free_speech",
                voice_profile_id=message.voice_profile_id,
                document_name=message.document_name,
                document_text=message.document_text,
                manual_text=message.manual_text,
            )
            for event in events:
                await self._broadcast_runtime_event(session, event)
            try:
                await self._connect_qa_realtime_session(session)
                await self._bootstrap_qa_first_question(session)
            except Exception as error:
                logger.exception("qa.realtime.start_failed session=%s error=%s", session.session_id, error)
                rollback_events = self.qa_mode_orchestrator.stop_qa(session_id=session.session_id)
                for event in rollback_events:
                    await self._broadcast_runtime_event(session, event)
                await self._broadcast(session, ErrorEvent(message=f"启动问答失败：{error}").model_dump())
            return

        if message.type == "qa_prewarm_context":
            self.qa_mode_orchestrator.configure_prewarm_context(
                session_id=session.session_id,
                training_mode=message.training_mode or "free_speech",
                document_name=message.document_name,
                document_text=message.document_text,
                manual_text=message.manual_text,
            )
            if session.status == "streaming":
                self._schedule_qa_prewarm_refresh(session.session_id, reason="context_updated", delay_seconds=0.0)
            elif self.qa_mode_orchestrator.is_enabled(session.session_id):
                await self._refresh_qa_realtime_instructions(session)
            await websocket.send_json(AckEvent(message="qa prewarm context updated").model_dump())
            return

        if message.type == "qa_request_question":
            logger.info(
                "qa.next_request session=%s transcript_chunks=%s",
                session.session_id,
                len(session.transcript_chunks),
            )
            self._clear_qa_runtime_state(session.session_id)
            if self.qa_mode_orchestrator.is_enabled(session.session_id):
                events = self.qa_mode_orchestrator.prepare_next_question(session_id=session.session_id)
                for event in events:
                    await self._broadcast_runtime_event(session, event)
                await self._bootstrap_qa_first_question(session)
            return

        if message.type == "qa_stop_answer":
            try:
                self._clear_qa_runtime_state(session.session_id)
                await self._commit_qa_user_turn(session)
            except Exception as error:
                await self._broadcast(session, ErrorEvent(message=f"结束回答失败：{error}").model_dump())
            return

        if message.type == "qa_select_voice_profile":
            events = self.qa_mode_orchestrator.select_voice_profile(
                session_id=session.session_id,
                voice_profile_id=message.voice_profile_id,
            )
            for event in events:
                await self._broadcast_runtime_event(session, event)
            if self.qa_mode_orchestrator.is_enabled(session.session_id):
                await self._refresh_qa_realtime_instructions(session)
            return

        if message.type == "qa_audio_playback_started":
            await self._handle_qa_audio_playback_started(session, message.turn_id or "")
            return

        if message.type == "qa_audio_playback_ended":
            await self._handle_qa_audio_playback_ended(session, message.turn_id or "")
            return

        if message.type == "stop_qa":
            self._clear_qa_runtime_state(session.session_id)
            await self.qa_mode_orchestrator.qa_omni_service.close_session(session.session_id)
            events = self.qa_mode_orchestrator.stop_qa(session_id=session.session_id)
            for event in events:
                await self._broadcast_runtime_event(session, event)
            return

        await websocket.send_json(ErrorEvent(message="unsupported message type").model_dump())

    async def broadcast_status(self, session: SessionRecord) -> None:
        await self._broadcast(session, RealtimeStatusEvent(sessionId=session.session_id, status=session.status).model_dump())

    async def broadcast_partial(self, session: SessionRecord, text: str) -> None:
        if text.strip() and self.qa_mode_orchestrator.is_user_answering(session.session_id):
            self.qa_mode_orchestrator.update_live_partial_answer(session.session_id, text)
            self._cancel_qa_auto_advance_task(session.session_id)
            self._schedule_qa_silence_fallback(session, reason="user_partial")
        await self._maybe_broadcast_speech_preview(session, text)
        await self._broadcast(session, TranscriptPartialEvent(text=text).model_dump())

    async def _maybe_broadcast_speech_preview(self, session: SessionRecord, text: str) -> None:
        if session.status != "streaming" or not text.strip():
            return

        now_ms = self._build_elapsed_ms(session)
        if session.speech_preview_last_update_ms and now_ms - session.speech_preview_last_update_ms < 800:
            return

        session.speech_preview_last_update_ms = now_ms
        speech_update = self.speech_analysis_service.preview_partial(
            session.session_id,
            session.language,
            text,
            timestamp_ms=now_ms,
        )
        if speech_update is None:
            return

        coach_panel = self.coach_panel_service.update_from_speech(
            session.session_id,
            session.language,
            speech_update,
            now_ms,
            allow_replace_omni=False,
        )
        if coach_panel is not None:
            await self._broadcast(session, CoachPanelEvent(coachPanel=coach_panel).model_dump())

    async def broadcast_transcript(self, session: SessionRecord, chunk: TranscriptChunk) -> None:
        previous_chunk = session.transcript_chunks[-1] if session.transcript_chunks else None
        if previous_chunk and previous_chunk.speaker == chunk.speaker and self._is_filler_fragment(session.language, chunk.text):
            merged_chunk = self._merge_transcript_chunks(session.language, previous_chunk, chunk)
            session.transcript_chunks[-1] = merged_chunk
            await self._broadcast(session, TranscriptFinalEvent(chunk=merged_chunk, replacePrevious=True).model_dump())
            await self._record_report_transcript_chunk(session.session_id, merged_chunk, replace_previous=True)
            accepted_for_qa = self._accept_qa_user_transcript(session, merged_chunk)
            if accepted_for_qa:
                self.qa_mode_orchestrator.replace_last_transcript_chunk(session.session_id, merged_chunk)
            if merged_chunk.speaker == "user" and session.status == "streaming":
                self._schedule_qa_prewarm_refresh(session.session_id, reason="transcript_merged")
            if (
                accepted_for_qa
                and self.qa_mode_orchestrator.qa_omni_service.has_pending_user_audio(session.session_id)
            ):
                if self._should_auto_advance_qa_answer(session):
                    self._ensure_qa_auto_advance_scheduled(session, reason="user_transcript_merged")
                else:
                    self._cancel_qa_auto_advance_task(session.session_id)
                self._schedule_qa_silence_fallback(session, reason="user_transcript_merged")
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
            return

        session.transcript_count += 1
        session.transcript_chunks.append(chunk)
        await self._broadcast(session, TranscriptFinalEvent(chunk=chunk).model_dump())
        await self._record_report_transcript_chunk(session.session_id, chunk, replace_previous=False)
        accepted_for_qa = self._accept_qa_user_transcript(session, chunk)
        if accepted_for_qa:
            self.qa_mode_orchestrator.ingest_transcript_chunk(session.session_id, chunk)
        if chunk.speaker == "user" and session.status == "streaming":
            self._schedule_qa_prewarm_refresh(session.session_id, reason="transcript_final")
        if (
            accepted_for_qa
            and self.qa_mode_orchestrator.qa_omni_service.has_pending_user_audio(session.session_id)
        ):
            if self._should_auto_advance_qa_answer(session):
                self._ensure_qa_auto_advance_scheduled(session, reason="user_transcript_final")
            else:
                self._cancel_qa_auto_advance_task(session.session_id)
            self._schedule_qa_silence_fallback(session, reason="user_transcript_final")
        speech_update = self.speech_analysis_service.ingest_chunk(session.session_id, session.language, chunk)
        coach_panel = self.coach_panel_service.update_from_speech(
            session.session_id,
            session.language,
            speech_update,
            chunk.endMs,
        )
        if coach_panel is not None:
            await self._broadcast(session, CoachPanelEvent(coachPanel=coach_panel).model_dump())

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
        await self.broadcast_transcript(session, chunk)

    async def _broadcast_provider_error(self, session: SessionRecord, message: str) -> None:
        await self._broadcast(session, ErrorEvent(message=message).model_dump())

    async def _broadcast_omni_update(self, session: SessionRecord, update: OmniCoachUpdate) -> None:
        updated_at_ms = self._build_elapsed_ms(session)

        if update.patch is not None:
            await self._record_report_coach_patch(session, update.patch, updated_at_ms)
            coach_panel = self.coach_panel_service.update_from_omni_patch(
                session.session_id,
                session.language,
                update.patch,
                updated_at_ms,
            )
            if coach_panel is not None:
                await self._record_report_panel_snapshot(session, coach_panel, updated_at_ms)
                await self._broadcast(session, CoachPanelEvent(coachPanel=coach_panel).model_dump())

    async def _record_omni_error(self, session: SessionRecord, message: str) -> None:
        await self._broadcast(session, ErrorEvent(message=message).model_dump())

    async def _record_report_transcript_chunk(
        self,
        session_id: str,
        chunk: TranscriptChunk,
        *,
        replace_previous: bool,
    ) -> None:
        try:
            await self.report_job_service.record_transcript_chunk(
                session_id,
                chunk,
                replace_previous=replace_previous,
            )
        except Exception as error:
            logger.exception(
                "report.artifact.transcript_failed session=%s replace_previous=%s error=%s",
                session_id,
                replace_previous,
                error,
            )

    async def _record_report_coach_patch(
        self,
        session: SessionRecord,
        patch,
        timestamp_ms: int,
    ) -> None:
        try:
            await self.report_job_service.record_coach_patch(
                session_id=session.session_id,
                patch=patch,
                timestamp_ms=timestamp_ms,
                source="omni-coach",
            )
        except Exception as error:
            logger.exception(
                "report.artifact.coach_patch_failed session=%s error=%s",
                session.session_id,
                error,
            )

    async def _record_report_qa_question_payload(self, session: SessionRecord, payload: dict) -> None:
        try:
            if payload.get("type") != "qa_question":
                return
            if not self.qa_mode_orchestrator.is_user_answering(session.session_id):
                return
            question = payload.get("question")
            if not isinstance(question, dict):
                return
            await self.report_job_service.record_qa_question(
                session_id=session.session_id,
                question=QAQuestion.model_validate(question),
                timestamp_ms=self._build_elapsed_ms(session),
            )
        except Exception as error:
            logger.exception(
                "report.artifact.qa_question_failed session=%s error=%s",
                session.session_id,
                error,
            )

    async def _broadcast_runtime_event(self, session: SessionRecord, event) -> None:
        payload = event if isinstance(event, dict) else event.model_dump()
        await self._broadcast(session, payload)
        await self._record_report_qa_question_payload(session, payload)

    async def _record_report_panel_snapshot(
        self,
        session: SessionRecord,
        panel,
        timestamp_ms: int,
    ) -> None:
        try:
            await self.report_job_service.record_panel_snapshot(
                session_id=session.session_id,
                panel=panel,
                timestamp_ms=timestamp_ms,
            )
        except Exception as error:
            logger.exception(
                "report.artifact.panel_snapshot_failed session=%s error=%s",
                session.session_id,
                error,
            )

    async def _mark_report_session_finished(self, session: SessionRecord, timestamp_ms: int) -> None:
        try:
            await self.report_job_service.mark_session_finished(
                session.session_id,
                timestamp_ms=timestamp_ms,
            )
        except Exception as error:
            logger.exception(
                "report.session_finished_failed session=%s error=%s",
                session.session_id,
                error,
            )

    async def _handle_omni_connect_failure(self, session: SessionRecord, lane: str, error: Exception) -> None:
        lane_label = "Omni coach" if lane == "coach" else "Omni body coach"
        await self._handle_omni_failure(session, lane, f"{lane_label} 连接失败：{error}")

    async def _handle_omni_send_failure(self, session: SessionRecord, lane: str, message: str) -> None:
        await self._handle_omni_failure(session, lane, message)

    async def _handle_omni_provider_error(self, session: SessionRecord, lane: str, message: str) -> None:
        lane_label = "Omni coach" if lane == "coach" else "Omni body coach"
        await self._handle_omni_failure(session, lane, f"{lane_label} 服务返回错误：{message}")

    async def _handle_omni_failure(self, session: SessionRecord, lane: str, message: str) -> None:
        if is_omni_account_access_denied(message):
            await self._disable_omni_for_account_access(session, message)
            return

        if lane == "body":
            if is_omni_body_buffer_too_small_error(message):
                logger.warning(
                    "omni.body.audio_underflow.soft_ignored session=%s message=%s",
                    session.session_id,
                    message[:240],
                )
                return
            if is_omni_body_append_image_before_audio_error(message):
                logger.warning(
                    "omni.body.append_image_before_audio.soft_ignored session=%s message=%s",
                    session.session_id,
                    message[:240],
                )
                return
            if is_omni_internal_service_error(message):
                await self._handle_body_lane_internal_error(session, message)
                return
            await self._record_omni_error(session, message)
            await self.omni_body_service.close_session(session.session_id)
            session.body_lane_retry_after_monotonic = monotonic() + 2.0
            return

        await self._record_omni_error(session, message)

        if lane == "coach":
            await self.omni_coach_service.close_session(session.session_id)

    async def _handle_body_lane_internal_error(self, session: SessionRecord, raw_message: str) -> None:
        now = monotonic()
        if now - session.body_lane_last_error_at_monotonic > self.body_lane_internal_error_window_seconds:
            session.body_lane_internal_error_count = 0
        session.body_lane_last_error_at_monotonic = now
        session.body_lane_internal_error_count += 1

        await self.omni_body_service.close_session(session.session_id)

        if session.body_lane_internal_error_count >= self.body_lane_internal_error_disable_threshold:
            session.omni_body_disabled_reason = "disabled_after_internal_errors"
            session.body_lane_retry_after_monotonic = float("inf")
            logger.warning(
                "omni.body.internal_error.soft_ignored_disable session=%s count=%s message=%s",
                session.session_id,
                session.body_lane_internal_error_count,
                raw_message[:240],
            )
            return

        cooldown_seconds = min(
            30.0,
            session.body_lane_internal_error_count * self.body_lane_internal_error_backoff_seconds,
        )
        session.body_lane_retry_after_monotonic = now + cooldown_seconds
        logger.warning(
            "omni.body.internal_error.soft_ignored_retry session=%s count=%s retry_after_s=%s message=%s",
            session.session_id,
            session.body_lane_internal_error_count,
            int(cooldown_seconds),
            raw_message[:240],
        )

    async def _disable_omni_for_account_access(self, session: SessionRecord, raw_message: str) -> None:
        reason = (
            "阿里云 Omni Live Coach 被云侧拒绝：当前 API Key 对应账号存在计费/权限状态异常。"
            "已停止本轮 Omni coach 发送，ASR 转写和本地规则反馈会继续运行；请在阿里云百炼确认账号余额、免费额度用完即停、API Key 所属账号与模型权限。"
        )
        first_report = session.omni_coach_disabled_reason is None and session.omni_body_disabled_reason is None
        session.omni_coach_disabled_reason = reason
        session.omni_body_disabled_reason = reason
        session.body_lane_retry_after_monotonic = float("inf")
        await self.omni_coach_service.close_session(session.session_id)
        await self.omni_body_service.close_session(session.session_id)
        logger.warning(
            "omni.account_access_denied session=%s message=%s",
            session.session_id,
            raw_message[:240],
        )
        if first_report:
            await self._record_omni_error(session, reason)

    async def _connect_qa_realtime_session(self, session: SessionRecord) -> None:
        instructions = self.qa_mode_orchestrator.build_realtime_instructions(
            session_id=session.session_id,
            transcript_chunks=list(session.transcript_chunks),
        )
        profile = self.qa_mode_orchestrator.get_voice_profile_config(session.session_id)
        await self.qa_mode_orchestrator.qa_omni_service.close_session(session.session_id)
        await self.qa_mode_orchestrator.qa_omni_service.connect_session(
            session_id=session.session_id,
            scenario_id=session.scenario_id,
            language=session.language,
            instructions=instructions,
            profile=profile,
            on_event=lambda stage, event, meta: self._handle_qa_provider_event(session.session_id, stage, event, meta),
            on_error=lambda message: self._handle_qa_provider_error(session.session_id, message),
        )
        logger.info(
            "qa.realtime.connected session=%s voice=%s transcript_chunks=%s",
            session.session_id,
            profile.profile.id,
            len(session.transcript_chunks),
        )

    async def _refresh_qa_realtime_instructions(self, session: SessionRecord, *, wait_for_provider_ack: bool = True) -> None:
        if not self.qa_mode_orchestrator.qa_omni_service.is_connected(session.session_id):
            return
        instructions = self.qa_mode_orchestrator.build_realtime_instructions(
            session_id=session.session_id,
            transcript_chunks=list(session.transcript_chunks),
        )
        profile = self.qa_mode_orchestrator.get_voice_profile_config(session.session_id)
        await self.qa_mode_orchestrator.qa_omni_service.update_session(
            session_id=session.session_id,
            instructions=instructions,
            profile=profile,
            wait_for_ack=wait_for_provider_ack,
        )
        logger.info(
            "qa.realtime.instructions_updated session=%s brief_builds=%s transcript_chunks=%s wait_ack=%s",
            session.session_id,
            self.qa_mode_orchestrator.sessions[session.session_id].prewarm_build_count,
            len(session.transcript_chunks),
            wait_for_provider_ack,
        )

    async def _bootstrap_qa_first_question(self, session: SessionRecord) -> None:
        if not await self.qa_mode_orchestrator.qa_omni_service.bootstrap_first_question(session.session_id):
            raise RuntimeError("QA Omni Realtime 未能触发首问")
        logger.info("qa.realtime.bootstrap session=%s", session.session_id)

    async def _commit_qa_user_turn(self, session: SessionRecord) -> None:
        plan, events = self.qa_mode_orchestrator.prepare_after_answer(session_id=session.session_id)
        for event in events:
            await self._broadcast_runtime_event(session, event)
        if plan.action == "end_qa":
            await self.qa_mode_orchestrator.qa_omni_service.close_session(session.session_id)
            logger.info(
                "qa.realtime.completed session=%s total_questions=%s max_follow_ups=%s",
                session.session_id,
                self.qa_mode_orchestrator.sessions[session.session_id].max_question_topics,
                self.qa_mode_orchestrator.sessions[session.session_id].max_follow_ups_per_question,
            )
            return
        await self._refresh_qa_realtime_instructions(session, wait_for_provider_ack=False)
        committed = await self.qa_mode_orchestrator.qa_omni_service.commit_user_turn(session.session_id)
        if not committed:
            raise RuntimeError("QA Omni Realtime 当前没有可提交的用户音频")
        logger.info(
            "qa.realtime.user_turn_committed session=%s action=%s next_question=%s next_round=%s",
            session.session_id,
            plan.action,
            plan.question_index,
            plan.round_index,
        )

    async def _flush_pending_qa_prompt(self, session: SessionRecord, *, turn_id: str, reason: str) -> bool:
        pending = self.qa_pending_response_done.get(session.session_id)
        if pending is None or pending[0] != turn_id:
            return False

        self.qa_pending_response_done.pop(session.session_id, None)
        self._cancel_qa_response_done_grace_task(session.session_id)
        for next_event in self.qa_mode_orchestrator.handle_assistant_transcript(
            session_id=session.session_id,
            turn_id=turn_id,
            text=pending[1],
            is_final=True,
        ):
            await self._broadcast_runtime_event(session, next_event)
        self._mark_qa_answer_window_open(session)
        self._schedule_qa_silence_fallback(session, reason=reason)
        logger.info(
            "qa.realtime.response_done.flush session=%s turn=%s reason=%s text=%s",
            session.session_id,
            turn_id,
            reason,
            pending[1][:160],
        )
        return True

    async def _handle_qa_audio_playback_started(self, session: SessionRecord, turn_id: str) -> None:
        if not turn_id:
            return
        self._cancel_qa_response_done_grace_task(session.session_id)
        self._cancel_qa_silence_fallback_task(session.session_id)
        self.qa_active_audio_turns[session.session_id] = turn_id
        logger.info("qa.audio_playback.started session=%s turn=%s", session.session_id, turn_id)

    async def _handle_qa_audio_playback_ended(self, session: SessionRecord, turn_id: str) -> None:
        if not turn_id:
            return
        if self.qa_active_audio_turns.get(session.session_id) == turn_id:
            self.qa_active_audio_turns.pop(session.session_id, None)
        flushed = await self._flush_pending_qa_prompt(
            session,
            turn_id=turn_id,
            reason="assistant_client_audio_end",
        )
        if not flushed and self.qa_mode_orchestrator.is_user_answering(session.session_id):
            self._schedule_qa_silence_fallback(session, reason="assistant_client_audio_end")
        logger.info("qa.audio_playback.ended session=%s turn=%s flushed=%s", session.session_id, turn_id, flushed)

    async def _handle_qa_provider_event(
        self,
        session_id: str,
        stage: str,
        event: dict,
        metadata: dict | None,
    ) -> None:
        session = self.sessions.get(session_id)
        if session is None:
            return
        meta = metadata or {}

        if stage == "assistant_turn_started":
            turn_id = str(meta.get("turnId", ""))
            for next_event in self.qa_mode_orchestrator.handle_assistant_turn_started(
                session_id=session_id,
                turn_id=turn_id,
            ):
                await self._broadcast(session, next_event.model_dump())
            self._clear_qa_runtime_state(session_id)
            return

        if stage == "assistant_text_delta":
            turn_id = str(meta.get("turnId", ""))
            text = str(meta.get("text", "")).strip()
            if not turn_id or not text:
                return
            display_text = self._trim_assistant_question_text(text)
            if self._should_cancel_assistant_self_answer(text):
                logger.warning(
                    "qa.assistant_response_trimmed session=%s turn=%s reason=self_answer_overflow text=%s",
                    session_id,
                    turn_id,
                    text[:200],
                )
            for next_event in self.qa_mode_orchestrator.handle_assistant_transcript(
                session_id=session_id,
                turn_id=turn_id,
                text=display_text,
                is_final=False,
            ):
                await self._broadcast(session, next_event.model_dump())
            return

        if stage == "assistant_audio_start":
            turn_id = str(meta.get("turnId", ""))
            if not turn_id:
                return
            self._cancel_qa_response_done_grace_task(session_id)
            await self._broadcast(
                session,
                QAAudioStreamStartEvent(
                    turnId=turn_id,
                    sampleRateHz=int(meta.get("sampleRateHz", 24000)),
                    channels=1,
                    voiceProfileId=str(meta.get("voiceProfileId", "")),
                ).model_dump(),
            )
            return

        if stage == "assistant_audio_delta":
            turn_id = str(meta.get("turnId", ""))
            audio_base64 = str(meta.get("audioBase64", ""))
            if not turn_id or not audio_base64:
                return
            await self._broadcast(
                session,
                QAAudioStreamDeltaEvent(
                    turnId=turn_id,
                    audioBase64=audio_base64,
                    sampleRateHz=int(meta.get("sampleRateHz", 24000)),
                ).model_dump(),
            )
            return

        if stage == "assistant_audio_end":
            turn_id = str(meta.get("turnId", ""))
            if not turn_id:
                return
            await self._broadcast(
                session,
                QAAudioStreamEndEvent(
                    turnId=turn_id,
                    durationMs=int(meta.get("durationMs", 1)),
                    audioUrl=str(meta.get("audioUrl", "")),
                    voiceProfileId=str(meta.get("voiceProfileId", "")),
                ).model_dump(),
            )
            if self.qa_active_audio_turns.get(session_id) != turn_id:
                await self._flush_pending_qa_prompt(
                    session,
                    turn_id=turn_id,
                    reason="assistant_audio_end",
                )
            return

        if stage == "assistant_response_done":
            turn_id = str(meta.get("turnId", ""))
            text = str(meta.get("text", "")).strip()
            if not turn_id:
                return
            display_text = self._trim_assistant_question_text(text)
            self.qa_pending_response_done[session_id] = (turn_id, display_text)
            if self.qa_active_audio_turns.get(session_id) == turn_id:
                for next_event in self.qa_mode_orchestrator.handle_assistant_transcript(
                    session_id=session_id,
                    turn_id=turn_id,
                    text=display_text,
                    is_final=False,
                ):
                    await self._broadcast_runtime_event(session, next_event)
                logger.info(
                    "qa.realtime.response_done.deferred_until_audio_end session=%s turn=%s text=%s",
                    session_id,
                    turn_id,
                    display_text[:160],
                )
                return
            for next_event in self.qa_mode_orchestrator.handle_assistant_transcript(
                session_id=session_id,
                turn_id=turn_id,
                text=display_text,
                is_final=False,
            ):
                await self._broadcast_runtime_event(session, next_event)
            self._schedule_qa_response_done_grace(session, turn_id=turn_id)
            logger.info(
                "qa.realtime.response_done.wait_audio_grace session=%s turn=%s text=%s",
                session_id,
                turn_id,
                display_text[:160],
            )
            return

        if stage == "user_transcript":
            transcript = str(meta.get("transcript", "")).strip()
            if transcript:
                logger.info("qa.realtime.user_transcript session=%s text=%s", session_id, transcript[:160])
            return

        if stage == "session_updated":
            logger.info("qa.realtime.session_updated session=%s", session_id)
            return

    async def _handle_qa_provider_error(self, session_id: str, message: str) -> None:
        session = self.sessions.get(session_id)
        if session is None:
            return
        await self._broadcast(session, ErrorEvent(message=message).model_dump())
        await self.qa_mode_orchestrator.qa_omni_service.close_session(session_id)
        if self.qa_mode_orchestrator.is_enabled(session_id):
            for event in self.qa_mode_orchestrator.stop_qa(session_id=session_id):
                await self._broadcast_runtime_event(session, event)

    async def _handle_stt_provider_event(
        self,
        session_id: str,
        stage: str,
        event: dict,
        metadata: dict | None,
    ) -> None:
        session = self.sessions.get(session_id)
        if session is None or not self.qa_mode_orchestrator.is_user_answering(session_id):
            return

        if stage == "speech_started":
            start_ms = metadata.get("startMs") if metadata else None
            if isinstance(start_ms, int):
                self.qa_answer_audio_started_at_ms[session_id] = start_ms
            self._cancel_qa_auto_advance_task(session_id)
            logger.info("qa.asr.speech_started session=%s start_ms=%s", session_id, start_ms)
            return

        if stage == "speech_stopped":
            answer_text = self._current_qa_answer_text(session_id)
            logger.info(
                "qa.asr.speech_stopped session=%s answer_chars=%s",
                session_id,
                len(re.sub(r"\s+", "", answer_text)),
            )
            if self._should_auto_advance_qa_answer(session):
                self._ensure_qa_auto_advance_scheduled(session, reason="asr_speech_stopped")
            return

    def _launch_qa_prewarm_task(self, session: SessionRecord) -> None:
        if session.session_id in self.qa_prewarm_tasks:
            return
        logger.info("qa.prewarm_task.launch session=%s interval_s=%s", session.session_id, self.qa_prewarm_interval_seconds)
        task = asyncio.create_task(self._run_qa_prewarm_loop(session.session_id))
        self.qa_prewarm_tasks[session.session_id] = task
        task.add_done_callback(lambda finished_task, session_id=session.session_id: self._on_qa_prewarm_task_done(session_id, finished_task))

    def _cancel_qa_prewarm_task(self, session_id: str) -> None:
        task = self.qa_prewarm_tasks.pop(session_id, None)
        if task is not None:
            logger.info("qa.prewarm_task.cancel session=%s", session_id)
            task.cancel()

    def _cancel_qa_prewarm_refresh_task(self, session_id: str) -> None:
        task = self.qa_prewarm_refresh_tasks.pop(session_id, None)
        if task is not None:
            logger.info("qa.prewarm_refresh.cancel session=%s", session_id)
            task.cancel()

    def _cancel_qa_auto_advance_task(self, session_id: str) -> None:
        task = self.qa_auto_advance_tasks.pop(session_id, None)
        if task is not None:
            logger.info("qa.auto_advance.cancel session=%s", session_id)
            task.cancel()

    def _cancel_qa_silence_fallback_task(self, session_id: str) -> None:
        task = self.qa_silence_fallback_tasks.pop(session_id, None)
        if task is not None:
            logger.info("qa.silence_fallback.cancel session=%s", session_id)
            task.cancel()

    def _cancel_qa_response_done_grace_task(self, session_id: str) -> None:
        task = self.qa_response_done_grace_tasks.pop(session_id, None)
        if task is not None:
            logger.info("qa.response_done_grace.cancel session=%s", session_id)
            task.cancel()

    def _clear_qa_runtime_state(self, session_id: str) -> None:
        self._cancel_qa_auto_advance_task(session_id)
        self._cancel_qa_silence_fallback_task(session_id)
        self._cancel_qa_response_done_grace_task(session_id)
        self.qa_active_audio_turns.pop(session_id, None)
        self.qa_pending_response_done.pop(session_id, None)
        self.qa_answer_audio_started_at_ms.pop(session_id, None)

    def _on_qa_prewarm_task_done(self, session_id: str, task: asyncio.Task[None]) -> None:
        if self.qa_prewarm_tasks.get(session_id) is task:
            self.qa_prewarm_tasks.pop(session_id, None)

    def _on_qa_prewarm_refresh_task_done(self, session_id: str, task: asyncio.Task[None]) -> None:
        if self.qa_prewarm_refresh_tasks.get(session_id) is task:
            self.qa_prewarm_refresh_tasks.pop(session_id, None)

    def _on_qa_auto_advance_task_done(self, session_id: str, task: asyncio.Task[None]) -> None:
        if self.qa_auto_advance_tasks.get(session_id) is task:
            self.qa_auto_advance_tasks.pop(session_id, None)

    def _on_qa_silence_fallback_task_done(self, session_id: str, task: asyncio.Task[None]) -> None:
        if self.qa_silence_fallback_tasks.get(session_id) is task:
            self.qa_silence_fallback_tasks.pop(session_id, None)

    def _on_qa_response_done_grace_task_done(self, session_id: str, task: asyncio.Task[None]) -> None:
        if self.qa_response_done_grace_tasks.get(session_id) is task:
            self.qa_response_done_grace_tasks.pop(session_id, None)

    def _schedule_qa_prewarm_refresh(
        self,
        session_id: str,
        *,
        reason: str,
        delay_seconds: float | None = None,
    ) -> None:
        if session_id in self.qa_prewarm_refresh_tasks:
            return
        delay = self.qa_prewarm_trigger_delay_seconds if delay_seconds is None else max(0.0, delay_seconds)
        logger.info(
            "qa.prewarm_refresh.schedule session=%s reason=%s delay_ms=%s",
            session_id,
            reason,
            int(delay * 1000),
        )
        task = asyncio.create_task(self._run_qa_prewarm_refresh(session_id, delay, reason))
        self.qa_prewarm_refresh_tasks[session_id] = task
        task.add_done_callback(
            lambda finished_task, current_session_id=session_id: self._on_qa_prewarm_refresh_task_done(
                current_session_id,
                finished_task,
            )
        )

    def _schedule_qa_silence_fallback(self, session: SessionRecord, *, reason: str) -> None:
        if not self.qa_mode_orchestrator.is_user_answering(session.session_id):
            return
        self._cancel_qa_silence_fallback_task(session.session_id)
        logger.info(
            "qa.silence_fallback.schedule session=%s reason=%s delay_ms=%s",
            session.session_id,
            reason,
            int(self.qa_silence_fallback_delay_seconds * 1000),
        )
        task = asyncio.create_task(self._run_qa_silence_fallback(session.session_id, reason))
        self.qa_silence_fallback_tasks[session.session_id] = task
        task.add_done_callback(
            lambda finished_task, current_session_id=session.session_id: self._on_qa_silence_fallback_task_done(
                current_session_id,
                finished_task,
            )
        )

    async def _run_qa_prewarm_loop(self, session_id: str) -> None:
        try:
            while True:
                session = self.sessions.get(session_id)
                if session is None or session.status != "streaming":
                    return
                await self.qa_mode_orchestrator.prewarm_question_cache(
                    session_id=session_id,
                    transcript_chunks=list(session.transcript_chunks),
                )
                await asyncio.sleep(self.qa_prewarm_interval_seconds)
        except asyncio.CancelledError:
            logger.info("qa.prewarm_task.cancelled session=%s", session_id)
            return
        except Exception as error:
            logger.exception("qa.prewarm_task.failed session=%s error=%s", session_id, error)

    async def _run_qa_prewarm_refresh(self, session_id: str, delay_seconds: float, reason: str) -> None:
        try:
            if delay_seconds > 0:
                await asyncio.sleep(delay_seconds)
            session = self.sessions.get(session_id)
            if session is None or session.status != "streaming":
                return
            logger.info("qa.prewarm_refresh.fire session=%s reason=%s", session_id, reason)
            await self.qa_mode_orchestrator.prewarm_question_cache(
                session_id=session_id,
                transcript_chunks=list(session.transcript_chunks),
            )
        except asyncio.CancelledError:
            logger.info("qa.prewarm_refresh.cancelled session=%s", session_id)
            return
        except Exception as error:
            logger.exception("qa.prewarm_refresh.failed session=%s reason=%s error=%s", session_id, reason, error)

    def _schedule_qa_auto_advance(self, session: SessionRecord) -> None:
        if not self.qa_mode_orchestrator.is_user_answering(session.session_id):
            return
        self._cancel_qa_auto_advance_task(session.session_id)
        logger.info(
            "qa.auto_advance.schedule session=%s delay_ms=%s",
            session.session_id,
            int(self.qa_auto_advance_delay_seconds * 1000),
        )
        task = asyncio.create_task(self._run_qa_auto_advance(session.session_id))
        self.qa_auto_advance_tasks[session.session_id] = task
        task.add_done_callback(lambda finished_task, session_id=session.session_id: self._on_qa_auto_advance_task_done(session_id, finished_task))

    def _ensure_qa_auto_advance_scheduled(self, session: SessionRecord, *, reason: str) -> None:
        if not self.qa_mode_orchestrator.is_user_answering(session.session_id):
            return
        existing_task = self.qa_auto_advance_tasks.get(session.session_id)
        if existing_task is not None and not existing_task.done():
            logger.info("qa.auto_advance.keep_existing session=%s reason=%s", session.session_id, reason)
            return
        logger.info("qa.auto_advance.schedule_request session=%s reason=%s", session.session_id, reason)
        self._schedule_qa_auto_advance(session)

    def _schedule_qa_response_done_grace(self, session: SessionRecord, *, turn_id: str) -> None:
        self._cancel_qa_response_done_grace_task(session.session_id)
        logger.info(
            "qa.response_done_grace.schedule session=%s turn=%s delay_ms=%s",
            session.session_id,
            turn_id,
            int(self.qa_response_done_audio_grace_seconds * 1000),
        )
        task = asyncio.create_task(self._run_qa_response_done_grace(session.session_id, turn_id))
        self.qa_response_done_grace_tasks[session.session_id] = task
        task.add_done_callback(
            lambda finished_task, session_id=session.session_id: self._on_qa_response_done_grace_task_done(
                session_id,
                finished_task,
            )
        )

    async def _run_qa_auto_advance(self, session_id: str) -> None:
        try:
            await asyncio.sleep(self.qa_auto_advance_delay_seconds)
            session = self.sessions.get(session_id)
            if session is None or not self.qa_mode_orchestrator.is_user_answering(session_id):
                return
            if session_id in self.qa_active_audio_turns:
                logger.info("qa.auto_advance.skip session=%s reason=assistant_audio_in_flight", session_id)
                return
            logger.info("qa.auto_advance.fire session=%s", session_id)
            if not self._should_auto_advance_qa_answer(session):
                logger.info("qa.auto_advance.skip session=%s reason=empty_or_filler", session_id)
                return
            await self._commit_qa_user_turn(session)
        except asyncio.CancelledError:
            logger.info("qa.auto_advance.cancelled session=%s", session_id)
            return
        except Exception as error:
            logger.exception("qa.auto_advance.failed session=%s error=%s", session_id, error)
            session = self.sessions.get(session_id)
            if session is not None:
                await self._broadcast(session, ErrorEvent(message=f"自动进入下一问失败：{error}").model_dump())

    async def _run_qa_response_done_grace(self, session_id: str, turn_id: str) -> None:
        try:
            await asyncio.sleep(self.qa_response_done_audio_grace_seconds)
            session = self.sessions.get(session_id)
            if session is None:
                return
            pending = self.qa_pending_response_done.get(session_id)
            if pending is None or pending[0] != turn_id:
                return
            if self.qa_active_audio_turns.get(session_id) == turn_id:
                logger.info(
                    "qa.response_done_grace.skip session=%s turn=%s reason=audio_started",
                    session_id,
                    turn_id,
                )
                return
            await self._flush_pending_qa_prompt(
                session,
                turn_id=turn_id,
                reason="assistant_response_done_grace",
            )
        except asyncio.CancelledError:
            logger.info("qa.response_done_grace.cancelled session=%s turn=%s", session_id, turn_id)
            return
        except Exception as error:
            logger.exception("qa.response_done_grace.failed session=%s turn=%s error=%s", session_id, turn_id, error)

    async def _run_qa_silence_fallback(self, session_id: str, reason: str) -> None:
        try:
            await asyncio.sleep(self.qa_silence_fallback_delay_seconds)
            session = self.sessions.get(session_id)
            if session is None or not self.qa_mode_orchestrator.is_user_answering(session_id):
                return
            if session_id in self.qa_active_audio_turns:
                logger.info("qa.silence_fallback.skip session=%s reason=assistant_audio_in_flight", session_id)
                return
            answer_text = self._current_qa_answer_text(session_id)
            if not self._is_empty_or_filler_qa_answer(session.language, answer_text):
                logger.info(
                    "qa.silence_fallback.skip session=%s reason=substantive_answer answer=%s",
                    session_id,
                    answer_text[:80],
                )
                return
            has_pending_user_audio = self.qa_mode_orchestrator.qa_omni_service.has_pending_user_audio(session_id)
            has_any_answer_text = bool(answer_text.strip())
            if not has_any_answer_text:
                logger.info(
                    "qa.silence_fallback.no_user_transcript session=%s trigger=%s pending_audio=%s",
                    session_id,
                    reason,
                    has_pending_user_audio,
                )
            logger.info(
                "qa.silence_fallback.fire session=%s reason=%s answer=%s",
                session_id,
                reason,
                answer_text[:80] or "<empty>",
            )
            self._cancel_qa_auto_advance_task(session_id)
            if has_pending_user_audio:
                await self.qa_mode_orchestrator.qa_omni_service.clear_input_audio_buffer(session.session_id)
            plan, events = self.qa_mode_orchestrator.prepare_after_silence_timeout(session_id=session_id)
            for event in events:
                await self._broadcast_runtime_event(session, event)
            if plan.action == "end_qa":
                await self.qa_mode_orchestrator.qa_omni_service.close_session(session.session_id)
                logger.info(
                    "qa.realtime.completed session=%s total_questions=%s max_follow_ups=%s fallback=silence_timeout",
                    session.session_id,
                    self.qa_mode_orchestrator.sessions[session.session_id].max_question_topics,
                    self.qa_mode_orchestrator.sessions[session.session_id].max_follow_ups_per_question,
                )
                return
            await self._refresh_qa_realtime_instructions(session, wait_for_provider_ack=False)
            committed = await self.qa_mode_orchestrator.qa_omni_service.commit_silent_user_turn(session.session_id)
            if not committed:
                raise RuntimeError("QA Omni Realtime 静默超时跳题提交失败")
            logger.info(
                "qa.realtime.user_turn_committed session=%s action=%s next_question=%s next_round=%s fallback=silence_timeout",
                session.session_id,
                plan.action,
                plan.question_index,
                plan.round_index,
            )
        except asyncio.CancelledError:
            logger.info("qa.silence_fallback.cancelled session=%s", session_id)
            return
        except Exception as error:
            logger.exception("qa.silence_fallback.failed session=%s reason=%s error=%s", session_id, reason, error)
            session = self.sessions.get(session_id)
            if session is not None:
                await self._broadcast(session, ErrorEvent(message=f"静默兜底进入下一问失败：{error}").model_dump())

    async def _ensure_body_lane_connected(self, session: SessionRecord) -> None:
        if session.omni_body_disabled_reason is not None:
            return
        if session.status != "streaming":
            return
        if session.session_id in self.omni_body_service.connections:
            return
        if monotonic() < session.body_lane_retry_after_monotonic:
            return

        try:
            await self.omni_body_service.connect_session(
                session.session_id,
                session.scenario_id,
                session.language,
                on_insight=lambda update: self._broadcast_omni_update(session, update),
                on_error=lambda message: self._handle_omni_provider_error(session, "body", message),
                on_event=None,
            )
            session.body_lane_retry_after_monotonic = 0.0
            session.body_lane_internal_error_count = 0
            session.body_lane_last_error_at_monotonic = 0.0
        except Exception as error:
            session.body_lane_retry_after_monotonic = monotonic() + 2.0
            await self._handle_omni_connect_failure(session, "body", error)

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

    def _current_qa_answer_text(self, session_id: str) -> str:
        qa_session = self.qa_mode_orchestrator.sessions.get(session_id)
        if qa_session is None:
            return ""
        committed_answer = " ".join(chunk.strip() for chunk in qa_session.current_answer_chunks if chunk.strip()).strip()
        if committed_answer:
            return committed_answer
        return (qa_session.current_live_partial_answer or "").strip()

    def _trim_assistant_question_text(self, text: str) -> str:
        stripped = text.strip()
        if not stripped:
            return stripped
        question_end = max(stripped.find("？"), stripped.find("?"))
        if question_end != -1:
            return stripped[: question_end + 1].strip()
        return stripped

    def _should_cancel_assistant_self_answer(self, text: str) -> bool:
        stripped = text.strip()
        if not stripped:
            return False

        question_end = max(stripped.find("？"), stripped.find("?"))
        if question_end != -1:
            tail = stripped[question_end + 1 :].strip()
            if tail and not re.fullmatch(r"[\s,.!?，。！？、…:：;；\"'“”‘’（）()\-\u3000]+", tail):
                return True
        return False

    def _should_auto_advance_qa_answer(self, session: SessionRecord) -> bool:
        answer_text = self._current_qa_answer_text(session.session_id)
        return not self._is_empty_or_filler_qa_answer(session.language, answer_text)

    def _is_empty_or_filler_qa_answer(self, language: LanguageOption, text: str) -> bool:
        normalized = re.sub(r"[\s,.!?，。！？、…:：;；\"'“”‘’（）()\-\u3000]+", "", text).lower()
        if not normalized:
            return True
        if normalized in self.QA_FALLBACK_FILLER_TOKENS[language]:
            return True
        if language == "zh":
            pieces = [piece for piece in re.split(r"[，。！？、；：\s]+", text) if piece.strip()]
        else:
            pieces = [piece for piece in re.split(r"[\s,.!?;:]+", text) if piece.strip()]
        if not pieces:
            return True
        return all(
            re.sub(r"[\s,.!?，。！？、…:：;；\"'“”‘’（）()\-\u3000]+", "", piece).lower()
            in self.QA_FALLBACK_FILLER_TOKENS[language]
            for piece in pieces
        )

    def _mark_qa_answer_window_open(self, session: SessionRecord) -> None:
        self.qa_answer_audio_started_at_ms.pop(session.session_id, None)
        self.qa_mode_orchestrator.clear_live_partial_answer(session.session_id)

    def _accept_qa_user_transcript(self, session: SessionRecord, chunk: TranscriptChunk) -> bool:
        if chunk.speaker != "user" or not self.qa_mode_orchestrator.is_user_answering(session.session_id):
            return False

        audio_started_at_ms = self.qa_answer_audio_started_at_ms.get(session.session_id)
        if audio_started_at_ms is not None and chunk.endMs < max(0, audio_started_at_ms - 250):
            logger.info(
                "qa.user_transcript.ignore_stale session=%s chunk_end_ms=%s answer_audio_start_ms=%s text=%s",
                session.session_id,
                chunk.endMs,
                audio_started_at_ms,
                chunk.text[:120],
            )
            return False

        return True

session_manager = SessionManager()
