import type { ScenarioType } from "./session";

export interface RadarMetric {
  subject: string;
  score: number;
  fullMark: number;
}

export interface SuggestionItem {
  title: string;
  detail: string;
}

export interface HistoricalSessionSummary {
  id: string;
  label: string;
  scenarioId: ScenarioType;
  overallScore: number;
  summary: string;
  deltas: Array<{
    metric: string;
    change: number;
  }>;
}

export interface SessionReport {
  overallScore: number;
  headline: string;
  encouragement: string;
  highlights: string[];
  suggestions: SuggestionItem[];
  radarMetrics: RadarMetric[];
  comparisonSummary: string;
}
