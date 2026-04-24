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
    <div className="flex flex-wrap items-center gap-2 rounded-full border border-slate-200 bg-slate-50 p-1">
      {showStart ? (
        <Button
          className="h-9 bg-slate-950 px-4 py-0 text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
          disabled={disabled || !isRunning}
          onClick={onStartQA}
          type="button"
        >
          开始提问
        </Button>
      ) : null}

      {showPreparing ? (
        <Button
          className="h-9 bg-slate-400 px-4 py-0 text-white disabled:cursor-wait disabled:opacity-100"
          disabled
          type="button"
        >
          AI 正在出题...
        </Button>
      ) : null}

      {qaEnabled ? (
        <Button
          className="h-9 border border-slate-200 bg-white px-4 py-0 text-slate-700 hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-60"
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
