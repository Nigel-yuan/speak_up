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
    <Card className="p-5 md:p-6">
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_320px] lg:items-stretch">
        <div className="min-w-0">
          <p className="text-sm font-semibold uppercase tracking-[0.2em] text-violet-600">本次总结</p>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight text-slate-950 md:text-3xl">
            {report.headline}
          </h1>
          <p className="mt-3 text-sm leading-7 text-slate-600">{report.encouragement}</p>
          {summaryReady ? (
            <p className="mt-3 max-w-3xl text-sm leading-7 text-slate-500">{report.summaryParagraph}</p>
          ) : (
            <ReportPendingState
              label="AI 正在生成本次总结"
              detail="完整报告生成完成后，这里会自动更新。"
              className="mt-4"
            />
          )}
        </div>
        <div className="flex min-h-[180px] flex-col justify-between rounded-[28px] bg-slate-950 px-7 py-6 text-white shadow-[0_20px_45px_rgba(15,23,42,0.2)]">
          <p className="text-base font-semibold text-slate-200">综合得分</p>
          {showPendingScore ? (
            <ReportPendingState
              label="AI 分析中"
              detail="完整报告生成完成后，这里会自动更新。"
              className="mt-3"
              invert
            />
          ) : (
            <p className="mt-2 text-7xl font-semibold leading-none">{report.overallScore}</p>
          )}
          {!showPendingScore ? <p className="mt-3 text-sm leading-6 text-slate-400">继续练 2-3 次，这个分数还能再抬一档。</p> : null}
        </div>
      </div>

      <div className="mt-5 grid gap-3 md:grid-cols-3">
        {highlightItems.map((highlight) => (
          <div key={highlight} className="rounded-2xl bg-slate-50 px-4 py-3 text-sm leading-6 text-slate-600">
            {highlight}
          </div>
        ))}
      </div>
    </Card>
  );
}
