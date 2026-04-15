import type { HistoricalSessionSummary, SessionReport } from "@/types/report";
import type {
  CoachPanelState,
  LanguageOption,
  ScenarioOption,
  ScenarioType,
  SessionReplay,
  TranscriptChunk,
} from "@/types/session";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);

  if (!(init?.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    cache: "no-store",
    ...init,
    headers,
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
  transcript: TranscriptChunk;
  insight: {
    id: string;
    title: string;
    detail: string;
    tone: "positive" | "neutral" | "warning";
    source: "system" | "omni-coach" | "manual";
  };
}

export interface RealtimeSession {
  sessionId: string;
  scenarioId: ScenarioType;
  language: LanguageOption;
  status: "created" | "streaming" | "finished";
  transcriptCount: number;
  audioChunkCount: number;
  videoFrameCount: number;
}

export interface RealtimeSessionResponse extends RealtimeSession {
  websocketUrl: string;
}

export interface RealtimeEvent {
  type: string;
  status: "created" | "streaming" | "finished" | null;
  sessionId: string | null;
  text: string | null;
  message: string | null;
  chunk: TranscriptChunk | null;
  replacePrevious?: boolean;
  coachPanel?: CoachPanelState | null;
}

export function getSessionStream(scenario: ScenarioType, language: LanguageOption) {
  return request<SessionStreamFrame[]>(`/api/session-stream?scenario=${scenario}&language=${language}`);
}

export function getReport(scenario: ScenarioType) {
  return request<SessionReport>(`/api/report?scenario=${scenario}`);
}

export function getSessionReplay(sessionId: string) {
  return request<SessionReplay>(`/api/session/${sessionId}/replay`);
}

export function startRealtimeSession(
  scenarioId: ScenarioType,
  language: LanguageOption,
) {
  return request<RealtimeSessionResponse>("/api/session/start", {
    method: "POST",
    body: JSON.stringify({ scenarioId, language }),
  });
}

export function finishRealtimeSession(sessionId: string) {
  return request<RealtimeSession>(`/api/session/${sessionId}/finish`, {
    method: "POST",
  });
}

export interface OutboundRealtimeMessage {
  type: "ping" | "start_stream" | "audio_chunk" | "video_frame";
  timestamp_ms?: number;
  payload?: string;
  image_base64?: string;
  mime_type?: string;
  sample_rate_hz?: number;
  channels?: number;
}
