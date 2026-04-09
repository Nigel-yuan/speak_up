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
}

export interface LiveInsight {
  id: string;
  title: string;
  detail: string;
  tone: "positive" | "neutral" | "warning";
}

export interface SessionSetup {
  scenarioId: ScenarioType;
  language: LanguageOption;
  debugEnabled: boolean;
}
