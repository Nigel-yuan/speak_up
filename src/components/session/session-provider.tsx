"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { getHistory, getReport } from "@/lib/api";
import type { SessionReport, HistoricalSessionSummary } from "@/types/report";
import type { SessionSetup } from "@/types/session";

interface SessionResultContextValue {
  setup: SessionSetup | null;
  report: SessionReport | null;
  history: HistoricalSessionSummary[];
  historyLoading: boolean;
  reportLoading: boolean;
  error: string | null;
  refreshHistory: () => Promise<void>;
  saveResult: (setup: SessionSetup) => Promise<void>;
}

const SessionResultContext = createContext<SessionResultContextValue | null>(null);

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [setup, setSetup] = useState<SessionSetup | null>(null);
  const [report, setReport] = useState<SessionReport | null>(null);
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

  const saveResult = useCallback(async (nextSetup: SessionSetup) => {
    setSetup(nextSetup);
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
      history,
      historyLoading,
      reportLoading,
      error,
      refreshHistory,
      saveResult,
    }),
    [error, history, historyLoading, refreshHistory, report, reportLoading, saveResult, setup],
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
