export type ScenarioType = "host" | "guest-sharing" | "standup";
export type LanguageOption = "zh" | "en";
export type TrainingMode = "free_speech" | "document_speech";
export type TrainingDocumentKind = "pdf" | "md";

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
}

export interface TrainingDocumentAsset {
  kind: TrainingDocumentKind;
  name: string;
  objectUrl: string | null;
  markdownSource: string | null;
}

export interface SessionReplay {
  sessionId: string;
  scenarioId: ScenarioType;
  language: LanguageOption;
  mediaUrl: string | null;
  mediaType: "audio" | "video" | null;
  transcript: TranscriptChunk[];
}
