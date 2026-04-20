import { Button } from "@/components/ui/button";
import type { QAPhase } from "@/types/session";

interface QAControlBarProps {
  disabled?: boolean;
  isRunning: boolean;
  phase: QAPhase;
  qaEnabled: boolean;
  onStartQA: () => void;
  onStopQA: () => void;
}

export function QAControlBar({
  disabled = false,
  isRunning,
  phase,
  qaEnabled,
  onStartQA,
  onStopQA,
}: QAControlBarProps) {
  const showStart = qaEnabled && phase === "idle";
  const showPreparing = qaEnabled && phase === "preparing_context";

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-slate-200 bg-white px-4 py-3 shadow-[0_12px_30px_rgba(15,23,42,0.06)]">
      {showStart ? (
        <Button
          className="bg-slate-950 text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
          disabled={disabled || !isRunning}
          onClick={onStartQA}
          type="button"
        >
          开始提问
        </Button>
      ) : null}

      {showPreparing ? (
        <Button
          className="bg-slate-400 text-white disabled:cursor-wait disabled:opacity-100"
          disabled
          type="button"
        >
          AI 正在出题...
        </Button>
      ) : null}

      {qaEnabled ? (
        <Button
          className="border border-slate-200 bg-slate-100 text-slate-700 hover:bg-slate-200 disabled:cursor-not-allowed disabled:opacity-60"
          disabled={disabled}
          onClick={onStopQA}
          type="button"
        >
          退出问答
        </Button>
      ) : null}
    </div>
  );
}
