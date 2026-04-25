import { Card } from "@/components/ui/card";
import type { ReportProgressState } from "@/types/report";

type StepStatus = ReportProgressState["steps"][number]["status"];

function StepIndicator({ status, index }: { status: StepStatus; index: number }) {
  if (status === "done") {
    return (
      <span className="flex h-6 w-6 items-center justify-center rounded-full bg-emerald-500 text-[11px] font-bold text-white shadow-[0_0_0_4px_rgba(16,185,129,0.12)]">
        ✓
      </span>
    );
  }
  if (status === "failed") {
    return (
      <span className="flex h-6 w-6 items-center justify-center rounded-full bg-rose-500 text-[11px] font-bold text-white shadow-[0_0_0_4px_rgba(244,63,94,0.12)]">
        !
      </span>
    );
  }
  if (status === "active") {
    return (
      <span className="flex h-6 w-6 items-center justify-center rounded-full bg-white shadow-[0_0_0_4px_rgba(124,58,237,0.12)]">
        <span aria-hidden="true" className="report-progress-step-active" />
      </span>
    );
  }
  return (
    <span className="flex h-6 w-6 items-center justify-center rounded-full border border-slate-300 bg-white text-[11px] font-semibold text-slate-400">
      {index + 1}
    </span>
  );
}

function stepTextClass(status: StepStatus) {
  if (status === "done") {
    return "text-emerald-700";
  }
  if (status === "failed") {
    return "text-rose-700";
  }
  if (status === "active") {
    return "text-violet-700";
  }
  return "text-slate-400";
}

function getUserFacingStepLabel(key: string, fallback: string) {
  switch (key) {
    case "collecting":
      return "整理训练素材";
    case "structuring":
      return "梳理关键表现";
    case "generating":
      return "生成完整建议";
    case "finalizing":
      return "准备展示报告";
    default:
      return fallback;
  }
}

export function ReportGenerationProgress({
  progress,
}: {
  progress: ReportProgressState;
}) {
  const currentLabel = getUserFacingStepLabel(progress.currentKey, progress.currentLabel);
  const displayLabel = currentLabel.endsWith("...") ? currentLabel : `${currentLabel}...`;
  const steps = progress.steps;
  const activeIndex = steps.findIndex((step) => step.status === "active" || step.status === "failed");
  const lastDoneIndex = steps.reduce((lastIndex, step, index) => (step.status === "done" ? index : lastIndex), -1);
  const reachedIndex = Math.max(0, activeIndex >= 0 ? activeIndex : lastDoneIndex);
  const progressWidth = steps.length > 1 ? (reachedIndex / (steps.length - 1)) * 100 : 0;
  const edgeOffset = steps.length > 0 ? `${50 / steps.length}%` : "0%";

  return (
    <Card className="overflow-hidden border-violet-100 bg-white/90 px-4 py-3 shadow-[0_12px_30px_rgba(109,40,217,0.08)]">
      <div className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 items-center gap-3">
          <span aria-hidden="true" className="report-progress-icon mt-1 shrink-0">
            <span className="report-progress-bar" />
            <span className="report-progress-bar" />
            <span className="report-progress-bar" />
          </span>
          <div className="min-w-0">
            <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-violet-600">
              AI 正在生成报告
            </p>
            <p className="report-progress-text mt-1 truncate text-sm font-semibold text-slate-900">
              {displayLabel}
            </p>
          </div>
        </div>
      </div>

      {steps.length > 0 ? (
        <div className="relative mt-4">
          <div className="absolute top-3 h-1 rounded-full bg-slate-200" style={{ left: edgeOffset, right: edgeOffset }} />
          <div
            className="absolute top-3 h-1 overflow-hidden rounded-full"
            style={{ left: edgeOffset, right: edgeOffset }}
          >
            <div
              className="h-full rounded-full bg-gradient-to-r from-violet-500 via-fuchsia-500 to-emerald-400 transition-[width] duration-500 ease-out"
              style={{ width: `${progressWidth}%` }}
            />
          </div>

          <div
            className="relative grid gap-2"
            style={{ gridTemplateColumns: `repeat(${steps.length}, minmax(0, 1fr))` }}
          >
            {steps.map((step, index) => (
              <div key={step.key} className="flex min-w-0 flex-col items-center gap-2">
                <StepIndicator status={step.status} index={index} />
                <p className={`w-full truncate text-center text-[11px] font-semibold ${stepTextClass(step.status)}`}>
                  {getUserFacingStepLabel(step.key, step.label)}
                </p>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </Card>
  );
}
