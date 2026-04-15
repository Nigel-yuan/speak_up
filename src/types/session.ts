export type ScenarioType = "host" | "guest-sharing" | "standup";
export type LanguageOption = "zh" | "en";

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

export interface LiveInsight {
  id: string;
  title: string;
  detail: string;
  tone: "positive" | "neutral" | "warning";
  source: "system" | "omni-coach" | "manual";
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

export interface OmniDebugState {
  configured: boolean;
  connected: boolean;
  sessionUpdated: boolean;
  responseCount: number;
  insightCount: number;
  lastStage: string | null;
  lastEventType: string | null;
  lastTextPreview: string | null;
  lastInsightTitle: string | null;
  lastError: string | null;
}

export interface SessionSetup {
  scenarioId: ScenarioType;
  language: LanguageOption;
  debugEnabled: boolean;
}

export interface SessionReplay {
  sessionId: string;
  scenarioId: ScenarioType;
  language: LanguageOption;
  mediaUrl: string | null;
  mediaType: "audio" | "video" | null;
  transcript: TranscriptChunk[];
}
