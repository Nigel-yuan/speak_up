from typing import Literal

from pydantic import BaseModel


ScenarioType = Literal["host", "guest-sharing", "standup"]
LanguageOption = Literal["zh", "en"]
InsightTone = Literal["positive", "neutral", "warning"]
TranscriptSpeaker = Literal["user", "coach"]
SessionStatus = Literal["created", "streaming", "finished"]
RealtimeEventType = Literal[
    "session_status",
    "transcript_partial",
    "transcript_final",
    "live_insight",
    "pong",
    "ack",
    "error",
]
ClientMessageType = Literal[
    "ping",
    "start_stream",
    "audio_chunk",
    "video_frame",
    "inject_partial",
    "inject_transcript",
    "inject_insight",
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


class LiveInsight(BaseModel):
    id: str
    title: str
    detail: str
    tone: InsightTone


class SessionSetup(BaseModel):
    scenarioId: ScenarioType
    language: LanguageOption
    debugEnabled: bool = False


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
    debugEnabled: bool = False


class RealtimeSession(BaseModel):
    sessionId: str
    scenarioId: ScenarioType
    language: LanguageOption
    debugEnabled: bool = False
    status: SessionStatus
    transcriptCount: int = 0
    insightCount: int = 0
    audioChunkCount: int = 0
    videoFrameCount: int = 0


class RealtimeSessionResponse(RealtimeSession):
    websocketUrl: str


class DebugAudioUploadResponse(BaseModel):
    path: str
    sizeBytes: int


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


class LiveInsightEvent(BaseModel):
    type: Literal["live_insight"] = "live_insight"
    insight: LiveInsight


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
    text: str | None = None
    title: str | None = None
    detail: str | None = None
    tone: InsightTone | None = None
    timestamp_label: str | None = None


class InjectTranscriptRequest(BaseModel):
    text: str
    timestampLabel: str
    speaker: TranscriptSpeaker = "user"


class InjectInsightRequest(BaseModel):
    title: str
    detail: str
    tone: InsightTone = "neutral"
