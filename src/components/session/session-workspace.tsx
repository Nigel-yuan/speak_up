"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { CameraPanel } from "@/components/session/camera-panel";
import { HistorySidebar } from "@/components/session/history-sidebar";
import { LiveAnalysisPanel } from "@/components/session/live-analysis-panel";
import { SessionToolbar } from "@/components/session/session-toolbar";
import { SessionControls } from "@/components/session/session-controls";
import { useSessionResult } from "@/components/session/session-provider";
import { TranscriptPanel } from "@/components/session/transcript-panel";
import { useMockSession } from "@/hooks/useMockSession";
import { getScenarios } from "@/lib/api";
import type { LanguageOption, ScenarioOption, ScenarioType } from "@/types/session";

interface SessionWorkspaceProps {
  defaultLanguage?: LanguageOption;
  defaultScenario?: ScenarioType;
}

export function SessionWorkspace({
  defaultLanguage = "zh",
  defaultScenario = "host",
}: SessionWorkspaceProps) {
  const router = useRouter();
  const { error: sessionError, history, saveResult } = useSessionResult();
  const [language, setLanguage] = useState<LanguageOption>(defaultLanguage);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [scenarioOpen, setScenarioOpen] = useState(false);
  const [scenariosData, setScenariosData] = useState<{
    error: string | null;
    isLoading: boolean;
    items: ScenarioOption[];
  }>({
    error: null,
    isLoading: true,
    items: [],
  });
  const [selectedScenarioId, setSelectedScenarioId] = useState<ScenarioType>(defaultScenario);

  useEffect(() => {
    let active = true;

    void getScenarios()
      .then((nextScenarios) => {
        if (!active) {
          return;
        }

        setScenariosData({
          error: null,
          isLoading: false,
          items: nextScenarios,
        });
      })
      .catch(() => {
        if (!active) {
          return;
        }

        setScenariosData({
          error: "场景加载失败",
          isLoading: false,
          items: [],
        });
      });

    return () => {
      active = false;
    };
  }, []);

  const scenarios = scenariosData.items;
  const scenarioId = useMemo(() => {
    if (scenarios.length === 0) {
      return selectedScenarioId;
    }

    return scenarios.some((item) => item.id === selectedScenarioId) ? selectedScenarioId : scenarios[0].id;
  }, [scenarios, selectedScenarioId]);

  const session = useMockSession({ scenarioId, language });
  const {
    currentInsight,
    elapsedSeconds,
    error,
    insights,
    isLoading,
    isRunning,
    partialTranscript,
    pause,
    registerVideoFrameProvider,
    reset,
    sessionId,
    start,
    statusText,
    transcript,
  } = session;

  const closeHistory = () => setHistoryOpen(false);
  const controlsDisabled = isLoading || !!error;
  const statusMessage = useMemo(
    () => scenariosData.error ?? error ?? sessionError ?? statusText ?? (scenariosData.isLoading ? "场景加载中..." : null),
    [error, scenariosData.error, scenariosData.isLoading, sessionError, statusText],
  );

  const finishSession = async () => {
    try {
      await saveResult({ scenarioId, language });
      router.push("/report");
    } catch {
      return;
    }
  };

  return (
    <main className="h-screen overflow-hidden bg-slate-100 p-4 text-slate-950 md:p-5">
      {historyOpen ? (
        <div className="fixed inset-0 z-30 bg-slate-950/18 backdrop-blur-[2px]">
          <div className="absolute inset-y-0 left-0 w-full max-w-[380px] p-4">
            <div className="flex h-full flex-col gap-3">
              <div className="flex items-center justify-between rounded-[24px] bg-white/92 px-4 py-3 shadow-[0_18px_45px_rgba(15,23,42,0.08)] backdrop-blur">
                <div>
                  <p className="text-sm font-semibold text-slate-900">历史演讲</p>
                  <p className="text-xs text-slate-500">这里可以回看历史记录与历史趋势</p>
                </div>
                <button
                  type="button"
                  onClick={closeHistory}
                  className="rounded-full bg-slate-100 px-3 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-200"
                >
                  关闭
                </button>
              </div>
              <div className="min-h-0 flex-1">
                <HistorySidebar activeScenario={scenarioId} history={history} scenarios={scenarios} />
              </div>
            </div>
          </div>
          <button
            type="button"
            aria-label="关闭历史面板"
            className="absolute inset-0 -z-10"
            onClick={closeHistory}
          />
        </div>
      ) : null}

      <div className="mx-auto grid h-full max-w-[1720px] gap-4 xl:grid-cols-[minmax(0,1.75fr)_420px]">
        <section className="flex min-h-0 flex-col gap-3">
          <SessionToolbar
            language={language}
            onHistoryToggle={() => setHistoryOpen((value) => !value)}
            onLanguageChange={setLanguage}
            onScenarioChange={setSelectedScenarioId}
            onScenarioToggle={() => setScenarioOpen((value) => !value)}
            scenario={scenarioId}
            scenarioOpen={scenarioOpen}
            scenarios={scenarios}
          />
          <div className="min-h-0 flex-1">
            <CameraPanel
              elapsedSeconds={elapsedSeconds}
              isRunning={isRunning && !controlsDisabled}
              onFrameCaptureReady={registerVideoFrameProvider}
            >
              <div className="space-y-2">
                {statusMessage ? (
                  <div className="rounded-2xl bg-black/50 px-4 py-2 text-sm font-medium text-white backdrop-blur">
                    {statusMessage}
                  </div>
                ) : null}
                {sessionId ? (
                  <div className="rounded-2xl bg-black/40 px-4 py-2 text-xs font-medium text-slate-200 backdrop-blur">
                    Session ID: {sessionId}
                  </div>
                ) : null}
                <SessionControls
                  disabled={controlsDisabled}
                  isRunning={isRunning}
                  onFinish={finishSession}
                  onPause={pause}
                  onReset={reset}
                  onStart={start}
                />
              </div>
            </CameraPanel>
          </div>
        </section>

        <aside className="flex min-h-0 flex-col gap-3 pt-[52px]">
          <div className="min-h-0 flex-[1.05]">
            <TranscriptPanel partialTranscript={partialTranscript} transcript={transcript} />
          </div>
          <div className="min-h-0 flex-1">
            <LiveAnalysisPanel currentInsight={currentInsight} insights={insights} />
          </div>
        </aside>
      </div>
    </main>
  );
}
