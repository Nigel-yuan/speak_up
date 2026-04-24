"use client";

import { createContext, startTransition, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

import { getSessionReport, triggerSessionReportGeneration } from "@/lib/api";
import type { ReportProgressState, ReportProgressStep, SessionReport } from "@/types/report";
import type { SessionSetup, TranscriptChunk } from "@/types/session";

interface CachedReplayMedia {
  sessionId: string;
  url: string;
  mediaType: "audio" | "video";
  durationMs: number;
}

interface SessionResultContextValue {
  setup: SessionSetup | null;
  report: SessionReport | null;
  replaySessionId: string | null;
  replayMedia: CachedReplayMedia | null;
  transcript: TranscriptChunk[];
  error: string | null;
  cacheReplayMedia: (sessionId: string, blob: Blob, mediaType: "audio" | "video", durationMs: number) => void;
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
  const [replayMedia, setReplayMedia] = useState<CachedReplayMedia | null>(null);
  const [transcript, setTranscript] = useState<TranscriptChunk[]>([]);
  const [error, setError] = useState<string | null>(null);
  const reportPollingTimerRef = useRef<number | null>(null);
  const replayMediaUrlRef = useRef<string | null>(null);

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

  const buildProcessingReport = useCallback((sessionId: string, coachProfileId: string | null): SessionReport => ({
    sessionId,
    coachProfileId,
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

  const buildFailedReport = useCallback((sessionId: string, coachProfileId: string | null, message: string): SessionReport => ({
    sessionId,
    coachProfileId,
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

  useEffect(() => clearReportPolling, [clearReportPolling]);

  useEffect(() => () => {
    if (replayMediaUrlRef.current) {
      URL.revokeObjectURL(replayMediaUrlRef.current);
      replayMediaUrlRef.current = null;
    }
  }, []);

  const applyReport = useCallback((nextReport: SessionReport) => {
    startTransition(() => {
      setReport(nextReport);
    });
    setError(null);
    if (nextReport.status !== "processing") {
      clearReportPolling();
    }
  }, [clearReportPolling]);

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

  const cacheReplayMedia = useCallback((
    sessionId: string,
    blob: Blob,
    mediaType: "audio" | "video",
    durationMs: number,
  ) => {
    if (replayMediaUrlRef.current) {
      URL.revokeObjectURL(replayMediaUrlRef.current);
    }

    const objectUrl = URL.createObjectURL(blob);
    replayMediaUrlRef.current = objectUrl;
    setReplayMedia({
      sessionId,
      url: objectUrl,
      mediaType,
      durationMs: Math.max(0, Math.round(durationMs)),
    });
  }, []);

  const saveResult = useCallback(async (nextSetup: SessionSetup, nextTranscript: TranscriptChunk[], sessionId: string | null) => {
    setSetup(nextSetup);
    setTranscript(nextTranscript);
    setReplaySessionId(sessionId);

    if (sessionId) {
      setReport(buildProcessingReport(sessionId, nextSetup.coachProfileId));
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
    setReport(buildFailedReport("missing-session-id", nextSetup.coachProfileId, message));
    setError(message);
  }, [applyReport, buildFailedReport, buildProcessingReport, clearReportPolling, startReportPolling]);

  const value = useMemo<SessionResultContextValue>(
    () => ({
      setup,
      report,
      replaySessionId,
      replayMedia,
      transcript,
      error,
      cacheReplayMedia,
      saveResult,
    }),
    [cacheReplayMedia, error, replayMedia, report, saveResult, setup, replaySessionId, transcript],
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
