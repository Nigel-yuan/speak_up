"use client";

import { createContext, startTransition, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

import { getHistory, getSessionReport, triggerSessionReportGeneration } from "@/lib/api";
import type { HistoricalSessionSummary, ReportProgressState, ReportProgressStep, SessionReport } from "@/types/report";
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
type ReportStepStatus = ReportProgressStep["status"];

function buildProgressSteps(
  activeKey: string,
  options?: {
    failedKey?: string;
    detailByKey?: Partial<Record<(typeof REPORT_PROGRESS_STEPS)[number]["key"], string>>;
  },
) {
  const activeIndex = REPORT_PROGRESS_STEPS.findIndex((step) => step.key === activeKey);

  return REPORT_PROGRESS_STEPS.map((step, index) => {
    let status: ReportStepStatus = "pending";
    if (options?.failedKey && step.key === options.failedKey) {
      status = "failed";
    } else if (step.key === activeKey) {
      status = "active";
    } else if (activeIndex >= 0 && index < activeIndex) {
      status = "done";
    }
    return {
      ...step,
      status,
      detail: options?.detailByKey?.[step.key] ?? null,
    };
  });
}

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [setup, setSetup] = useState<SessionSetup | null>(null);
  const [report, setReport] = useState<SessionReport | null>(null);
  const [replaySessionId, setReplaySessionId] = useState<string | null>(null);
  const [transcript, setTranscript] = useState<TranscriptChunk[]>([]);
  const [history, setHistory] = useState<HistoricalSessionSummary[]>([]);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const reportPollingTimerRef = useRef<number | null>(null);

  const clearReportPolling = useCallback(() => {
    if (reportPollingTimerRef.current !== null) {
      window.clearInterval(reportPollingTimerRef.current);
      reportPollingTimerRef.current = null;
    }
  }, []);

  const buildProcessingProgress = useCallback((): ReportProgressState => ({
    currentKey: "collecting",
    currentLabel: "收集本轮素材",
    detail: "正在收集文字稿、问答提问和 AI Live Coach 信号。",
    steps: buildProgressSteps("collecting", {
      detailByKey: {
        collecting: "正在收集文字稿、问答提问和 AI Live Coach 信号。",
      },
    }),
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
      steps: buildProgressSteps("generating", {
        failedKey: "generating",
        detailByKey: {
          generating: message,
        },
      }),
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

  useEffect(() => clearReportPolling, [clearReportPolling]);

  const applyReport = useCallback((nextReport: SessionReport) => {
    startTransition(() => {
      setReport(nextReport);
    });
    setError(null);
    if (nextReport.status !== "processing") {
      clearReportPolling();
    }
    if (nextReport.status === "ready") {
      void refreshHistory();
    }
  }, [clearReportPolling, refreshHistory]);

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
      setReport(buildProcessingReport(sessionId));
      setError(null);
      startReportPolling(sessionId);
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
    setReport(buildFailedReport("missing-session-id", message));
    setError(message);
  }, [applyReport, buildFailedReport, buildProcessingReport, clearReportPolling, startReportPolling]);

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
