import logging

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from app.schemas import (
    ClientMessage,
    DocumentExtractionResponse,
    RealtimeSession,
    RealtimeSessionResponse,
    ReplayMediaUploadResponse,
    VoiceProfile,
    SessionReport,
    SessionReplay,
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


@app.post("/api/session/start", response_model=RealtimeSessionResponse)
async def start_session(payload: StartSessionRequest, request: Request) -> RealtimeSessionResponse:
    session = session_manager.create_session(payload.scenarioId, payload.language, payload.coachProfileId)
    await session_manager.report_job_service.register_session(
        session_id=session.session_id,
        scenario_id=payload.scenarioId,
        language=payload.language,
        coach_profile_id=session.coach_profile_id,
    )
    websocket_scheme = "wss" if request.url.scheme == "https" else "ws"
    websocket_url = f"{websocket_scheme}://{request.headers.get('host', '127.0.0.1:8000')}/ws/session/{session.session_id}"
    return RealtimeSessionResponse(
        **session.to_schema().model_dump(),
        websocketUrl=websocket_url,
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
async def get_session_replay(session_id: str) -> SessionReplay:
    replay = await session_manager.replay_service.build_replay(session_id)
    if replay is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return replay


@app.post("/api/session/{session_id}/replay/media", response_model=ReplayMediaUploadResponse)
async def upload_session_replay_media(
    session_id: str,
    file: UploadFile = File(...),
    duration_ms: int = Form(default=0),
) -> ReplayMediaUploadResponse:
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Replay media file is empty")
    try:
        return await session_manager.replay_service.save_media(
            session_id,
            filename=file.filename,
            content_type=file.content_type,
            data=data,
            duration_ms=duration_ms,
        )
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="Session not found") from error


@app.get("/api/session/{session_id}/replay/media")
async def get_session_replay_media(session_id: str) -> FileResponse:
    media = await session_manager.replay_service.get_media_file(session_id)
    if media is None:
        raise HTTPException(status_code=404, detail="Replay media not found")
    return FileResponse(
        path=media.path,
        media_type=media.content_type or "application/octet-stream",
        filename=media.path.name,
    )


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
