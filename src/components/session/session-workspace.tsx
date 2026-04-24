"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent } from "react";

import { getCoachProfileById, getCoachProfiles, isCoachProfileId } from "@/lib/coach-profiles";
import { CoachEntryDialog } from "@/components/session/coach-entry-dialog";
import { CoachSidebarHeader } from "@/components/session/coach-sidebar-header";
import { LiveAnalysisPanel } from "@/components/session/live-analysis-panel";
import { QAControlBar } from "@/components/session/qa-control-bar";
import { SessionStage } from "@/components/session/session-stage";
import { SessionToolbar } from "@/components/session/session-toolbar";
import { SessionControls } from "@/components/session/session-controls";
import { useSessionResult } from "@/components/session/session-provider";
import { primeAudioPlayback } from "@/lib/audio-playback";
import { TranscriptPanel } from "@/components/session/transcript-panel";
import { useMockSession } from "@/hooks/useMockSession";
import { extractDocumentText, uploadSessionReplayMedia } from "@/lib/api";
import type {
  CoachProfileId,
  ScenarioType,
  TrainingDocumentAsset,
  TrainingMode,
} from "@/types/session";

interface SessionWorkspaceProps {
  defaultScenario?: ScenarioType;
}

function readScenarioFromLocation(defaultScenario: ScenarioType) {
  if (typeof window === "undefined") {
    return defaultScenario;
  }
  const searchParams = new URLSearchParams(window.location.search);
  const scenario = searchParams.get("scenario");
  return scenario === "general" || scenario === "host" || scenario === "guest-sharing" || scenario === "standup"
    ? scenario
    : defaultScenario;
}

function readCoachProfileIdFromLocation() {
  if (typeof window === "undefined") {
    return null;
  }
  const searchParams = new URLSearchParams(window.location.search);
  const coachProfileId = searchParams.get("coach");
  return isCoachProfileId(coachProfileId) ? coachProfileId : null;
}

function getReplayCaptureMimeType() {
  if (typeof window === "undefined" || typeof MediaRecorder === "undefined") {
    return "";
  }

  const candidates = [
    "video/webm;codecs=vp8,opus",
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
  defaultScenario = "general",
}: SessionWorkspaceProps) {
  const router = useRouter();
  const { cacheReplayMedia, error: sessionError, saveResult } = useSessionResult();
  const coachProfiles = useMemo(() => getCoachProfiles(), []);
  const [documentAsset, setDocumentAsset] = useState<TrainingDocumentAsset | null>(null);
  const [documentError, setDocumentError] = useState<string | null>(null);
  const [documentLoading, setDocumentLoading] = useState(false);
  const language = "zh";
  const [trainingMode, setTrainingMode] = useState<TrainingMode>("free_speech");
  const [qaEnabled, setQAEnabled] = useState(false);
  const [cameraPermissionState, setCameraPermissionState] = useState<"idle" | "granted" | "denied">("idle");
  const [cameraStream, setCameraStream] = useState<MediaStream | null>(null);
  const [coachSelectionOpen, setCoachSelectionOpen] = useState(false);
  const [routeParamsReady, setRouteParamsReady] = useState(false);
  const [selectedCoachProfileId, setSelectedCoachProfileId] = useState<CoachProfileId>(coachProfiles[0]?.id ?? "");
  const [scenarioId, setScenarioId] = useState<ScenarioType>(defaultScenario);
  const documentInputRef = useRef<HTMLInputElement | null>(null);
  const currentDocumentUrlRef = useRef<string | null>(null);
  const replayCameraStreamRef = useRef<MediaStream | null>(null);
  const replayRecorderRef = useRef<MediaRecorder | null>(null);
  const replayStopTaskRef = useRef<Promise<void> | null>(null);
  const replayUploadTaskRef = useRef<Promise<void> | null>(null);
  const replayChunksRef = useRef<Blob[]>([]);
  const replaySessionIdRef = useRef<string | null>(null);
  const replayStartAtMsRef = useRef(0);
  const replayMimeTypeRef = useRef("");

  useEffect(() => {
    router.prefetch("/report");
  }, [router]);

  useEffect(() => {
    let active = true;
    let ownedStream: MediaStream | null = null;

    async function enableCamera() {
      if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia) {
        setCameraPermissionState("denied");
        return;
      }

      try {
        const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
        ownedStream = stream;
        if (!active) {
          stream.getTracks().forEach((track) => track.stop());
          return;
        }
        replayCameraStreamRef.current = stream;
        setCameraStream(stream);
        setCameraPermissionState("granted");
      } catch {
        if (!active) {
          return;
        }
        replayCameraStreamRef.current = null;
        setCameraStream(null);
        setCameraPermissionState("denied");
      }
    }

    void enableCamera();

    return () => {
      active = false;
      replayCameraStreamRef.current = null;
      ownedStream?.getTracks().forEach((track) => track.stop());
    };
  }, []);

  useEffect(() => {
    const routeCoachProfileId = readCoachProfileIdFromLocation();
    setScenarioId(readScenarioFromLocation(defaultScenario));
    if (routeCoachProfileId) {
      setSelectedCoachProfileId(routeCoachProfileId);
      setCoachSelectionOpen(false);
    } else {
      setCoachSelectionOpen(true);
    }
    setRouteParamsReady(true);
  }, [defaultScenario]);

  useEffect(() => {
    if (typeof window === "undefined" || !routeParamsReady || !selectedCoachProfileId || coachSelectionOpen) {
      return;
    }

    const url = new URL(window.location.href);
    url.searchParams.set("coach", selectedCoachProfileId);
    url.searchParams.set("scenario", scenarioId);
    url.searchParams.delete("language");
    window.history.replaceState(window.history.state, "", `${url.pathname}?${url.searchParams.toString()}`);
  }, [coachSelectionOpen, routeParamsReady, scenarioId, selectedCoachProfileId]);

  const session = useMockSession({
    scenarioId,
    language,
    coachProfileId: selectedCoachProfileId,
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
    registerVideoFrameProvider,
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
    silenceInterviewer,
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

      if (!activeSessionId || chunks.length === 0) {
        return;
      }

      const blob = new Blob(chunks, { type: mimeType });
      if (blob.size === 0) {
        return;
      }

      cacheReplayMedia(
        activeSessionId,
        blob,
        mimeType.startsWith("audio/") ? "audio" : "video",
        durationMs,
      );

      if (!shouldUpload) {
        return;
      }

      const file = new File([blob], buildReplayFilename(mimeType), { type: mimeType });
      const uploadTask = uploadSessionReplayMedia(activeSessionId, file, durationMs)
        .then(() => undefined)
        .catch(() => undefined)
        .finally(() => {
          if (replayUploadTaskRef.current === uploadTask) {
            replayUploadTaskRef.current = null;
          }
        });
      replayUploadTaskRef.current = uploadTask;
    })();

    replayStopTaskRef.current = task;
    await task.finally(() => {
      replayStopTaskRef.current = null;
    });
  }, [cacheReplayMedia]);

  const startReplayCapture = useCallback((activeSessionId: string) => {
    if (replayRecorderRef.current || replayStopTaskRef.current || !replayCameraStreamRef.current) {
      return;
    }
    if (typeof window === "undefined" || typeof MediaRecorder === "undefined") {
      return;
    }

    const cameraStream = replayCameraStreamRef.current;
    if (!cameraStream || cameraStream.getVideoTracks().length === 0) {
      return;
    }
    const audioTracks = audioCaptureStream?.getAudioTracks() ?? [];
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
    recorder.start();
    replayRecorderRef.current = recorder;
  }, [audioCaptureStream]);

  const controlsDisabled = isLoading;
  const statusMessage = useMemo(
    () =>
      (documentLoading ? "正在抽取文档正文..." : null) ??
      documentError ??
      error ??
      sessionError ??
      statusText,
    [documentError, documentLoading, error, sessionError, statusText],
  );

  useEffect(() => {
    return () => {
      if (currentDocumentUrlRef.current) {
        URL.revokeObjectURL(currentDocumentUrlRef.current);
      }
    };
  }, []);

  useEffect(() => {
    if (cameraStream && isRunning && sessionId) {
      startReplayCapture(sessionId);
    }
  }, [audioCaptureStream, cameraStream, isRunning, sessionId, startReplayCapture]);

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

  const handleCoachProfileChange = (coachProfileId: string) => {
    if (qaEnabled) {
      return;
    }
    setSelectedCoachProfileId(coachProfileId);
    if (sessionId) {
      selectVoiceProfile(coachProfileId);
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
    const finishingCoachProfileId = selectedCoachProfileId;
    const { active, committed } = flushTranscript();
    const nextTranscript = active ? [...committed, active] : committed;
    const replayCapturePromise = stopReplayCapture({
      sessionId: finishedSessionId,
      upload: !!finishedSessionId,
    });
    const reportHref = `/report?sessionId=${finishedSessionId ?? ""}&scenario=${scenarioId}&coach=${finishingCoachProfileId}`;

    silenceInterviewer();
    if (qaState.enabled) {
      stopQA();
      setQAEnabled(false);
    }
    primeAudioPlayback();
    void saveResult(
      { scenarioId, language, coachProfileId: finishingCoachProfileId },
      nextTranscript,
      finishedSessionId,
    ).catch(() => undefined);

    void replayCapturePromise
      .catch(() => undefined)
      .finally(() => {
        router.push(reportHref);
      });

    window.setTimeout(() => {
      void finish().catch(() => undefined);
    }, 0);
  };

  const activeCoachProfileId = qaState.enabled
    ? (qaState.voiceProfileId ?? selectedCoachProfileId)
    : selectedCoachProfileId;
  const activeCoachProfile = getCoachProfileById(activeCoachProfileId) ?? coachProfiles[0] ?? null;
  const avatarSrc = activeCoachProfile?.avatarSrc ?? "/avatars/interviewer-female.svg";
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
      voiceProfileId: selectedCoachProfileId,
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
      <div className="mx-auto grid h-full max-w-[1720px] gap-4 xl:grid-cols-[minmax(0,1.75fr)_420px]">
        <section className="flex min-h-0 flex-col gap-3">
          <SessionToolbar
            documentAsset={documentAsset}
            elapsedSeconds={elapsedSeconds}
            isRunning={isRunning && !controlsDisabled}
            onDocumentClear={clearDocumentAsset}
            onDocumentPick={openDocumentPicker}
            onQAToggle={handleQAToggle}
            onTrainingModeChange={handleTrainingModeChange}
            primaryControls={
              <SessionControls
                disabled={controlsDisabled}
                isRunning={isRunning}
                onFinish={finishSession}
                onStart={start}
              />
            }
            qaControls={
              qaEnabled ? (
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
              ) : null
            }
            qaEnabled={qaEnabled}
            trainingMode={trainingMode}
          />
          <div className="min-h-0 flex-1">
            <SessionStage
              avatarSrc={avatarSrc}
              cameraPermissionState={cameraPermissionState}
              cameraStream={cameraStream}
              controls={null}
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
              speaking={interviewerSpeaking}
              statusMessage={statusMessage}
              trainingMode={trainingMode}
              onQAAudioPlaybackEnded={notifyQAAudioPlaybackEnded}
              onQAAudioPlaybackStarted={notifyQAAudioPlaybackStarted}
              onDocumentPick={openDocumentPicker}
              onInterviewerSpeakingChange={setInterviewerSpeaking}
            />
          </div>
        </section>

        <aside className="flex min-h-0 flex-col gap-3">
          <div className="flex-none">
            <CoachSidebarHeader
              coachLocked={qaEnabled}
              coachProfile={activeCoachProfile}
              coachProfiles={coachProfiles}
              isRunning={isRunning}
              onCoachProfileChange={handleCoachProfileChange}
            />
          </div>
          <div className="min-h-0 flex-[0.7]">
            <TranscriptPanel activeTranscript={activeTranscript} transcript={transcript} />
          </div>
          <div className="min-h-0 flex-[1.3]">
            <LiveAnalysisPanel coachPanel={coachPanel} />
          </div>
        </aside>
      </div>

      {coachSelectionOpen ? (
        <CoachEntryDialog
          coachProfiles={coachProfiles}
          selectedCoachProfileId={selectedCoachProfileId}
          onSelect={(coachProfileId) => setSelectedCoachProfileId(coachProfileId)}
          onConfirm={() => setCoachSelectionOpen(false)}
        />
      ) : null}
    </main>
  );
}
