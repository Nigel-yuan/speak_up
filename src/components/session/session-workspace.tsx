"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState, type ChangeEvent } from "react";

import { CameraPanel } from "@/components/session/camera-panel";
import { DocumentStage } from "@/components/session/document-stage";
import { HistorySidebar } from "@/components/session/history-sidebar";
import { LiveAnalysisPanel } from "@/components/session/live-analysis-panel";
import { SessionToolbar } from "@/components/session/session-toolbar";
import { SessionControls } from "@/components/session/session-controls";
import { useSessionResult } from "@/components/session/session-provider";
import { TranscriptPanel } from "@/components/session/transcript-panel";
import { useMockSession } from "@/hooks/useMockSession";
import { getScenarios } from "@/lib/api";
import type {
  LanguageOption,
  ScenarioOption,
  ScenarioType,
  TrainingDocumentAsset,
  TrainingMode,
} from "@/types/session";

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
  const [documentAsset, setDocumentAsset] = useState<TrainingDocumentAsset | null>(null);
  const [documentError, setDocumentError] = useState<string | null>(null);
  const [language, setLanguage] = useState<LanguageOption>(defaultLanguage);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [scenarioOpen, setScenarioOpen] = useState(false);
  const [trainingMode, setTrainingMode] = useState<TrainingMode>("free_speech");
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
  const documentInputRef = useRef<HTMLInputElement | null>(null);
  const currentDocumentUrlRef = useRef<string | null>(null);

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
    activeTranscript,
    coachPanel,
    elapsedSeconds,
    error,
    finish,
    flushTranscript,
    isLoading,
    isRunning,
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
    () =>
      documentError ??
      scenariosData.error ??
      error ??
      sessionError ??
      statusText ??
      (scenariosData.isLoading ? "场景加载中..." : null),
    [documentError, error, scenariosData.error, scenariosData.isLoading, sessionError, statusText],
  );

  useEffect(() => {
    return () => {
      if (currentDocumentUrlRef.current) {
        URL.revokeObjectURL(currentDocumentUrlRef.current);
      }
    };
  }, []);

  const openDocumentPicker = () => {
    documentInputRef.current?.click();
  };

  const clearDocumentAsset = () => {
    if (currentDocumentUrlRef.current) {
      URL.revokeObjectURL(currentDocumentUrlRef.current);
      currentDocumentUrlRef.current = null;
    }
    setDocumentAsset(null);
    setDocumentError(null);
    if (documentInputRef.current) {
      documentInputRef.current.value = "";
    }
  };

  const handleTrainingModeChange = (nextMode: TrainingMode) => {
    setTrainingMode(nextMode);
    setDocumentError(null);
  };

  const handleDocumentSelection = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0] ?? null;

    if (!file) {
      return;
    }

    const lowerName = file.name.toLowerCase();
    const isPdf = lowerName.endsWith(".pdf") || file.type === "application/pdf";
    const isMarkdown =
      lowerName.endsWith(".md") || lowerName.endsWith(".markdown") || file.type === "text/markdown" || file.type === "text/plain";

    if (!isPdf && !isMarkdown) {
      clearDocumentAsset();
      setDocumentError("当前只支持 PDF 或 Markdown 文档。");
      return;
    }

    if (currentDocumentUrlRef.current) {
      URL.revokeObjectURL(currentDocumentUrlRef.current);
      currentDocumentUrlRef.current = null;
    }

    if (isPdf) {
      const objectUrl = URL.createObjectURL(file);
      currentDocumentUrlRef.current = objectUrl;
      setDocumentAsset({
        kind: "pdf",
        name: file.name,
        objectUrl,
        markdownSource: null,
      });
      setDocumentError(null);
      return;
    }

    const markdownSource = await file.text();
    setDocumentAsset({
      kind: "md",
      name: file.name,
      objectUrl: null,
      markdownSource,
    });
    setDocumentError(null);
  };

  const finishSession = async () => {
    try {
      const finishedSessionId = sessionId;
      const { active, committed } = flushTranscript();
      await finish();
      await saveResult({ scenarioId, language }, active ? [...committed, active] : committed, finishedSessionId);
      router.push("/report");
    } catch {
      return;
    }
  };

  return (
    <main className="h-screen overflow-hidden bg-slate-100 p-4 text-slate-950 md:p-5">
      <input
        ref={documentInputRef}
        type="file"
        accept=".pdf,.md,.markdown,application/pdf,text/markdown,text/plain"
        className="hidden"
        onChange={(event) => {
          void handleDocumentSelection(event);
        }}
      />
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
            documentAsset={documentAsset}
            language={language}
            onDocumentClear={clearDocumentAsset}
            onDocumentPick={openDocumentPicker}
            onHistoryToggle={() => setHistoryOpen((value) => !value)}
            onLanguageChange={setLanguage}
            onScenarioChange={setSelectedScenarioId}
            onScenarioToggle={() => setScenarioOpen((value) => !value)}
            onTrainingModeChange={handleTrainingModeChange}
            scenario={scenarioId}
            scenarioOpen={scenarioOpen}
            scenarios={scenarios}
            trainingMode={trainingMode}
          />
          <div className="min-h-0 flex-1">
            {trainingMode === "document_speech" ? (
              <DocumentStage
                documentAsset={documentAsset}
                elapsedSeconds={elapsedSeconds}
                isRunning={isRunning && !controlsDisabled}
                onDocumentPick={openDocumentPicker}
                onFrameCaptureReady={registerVideoFrameProvider}
                sessionId={sessionId}
                statusMessage={statusMessage}
              >
                <SessionControls
                  disabled={controlsDisabled}
                  isRunning={isRunning}
                  onFinish={finishSession}
                  onPause={pause}
                  onReset={reset}
                  onStart={start}
                />
              </DocumentStage>
            ) : (
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
            )}
          </div>
        </section>

        <aside className="flex min-h-0 flex-col gap-3 pt-[52px]">
          <div className="min-h-0 flex-[0.7]">
            <TranscriptPanel activeTranscript={activeTranscript} transcript={transcript} />
          </div>
          <div className="min-h-0 flex-[1.3]">
            <LiveAnalysisPanel
              coachPanel={coachPanel}
              language={language}
            />
          </div>
        </aside>
      </div>
    </main>
  );
}
