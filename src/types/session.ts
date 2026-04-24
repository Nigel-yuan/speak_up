export type ScenarioType = "host" | "guest-sharing" | "standup";
export type LanguageOption = "zh" | "en";
export type TrainingMode = "free_speech" | "document_speech";
export type TrainingDocumentKind = "pdf" | "md";
export type CoachProfileId = string;
export type VoiceGender = "male" | "female";
export type VoiceStyle = "professional" | "gentle" | "firm" | "encouraging";
export type QAPhase =
  | "idle"
  | "preparing_context"
  | "ai_asking"
  | "user_answering"
  | "evaluating_answer"
  | "ready_next_turn"
  | "completed";

export interface ScenarioOption {
  id: ScenarioType;
  title: string;
  subtitle: string;
  description: string;
  goals: string[];
  audience: string;
  accentColor: string;
}

export interface TranscriptChunk {
  id: string;
  speaker: "user" | "coach";
  text: string;
  timestampLabel: string;
  startMs: number;
  endMs: number;
}

export type CoachDimensionId = "body_expression" | "voice_pacing" | "content_expression";
export type CoachDisplayStatus = "doing_well" | "stable" | "adjust_now" | "analyzing";
export type CoachDimensionSource = "system" | "omni-coach" | "speech-rule";

export interface CoachSummary {
  title: string;
  detail: string;
  sourceDimension: CoachDimensionId | null;
  updatedAtMs: number;
}

export interface CoachDimensionState {
  id: CoachDimensionId;
  status: CoachDisplayStatus;
  headline: string;
  detail: string;
  updatedAtMs: number;
  source: CoachDimensionSource;
}

export interface CoachPanelState {
  summary: CoachSummary;
  bodyExpression: CoachDimensionState;
  voicePacing: CoachDimensionState;
  contentExpression: CoachDimensionState;
}

export interface SessionSetup {
  scenarioId: ScenarioType;
  language: LanguageOption;
  coachProfileId: CoachProfileId;
  trainingMode?: TrainingMode;
  documentName?: string | null;
  documentText?: string | null;
  manualText?: string | null;
}

export interface VoiceProfile {
  id: string;
  label: string;
  gender: VoiceGender;
  style: VoiceStyle;
}

export interface TrainingDocumentPreview {
  kind: "none" | "pdf";
  status: "ready" | "unavailable";
  message: string | null;
}

export interface QAState {
  enabled: boolean;
  phase: QAPhase;
  currentTurnId: string | null;
  currentQuestion: string | null;
  currentQuestionGoal: string | null;
  latestFeedback: string | null;
  speaking: boolean;
  voiceProfileId: string | null;
}

export interface QAQuestion {
  turnId: string;
  questionText: string;
  goal: string;
  followUp: boolean;
  expectedPoints: string[];
}

export interface QAFeedback {
  turnId: string;
  feedbackText: string;
  strengths: string[];
  missedPoints: string[];
  nextAction: "follow_up" | "next_question" | "end_qa";
}

export interface QAAudioStreamStart {
  turnId: string;
  sampleRateHz: number;
  channels: number;
  voiceProfileId: string;
}

export interface QAAudioStreamDelta {
  turnId: string;
  audioBase64: string;
  sampleRateHz: number;
}

export interface QAAudioStreamEnd {
  turnId: string;
  durationMs: number;
  audioUrl: string;
  voiceProfileId: string;
}

export interface TrainingDocumentAsset {
  kind: TrainingDocumentKind;
  name: string;
  objectUrl: string | null;
  markdownSource: string | null;
  extractedText: string | null;
  extractedCharCount: number;
  preview: TrainingDocumentPreview;
}

export interface ReplayCoachInsight {
  id: string;
  startMs: number;
  endMs: number;
  dimensionId: CoachDimensionId;
  subDimensionId: string | null;
  severity: "low" | "medium" | "high";
  polarity: "positive" | "neutral" | "negative";
  title: string;
  message: string;
  evidenceText: string | null;
}

export interface SessionReplay {
  sessionId: string;
  scenarioId: ScenarioType;
  language: LanguageOption;
  coachProfileId: CoachProfileId | null;
  mediaUrl: string | null;
  mediaType: "audio" | "video" | null;
  durationMs: number;
  transcript: TranscriptChunk[];
  coachInsights: ReplayCoachInsight[];
}
