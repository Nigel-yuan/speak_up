import logging

from fastapi import Body, FastAPI, File, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from app.data.history import HISTORICAL_SESSIONS, get_report_by_scenario
from app.data.scenarios import SCENARIOS
from app.data.session_stream import get_session_frames
from app.schemas import (
    ClientMessage,
    DocumentExtractionResponse,
    HistoricalSessionSummary,
    LanguageOption,
    RealtimeSession,
    RealtimeSessionResponse,
    ReportReassuranceAudioRequest,
    ReportReassuranceAudioResponse,
    VoiceProfile,
    ScenarioOption,
    ScenarioType,
    SessionReport,
    SessionReplay,
    SessionStreamFrame,
    StartSessionRequest,
)
from app.services.document_extraction_service import DocumentExtractionError, document_extraction_service
from app.services.document_preview_service import document_preview_service
from app.services.session_manager import session_manager


def _configure_app_logging() -> None:
    uvicorn_logger = logging.getLogger("uvicorn.error")
    formatter = logging.Formatter("%(levelname)s:     %(name)s - %(message)s")
    fallback_handler = logging.StreamHandler()
    fallback_handler.setFormatter(formatter)

    for logger_name in ("speak_up.session", "speak_up.qa"):
        app_logger = logging.getLogger(logger_name)
        app_logger.setLevel(logging.INFO)
        app_logger.handlers = uvicorn_logger.handlers or [fallback_handler]
        app_logger.propagate = False


_configure_app_logging()


app = FastAPI(title="Speak Up API", version="0.3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_origin_regex=r"https?://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/scenarios", response_model=list[ScenarioOption])
def list_scenarios() -> list[ScenarioOption]:
    return SCENARIOS


@app.get("/api/qa/voice-profiles", response_model=list[VoiceProfile])
def list_qa_voice_profiles() -> list[VoiceProfile]:
    return session_manager.qa_mode_orchestrator.list_voice_profiles()


@app.post("/api/document/extract", response_model=DocumentExtractionResponse)
async def extract_document_text(file: UploadFile = File(...)) -> DocumentExtractionResponse:
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Document file is empty")

    try:
        extraction = document_extraction_service.extract(
            filename=file.filename or "document",
            content_type=file.content_type,
            data=data,
        )
    except DocumentExtractionError as error:
        logging.getLogger("speak_up.session").warning(
            "document.extract.failed filename=%s content_type=%s bytes=%s error=%s",
            file.filename or "document",
            file.content_type,
            len(data),
            error,
        )
        raise HTTPException(status_code=400, detail=str(error)) from error

    if not extraction.text.strip():
        logging.getLogger("speak_up.session").warning(
            "document.extract.empty filename=%s kind=%s bytes=%s",
            file.filename or "document",
            extraction.kind,
            len(data),
        )
        raise HTTPException(status_code=400, detail="未能从文档中抽取到可用正文。")

    preview = await document_preview_service.build_preview(
        kind=extraction.kind,
        filename=file.filename or "document",
        content_type=file.content_type,
        data=data,
    )

    logging.getLogger("speak_up.session").info(
        "document.extract.done filename=%s kind=%s bytes=%s chars=%s preview_kind=%s preview_status=%s",
        file.filename or "document",
        extraction.kind,
        len(data),
        len(extraction.text),
        preview.kind,
        preview.status,
    )

    return DocumentExtractionResponse(
        kind=extraction.kind,
        filename=file.filename or "document",
        text=extraction.text,
        charCount=len(extraction.text),
        preview=preview,
    )


@app.get("/api/history", response_model=list[HistoricalSessionSummary])
def list_history(
    scenario: ScenarioType | None = Query(default=None),
) -> list[HistoricalSessionSummary]:
    if scenario is None:
        return HISTORICAL_SESSIONS
    return [item for item in HISTORICAL_SESSIONS if item.scenarioId == scenario]


@app.get("/api/session-stream", response_model=list[SessionStreamFrame])
def session_stream(
    scenario: ScenarioType = Query(default="host"),
    language: LanguageOption = Query(default="zh"),
) -> list[SessionStreamFrame]:
    return get_session_frames(scenario, language)


@app.get("/api/report", response_model=SessionReport)
def get_report(
    scenario: ScenarioType = Query(default="host"),
) -> SessionReport:
    return get_report_by_scenario(scenario)


@app.post("/api/session/start", response_model=RealtimeSessionResponse)
async def start_session(payload: StartSessionRequest) -> RealtimeSessionResponse:
    session = session_manager.create_session(payload.scenarioId, payload.language)
    await session_manager.report_job_service.register_session(
        session_id=session.session_id,
        scenario_id=payload.scenarioId,
        language=payload.language,
    )
    return RealtimeSessionResponse(
        **session.to_schema().model_dump(),
        websocketUrl=f"ws://127.0.0.1:8000/ws/session/{session.session_id}",
    )


@app.get("/api/session/{session_id}", response_model=RealtimeSession)
def get_realtime_session(session_id: str) -> RealtimeSession:
    session = session_manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session.to_schema()


@app.post("/api/session/{session_id}/finish", response_model=RealtimeSession)
async def finish_session(session_id: str) -> RealtimeSession:
    session = await session_manager.finish_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session.to_schema()


@app.get("/api/session/{session_id}/report", response_model=SessionReport)
async def get_session_report(session_id: str) -> SessionReport:
    report = await session_manager.report_job_service.get_report(session_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return report


@app.post("/api/session/{session_id}/report/generate", response_model=SessionReport)
async def generate_session_report(session_id: str) -> SessionReport:
    try:
        report = await session_manager.report_job_service.trigger_final_report(session_id)
        if report is None:
            raise FileNotFoundError(session_id)
        return report
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="Session not found") from error
    except Exception as error:
        logging.getLogger("speak_up.session").exception(
            "report.generate.failed session=%s error=%s",
            session_id,
            error,
        )
        raise HTTPException(status_code=500, detail="报告生成失败") from error


@app.post("/api/session/{session_id}/report/reassurance-audio", response_model=ReportReassuranceAudioResponse)
async def generate_report_reassurance_audio(
    session_id: str,
    payload: ReportReassuranceAudioRequest = Body(default_factory=ReportReassuranceAudioRequest),
) -> ReportReassuranceAudioResponse:
    try:
        audio = await session_manager.report_job_service.generate_reassurance_audio(
            session_id,
            attempt_index=payload.attemptIndex,
            voice_profile_id=payload.voiceProfileId,
        )
        if audio is None:
            raise FileNotFoundError(session_id)
        return audio
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="Session not found") from error
    except Exception as error:
        logging.getLogger("speak_up.session").exception(
            "report.reassurance_audio.failed session=%s error=%s",
            session_id,
            error,
        )
        raise HTTPException(status_code=503, detail="安抚语音生成失败") from error


@app.get("/api/session/{session_id}/report/windows")
async def list_session_report_windows(session_id: str) -> list[dict]:
    try:
        packs = await session_manager.report_job_service.list_window_packs(session_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="Session not found") from error
    return [pack.model_dump() for pack in packs]


@app.get("/api/session/{session_id}/report/artifacts")
async def list_session_report_artifacts(session_id: str) -> list[dict]:
    try:
        return await session_manager.report_job_service.list_artifacts(session_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="Session not found") from error


@app.get("/api/session/{session_id}/report/signals")
async def get_session_report_signals(session_id: str) -> dict:
    payload = await session_manager.report_job_service.get_signals(session_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return payload


@app.get("/api/session/{session_id}/replay", response_model=SessionReplay)
def get_session_replay(session_id: str) -> SessionReplay:
    replay = session_manager.get_replay(session_id)
    if replay is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionReplay.model_validate(replay)


@app.get("/api/session/{session_id}/qa/turns/{turn_id}/audio")
def get_qa_turn_audio(session_id: str, turn_id: str) -> FileResponse:
    file_path = session_manager.qa_mode_orchestrator.get_audio_path(session_id, turn_id)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="QA audio not found")
    return FileResponse(path=file_path, media_type="audio/wav", filename=file_path.name)


@app.websocket("/ws/session/{session_id}")
async def session_websocket(websocket: WebSocket, session_id: str) -> None:
    session = session_manager.get_session(session_id)
    if session is None:
        await websocket.close(code=4404)
        return

    await session_manager.connect(session, websocket)

    try:
        while True:
            payload = await websocket.receive_json()
            message = ClientMessage.model_validate(payload)
            await session_manager.handle_client_message(session, message, websocket)
    except WebSocketDisconnect:
        session_manager.disconnect(session, websocket)
        return
