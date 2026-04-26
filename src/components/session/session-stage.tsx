"use client";

import { CameraPanel } from "@/components/session/camera-panel";
import { DocumentPreviewPanel } from "@/components/session/document-preview-panel";
import { DocumentStage } from "@/components/session/document-stage";
import { QAAvatarPanel } from "@/components/session/qa-avatar-panel";
import type {
  CapturedVideoFrame,
  QAQuestion,
  QAPhase,
  TrainingDocumentAsset,
  TrainingMode,
} from "@/types/session";

interface SessionStageProps {
  avatarSrc: string;
  cameraPermissionState: "idle" | "granted" | "denied";
  cameraStream: MediaStream | null;
  controls: React.ReactNode;
  documentAsset: TrainingDocumentAsset | null;
  elapsedSeconds: number;
  isRunning: boolean;
  phase: QAPhase;
  qaAudioUrl: string | null;
  qaAudioAutoPlay: boolean;
  qaEnabled: boolean;
  question: QAQuestion | null;
  registerVideoFrameProvider: (capture: () => Promise<CapturedVideoFrame | null>) => void;
  speaking: boolean;
  statusMessage: string | null;
  trainingMode: TrainingMode;
  onQAAudioPlaybackEnded: (turnId: string) => void;
  onQAAudioPlaybackStarted: (turnId: string) => void;
  onDocumentPick: () => void;
  onInterviewerSpeakingChange: (speaking: boolean) => void;
}

export function SessionStage({
  avatarSrc,
  cameraPermissionState,
  cameraStream,
  controls,
  documentAsset,
  elapsedSeconds,
  isRunning,
  phase,
  qaAudioUrl,
  qaAudioAutoPlay,
  qaEnabled,
  question,
  registerVideoFrameProvider,
  speaking,
  statusMessage,
  trainingMode,
  onQAAudioPlaybackEnded,
  onQAAudioPlaybackStarted,
  onDocumentPick,
  onInterviewerSpeakingChange,
}: SessionStageProps) {
  if (!qaEnabled) {
    if (trainingMode === "document_speech") {
      return (
        <DocumentStage
          documentAsset={documentAsset}
          elapsedSeconds={elapsedSeconds}
          isRunning={isRunning}
          cameraPermissionState={cameraPermissionState}
          cameraStream={cameraStream}
          onDocumentPick={onDocumentPick}
          onFrameCaptureReady={registerVideoFrameProvider}
        >
          {controls}
        </DocumentStage>
      );
    }

    return (
      <CameraPanel
        elapsedSeconds={elapsedSeconds}
        isRunning={isRunning}
        cameraPermissionState={cameraPermissionState}
        cameraStream={cameraStream}
        onFrameCaptureReady={registerVideoFrameProvider}
      >
        <div className="space-y-2">
          {statusMessage ? (
            <div className="rounded-2xl bg-black/50 px-4 py-2 text-sm font-medium text-white backdrop-blur">
              {statusMessage}
            </div>
          ) : null}
          {controls}
        </div>
      </CameraPanel>
    );
  }

  return (
    <div className="grid h-full min-h-0 gap-3 xl:grid-cols-[minmax(0,2fr)_minmax(320px,1fr)]">
      <div className="min-h-0">
        {trainingMode === "document_speech" ? (
          <DocumentPreviewPanel documentAsset={documentAsset} />
        ) : (
          <CameraPanel
            elapsedSeconds={elapsedSeconds}
            isRunning={isRunning}
            cameraPermissionState={cameraPermissionState}
            cameraStream={cameraStream}
            onFrameCaptureReady={registerVideoFrameProvider}
          >
            <div className="space-y-2">
              {statusMessage ? (
                <div className="rounded-2xl bg-black/50 px-4 py-2 text-sm font-medium text-white backdrop-blur">
                  {statusMessage}
                </div>
              ) : null}
            </div>
          </CameraPanel>
        )}
      </div>

      <div className={trainingMode === "document_speech" ? "flex min-h-0 flex-col gap-3" : "min-h-0"}>
        {trainingMode === "document_speech" ? (
          <div className="h-[118px] shrink-0 overflow-hidden rounded-[24px] border border-white/70 bg-slate-950 shadow-[0_18px_45px_rgba(15,23,42,0.16)]">
            <CameraPanel
              elapsedSeconds={elapsedSeconds}
              isRunning={isRunning}
              cameraPermissionState={cameraPermissionState}
              cameraStream={cameraStream}
              onFrameCaptureReady={registerVideoFrameProvider}
              variant="inset"
            >
              <div />
            </CameraPanel>
          </div>
        ) : null}
        <div className={trainingMode === "document_speech" ? "min-h-0 flex-1" : "h-full min-h-0"}>
          <QAAvatarPanel
            audioUrl={qaAudioUrl}
            autoPlayAudio={qaAudioAutoPlay}
            avatarSrc={avatarSrc}
            phase={phase}
            questionText={question?.questionText ?? null}
            speaking={speaking}
            turnId={question?.turnId ?? null}
            onAudioPlaybackEnded={onQAAudioPlaybackEnded}
            onAudioPlaybackStarted={onQAAudioPlaybackStarted}
            onSpeakingChange={onInterviewerSpeakingChange}
          />
        </div>
      </div>
    </div>
  );
}
