import type { HistoricalSessionSummary, SessionReport } from "@/types/report";
import type {
  CoachPanelState,
  QAFeedback,
  QAAudioStreamDelta,
  QAAudioStreamEnd,
  QAAudioStreamStart,
  QAQuestion,
  QAState,
  LanguageOption,
  ScenarioOption,
  ScenarioType,
  SessionReplay,
  TrainingMode,
  TranscriptChunk,
  VoiceProfile,
} from "@/types/session";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

export function resolveApiUrl(url: string | null | undefined) {
  if (!url) {
    return "";
  }
  if (url.startsWith("http://") || url.startsWith("https://")) {
    return url;
  }
  return `${API_BASE_URL}${url}`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);

  if (!(init?.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      cache: "no-store",
      ...init,
      headers,
    });
  } catch (error) {
    const detail = error instanceof Error ? error.message : "unknown network error";
    throw new Error(`无法连接后端服务，请确认 API 正在运行且 CORS 配置正确：${detail}`);
  }

  if (!response.ok) {
    const contentType = response.headers.get("Content-Type") ?? "";
    if (contentType.includes("application/json")) {
      const payload = await response.json().catch(() => null);
      const detail = typeof payload?.detail === "string" ? payload.detail : null;
      throw new Error(detail ?? `Request failed: ${response.status}`);
    }
    const detail = await response.text().catch(() => "");
    throw new Error(detail || `Request failed: ${response.status}`);
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
  qaState?: QAState | null;
  question?: QAQuestion | null;
  feedback?: QAFeedback | null;
  sampleRateHz?: number | null;
  channels?: number | null;
  audioBase64?: string | null;
  voiceProfileId?: string | null;
  audioStreamStart?: QAAudioStreamStart | null;
  audioStreamDelta?: QAAudioStreamDelta | null;
  audioStreamEnd?: QAAudioStreamEnd | null;
  turnId?: string | null;
  audioUrl?: string | null;
  durationMs?: number | null;
  voiceProfiles?: VoiceProfile[] | null;
}

export function getSessionStream(scenario: ScenarioType, language: LanguageOption) {
  return request<SessionStreamFrame[]>(`/api/session-stream?scenario=${scenario}&language=${language}`);
}

export function getReport(scenario: ScenarioType) {
  return request<SessionReport>(`/api/report?scenario=${scenario}`);
}

export function getSessionReport(sessionId: string) {
  return request<SessionReport>(`/api/session/${sessionId}/report`);
}

export function triggerSessionReportGeneration(sessionId: string) {
  return request<SessionReport>(`/api/session/${sessionId}/report/generate`, {
    method: "POST",
  });
}

export interface ReportReassuranceAudio {
  text: string;
  audioUrl: string;
  durationMs: number;
  voiceProfileId: string;
}

export function triggerReportReassuranceAudio(
  sessionId: string,
  options?: {
    attemptIndex?: number;
    voiceProfileId?: string | null;
  },
) {
  return request<ReportReassuranceAudio>(`/api/session/${sessionId}/report/reassurance-audio`, {
    method: "POST",
    body: JSON.stringify({
      attemptIndex: options?.attemptIndex ?? 0,
      voiceProfileId: options?.voiceProfileId ?? null,
    }),
  });
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

export function getQAVoiceProfiles() {
  return request<VoiceProfile[]>("/api/qa/voice-profiles");
}

export interface DocumentExtractionResult {
  kind: "pdf" | "md";
  filename: string;
  text: string;
  charCount: number;
  preview: {
    kind: "none" | "pdf";
    status: "ready" | "unavailable";
    message: string | null;
  };
}

export function extractDocumentText(file: File) {
  const formData = new FormData();
  formData.append("file", file);
  return request<DocumentExtractionResult>("/api/document/extract", {
    method: "POST",
    body: formData,
  });
}

export interface OutboundRealtimeMessage {
  type:
    | "ping"
    | "start_stream"
    | "audio_chunk"
    | "video_frame"
    | "start_qa"
    | "stop_qa"
    | "qa_prewarm_context"
    | "qa_select_voice_profile"
    | "qa_audio_playback_started"
    | "qa_audio_playback_ended";
  timestamp_ms?: number;
  payload?: string;
  turn_id?: string;
  image_base64?: string;
  mime_type?: string;
  sample_rate_hz?: number;
  channels?: number;
  training_mode?: TrainingMode;
  voice_profile_id?: string;
  document_name?: string;
  document_text?: string;
  manual_text?: string;
}
