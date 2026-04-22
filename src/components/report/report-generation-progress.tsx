import clsx from "clsx";

import { Card } from "@/components/ui/card";
import type { ReportProgressState } from "@/types/report";

function StepIndicator({ status }: { status: "pending" | "active" | "done" | "failed" }) {
  if (status === "done") {
    return (
      <span className="flex h-4 w-4 items-center justify-center rounded-full bg-emerald-500 text-[10px] font-bold text-white">
        ✓
      </span>
    );
  }
  if (status === "failed") {
    return (
      <span className="flex h-4 w-4 items-center justify-center rounded-full bg-rose-500 text-[10px] font-bold text-white">
        !
      </span>
    );
  }
  if (status === "active") {
    return <span aria-hidden="true" className="report-progress-step-active" />;
  }
  return <span className="inline-block h-4 w-4 rounded-full border border-slate-300 bg-white" />;
}

export function ReportGenerationProgress({
  progress,
}: {
  progress: ReportProgressState;
}) {
  const displayLabel = progress.currentLabel.endsWith("...") ? progress.currentLabel : `${progress.currentLabel}...`;

  return (
    <Card className="overflow-hidden border-violet-100 bg-white/90 shadow-[0_12px_30px_rgba(109,40,217,0.08)]">
      <details className="group">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-4 px-4 py-3">
          <div className="flex min-w-0 items-center gap-3">
            <span aria-hidden="true" className="report-progress-icon shrink-0">
              <span className="report-progress-bar" />
              <span className="report-progress-bar" />
              <span className="report-progress-bar" />
            </span>
            <div className="min-w-0">
              <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-violet-600">
                AI 正在生成报告
              </p>
              <div className="mt-1 min-w-0">
                <p className="report-progress-text truncate text-sm font-semibold text-slate-900">
                  {displayLabel}
                </p>
              </div>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2 text-xs font-medium text-slate-500">
            <span className="hidden sm:inline">查看详细动作</span>
            <span className="transition-transform duration-200 group-open:rotate-180">⌄</span>
          </div>
        </summary>

        <div className="border-t border-slate-100 bg-slate-50/80 px-4 py-3">
          {progress.detail ? (
            <p className="mb-3 text-xs leading-6 text-slate-500">{progress.detail}</p>
          ) : null}
          <div className="grid gap-2 md:grid-cols-2">
            {progress.steps.map((step) => (
              <div
                key={step.key}
                className={clsx(
                  "rounded-xl border px-3 py-2.5",
                  step.status === "active" && "border-violet-200 bg-white shadow-sm",
                  step.status === "done" && "border-emerald-200 bg-emerald-50/80",
                  step.status === "failed" && "border-rose-200 bg-rose-50/80",
                  step.status === "pending" && "border-slate-200 bg-white/70",
                )}
              >
                <div className="flex items-center gap-2.5">
                  <StepIndicator status={step.status} />
                  <p className="text-sm font-medium text-slate-800">{step.label}</p>
                </div>
                {step.detail ? (
                  <p className="mt-1.5 pl-6 text-xs leading-6 text-slate-500">{step.detail}</p>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      </details>
    </Card>
  );
}
