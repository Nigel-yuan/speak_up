import type { HistoricalSessionSummary } from "@/types/report";
import type { ScenarioOption, ScenarioType } from "@/types/session";
import { Card } from "@/components/ui/card";

interface HistorySidebarProps {
  activeScenario: ScenarioType;
  history: HistoricalSessionSummary[];
  scenarios: ScenarioOption[];
}

export function HistorySidebar({ activeScenario, history, scenarios }: HistorySidebarProps) {
  const sortedHistory = [...history].sort((a, b) => {
    if (a.scenarioId === activeScenario && b.scenarioId !== activeScenario) {
      return -1;
    }
    if (a.scenarioId !== activeScenario && b.scenarioId === activeScenario) {
      return 1;
    }
    return b.overallScore - a.overallScore;
  });

  return (
    <div className="flex h-full min-h-0 flex-col gap-4 rounded-[28px] border border-white/60 bg-white/95 p-4 shadow-[0_18px_45px_rgba(15,23,42,0.08)] backdrop-blur">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.24em] text-violet-600">History</p>
        <h2 className="mt-2 text-xl font-semibold text-slate-950">历史演讲管理</h2>
        <p className="mt-2 text-sm leading-6 text-slate-500">这里可以回看最近训练记录，对比同场景的表现变化。</p>
      </div>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto pr-1">
        {sortedHistory.map((item) => (
          <HistoryItem
            key={item.id}
            active={item.scenarioId === activeScenario}
            item={item}
            scenarios={scenarios}
          />
        ))}
      </div>

      <Card className="rounded-2xl bg-slate-950 p-4 text-white shadow-none">
        <p className="text-sm font-semibold">最近重点</p>
        <p className="mt-2 text-sm leading-6 text-slate-300">
          当前场景下，优先关注结构性、节奏掌控和镜头感染力的连续提升。
        </p>
      </Card>
    </div>
  );
}

function HistoryItem({
  item,
  active,
  scenarios,
}: {
  item: HistoricalSessionSummary;
  active: boolean;
  scenarios: ScenarioOption[];
}) {
  const scenario = scenarios.find((entry) => entry.id === item.scenarioId);

  return (
    <div
      className={`rounded-2xl border px-4 py-4 transition ${
        active
          ? "border-violet-200 bg-violet-50 shadow-sm"
          : "border-slate-200 bg-slate-50 hover:border-slate-300"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-slate-900">{item.label}</p>
          <p className="mt-1 text-xs text-slate-500">{scenario?.title ?? item.scenarioId}</p>
        </div>
        <div className="rounded-full bg-white px-3 py-1 text-sm font-semibold text-slate-800">
          {item.overallScore}
        </div>
      </div>
      <p className="mt-3 text-sm leading-6 text-slate-500">{item.summary}</p>
      <div className="mt-3 flex flex-wrap gap-2">
        {item.deltas.map((delta) => (
          <span
            key={`${item.id}-${delta.metric}`}
            className="rounded-full bg-white px-2.5 py-1 text-[11px] font-semibold text-slate-600"
          >
            {delta.metric} {delta.change > 0 ? `+${delta.change}` : delta.change}%
          </span>
        ))}
      </div>
    </div>
  );
}
