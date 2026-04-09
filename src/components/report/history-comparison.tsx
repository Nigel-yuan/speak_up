import { Card } from "@/components/ui/card";
import type { HistoricalSessionSummary } from "@/types/report";

export function HistoryComparison({ history }: { history: HistoricalSessionSummary[] }) {
  return (
    <Card className="p-6">
      <div className="mb-4">
        <p className="text-sm text-slate-500">历史对比</p>
        <h3 className="text-xl font-semibold text-slate-950">最近几次表现变化</h3>
      </div>

      <div className="space-y-4">
        {history.map((item) => (
          <div key={item.id} className="rounded-2xl bg-slate-50 px-4 py-4">
            <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
              <div>
                <p className="text-sm font-semibold text-slate-800">{item.label}</p>
                <p className="mt-1 text-sm text-slate-500">{item.summary}</p>
              </div>
              <div className="text-right">
                <p className="text-xs text-slate-400">综合得分</p>
                <p className="text-xl font-semibold text-slate-900">{item.overallScore}</p>
              </div>
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              {item.deltas.map((delta) => (
                <span
                  key={`${item.id}-${delta.metric}`}
                  className="rounded-full bg-white px-3 py-1 text-xs font-semibold text-slate-600"
                >
                  {delta.metric} {delta.change > 0 ? `+${delta.change}` : delta.change}%
                </span>
              ))}
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}
