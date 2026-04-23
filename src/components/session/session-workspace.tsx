"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent } from "react";

import { HistorySidebar } from "@/components/session/history-sidebar";
import { LiveAnalysisPanel } from "@/components/session/live-analysis-panel";
import { QAControlBar } from "@/components/session/qa-control-bar";
import { SessionStage } from "@/components/session/session-stage";
import { SessionToolbar } from "@/components/session/session-toolbar";
import { SessionControls } from "@/components/session/session-controls";
import { useSessionResult } from "@/components/session/session-provider";
import { primeAudioPlayback } from "@/lib/audio-playback";
import { TranscriptPanel } from "@/components/session/transcript-panel";
import { useMockSession } from "@/hooks/useMockSession";
import { extractDocumentText, getQAVoiceProfiles, getScenarios, uploadSessionReplayMedia } from "@/lib/api";
import type {
  LanguageOption,
  ScenarioOption,
  ScenarioType,
  TrainingDocumentAsset,
  TrainingMode,
  VoiceProfile,
} from "@/types/session";

interface SessionWorkspaceProps {
  defaultLanguage?: LanguageOption;
  defaultScenario?: ScenarioType;
}

const fallbackVoiceProfiles: VoiceProfile[] = [
  {
    id: "female_professional_01",
    label: "女声 · 专业",
    gender: "female",
    style: "professional",
  },
  {
    id: "male_professional_01",
    label: "男声 · 专业",
    gender: "male",
    style: "professional",
  },
];

function getReplayCaptureMimeType() {
  if (typeof window === "undefined" || typeof MediaRecorder === "undefined") {
    return "";
  }

  const candidates = [
    "video/webm;codecs=vp9",
    "video/webm;codecs=vp8",
    "video/webm",
    "video/mp4",
  ];

  return candidates.find((candidate) => MediaRecorder.isTypeSupported(candidate)) ?? "";
}

function buildReplayFilename(mimeType: string) {
  if (mimeType.includes("mp4")) {
    return "replay-video.mp4";
  }
  return "replay-video.webm";
}

export function SessionWorkspace({
  defaultLanguage = "zh",
  defaultScenario = "host",
}: SessionWorkspaceProps) {
  const router = useRouter();
  const { error: sessionError, history, saveResult } = useSessionResult();
  const [documentAsset, setDocumentAsset] = useState<TrainingDocumentAsset | null>(null);
  const [documentError, setDocumentError] = useState<string | null>(null);
  const [documentLoading, setDocumentLoading] = useState(false);
  const [language, setLanguage] = useState<LanguageOption>(defaultLanguage);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [scenarioOpen, setScenarioOpen] = useState(false);
  const [trainingMode, setTrainingMode] = useState<TrainingMode>("free_speech");
  const [qaEnabled, setQAEnabled] = useState(false);
  const [voiceProfiles, setVoiceProfiles] = useState<VoiceProfile[]>(fallbackVoiceProfiles);
  const [selectedVoiceProfileId, setSelectedVoiceProfileId] = useState<string>(fallbackVoiceProfiles[0]?.id ?? "female_professional_01");
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
  const replayCameraStreamRef = useRef<MediaStream | null>(null);
  const replayRecorderRef = useRef<MediaRecorder | null>(null);
  const replayStopTaskRef = useRef<Promise<void> | null>(null);
  const replayChunksRef = useRef<Blob[]>([]);
  const replaySessionIdRef = useRef<string | null>(null);
  const replayStartAtMsRef = useRef(0);
  const replayMimeTypeRef = useRef("");

  useEffect(() => {
    router.prefetch("/report");
  }, [router]);

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
      .catch((loadError) => {
        if (!active) {
          return;
        }

        setScenariosData({
          error: loadError instanceof Error ? `场景加载失败：${loadError.message}` : "场景加载失败",
          isLoading: false,
          items: [],
        });
      });

    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    let active = true;

    void getQAVoiceProfiles()
      .then((profiles) => {
        if (!active || profiles.length === 0) {
          return;
        }

        setVoiceProfiles(profiles);
        setSelectedVoiceProfileId((current) =>
          profiles.some((profile) => profile.id === current) ? current : profiles[0]?.id ?? current,
        );
      })
      .catch(() => {
        if (!active) {
          return;
        }
        setVoiceProfiles(fallbackVoiceProfiles);
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

  const session = useMockSession({
    scenarioId,
    language,
    trainingMode,
    documentName: documentAsset?.name ?? null,
    documentText: documentAsset?.extractedText ?? documentAsset?.markdownSource ?? null,
    manualText: null,
  });
  const {
    audioCaptureStream,
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
    qaAudioUrl,
    qaFeedback,
    qaQuestion,
    qaState,
    qaAudioAutoPlay,
    interviewerSpeaking,
    notifyQAAudioPlaybackEnded,
    notifyQAAudioPlaybackStarted,
    selectVoiceProfile,
    setInterviewerSpeaking,
    startQA,
    stopQA,
    updateQAPrewarmContext,
  } = session;

  const stopReplayCapture = useCallback(async (options?: {
    sessionId?: string | null;
    upload?: boolean;
  }) => {
    if (replayStopTaskRef.current) {
      return replayStopTaskRef.current;
    }

    const recorder = replayRecorderRef.current;
    replayRecorderRef.current = null;

    if (!recorder) {
      replayChunksRef.current = [];
      return;
    }

    const task = (async () => {
      const activeSessionId = options?.sessionId ?? replaySessionIdRef.current;
      const shouldUpload = options?.upload === true && !!activeSessionId;

      await new Promise<void>((resolve) => {
        recorder.onstop = () => {
          resolve();
        };
        if (recorder.state === "inactive") {
          resolve();
          return;
        }
        recorder.stop();
      });

      const chunks = replayChunksRef.current;
      const mimeType = replayMimeTypeRef.current || recorder.mimeType || "video/webm";
      const durationMs = Math.max(0, Date.now() - replayStartAtMsRef.current);

      replayChunksRef.current = [];
      replaySessionIdRef.current = null;
      replayMimeTypeRef.current = "";
      replayStartAtMsRef.current = 0;

      if (!shouldUpload || !activeSessionId || chunks.length === 0) {
        return;
      }

      const blob = new Blob(chunks, { type: mimeType });
      if (blob.size === 0) {
        return;
      }

      const file = new File([blob], buildReplayFilename(mimeType), { type: mimeType });
      await uploadSessionReplayMedia(activeSessionId, file, durationMs).catch(() => undefined);
    })();

    replayStopTaskRef.current = task;
    await task.finally(() => {
      replayStopTaskRef.current = null;
    });
  }, []);

  const startReplayCapture = useCallback((activeSessionId: string) => {
    if (replayRecorderRef.current || replayStopTaskRef.current || !replayCameraStreamRef.current) {
      return;
    }
    if (typeof window === "undefined" || typeof MediaRecorder === "undefined") {
      return;
    }

    const cameraStream = replayCameraStreamRef.current;
    if (!cameraStream || cameraStream.getVideoTracks().length === 0 || !audioCaptureStream) {
      return;
    }
    const audioTracks = audioCaptureStream.getAudioTracks();
    if (audioTracks.length === 0) {
      return;
    }

    const recordingStream = new MediaStream([
      ...cameraStream.getVideoTracks(),
      ...audioTracks,
    ]);

    const mimeType = getReplayCaptureMimeType();
    const recorder = mimeType
      ? new MediaRecorder(recordingStream, { mimeType })
      : new MediaRecorder(recordingStream);

    replayChunksRef.current = [];
    replaySessionIdRef.current = activeSessionId;
    replayMimeTypeRef.current = recorder.mimeType || mimeType;
    replayStartAtMsRef.current = Date.now();

    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) {
        replayChunksRef.current.push(event.data);
      }
    };
    recorder.start(1000);
    replayRecorderRef.current = recorder;
  }, [audioCaptureStream]);

  const handleCameraStreamReady = useCallback((stream: MediaStream | null) => {
    replayCameraStreamRef.current = stream;
    if (stream && isRunning && sessionId && audioCaptureStream) {
      startReplayCapture(sessionId);
    }
  }, [audioCaptureStream, isRunning, sessionId, startReplayCapture]);

  const closeHistory = () => setHistoryOpen(false);
  const controlsDisabled = isLoading;
  const statusMessage = useMemo(
    () =>
      (documentLoading ? "正在抽取文档正文..." : null) ??
      documentError ??
      scenariosData.error ??
      error ??
      sessionError ??
      statusText ??
      (scenariosData.isLoading ? "场景加载中..." : null),
    [documentError, documentLoading, error, scenariosData.error, scenariosData.isLoading, sessionError, statusText],
  );

  useEffect(() => {
    return () => {
      if (currentDocumentUrlRef.current) {
        URL.revokeObjectURL(currentDocumentUrlRef.current);
      }
    };
  }, []);

  useEffect(() => {
    if (isRunning && sessionId && audioCaptureStream) {
      startReplayCapture(sessionId);
    }
  }, [audioCaptureStream, isRunning, sessionId, startReplayCapture]);

  useEffect(() => () => {
    void stopReplayCapture({ upload: false });
  }, [stopReplayCapture]);

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
    setDocumentLoading(false);
    if (documentInputRef.current) {
      documentInputRef.current.value = "";
    }
  };

  const handleTrainingModeChange = (nextMode: TrainingMode) => {
    setTrainingMode(nextMode);
    setDocumentError(null);
  };

  const handleQAToggle = () => {
    if (qaEnabled) {
      setQAEnabled(false);
      if (qaState.enabled) {
        stopQA();
      }
      return;
    }

    setQAEnabled(true);
  };

  const handleVoiceProfileChange = (voiceProfileId: string) => {
    setSelectedVoiceProfileId(voiceProfileId);
    if (sessionId) {
      selectVoiceProfile(voiceProfileId);
    }
  };

  useEffect(() => {
    if (!sessionId || !isRunning || qaState.enabled) {
      return;
    }

    updateQAPrewarmContext({
      trainingMode,
      documentName: documentAsset?.name ?? null,
      documentText: documentAsset?.extractedText ?? documentAsset?.markdownSource ?? null,
      manualText: null,
    });
  }, [
    documentAsset?.extractedText,
    documentAsset?.markdownSource,
    documentAsset?.name,
    isRunning,
    qaState.enabled,
    sessionId,
    trainingMode,
    updateQAPrewarmContext,
  ]);

  const handleDocumentSelection = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0] ?? null;

    if (!file) {
      return;
    }

    const lowerName = file.name.toLowerCase();
    const isPdf = lowerName.endsWith(".pdf") || file.type === "application/pdf";
    const isPowerPoint =
      lowerName.endsWith(".ppt") ||
      lowerName.endsWith(".pptx") ||
      file.type === "application/vnd.ms-powerpoint" ||
      file.type === "application/vnd.openxmlformats-officedocument.presentationml.presentation";
    const isMarkdown =
      lowerName.endsWith(".md") || lowerName.endsWith(".markdown") || file.type === "text/markdown" || file.type === "text/plain";

    if (isPowerPoint) {
      clearDocumentAsset();
      setDocumentError("PPT / PPTX 文档上传已下线，当前只支持 PDF 和 Markdown。");
      return;
    }

    if (!isPdf && !isMarkdown) {
      clearDocumentAsset();
      setDocumentError("当前只支持 PDF 或 Markdown 文档。");
      return;
    }

    if (currentDocumentUrlRef.current) {
      URL.revokeObjectURL(currentDocumentUrlRef.current);
      currentDocumentUrlRef.current = null;
    }

    setDocumentLoading(true);
    setDocumentError(null);

    try {
      const extraction = await extractDocumentText(file);
      const textSource = extraction.text;

      if (isPdf) {
        const objectUrl = URL.createObjectURL(file);
        currentDocumentUrlRef.current = objectUrl;
        setDocumentAsset({
          kind: "pdf",
          name: file.name,
          objectUrl,
          markdownSource: null,
          extractedText: textSource,
          extractedCharCount: extraction.charCount,
          preview: extraction.preview,
        });
        return;
      }

      setDocumentAsset({
        kind: "md",
        name: file.name,
        objectUrl: null,
        markdownSource: textSource,
        extractedText: textSource,
        extractedCharCount: extraction.charCount,
        preview: extraction.preview,
      });
    } catch (extractionError) {
      if (isPdf) {
        const objectUrl = URL.createObjectURL(file);
        currentDocumentUrlRef.current = objectUrl;
        setDocumentAsset({
          kind: "pdf",
          name: file.name,
          objectUrl,
          markdownSource: null,
          extractedText: null,
          extractedCharCount: 0,
          preview: {
            kind: "pdf",
            status: "ready",
            message: null,
          },
        });
      } else {
        setDocumentAsset(null);
      }
      setDocumentError(extractionError instanceof Error ? extractionError.message : "文档正文抽取失败");
    } finally {
      setDocumentLoading(false);
    }
  };

  const finishSession = () => {
    const finishedSessionId = sessionId;
    const { active, committed } = flushTranscript();
    const nextTranscript = active ? [...committed, active] : committed;
    const uploadPromise = stopReplayCapture({
      sessionId: finishedSessionId,
      upload: !!finishedSessionId,
    });

    primeAudioPlayback();
    void saveResult({ scenarioId, language }, nextTranscript, finishedSessionId).catch(() => undefined);
    router.push("/report");

    window.setTimeout(() => {
      void uploadPromise.catch(() => undefined);
      void finish().catch(() => undefined);
    }, 0);
  };

  const pauseSession = () => {
    void stopReplayCapture({ upload: false }).catch(() => undefined);
    void pause().catch(() => undefined);
  };

  const resetSession = () => {
    void stopReplayCapture({ upload: false }).catch(() => undefined);
    void reset().catch(() => undefined);
  };

  const activeVoiceProfileId = qaState.voiceProfileId ?? selectedVoiceProfileId;
  const activeVoiceProfile = voiceProfiles.find((profile) => profile.id === activeVoiceProfileId) ?? voiceProfiles[0] ?? null;
  const avatarSrc = activeVoiceProfile?.gender === "male"
    ? "/avatars/interviewer-male.svg"
    : "/avatars/interviewer-female.svg";
  const displayedQuestion = qaQuestion ?? (qaState.currentQuestion
    ? {
        turnId: qaState.currentTurnId ?? "qa-current",
        questionText: qaState.currentQuestion,
        goal: qaState.currentQuestionGoal ?? "",
        followUp: false,
        expectedPoints: [],
      }
    : qaState.phase === "preparing_context"
      ? {
          turnId: qaState.currentTurnId ?? "qa-preparing",
          questionText: "AI 正在基于你刚才的演讲内容生成问题，Transcript 和 Live Coach 会继续更新。",
          goal: "整理上下文并生成当前最合适的问题。",
          followUp: false,
          expectedPoints: [],
        }
      : null);
  const displayedFeedback = qaFeedback ?? (qaState.latestFeedback
    ? {
        turnId: qaState.currentTurnId ?? "qa-current",
        feedbackText: qaState.latestFeedback,
        strengths: [],
        missedPoints: [],
        nextAction: "next_question" as const,
      }
    : null);

  const launchQA = () => {
    startQA({
      trainingMode,
      voiceProfileId: activeVoiceProfileId,
      documentName: documentAsset?.name ?? null,
      documentText: documentAsset?.extractedText ?? documentAsset?.markdownSource ?? null,
      manualText: null,
    });
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
            onQAToggle={handleQAToggle}
            onScenarioChange={setSelectedScenarioId}
            onScenarioToggle={() => setScenarioOpen((value) => !value)}
            onTrainingModeChange={handleTrainingModeChange}
            onVoiceProfileChange={handleVoiceProfileChange}
            qaEnabled={qaEnabled}
            scenario={scenarioId}
            scenarioOpen={scenarioOpen}
            selectedVoiceProfileId={activeVoiceProfileId}
            scenarios={scenarios}
            trainingMode={trainingMode}
            voiceProfiles={voiceProfiles}
          />
          <div className="min-h-0 flex-1">
            <SessionStage
              avatarSrc={avatarSrc}
              controls={
                <SessionControls
                  disabled={controlsDisabled}
                  isRunning={isRunning}
                  onFinish={finishSession}
                  onPause={pauseSession}
                  onReset={resetSession}
                  onStart={start}
                />
              }
              documentAsset={documentAsset}
              elapsedSeconds={elapsedSeconds}
              feedback={displayedFeedback}
              goal={qaState.currentQuestionGoal}
              isRunning={isRunning && !controlsDisabled}
              phase={qaState.phase}
              qaAudioUrl={qaAudioUrl}
              qaAudioAutoPlay={qaAudioAutoPlay}
              qaEnabled={qaEnabled}
              question={displayedQuestion}
              registerVideoFrameProvider={registerVideoFrameProvider}
              onCameraStreamReady={handleCameraStreamReady}
              sessionId={sessionId}
              speaking={interviewerSpeaking}
              statusMessage={statusMessage}
              trainingMode={trainingMode}
              voiceLabel={activeVoiceProfile?.label ?? null}
              onQAAudioPlaybackEnded={notifyQAAudioPlaybackEnded}
              onQAAudioPlaybackStarted={notifyQAAudioPlaybackStarted}
              onDocumentPick={openDocumentPicker}
              onInterviewerSpeakingChange={setInterviewerSpeaking}
            />
          </div>
          {qaEnabled ? (
            <div className="flex flex-wrap items-start justify-between gap-3">
              <QAControlBar
                disabled={controlsDisabled}
                isRunning={isRunning}
                phase={qaState.phase}
                qaEnabled={qaEnabled}
                onStartQA={launchQA}
                onStopQA={() => {
                  setQAEnabled(false);
                  stopQA();
                }}
              />
              <SessionControls
                disabled={controlsDisabled}
                isRunning={isRunning}
                onFinish={finishSession}
                onPause={pauseSession}
                onReset={resetSession}
                onStart={start}
              />
            </div>
          ) : null}
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
