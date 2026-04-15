from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.data.history import HISTORICAL_SESSIONS, get_report_by_scenario
from app.data.scenarios import SCENARIOS
from app.data.session_stream import get_session_frames
from app.schemas import (
    ClientMessage,
    HistoricalSessionSummary,
    LanguageOption,
    RealtimeSession,
    RealtimeSessionResponse,
    ScenarioOption,
    ScenarioType,
    SessionReport,
    SessionReplay,
    SessionStreamFrame,
    StartSessionRequest,
)
from app.services.session_manager import session_manager


app = FastAPI(title="Speak Up API", version="0.3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
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
def start_session(payload: StartSessionRequest) -> RealtimeSessionResponse:
    session = session_manager.create_session(payload.scenarioId, payload.language)
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


@app.get("/api/session/{session_id}/replay", response_model=SessionReplay)
def get_session_replay(session_id: str) -> SessionReplay:
    replay = session_manager.get_replay(session_id)
    if replay is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionReplay.model_validate(replay)


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
