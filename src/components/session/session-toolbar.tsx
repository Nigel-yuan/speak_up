import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import type {
  TrainingDocumentAsset,
  TrainingMode,
} from "@/types/session";

interface SessionToolbarProps {
  elapsedSeconds: number;
  documentAsset: TrainingDocumentAsset | null;
  isRunning: boolean;
  onDocumentClear: () => void;
  onDocumentPick: () => void;
  onQAToggle: () => void;
  onTrainingModeChange: (mode: TrainingMode) => void;
  primaryControls: ReactNode;
  qaControls?: ReactNode;
  qaEnabled: boolean;
  trainingMode: TrainingMode;
}

function formatElapsedTime(totalSeconds: number) {
  const minutes = String(Math.floor(totalSeconds / 60)).padStart(2, "0");
  const seconds = String(totalSeconds % 60).padStart(2, "0");
  return `${minutes}:${seconds}`;
}

export function SessionToolbar({
  elapsedSeconds,
  documentAsset,
  isRunning,
  onDocumentClear,
  onDocumentPick,
  onQAToggle,
  onTrainingModeChange,
  primaryControls,
  qaControls,
  qaEnabled,
  trainingMode,
}: SessionToolbarProps) {
  return (
    <div className="rounded-[26px] border border-white/75 bg-white/92 px-3 py-3 shadow-[0_16px_40px_rgba(15,23,42,0.08)] backdrop-blur">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <div className="flex items-center gap-1 rounded-full border border-slate-200 bg-slate-50 p-1">
            <button
              type="button"
              onClick={() => onTrainingModeChange("free_speech")}
              className={`rounded-full px-3 py-1.5 text-sm font-semibold transition ${
                trainingMode === "free_speech"
                  ? "bg-slate-950 text-white"
                  : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
              }`}
            >
              自由演讲
            </button>
            <button
              type="button"
              onClick={() => onTrainingModeChange("document_speech")}
              className={`rounded-full px-3 py-1.5 text-sm font-semibold transition ${
                trainingMode === "document_speech"
                  ? "bg-slate-950 text-white"
                  : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
              }`}
            >
              文档演讲
            </button>
          </div>
          <button
            type="button"
            onClick={onQAToggle}
            className={`rounded-full px-3.5 py-2 text-sm font-semibold transition ${
              qaEnabled
                ? "bg-slate-950 text-white hover:bg-slate-800"
                : "border border-slate-200 bg-white text-slate-700 hover:border-slate-300 hover:bg-slate-100"
            }`}
          >
            {qaEnabled ? "退出问答模式" : "进入问答模式"}
          </button>
          {trainingMode === "document_speech" ? (
            <>
              <button
                type="button"
                onClick={onDocumentPick}
                className="rounded-full border border-slate-200 bg-white px-3.5 py-2 text-sm font-semibold text-slate-700 transition hover:border-emerald-200 hover:bg-emerald-50 hover:text-emerald-700"
              >
                {documentAsset ? "更换文档" : "上传文档"}
              </button>
              {documentAsset ? (
                <>
                  <div className="flex min-w-0 items-center gap-2 rounded-full border border-emerald-100 bg-emerald-50 px-3.5 py-2 text-sm text-emerald-800">
                    <span className="rounded-full bg-white/80 px-2 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-emerald-700">
                      {documentAsset.kind}
                    </span>
                    <span className="max-w-[220px] truncate font-medium">{documentAsset.name}</span>
                  </div>
                  <button
                    type="button"
                    onClick={onDocumentClear}
                    className="rounded-full border border-slate-200 bg-white px-3.5 py-2 text-sm font-semibold text-slate-600 transition hover:border-slate-300 hover:bg-slate-50 hover:text-slate-900"
                  >
                    移除文档
                  </button>
                </>
              ) : null}
            </>
          ) : null}
        </div>
        <div className="flex shrink-0 items-center gap-2 rounded-full border border-slate-200 bg-slate-50 p-1.5">
          <Badge tone={isRunning ? "positive" : "neutral"}>{isRunning ? "进行中" : "待开始"}</Badge>
          <span className="rounded-full bg-white px-3 py-1.5 font-mono text-sm font-semibold tabular-nums text-slate-700 shadow-[0_6px_14px_rgba(15,23,42,0.05)]">
            {formatElapsedTime(elapsedSeconds)}
          </span>
          {primaryControls}
        </div>
      </div>
      {qaControls ? (
        <div className="mt-2 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-2">{qaControls}</div>
      ) : null}
    </div>
  );
}
