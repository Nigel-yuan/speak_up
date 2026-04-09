import { Button } from "@/components/ui/button";

interface SessionControlsProps {
  disabled?: boolean;
  isRunning: boolean;
  onStart: () => void;
  onPause: () => void;
  onReset: () => void;
  onFinish: () => void;
}

export function SessionControls({
  disabled = false,
  isRunning,
  onStart,
  onPause,
  onReset,
  onFinish,
}: SessionControlsProps) {
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-2xl bg-black/35 p-3 backdrop-blur">
      <Button
        className="bg-gradient-to-r from-fuchsia-500 via-violet-500 to-indigo-500 text-white shadow-[0_14px_30px_rgba(139,92,246,0.42)] hover:from-fuchsia-400 hover:via-violet-400 hover:to-indigo-400 disabled:cursor-not-allowed disabled:opacity-60"
        disabled={disabled}
        onClick={isRunning ? onPause : onStart}
        type="button"
      >
        {isRunning ? "暂停" : "开始"}
      </Button>
      <Button
        className="border border-white/15 bg-white/10 text-white hover:bg-white/18 disabled:cursor-not-allowed disabled:opacity-60"
        disabled={disabled}
        onClick={onReset}
        type="button"
      >
        重置
      </Button>
      <Button
        className="bg-violet-600/92 text-white shadow-[0_12px_24px_rgba(109,40,217,0.24)] hover:bg-violet-500 disabled:cursor-not-allowed disabled:opacity-60"
        disabled={disabled}
        onClick={onFinish}
        type="button"
      >
        结束并生成报告
      </Button>
    </div>
  );
}
