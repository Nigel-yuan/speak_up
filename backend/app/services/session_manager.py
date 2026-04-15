import asyncio
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
from app.services.omni_service import AliyunOmniCoachService, OmniCoachUpdate
from app.services.speech_analysis_service import SpeechAnalysisService
from app.services.stt_service import ProviderTranscriptResult, build_stt_service


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

    def create_session(self, scenario_id: ScenarioType, language: LanguageOption) -> SessionRecord:
        session_id = uuid4().hex
        session = SessionRecord(
            session_id=session_id,
            scenario_id=scenario_id,
            language=language,
        )
        self.coach_panel_service.get_or_create_panel(session_id, language)
        self.sessions[session_id] = session
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

        try:
            await self.omni_coach_service.finish_session(session_id)
        except Exception:
            pass
        try:
            await self.omni_body_service.finish_session(session_id)
        except Exception:
            pass

        session.status = "finished"
        self.speech_analysis_service.close_session(session_id)
        self.coach_panel_service.close_session(session_id)
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

    def disconnect(self, session: SessionRecord, websocket: WebSocket) -> None:
        if websocket in session.sockets:
            session.sockets.remove(websocket)
        if not session.sockets:
            self.speech_analysis_service.close_session(session.session_id)
            self.coach_panel_service.close_session(session.session_id)
            asyncio.create_task(self.stt_service.close_session(session.session_id))
            asyncio.create_task(self.omni_coach_service.close_session(session.session_id))
            asyncio.create_task(self.omni_body_service.close_session(session.session_id))

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
                    on_event=None,
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
                    on_event=None,
                )
            except Exception as error:
                await self._broadcast(session, ErrorEvent(message=f"Omni coach 连接失败：{error}").model_dump())
            try:
                await self.omni_body_service.connect_session(
                    session.session_id,
                    session.scenario_id,
                    session.language,
                    on_insight=lambda update: self._broadcast_omni_update(session, update),
                    on_error=lambda message: self._record_omni_error(session, message),
                    on_event=None,
                )
            except Exception as error:
                await self._broadcast(session, ErrorEvent(message=f"Omni body coach 连接失败：{error}").model_dump())

            session.status = "streaming"
            session.started_at_monotonic = monotonic()
            await self.broadcast_status(session)
            return

        if message.type == "audio_chunk":
            session.audio_chunk_count += 1
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

            return

        if message.type == "video_frame":
            session.video_frame_count += 1
            try:
                await self.omni_coach_service.send_video_frame(session.session_id, message.image_base64)
            except Exception as error:
                await self._record_omni_error(session, f"发送视频帧到 Omni coach 失败：{error}")
            try:
                await self.omni_body_service.send_video_frame(session.session_id, message.image_base64)
            except Exception as error:
                await self._record_omni_error(session, f"发送视频帧到 Omni body coach 失败：{error}")
            return

        await websocket.send_json(ErrorEvent(message="unsupported message type").model_dump())

    async def broadcast_status(self, session: SessionRecord) -> None:
        await self._broadcast(session, RealtimeStatusEvent(sessionId=session.session_id, status=session.status).model_dump())

    async def broadcast_partial(self, session: SessionRecord, text: str) -> None:
        await self._broadcast(session, TranscriptPartialEvent(text=text).model_dump())

    async def broadcast_transcript(self, session: SessionRecord, chunk: TranscriptChunk) -> None:
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
            coach_panel = self.coach_panel_service.update_from_omni_patch(
                session.session_id,
                session.language,
                update.patch,
                updated_at_ms,
            )
            if coach_panel is not None:
                await self._broadcast(session, CoachPanelEvent(coachPanel=coach_panel).model_dump())

    async def _record_omni_error(self, session: SessionRecord, message: str) -> None:
        await self._broadcast(session, ErrorEvent(message=message).model_dump())

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

session_manager = SessionManager()
