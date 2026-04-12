"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { getHistory, getReport } from "@/lib/api";
import type { HistoricalSessionSummary, SessionReport } from "@/types/report";
import type { SessionSetup, TranscriptChunk } from "@/types/session";

interface SessionResultContextValue {
  setup: SessionSetup | null;
  report: SessionReport | null;
  replaySessionId: string | null;
  transcript: TranscriptChunk[];
  history: HistoricalSessionSummary[];
  historyLoading: boolean;
  reportLoading: boolean;
  error: string | null;
  refreshHistory: () => Promise<void>;
  saveResult: (setup: SessionSetup, transcript: TranscriptChunk[], sessionId: string | null) => Promise<void>;
}

const SessionResultContext = createContext<SessionResultContextValue | null>(null);

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [setup, setSetup] = useState<SessionSetup | null>(null);
  const [report, setReport] = useState<SessionReport | null>(null);
  const [replaySessionId, setReplaySessionId] = useState<string | null>(null);
  const [transcript, setTranscript] = useState<TranscriptChunk[]>([]);
  const [history, setHistory] = useState<HistoricalSessionSummary[]>([]);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [reportLoading, setReportLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

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

  const saveResult = useCallback(async (nextSetup: SessionSetup, nextTranscript: TranscriptChunk[], sessionId: string | null) => {
    setSetup(nextSetup);
    setTranscript(nextTranscript);
    setReplaySessionId(sessionId);
    setReportLoading(true);

    try {
      const nextReport = await getReport(nextSetup.scenarioId);
      setReport(nextReport);
      setError(null);
      await refreshHistory();
    } catch {
      setReport(null);
      setError("报告加载失败");
      throw new Error("报告加载失败");
    } finally {
      setReportLoading(false);
    }
  }, [refreshHistory]);

  const value = useMemo<SessionResultContextValue>(
    () => ({
      setup,
      report,
      replaySessionId,
      transcript,
      history,
      historyLoading,
      reportLoading,
      error,
      refreshHistory,
      saveResult,
    }),
    [error, history, historyLoading, refreshHistory, report, reportLoading, saveResult, setup, replaySessionId, transcript],
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
