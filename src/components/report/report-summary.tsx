import { Card } from "@/components/ui/card";
import type { SessionReport } from "@/types/report";
import { ReportPendingState } from "@/components/report/report-pending-state";

export function ReportSummary({ report }: { report: SessionReport }) {
  const summaryReady = report.sectionStatus.summary === "ready";
  const radarReady = report.sectionStatus.radar === "ready";
  const showPendingScore = !radarReady;
  const highlightItems = summaryReady
    ? (report.highlights.length > 0 ? report.highlights : ["本轮亮点暂未生成。"])
    : ["AI 正在生成本次总结，请稍候。"];

  return (
    <Card className="p-6 md:p-8">
      <div className="flex flex-col gap-6 md:flex-row md:items-start md:justify-between">
        <div className="max-w-3xl">
          <p className="text-sm font-semibold uppercase tracking-[0.2em] text-violet-600">本次总结</p>
          <h1 className="mt-3 text-3xl font-semibold tracking-tight text-slate-950 md:text-4xl">
            {report.headline}
          </h1>
          <p className="mt-4 text-base leading-8 text-slate-600">{report.encouragement}</p>
          {summaryReady ? (
            <p className="mt-4 max-w-2xl text-sm leading-7 text-slate-500">{report.summaryParagraph}</p>
          ) : (
            <ReportPendingState
              label="AI 正在生成本次总结"
              detail={report.progress.detail ?? `当前步骤：${report.progress.currentLabel}`}
              className="mt-4"
            />
          )}
        </div>
        <div className="rounded-3xl bg-slate-950 px-6 py-5 text-white">
          <p className="text-sm text-slate-300">综合得分</p>
          {showPendingScore ? (
            <ReportPendingState
              label="AI 分析中"
              detail={report.progress.detail ?? `当前步骤：${report.progress.currentLabel}`}
              className="mt-3"
              invert
            />
          ) : (
            <p className="mt-2 text-5xl font-semibold">{report.overallScore}</p>
          )}
          {!showPendingScore ? <p className="mt-2 text-sm text-slate-400">继续练 2-3 次，这个分数还能再抬一档。</p> : null}
        </div>
      </div>

      <div className="mt-8 grid gap-4 md:grid-cols-3">
        {highlightItems.map((highlight) => (
          <div key={highlight} className="rounded-2xl bg-slate-50 px-4 py-4 text-sm leading-7 text-slate-600">
            {highlight}
          </div>
        ))}
      </div>
    </Card>
  );
}
