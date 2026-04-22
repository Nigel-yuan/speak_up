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

export interface ReportEvidenceRef {
  timestampMs: number;
  quote: string | null;
  dimensionId: string;
  subDimensionId: string | null;
}

export interface ReportSubDimensionScore {
  id: string;
  label: string;
  score: number;
  reason: string;
}

export interface ReportTopDimensionScore {
  id: string;
  label: string;
  score: number;
  weight: number;
  strengths: string[];
  weaknesses: string[];
  subDimensions: ReportSubDimensionScore[];
  evidenceRefs: ReportEvidenceRef[];
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

export interface ReportProgressStep {
  key: string;
  label: string;
  status: "pending" | "active" | "done" | "failed";
  detail: string | null;
}

export interface ReportProgressState {
  currentKey: string;
  currentLabel: string;
  detail: string | null;
  steps: ReportProgressStep[];
}

export interface SessionReport {
  sessionId: string;
  status: "processing" | "ready" | "failed";
  overallScore: number;
  headline: string;
  encouragement: string;
  summaryParagraph: string;
  highlights: string[];
  suggestions: SuggestionItem[];
  radarMetrics: RadarMetric[];
  dimensions: ReportTopDimensionScore[];
  generatedAt: string;
  sectionStatus: {
    summary: "processing" | "ready";
    radar: "processing" | "ready";
    suggestions: "processing" | "ready";
  };
  progress: ReportProgressState;
}
