from typing import Literal

from pydantic import BaseModel


ScenarioType = Literal["host", "guest-sharing", "standup"]
LanguageOption = Literal["zh", "en"]
TrainingMode = Literal["free_speech", "document_speech"]
DocumentKind = Literal["pdf", "md"]
DocumentPreviewKind = Literal["none", "pdf"]
DocumentPreviewStatus = Literal["ready", "unavailable"]
InsightTone = Literal["positive", "neutral", "warning"]
InsightSource = Literal["system", "omni-coach", "manual"]
CoachDimensionId = Literal["body_expression", "voice_pacing", "content_expression"]
CoachDisplayStatus = Literal["doing_well", "stable", "adjust_now", "analyzing"]
CoachDimensionSource = Literal["system", "omni-coach", "speech-rule"]
TranscriptSpeaker = Literal["user", "coach"]
SessionStatus = Literal["created", "streaming", "finished"]
VoiceGender = Literal["male", "female"]
VoiceStyle = Literal["professional", "gentle", "firm", "encouraging"]
QAPhase = Literal[
    "idle",
    "preparing_context",
    "ai_asking",
    "user_answering",
    "evaluating_answer",
    "ready_next_turn",
    "completed",
]
RealtimeEventType = Literal[
    "session_status",
    "transcript_partial",
    "transcript_final",
    "coach_panel",
    "qa_state",
    "qa_question",
    "qa_audio",
    "qa_audio_stream_start",
    "qa_audio_stream_delta",
    "qa_audio_stream_end",
    "qa_feedback",
    "qa_voice_profiles",
    "pong",
    "ack",
    "error",
]
ClientMessageType = Literal[
    "ping",
    "start_stream",
    "audio_chunk",
    "video_frame",
    "start_qa",
    "stop_qa",
    "qa_prewarm_context",
    "qa_request_question",
    "qa_stop_answer",
    "qa_select_voice_profile",
    "qa_audio_playback_started",
    "qa_audio_playback_ended",
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


class VoiceProfile(BaseModel):
    id: str
    label: str
    gender: VoiceGender
    style: VoiceStyle


class DocumentPreview(BaseModel):
    kind: DocumentPreviewKind = "none"
    status: DocumentPreviewStatus = "unavailable"
    message: str | None = None


class DocumentExtractionResponse(BaseModel):
    kind: DocumentKind
    filename: str
    text: str
    charCount: int
    preview: DocumentPreview = DocumentPreview()


class QAState(BaseModel):
    enabled: bool = False
    phase: QAPhase = "idle"
    currentTurnId: str | None = None
    currentQuestion: str | None = None
    currentQuestionGoal: str | None = None
    latestFeedback: str | None = None
    speaking: bool = False
    voiceProfileId: str | None = None


class QAQuestion(BaseModel):
    turnId: str
    questionText: str
    goal: str
    followUp: bool = False
    expectedPoints: list[str] = []


class QAFeedback(BaseModel):
    turnId: str
    feedbackText: str
    strengths: list[str] = []
    missedPoints: list[str] = []
    nextAction: Literal["follow_up", "next_question", "end_qa"] = "next_question"


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


class QAStateEvent(BaseModel):
    type: Literal["qa_state"] = "qa_state"
    qaState: QAState


class QAQuestionEvent(BaseModel):
    type: Literal["qa_question"] = "qa_question"
    question: QAQuestion


class QAAudioEvent(BaseModel):
    type: Literal["qa_audio"] = "qa_audio"
    turnId: str
    audioUrl: str
    durationMs: int
    voiceProfileId: str


class QAAudioStreamStartEvent(BaseModel):
    type: Literal["qa_audio_stream_start"] = "qa_audio_stream_start"
    turnId: str
    sampleRateHz: int
    channels: int = 1
    voiceProfileId: str


class QAAudioStreamDeltaEvent(BaseModel):
    type: Literal["qa_audio_stream_delta"] = "qa_audio_stream_delta"
    turnId: str
    audioBase64: str
    sampleRateHz: int


class QAAudioStreamEndEvent(BaseModel):
    type: Literal["qa_audio_stream_end"] = "qa_audio_stream_end"
    turnId: str
    durationMs: int
    audioUrl: str
    voiceProfileId: str


class QAFeedbackEvent(BaseModel):
    type: Literal["qa_feedback"] = "qa_feedback"
    feedback: QAFeedback


class QAVoiceProfilesEvent(BaseModel):
    type: Literal["qa_voice_profiles"] = "qa_voice_profiles"
    voiceProfiles: list[VoiceProfile]


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
    turn_id: str | None = None
    image_base64: str | None = None
    mime_type: str | None = None
    sample_rate_hz: int | None = None
    channels: int | None = None
    training_mode: TrainingMode | None = None
    voice_profile_id: str | None = None
    document_name: str | None = None
    document_text: str | None = None
    manual_text: str | None = None
