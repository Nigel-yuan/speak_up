"use client";

import { CameraPanel } from "@/components/session/camera-panel";
import { DocumentPreviewPanel } from "@/components/session/document-preview-panel";
import { DocumentStage } from "@/components/session/document-stage";
import { QAAvatarPanel } from "@/components/session/qa-avatar-panel";
import type { QAFeedback, QAQuestion, QAPhase, TrainingDocumentAsset, TrainingMode } from "@/types/session";

interface SessionStageProps {
  avatarSrc: string;
  controls: React.ReactNode;
  documentAsset: TrainingDocumentAsset | null;
  elapsedSeconds: number;
  feedback: QAFeedback | null;
  goal: string | null;
  isRunning: boolean;
  phase: QAPhase;
  qaAudioUrl: string | null;
  qaAudioAutoPlay: boolean;
  qaEnabled: boolean;
  question: QAQuestion | null;
  registerVideoFrameProvider: (capture: () => string | null) => void;
  sessionId: string | null;
  speaking: boolean;
  statusMessage: string | null;
  trainingMode: TrainingMode;
  voiceLabel: string | null;
  onQAAudioPlaybackEnded: (turnId: string) => void;
  onQAAudioPlaybackStarted: (turnId: string) => void;
  onDocumentPick: () => void;
  onInterviewerSpeakingChange: (speaking: boolean) => void;
}

export function SessionStage({
  avatarSrc,
  controls,
  documentAsset,
  elapsedSeconds,
  feedback,
  goal,
  isRunning,
  phase,
  qaAudioUrl,
  qaAudioAutoPlay,
  qaEnabled,
  question,
  registerVideoFrameProvider,
  sessionId,
  speaking,
  statusMessage,
  trainingMode,
  voiceLabel,
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
          onDocumentPick={onDocumentPick}
          onFrameCaptureReady={registerVideoFrameProvider}
          sessionId={sessionId}
          statusMessage={statusMessage}
        >
          {controls}
        </DocumentStage>
      );
    }

    return (
      <CameraPanel
        elapsedSeconds={elapsedSeconds}
        isRunning={isRunning}
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
            </div>
          </CameraPanel>
        )}
      </div>

      <div className="min-h-0">
        <QAAvatarPanel
          audioUrl={qaAudioUrl}
          autoPlayAudio={qaAudioAutoPlay}
          avatarSrc={avatarSrc}
          feedbackText={feedback?.feedbackText ?? null}
          goal={goal}
          phase={phase}
          questionText={question?.questionText ?? null}
          speaking={speaking}
          turnId={question?.turnId ?? null}
          voiceLabel={voiceLabel}
          onAudioPlaybackEnded={onQAAudioPlaybackEnded}
          onAudioPlaybackStarted={onQAAudioPlaybackStarted}
          onSpeakingChange={onInterviewerSpeakingChange}
          insetPreview={
            trainingMode === "document_speech" ? (
              <CameraPanel
                elapsedSeconds={elapsedSeconds}
                isRunning={isRunning}
                onFrameCaptureReady={registerVideoFrameProvider}
                variant="inset"
              >
                <div />
              </CameraPanel>
            ) : undefined
          }
        />
      </div>
    </div>
  );
}
