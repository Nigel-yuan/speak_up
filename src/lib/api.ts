import type { HistoricalSessionSummary, SessionReport } from "@/types/report";
import type { LanguageOption, ScenarioOption, ScenarioType } from "@/types/session";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    cache: "no-store",
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });

  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }

  return response.json() as Promise<T>;
}

export function getScenarios() {
  return request<ScenarioOption[]>("/api/scenarios");
}

export function getHistory(scenario?: ScenarioType) {
  const query = scenario ? `?scenario=${scenario}` : "";
  return request<HistoricalSessionSummary[]>(`/api/history${query}`);
}

export interface SessionStreamFrame {
  second: number;
  transcript: {
    id: string;
    speaker: "user" | "coach";
    text: string;
    timestampLabel: string;
  };
  insight: {
    id: string;
    title: string;
    detail: string;
    tone: "positive" | "neutral" | "warning";
  };
}

export interface RealtimeSessionResponse {
  sessionId: string;
  scenarioId: ScenarioType;
  language: LanguageOption;
  status: "created" | "streaming" | "finished";
  transcriptCount: number;
  insightCount: number;
  audioChunkCount: number;
  videoFrameCount: number;
  websocketUrl: string;
}

export interface RealtimeEvent {
  type: string;
  status: "created" | "streaming" | "finished" | null;
  sessionId: string | null;
  text: string | null;
  message: string | null;
  chunk:
    | {
        id: string;
        speaker: "user" | "coach";
        text: string;
        timestampLabel: string;
      }
    | null;
  insight:
    | {
        id: string;
        title: string;
        detail: string;
        tone: "positive" | "neutral" | "warning";
      }
    | null;
}

export function getSessionStream(scenario: ScenarioType, language: LanguageOption) {
  return request<SessionStreamFrame[]>(`/api/session-stream?scenario=${scenario}&language=${language}`);
}

export function getReport(scenario: ScenarioType) {
  return request<SessionReport>(`/api/report?scenario=${scenario}`);
}

export function startRealtimeSession(scenarioId: ScenarioType, language: LanguageOption) {
  return request<RealtimeSessionResponse>("/api/session/start", {
    method: "POST",
    body: JSON.stringify({ scenarioId, language }),
  });
}

export interface OutboundRealtimeMessage {
  type:
    | "ping"
    | "start_stream"
    | "audio_chunk"
    | "video_frame"
    | "inject_partial"
    | "inject_transcript"
    | "inject_insight";
  timestamp_ms?: number;
  payload?: string;
  image_base64?: string;
  mime_type?: string;
  text?: string;
  title?: string;
  detail?: string;
  tone?: "positive" | "neutral" | "warning";
  timestamp_label?: string;
}
