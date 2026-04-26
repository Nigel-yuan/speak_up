"use client";

import { CameraPanel } from "@/components/session/camera-panel";
import { DocumentAssetPreview } from "@/components/session/document-viewer";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import type { CapturedVideoFrame, TrainingDocumentAsset } from "@/types/session";

interface DocumentStageProps {
  children: React.ReactNode;
  cameraPermissionState: "idle" | "granted" | "denied";
  cameraStream: MediaStream | null;
  documentAsset: TrainingDocumentAsset | null;
  elapsedSeconds: number;
  isRunning: boolean;
  onDocumentPick: () => void;
  onFrameCaptureReady?: (capture: () => Promise<CapturedVideoFrame | null>) => void;
}

function EmptyDocumentState({ onDocumentPick }: { onDocumentPick: () => void }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-5 px-8 text-center">
      <div className="space-y-2">
        <p className="text-xs font-semibold uppercase tracking-[0.24em] text-violet-500">Document Rehearsal</p>
        <h3 className="text-3xl font-semibold tracking-tight text-slate-950">上传 `PDF` 或 `Markdown` 文档</h3>
        <p className="max-w-2xl text-sm leading-7 text-slate-500">
          PDF 和 Markdown 直接预览。文档会占据主视区，摄像头缩到右上角。
        </p>
      </div>
      <Button
        type="button"
        onClick={onDocumentPick}
        className="bg-violet-700 px-6 text-white shadow-[0_12px_26px_rgba(109,40,217,0.2)] hover:bg-violet-600"
      >
        选择文档
      </Button>
      <div className="flex items-center gap-2 text-xs font-medium text-slate-400">
        <span className="rounded-full bg-violet-100 px-3 py-1 text-violet-700">PDF</span>
        <span className="rounded-full bg-violet-100 px-3 py-1 text-violet-700">MD</span>
      </div>
    </div>
  );
}

export function DocumentStage({
  children,
  cameraPermissionState,
  cameraStream,
  documentAsset,
  elapsedSeconds,
  isRunning,
  onDocumentPick,
  onFrameCaptureReady,
}: DocumentStageProps) {
  return (
    <Card className="flex h-full min-h-0 flex-col overflow-hidden rounded-[28px] border-white/70 bg-white shadow-[0_18px_45px_rgba(15,23,42,0.08)]">
      <div className="relative min-h-0 flex-1 overflow-hidden">
        <div className="absolute right-4 top-4 z-20 h-[104px] w-[160px]">
          <CameraPanel
            elapsedSeconds={elapsedSeconds}
            isRunning={isRunning}
            cameraPermissionState={cameraPermissionState}
            cameraStream={cameraStream}
            onFrameCaptureReady={onFrameCaptureReady}
            variant="inset"
          >
            <div />
          </CameraPanel>
        </div>

        <div className="h-full overflow-y-auto p-3">
          {documentAsset ? (
            <div className="mx-auto flex h-full max-w-[1320px] flex-col rounded-[30px] border border-slate-100 bg-white p-3 shadow-[0_24px_60px_rgba(15,23,42,0.06)]">
              <DocumentAssetPreview documentAsset={documentAsset} />
            </div>
          ) : (
            <div className="h-full rounded-[28px] border border-dashed border-slate-200 bg-white shadow-[0_20px_50px_rgba(15,23,42,0.06)]">
              <EmptyDocumentState onDocumentPick={onDocumentPick} />
            </div>
          )}
        </div>

        {children ? <div className="absolute bottom-5 right-5 z-20">{children}</div> : null}
      </div>
    </Card>
  );
}
