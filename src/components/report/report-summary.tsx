import { Card } from "@/components/ui/card";
import type { SessionReport } from "@/types/report";

export function ReportSummary({ report }: { report: SessionReport }) {
  return (
    <Card className="p-6 md:p-8">
      <div className="flex flex-col gap-6 md:flex-row md:items-start md:justify-between">
        <div className="max-w-3xl">
          <p className="text-sm font-semibold uppercase tracking-[0.2em] text-violet-600">本次总结</p>
          <h1 className="mt-3 text-3xl font-semibold tracking-tight text-slate-950 md:text-4xl">
            {report.headline}
          </h1>
          <p className="mt-4 text-base leading-8 text-slate-600">{report.encouragement}</p>
        </div>
        <div className="rounded-3xl bg-slate-950 px-6 py-5 text-white">
          <p className="text-sm text-slate-300">综合得分</p>
          <p className="mt-2 text-5xl font-semibold">{report.overallScore}</p>
          <p className="mt-2 text-sm text-slate-400">继续练 2-3 次，这个分数还能再抬一档。</p>
        </div>
      </div>

      <div className="mt-8 grid gap-4 md:grid-cols-3">
        {report.highlights.map((highlight) => (
          <div key={highlight} className="rounded-2xl bg-slate-50 px-4 py-4 text-sm leading-7 text-slate-600">
            {highlight}
          </div>
        ))}
      </div>
    </Card>
  );
}
