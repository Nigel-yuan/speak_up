from typing import Any, Literal

from pydantic import BaseModel, Field


ScenarioType = Literal["general", "host", "guest-sharing", "standup"]
LanguageOption = Literal["zh", "en"]
TrainingMode = Literal["free_speech", "document_speech"]
DocumentKind = Literal["pdf", "md"]
DocumentPreviewKind = Literal["none", "pdf"]
DocumentPreviewStatus = Literal["ready", "unavailable"]
CoachDimensionId = Literal["body_expression", "voice_pacing", "content_expression"]
CoachDisplayStatus = Literal["doing_well", "stable", "adjust_now", "analyzing"]
CoachDimensionSource = Literal["system", "omni-coach", "speech-rule"]
CoachSignalPolarity = Literal["positive", "neutral", "negative"]
CoachSignalSeverity = Literal["low", "medium", "high"]
TranscriptSpeaker = Literal["user", "coach"]
SessionStatus = Literal["created", "streaming", "finished"]
VoiceGender = Literal["male", "female"]
VoiceStyle = Literal["professional", "gentle", "firm", "encouraging"]
ReportStatus = Literal["processing", "ready", "failed"]
ReportSectionPhase = Literal["processing", "ready"]
ReportProgressStepPhase = Literal["pending", "active", "done", "failed"]
ReportArtifactType = Literal[
    "transcript_final",
    "transcript_merged",
    "qa_question",
    "coach_signal",
    "coach_panel_snapshot",
    "session_finished",
]
TopDimensionId = Literal[
    "body",
    "facial_expression",
    "vocal_tone",
    "rhythm",
    "content_quality",
    "expression_structure",
]
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


class TranscriptChunk(BaseModel):
    id: str
    speaker: TranscriptSpeaker
    text: str
    timestampLabel: str
    startMs: int = 0
    endMs: int = 0


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
    subDimensionId: str | None = None
    signalPolarity: CoachSignalPolarity | None = None
    severity: CoachSignalSeverity | None = None
    confidence: float | None = None
    evidenceText: str | None = None


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
    subDimensionId: str | None = None
    signalPolarity: CoachSignalPolarity | None = None
    severity: CoachSignalSeverity | None = None
    confidence: float | None = None
    evidenceText: str | None = None


class CoachPanelPatch(BaseModel):
    dimensions: list[CoachPanelPatchDimension] = Field(default_factory=list)


class SessionSetup(BaseModel):
    scenarioId: ScenarioType
    language: LanguageOption
    coachProfileId: str | None = None


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
    expectedPoints: list[str] = Field(default_factory=list)


class QAFeedback(BaseModel):
    turnId: str
    feedbackText: str
    strengths: list[str] = Field(default_factory=list)
    missedPoints: list[str] = Field(default_factory=list)
    nextAction: Literal["follow_up", "next_question", "end_qa"] = "next_question"


class RadarMetric(BaseModel):
    subject: str
    score: int
    fullMark: int


class SuggestionItem(BaseModel):
    title: str
    detail: str


class ReportEvidenceRef(BaseModel):
    timestampMs: int = 0
    quote: str | None = None
    dimensionId: TopDimensionId
    subDimensionId: str | None = None


class ReportSubDimensionScore(BaseModel):
    id: str
    label: str
    score: int
    reason: str


class ReportTopDimensionScore(BaseModel):
    id: TopDimensionId
    label: str
    score: int
    weight: int = 0
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    subDimensions: list[ReportSubDimensionScore] = Field(default_factory=list)
    evidenceRefs: list[ReportEvidenceRef] = Field(default_factory=list)


class ReportArtifactEntry(BaseModel):
    sessionId: str
    type: ReportArtifactType
    timestampMs: int
    payload: dict[str, Any] = Field(default_factory=dict)


class ReportWindowPack(BaseModel):
    sessionId: str
    windowId: str
    windowStartMs: int
    windowEndMs: int
    topDimensionScores: list[ReportTopDimensionScore] = Field(default_factory=list)
    candidateSuggestions: list[SuggestionItem] = Field(default_factory=list)
    evidenceRefs: list[ReportEvidenceRef] = Field(default_factory=list)
    confidence: float | None = None
    createdAt: str


class ReportProgressStep(BaseModel):
    key: str
    label: str
    status: ReportProgressStepPhase = "pending"
    detail: str | None = None


class ReportProgressState(BaseModel):
    currentKey: str = "collecting"
    currentLabel: str = "等待开始"
    detail: str | None = None
    steps: list[ReportProgressStep] = Field(
        default_factory=lambda: [
            ReportProgressStep(key="collecting", label="收集本轮素材"),
            ReportProgressStep(key="structuring", label="整理问答与教练信号"),
            ReportProgressStep(key="generating", label="生成整场分析报告"),
            ReportProgressStep(key="finalizing", label="写入最终结果"),
        ]
    )


class ReportRepositoryState(BaseModel):
    sessionId: str
    scenarioId: ScenarioType
    language: LanguageOption
    coachProfileId: str | None = None
    lastCoveredMs: int = 0
    windowCount: int = 0
    status: ReportStatus = "processing"
    latestArtifactMs: int = 0
    finalGeneratedAt: str | None = None
    finalCoveredMs: int = 0
    errorMessage: str | None = None
    progress: ReportProgressState = Field(default_factory=ReportProgressState)


class ReportSectionStatus(BaseModel):
    summary: ReportSectionPhase = "ready"
    radar: ReportSectionPhase = "ready"
    suggestions: ReportSectionPhase = "ready"


class SessionReport(BaseModel):
    sessionId: str
    coachProfileId: str | None = None
    status: ReportStatus = "ready"
    overallScore: int = 0
    headline: str = ""
    encouragement: str = ""
    summaryParagraph: str = ""
    highlights: list[str] = Field(default_factory=list)
    suggestions: list[SuggestionItem] = Field(default_factory=list)
    radarMetrics: list[RadarMetric] = Field(default_factory=list)
    dimensions: list[ReportTopDimensionScore] = Field(default_factory=list)
    generatedAt: str = ""
    sectionStatus: ReportSectionStatus = Field(default_factory=ReportSectionStatus)
    progress: ReportProgressState = Field(default_factory=ReportProgressState)


class StartSessionRequest(BaseModel):
    scenarioId: ScenarioType
    language: LanguageOption
    coachProfileId: str | None = None


class RealtimeSession(BaseModel):
    sessionId: str
    scenarioId: ScenarioType
    language: LanguageOption
    coachProfileId: str | None = None
    status: SessionStatus
    transcriptCount: int = 0
    audioChunkCount: int = 0
    videoFrameCount: int = 0


class RealtimeSessionResponse(RealtimeSession):
    websocketUrl: str


class ReplayCoachInsight(BaseModel):
    id: str
    startMs: int
    endMs: int
    dimensionId: CoachDimensionId
    subDimensionId: str | None = None
    severity: CoachSignalSeverity = "medium"
    polarity: CoachSignalPolarity = "neutral"
    title: str
    message: str
    evidenceText: str | None = None


class SessionReplay(BaseModel):
    sessionId: str
    scenarioId: ScenarioType
    language: LanguageOption
    coachProfileId: str | None = None
    mediaUrl: str | None = None
    mediaType: Literal["audio", "video"] | None = None
    durationMs: int = 0
    transcript: list[TranscriptChunk] = Field(default_factory=list)
    coachInsights: list[ReplayCoachInsight] = Field(default_factory=list)


class ReplayMediaUploadResponse(BaseModel):
    mediaUrl: str
    mediaType: Literal["audio", "video"]
    durationMs: int = 0


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
