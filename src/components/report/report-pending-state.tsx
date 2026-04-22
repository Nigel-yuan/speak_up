import clsx from "clsx";

interface ReportPendingStateProps {
  label: string;
  detail?: string;
  className?: string;
  center?: boolean;
  invert?: boolean;
}

export function ReportPendingState({
  label,
  detail,
  className,
  center = false,
  invert = false,
}: ReportPendingStateProps) {
  return (
    <div className={clsx("flex items-center gap-3", center && "justify-center", className)}>
      <span
        aria-hidden="true"
        className={clsx(
          "inline-block h-4 w-4 animate-spin rounded-full border-2 border-solid border-current border-r-transparent",
          invert ? "text-slate-200" : "text-violet-500",
        )}
      />
      <div className="min-w-0">
        <p className={clsx("text-sm font-medium", invert ? "text-slate-100" : "text-slate-700")}>{label}</p>
        {detail ? (
          <p className={clsx("mt-1 text-xs leading-6", invert ? "text-slate-400" : "text-slate-500")}>{detail}</p>
        ) : null}
      </div>
    </div>
  );
}
