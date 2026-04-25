import { Button } from "@/components/ui/button";
import type { QAPhase } from "@/types/session";

interface QAControlBarProps {
  disabled?: boolean;
  phase: QAPhase;
  onStopQA: () => void;
}

export function QAControlBar({
  disabled = false,
  phase,
  onStopQA,
}: QAControlBarProps) {
  const isPreparing = phase === "preparing_context";

  if (phase === "idle" || phase === "completed") {
    return null;
  }

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-full border border-slate-200 bg-slate-50 p-1">
      {isPreparing ? (
        <Button
          className="h-9 bg-slate-400 px-4 py-0 text-white disabled:cursor-wait disabled:opacity-100"
          disabled
          type="button"
        >
          AI 正在出题...
        </Button>
      ) : (
        <Button
          className="h-9 bg-slate-950 px-4 py-0 text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
          disabled={disabled}
          onClick={onStopQA}
          type="button"
        >
          结束提问
        </Button>
      )}
    </div>
  );
}
