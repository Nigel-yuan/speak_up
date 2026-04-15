from typing import Literal

from pydantic import BaseModel


ScenarioType = Literal["host", "guest-sharing", "standup"]
LanguageOption = Literal["zh", "en"]
InsightTone = Literal["positive", "neutral", "warning"]
InsightSource = Literal["system", "omni-coach", "manual"]
CoachDimensionId = Literal["body_expression", "voice_pacing", "content_expression"]
CoachDisplayStatus = Literal["doing_well", "stable", "adjust_now", "analyzing"]
CoachDimensionSource = Literal["system", "omni-coach", "speech-rule"]
TranscriptSpeaker = Literal["user", "coach"]
SessionStatus = Literal["created", "streaming", "finished"]
RealtimeEventType = Literal[
    "session_status",
    "transcript_partial",
    "transcript_final",
    "coach_panel",
    "pong",
    "ack",
    "error",
]
ClientMessageType = Literal[
    "ping",
    "start_stream",
    "audio_chunk",
    "video_frame",
]


class ScenarioOption(BaseModel):
    id: ScenarioType
    title: str
    subtitle: str
    description: str
    goals: list[str]
    audience: str
    accentColor: str


class TranscriptChunk(BaseModel):
    id: str
    speaker: TranscriptSpeaker
    text: str
    timestampLabel: str
    startMs: int = 0
    endMs: int = 0


class LiveInsight(BaseModel):
    id: str
    title: str
    detail: str
    tone: InsightTone
    source: InsightSource = "system"


class CoachSummary(BaseModel):
    title: str
    detail: str
    sourceDimension: CoachDimensionId | None = None
    updatedAtMs: int = 0


class CoachDimensionState(BaseModel):
    id: CoachDimensionId
    status: CoachDisplayStatus
    headline: str
    detail: str
    updatedAtMs: int = 0
    source: CoachDimensionSource = "system"


class CoachPanelState(BaseModel):
    summary: CoachSummary
    bodyExpression: CoachDimensionState
    voicePacing: CoachDimensionState
    contentExpression: CoachDimensionState


class CoachPanelPatchDimension(BaseModel):
    id: CoachDimensionId
    status: CoachDisplayStatus
    headline: str
    detail: str


class CoachPanelPatch(BaseModel):
    dimensions: list[CoachPanelPatchDimension] = []


class SessionSetup(BaseModel):
    scenarioId: ScenarioType
    language: LanguageOption


class RadarMetric(BaseModel):
    subject: str
    score: int
    fullMark: int


class SuggestionItem(BaseModel):
    title: str
    detail: str


class MetricDelta(BaseModel):
    metric: str
    change: int


class HistoricalSessionSummary(BaseModel):
    id: str
    label: str
    scenarioId: ScenarioType
    overallScore: int
    summary: str
    deltas: list[MetricDelta]


class SessionReport(BaseModel):
    overallScore: int
    headline: str
    encouragement: str
    highlights: list[str]
    suggestions: list[SuggestionItem]
    radarMetrics: list[RadarMetric]
    comparisonSummary: str


class SessionStreamFrame(BaseModel):
    second: int
    transcript: TranscriptChunk
    insight: LiveInsight


class StartSessionRequest(BaseModel):
    scenarioId: ScenarioType
    language: LanguageOption


class RealtimeSession(BaseModel):
    sessionId: str
    scenarioId: ScenarioType
    language: LanguageOption
    status: SessionStatus
    transcriptCount: int = 0
    audioChunkCount: int = 0
    videoFrameCount: int = 0


class RealtimeSessionResponse(RealtimeSession):
    websocketUrl: str


class SessionReplay(BaseModel):
    sessionId: str
    scenarioId: ScenarioType
    language: LanguageOption
    mediaUrl: str | None = None
    mediaType: Literal["audio", "video"] | None = None
    transcript: list[TranscriptChunk]


class RealtimeStatusEvent(BaseModel):
    type: Literal["session_status"] = "session_status"
    sessionId: str
    status: SessionStatus


class TranscriptPartialEvent(BaseModel):
    type: Literal["transcript_partial"] = "transcript_partial"
    text: str


class TranscriptFinalEvent(BaseModel):
    type: Literal["transcript_final"] = "transcript_final"
    chunk: TranscriptChunk
    replacePrevious: bool = False


class CoachPanelEvent(BaseModel):
    type: Literal["coach_panel"] = "coach_panel"
    coachPanel: CoachPanelState


class PongEvent(BaseModel):
    type: Literal["pong"] = "pong"


class AckEvent(BaseModel):
    type: Literal["ack"] = "ack"
    message: str


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    message: str


class ClientMessage(BaseModel):
    type: ClientMessageType
    timestamp_ms: int | None = None
    payload: str | None = None
    image_base64: str | None = None
    mime_type: str | None = None
    sample_rate_hz: int | None = None
    channels: int | None = None
