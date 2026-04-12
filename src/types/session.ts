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
}

export interface PoseSnapshot {
  bodyPresent: boolean;
  faceVisible: boolean;
  handsVisible: boolean;
  shoulderVisible: boolean;
  hipVisible: boolean;
  bodyScale: number;
  centerOffsetX: number;
  shoulderTiltDeg: number;
  torsoTiltDeg: number;
  gestureActivity: number;
  stabilityScore: number;
}

export interface PoseDebugState {
  snapshotCount: number;
  closeUpMode: boolean;
  selectedRuleKey: string | null;
  selectedRuleTitle: string | null;
  selectedRuleTone: "positive" | "neutral" | "warning" | null;
  bodyPresenceRatio: number;
  faceVisibilityRatio: number;
  handsVisibilityRatio: number;
  shoulderVisibilityRatio: number;
  hipVisibilityRatio: number;
  averageBodyScale: number;
  averageCenterOffsetX: number;
  averageShoulderTiltDeg: number;
  averageTorsoTiltDeg: number;
  averageGestureActivity: number;
  averageStabilityScore: number;
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
