"use client";

import { createContext, startTransition, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

import { playBufferedAudioFromUrl, type AudioPlaybackHandle } from "@/lib/audio-playback";
import { getHistory, getSessionReport, resolveApiUrl, triggerReportReassuranceAudio, triggerSessionReportGeneration } from "@/lib/api";
import type { HistoricalSessionSummary, SessionReport } from "@/types/report";
import type { SessionSetup, TranscriptChunk } from "@/types/session";

interface SessionResultContextValue {
  setup: SessionSetup | null;
  report: SessionReport | null;
  replaySessionId: string | null;
  transcript: TranscriptChunk[];
  history: HistoricalSessionSummary[];
  historyLoading: boolean;
  error: string | null;
  refreshHistory: () => Promise<void>;
  saveResult: (setup: SessionSetup, transcript: TranscriptChunk[], sessionId: string | null) => Promise<void>;
}

const SessionResultContext = createContext<SessionResultContextValue | null>(null);
const REPORT_PROGRESS_STEPS = [
  { key: "collecting", label: "收集本轮素材" },
  { key: "structuring", label: "整理问答与教练信号" },
  { key: "generating", label: "生成整场分析报告" },
  { key: "finalizing", label: "写入最终结果" },
] as const;
const REPORT_REASSURANCE_MAX_ATTEMPTS = 3;
const REPORT_REASSURANCE_RETRY_DELAY_MS = 420;

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [setup, setSetup] = useState<SessionSetup | null>(null);
  const [report, setReport] = useState<SessionReport | null>(null);
  const [replaySessionId, setReplaySessionId] = useState<string | null>(null);
  const [transcript, setTranscript] = useState<TranscriptChunk[]>([]);
  const [history, setHistory] = useState<HistoricalSessionSummary[]>([]);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const reportPollingTimerRef = useRef<number | null>(null);
  const reportReassuranceRequestedSessionRef = useRef<string | null>(null);
  const reportReassurancePlaybackRef = useRef<AudioPlaybackHandle | null>(null);
  const reportReassuranceRequestTokenRef = useRef(0);
  const reportReassuranceAttemptRef = useRef(0);
  const reportReassuranceLoopTimerRef = useRef<number | null>(null);
  const latestReportRef = useRef<SessionReport | null>(null);

  const clearReportReassuranceTimers = useCallback(() => {
    if (reportReassuranceLoopTimerRef.current !== null) {
      window.clearTimeout(reportReassuranceLoopTimerRef.current);
      reportReassuranceLoopTimerRef.current = null;
    }
  }, []);

  const isProcessingReportSession = useCallback((sessionId: string, candidate: SessionReport | null) => (
    candidate?.sessionId === sessionId && candidate.status === "processing"
  ), []);

  const stopReportReassuranceAudio = useCallback((smooth: boolean) => {
    clearReportReassuranceTimers();
    reportReassurancePlaybackRef.current?.stop(smooth);
    reportReassurancePlaybackRef.current = null;
  }, [clearReportReassuranceTimers]);

  const cancelReportReassurance = useCallback((smooth: boolean) => {
    reportReassuranceRequestTokenRef.current += 1;
    reportReassuranceRequestedSessionRef.current = null;
    stopReportReassuranceAudio(smooth);
  }, [stopReportReassuranceAudio]);

  const startReportReassuranceAudio = useCallback(async (sessionId: string) => {
    if (reportReassuranceRequestedSessionRef.current === sessionId) {
      return;
    }
    if (reportReassuranceAttemptRef.current >= REPORT_REASSURANCE_MAX_ATTEMPTS) {
      return;
    }
    reportReassuranceRequestedSessionRef.current = sessionId;
    const requestToken = reportReassuranceRequestTokenRef.current + 1;
    reportReassuranceRequestTokenRef.current = requestToken;
    const attemptIndex = reportReassuranceAttemptRef.current;
    reportReassuranceAttemptRef.current += 1;

    try {
      const payload = await triggerReportReassuranceAudio(sessionId, {
        attemptIndex,
        voiceProfileId: "female_gentle_01",
      });
      const activeReport = latestReportRef.current;
      if (
        reportReassuranceRequestTokenRef.current !== requestToken ||
        !payload.audioUrl ||
        !isProcessingReportSession(sessionId, activeReport)
      ) {
        reportReassuranceRequestedSessionRef.current = null;
        return;
      }

      stopReportReassuranceAudio(false);
      const resolvedUrl = resolveApiUrl(payload.audioUrl);
      const playbackHandle = await playBufferedAudioFromUrl(resolvedUrl, {
        volume: 0.92,
        onEnded: () => {
          reportReassurancePlaybackRef.current = null;
          reportReassuranceRequestedSessionRef.current = null;
          const activeReport = latestReportRef.current;
          if (isProcessingReportSession(sessionId, activeReport) && reportReassuranceAttemptRef.current < REPORT_REASSURANCE_MAX_ATTEMPTS) {
            reportReassuranceLoopTimerRef.current = window.setTimeout(() => {
              reportReassuranceLoopTimerRef.current = null;
              void startReportReassuranceAudio(sessionId);
            }, REPORT_REASSURANCE_RETRY_DELAY_MS);
          }
        },
      });
      const activeReportAfterStart = latestReportRef.current;
      if (
        reportReassuranceRequestTokenRef.current !== requestToken ||
        !isProcessingReportSession(sessionId, activeReportAfterStart)
      ) {
        playbackHandle.stop(false);
        reportReassuranceRequestedSessionRef.current = null;
        return;
      }

      reportReassurancePlaybackRef.current = playbackHandle;
    } catch {
      reportReassuranceRequestedSessionRef.current = null;
    }
  }, [isProcessingReportSession, stopReportReassuranceAudio]);

  const clearReportPolling = useCallback(() => {
    if (reportPollingTimerRef.current !== null) {
      window.clearInterval(reportPollingTimerRef.current);
      reportPollingTimerRef.current = null;
    }
  }, []);

  const buildProcessingProgress = useCallback(() => ({
    currentKey: "collecting",
    currentLabel: "收集本轮素材",
    detail: "正在收集文字稿、问答提问和 AI Live Coach 信号。",
    steps: REPORT_PROGRESS_STEPS.map((step, index) => ({
      ...step,
      status: index === 0 ? "active" : "pending",
      detail: index === 0 ? "正在收集文字稿、问答提问和 AI Live Coach 信号。" : null,
    })),
  }), []);

  const buildProcessingReport = useCallback((sessionId: string): SessionReport => ({
    sessionId,
    status: "processing",
    overallScore: 0,
    headline: "AI 分析中...",
    encouragement: "回放和文字稿已经可看，AI 正在一次性生成完整报告。",
    summaryParagraph: "报告生成完成后，页面会自动切换为最终结果。",
    highlights: [],
    suggestions: [],
    radarMetrics: [],
    dimensions: [],
    generatedAt: "",
    sectionStatus: {
      summary: "processing",
      radar: "processing",
      suggestions: "processing",
    },
    progress: buildProcessingProgress(),
  }), [buildProcessingProgress]);

  const buildFailedReport = useCallback((sessionId: string, message: string): SessionReport => ({
    sessionId,
    status: "failed",
    overallScore: 0,
    headline: "报告生成失败",
    encouragement: message,
    summaryParagraph: "这次未能生成报告。请重新发起一轮会话；如果问题持续出现，需要继续排查 session 建立或 finish 链路。",
    highlights: [],
    suggestions: [],
    radarMetrics: [],
    dimensions: [],
    generatedAt: "",
    sectionStatus: {
      summary: "ready",
      radar: "ready",
      suggestions: "ready",
    },
    progress: {
      currentKey: "finalizing",
      currentLabel: "报告生成失败",
      detail: message,
      steps: REPORT_PROGRESS_STEPS.map((step, index) => ({
        ...step,
        status: index < 2 ? "done" : index === 2 ? "failed" : "pending",
        detail: index === 2 ? message : null,
      })),
    },
  }), []);

  const refreshHistory = useCallback(async () => {
    setHistoryLoading(true);

    try {
      const nextHistory = await getHistory();
      setHistory(nextHistory);
      setError(null);
    } catch {
      setError("历史记录加载失败");
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshHistory();
  }, [refreshHistory]);

  useEffect(() => {
    latestReportRef.current = report;
  }, [report]);

  useEffect(() => clearReportPolling, [clearReportPolling]);
  useEffect(() => () => {
    cancelReportReassurance(false);
  }, [cancelReportReassurance]);

  const applyReport = useCallback((nextReport: SessionReport) => {
    startTransition(() => {
      setReport(nextReport);
    });
    setError(null);
    if (nextReport.status !== "processing") {
      clearReportPolling();
      cancelReportReassurance(true);
    }
    if (nextReport.status === "ready") {
      void refreshHistory();
    }
  }, [cancelReportReassurance, clearReportPolling, refreshHistory]);

  const startReportPolling = useCallback((sessionId: string) => {
    clearReportPolling();
    reportPollingTimerRef.current = window.setInterval(() => {
      void getSessionReport(sessionId)
        .then((nextReport) => {
          applyReport(nextReport);
        })
        .catch(() => undefined);
    }, 1200);
  }, [applyReport, clearReportPolling]);

  const saveResult = useCallback(async (nextSetup: SessionSetup, nextTranscript: TranscriptChunk[], sessionId: string | null) => {
    setSetup(nextSetup);
    setTranscript(nextTranscript);
    setReplaySessionId(sessionId);

    if (sessionId) {
      cancelReportReassurance(false);
      reportReassuranceAttemptRef.current = 0;
      const processingReport = buildProcessingReport(sessionId);
      latestReportRef.current = processingReport;
      setReport(processingReport);
      setError(null);
      startReportPolling(sessionId);
      void startReportReassuranceAudio(sessionId);
      void triggerSessionReportGeneration(sessionId)
        .then((nextReport) => {
          applyReport(nextReport);
          setError(null);
        })
        .catch(() => {
          void getSessionReport(sessionId)
            .then((nextReport) => {
              applyReport(nextReport);
            })
            .catch(() => {
              clearReportPolling();
              setError("报告加载失败");
            });
        });
      return;
    }

    const message = "未获取到有效 sessionId，无法生成报告。";
    cancelReportReassurance(false);
    setReport(buildFailedReport("missing-session-id", message));
    setError(message);
  }, [applyReport, buildFailedReport, buildProcessingReport, cancelReportReassurance, clearReportPolling, startReportPolling, startReportReassuranceAudio]);

  const value = useMemo<SessionResultContextValue>(
    () => ({
      setup,
      report,
      replaySessionId,
      transcript,
      history,
      historyLoading,
      error,
      refreshHistory,
      saveResult,
    }),
    [error, history, historyLoading, refreshHistory, report, saveResult, setup, replaySessionId, transcript],
  );

  return <SessionResultContext.Provider value={value}>{children}</SessionResultContext.Provider>;
}

export function useSessionResult() {
  const context = useContext(SessionResultContext);

  if (!context) {
    throw new Error("useSessionResult must be used within SessionProvider");
  }

  return context;
}
