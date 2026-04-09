import asyncio
from dataclasses import dataclass, field
from datetime import datetime, UTC
from pathlib import Path
from uuid import uuid4

from fastapi import WebSocket

from app.data.session_stream import get_session_frames_for_realtime
from app.schemas import (
    AckEvent,
    ClientMessage,
    ErrorEvent,
    InjectInsightRequest,
    InjectTranscriptRequest,
    LiveInsight,
    LiveInsightEvent,
    PongEvent,
    RealtimeSession,
    RealtimeStatusEvent,
    ScenarioType,
    LanguageOption,
    SessionStatus,
    TranscriptChunk,
    TranscriptFinalEvent,
    TranscriptPartialEvent,
)
from app.services.coaching_service import MockCoachingService
from app.services.debug_store import DebugStore
from app.services.stt_service import MockSttService
from app.services.vision_service import MockVisionService


@dataclass
class SessionRecord:
    session_id: str
    scenario_id: ScenarioType
    language: LanguageOption
    status: SessionStatus = "created"
    transcript_count: int = 0
    insight_count: int = 0
    audio_chunk_count: int = 0
    video_frame_count: int = 0
    stream_task: asyncio.Task[None] | None = field(default=None, repr=False)
    sockets: list[WebSocket] = field(default_factory=list, repr=False)

    def to_schema(self) -> RealtimeSession:
        return RealtimeSession(
            sessionId=self.session_id,
            scenarioId=self.scenario_id,
            language=self.language,
            status=self.status,
            transcriptCount=self.transcript_count,
            insightCount=self.insight_count,
            audioChunkCount=self.audio_chunk_count,
            videoFrameCount=self.video_frame_count,
        )


class SessionManager:
    def __init__(self) -> None:
        self.sessions: dict[str, SessionRecord] = {}
        self.stt_service = MockSttService()
        self.vision_service = MockVisionService()
        self.coaching_service = MockCoachingService()
        self.debug_store = DebugStore(Path(__file__).resolve().parents[2] / "debug")

    def create_session(self, scenario_id: ScenarioType, language: LanguageOption) -> SessionRecord:
        session_id = uuid4().hex
        session = SessionRecord(session_id=session_id, scenario_id=scenario_id, language=language)
        self.sessions[session_id] = session
        self.debug_store.init_session(
            session_id,
            {
                "sessionId": session_id,
                "scenarioId": scenario_id,
                "language": language,
                "status": session.status,
                "createdAt": datetime.now(UTC).isoformat(),
            },
        )
        return session

    def get_session(self, session_id: str) -> SessionRecord | None:
        return self.sessions.get(session_id)

    def finish_session(self, session_id: str) -> SessionRecord | None:
        session = self.sessions.get(session_id)
        if session is None:
            return None

        session.status = "finished"
        self.debug_store.append_event(session_id, {"type": "session_finished", "status": session.status})
        if session.stream_task and not session.stream_task.done():
            session.stream_task.cancel()
        return session

    async def connect(self, session: SessionRecord, websocket: WebSocket) -> None:
        await websocket.accept()
        session.sockets.append(websocket)
        await websocket.send_json(RealtimeStatusEvent(sessionId=session.session_id, status=session.status).model_dump())

    def disconnect(self, session: SessionRecord, websocket: WebSocket) -> None:
        if websocket in session.sockets:
            session.sockets.remove(websocket)

    async def handle_client_message(self, session: SessionRecord, message: ClientMessage, websocket: WebSocket) -> None:
        self.debug_store.append_event(session.session_id, {"type": "client_message", **message.model_dump(exclude={"payload", "image_base64"})})

        if message.type == "ping":
            await websocket.send_json(PongEvent().model_dump())
            return

        if message.type == "start_stream":
            if session.status == "streaming":
                await websocket.send_json(AckEvent(message="stream already started").model_dump())
                return

            session.status = "streaming"
            await self.broadcast_status(session)
            session.stream_task = asyncio.create_task(self._stream_mock_events(session))
            return

        if message.type == "audio_chunk":
            session.audio_chunk_count += 1
            path = self.debug_store.save_audio_chunk(
                session.session_id,
                session.audio_chunk_count,
                message.payload,
                message.mime_type,
            )
            await websocket.send_json(
                AckEvent(
                    message=f"{self.stt_service.acknowledge_audio_chunk(session.audio_chunk_count)} -> {path}"
                ).model_dump()
            )
            return

        if message.type == "video_frame":
            session.video_frame_count += 1
            path = self.debug_store.save_video_frame(session.session_id, session.video_frame_count, message.image_base64)
            await websocket.send_json(
                AckEvent(message=f"{self.vision_service.acknowledge_video_frame(session.video_frame_count)} -> {path}").model_dump()
            )
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
            )
            await self.broadcast_transcript(session, chunk, source="websocket")
            return

        if message.type == "inject_insight" and message.title and message.detail and message.tone:
            insight = LiveInsight(
                id=f"manual-insight-{session.insight_count + 1}",
                title=message.title,
                detail=message.detail,
                tone=message.tone,
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
        )
        await self.broadcast_transcript(session, chunk, source="rest")

    async def inject_insight(self, session: SessionRecord, payload: InjectInsightRequest) -> None:
        insight = LiveInsight(
            id=f"manual-insight-{session.insight_count + 1}",
            title=payload.title,
            detail=payload.detail,
            tone=payload.tone,
        )
        await self.broadcast_insight(session, insight, source="rest")

    async def broadcast_status(self, session: SessionRecord) -> None:
        await self._broadcast(session, RealtimeStatusEvent(sessionId=session.session_id, status=session.status).model_dump())
        self.debug_store.append_event(session.session_id, {"type": "status_broadcast", "status": session.status})

    async def broadcast_partial(self, session: SessionRecord, text: str, source: str) -> None:
        await self._broadcast(session, TranscriptPartialEvent(text=text).model_dump())
        self.debug_store.append_event(
            session.session_id,
            {"type": "partial_broadcast", "source": source, "text": text},
        )

    async def broadcast_transcript(self, session: SessionRecord, chunk: TranscriptChunk, source: str) -> None:
        session.transcript_count += 1
        await self._broadcast(session, TranscriptFinalEvent(chunk=chunk).model_dump())
        self.debug_store.save_transcript_injection(session.session_id, chunk, source)

    async def broadcast_insight(self, session: SessionRecord, insight: LiveInsight, source: str) -> None:
        session.insight_count += 1
        await self._broadcast(session, self.coaching_service.build_live_insight_event(insight).model_dump())
        self.debug_store.save_insight_injection(session.session_id, insight, source)

    async def _broadcast(self, session: SessionRecord, payload: dict) -> None:
        stale: list[WebSocket] = []
        for socket in session.sockets:
            try:
                await socket.send_json(payload)
            except RuntimeError:
                stale.append(socket)

        for socket in stale:
            self.disconnect(session, socket)

    async def _stream_mock_events(self, session: SessionRecord) -> None:
        frames = get_session_frames_for_realtime(session.scenario_id, session.language)
        previous_second = 0

        try:
            for frame in frames:
                await asyncio.sleep(max(frame.second - previous_second, 0))
                previous_second = frame.second

                partial_text = self.stt_service.build_partial_text(frame.transcript)
                await self.broadcast_partial(session, partial_text, source="mock")
                await self.broadcast_transcript(session, frame.transcript, source="mock")
                await self.broadcast_insight(session, frame.insight, source="mock")
        except asyncio.CancelledError:
            return


session_manager = SessionManager()
