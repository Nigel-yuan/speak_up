import { Button } from "@/components/ui/button";

interface SessionControlsProps {
  disabled?: boolean;
  isRunning: boolean;
  onStart: () => void;
  onFinish: () => void;
}

export function SessionControls({
  disabled = false,
  isRunning,
  onStart,
  onFinish,
}: SessionControlsProps) {
  return (
    <div className="flex items-center">
      <Button
        className="h-9 min-w-[180px] justify-center bg-gradient-to-r from-fuchsia-500 via-violet-500 to-indigo-500 px-4 py-0 text-white shadow-[0_14px_30px_rgba(139,92,246,0.28)] hover:from-fuchsia-400 hover:via-violet-400 hover:to-indigo-400 disabled:cursor-not-allowed disabled:opacity-60"
        disabled={disabled}
        onClick={isRunning ? onFinish : onStart}
        type="button"
      >
        {isRunning ? "结束并生成报告" : "开始"}
      </Button>
    </div>
  );
}
