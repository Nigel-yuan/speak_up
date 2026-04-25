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

function ModeButton({
  active,
  children,
  disabled = false,
  onClick,
}: {
  active: boolean;
  children: ReactNode;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={`rounded-full px-3 py-1.5 text-sm font-semibold transition ${
        active
          ? disabled
            ? "bg-slate-950/70 text-white"
            : "bg-slate-950 text-white"
          : disabled
            ? "cursor-not-allowed text-slate-400"
            : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
      }`}
    >
      {children}
    </button>
  );
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
  const isDocumentMode = trainingMode === "document_speech";

  return (
    <div className="rounded-[26px] border border-white/75 bg-white/92 px-3 py-3 shadow-[0_16px_40px_rgba(15,23,42,0.08)] backdrop-blur">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <div className="flex items-center gap-1 rounded-full border border-slate-200 bg-slate-50 p-1">
            <ModeButton
              active={trainingMode === "free_speech"}
              disabled={qaEnabled}
              onClick={() => onTrainingModeChange("free_speech")}
            >
              自由演讲
            </ModeButton>
            <ModeButton
              active={isDocumentMode}
              disabled={qaEnabled}
              onClick={() => onTrainingModeChange("document_speech")}
            >
              文档演讲
            </ModeButton>
          </div>
          <button
            type="button"
            onClick={onQAToggle}
            className="rounded-full bg-slate-950 px-3.5 py-2 text-sm font-semibold text-white shadow-[0_10px_22px_rgba(15,23,42,0.16)] transition hover:bg-slate-800"
          >
            {qaEnabled ? "退出问答模式" : "进入问答模式"}
          </button>
          {qaEnabled && qaControls ? <div className="toolbar-panel-enter">{qaControls}</div> : null}
        </div>
        <div className="flex shrink-0 items-center gap-2 rounded-full border border-slate-200 bg-slate-50 p-1.5">
          <Badge tone={isRunning ? "positive" : "neutral"}>{isRunning ? "进行中" : "待开始"}</Badge>
          <span className="rounded-full bg-white px-3 py-1.5 font-mono text-sm font-semibold tabular-nums text-slate-700 shadow-[0_6px_14px_rgba(15,23,42,0.05)]">
            {formatElapsedTime(elapsedSeconds)}
          </span>
          {primaryControls}
        </div>
      </div>

      <div className="mt-2 space-y-2">
        {isDocumentMode ? (
          <div
            key="document-actions"
            className="toolbar-panel-enter flex flex-wrap items-center gap-2 rounded-full border border-emerald-100 bg-emerald-50/80 px-3 py-2"
          >
            <span className="rounded-full bg-white/80 px-2.5 py-1 text-xs font-semibold text-emerald-700">
              文档模式
            </span>
            <button
              type="button"
              disabled={qaEnabled}
              onClick={onDocumentPick}
              className={`rounded-full px-3.5 py-2 text-sm font-semibold transition ${
                qaEnabled
                  ? "cursor-not-allowed bg-emerald-200 text-emerald-800 opacity-70 shadow-none"
                  : "bg-emerald-600 text-white shadow-[0_10px_22px_rgba(16,185,129,0.18)] hover:bg-emerald-500"
              }`}
              title={qaEnabled ? "退出问答模式后可更换文档" : undefined}
            >
              {documentAsset ? "更换文档" : "上传文档"}
            </button>
            {documentAsset ? (
              <>
                <div className="flex min-w-0 max-w-[420px] items-center gap-2 rounded-full border border-emerald-100 bg-white px-3.5 py-2 text-sm text-emerald-800">
                  <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-[0.16em] text-emerald-700">
                    {documentAsset.kind}
                  </span>
                  <span className="truncate font-medium">{documentAsset.name}</span>
                </div>
                <button
                  type="button"
                  disabled={qaEnabled}
                  onClick={onDocumentClear}
                  className={`rounded-full border px-3.5 py-2 text-sm font-semibold transition ${
                    qaEnabled
                      ? "cursor-not-allowed border-emerald-100 bg-white/70 text-emerald-400"
                      : "border-emerald-200 bg-white text-emerald-700 hover:bg-emerald-50"
                  }`}
                  title={qaEnabled ? "退出问答模式后可移除文档" : undefined}
                >
                  移除文档
                </button>
              </>
            ) : (
              <span className="text-sm text-emerald-700/75">上传后，文档内容会进入问答上下文。</span>
            )}
          </div>
        ) : null}
      </div>
    </div>
  );
}
