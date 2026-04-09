import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import type { LiveInsight } from "@/types/session";

export function LiveAnalysisPanel({
  currentInsight,
  insights,
}: {
  currentInsight: LiveInsight | null;
  insights: LiveInsight[];
}) {
  return (
    <Card className="flex h-full min-h-0 flex-col rounded-[28px] border-white/60 bg-white/85 p-5 shadow-[0_18px_45px_rgba(15,23,42,0.08)] backdrop-blur">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <p className="text-sm text-slate-500">同步分析</p>
          <h3 className="text-lg font-semibold text-slate-950">AI Live Coach</h3>
        </div>
        <Badge tone={currentInsight?.tone ?? "neutral"}>实时观察</Badge>
      </div>

      <div className="rounded-2xl bg-slate-950 px-4 py-4 text-white">
        <p className="text-sm font-semibold text-slate-100">
          {currentInsight?.title ?? "等待演讲开始"}
        </p>
        <p className="mt-2 text-sm leading-6 text-slate-300">
          {currentInsight?.detail ?? "AI 会根据视频状态与文字稿，持续给出即时反馈。"}
        </p>
      </div>

      <div className="mt-4 min-h-0 space-y-3 overflow-y-auto pr-1">
        {insights.map((insight) => (
          <div key={insight.id} className="rounded-2xl border border-slate-200 px-4 py-3">
            <div className="mb-2 flex items-center justify-between">
              <p className="text-sm font-semibold text-slate-700">{insight.title}</p>
              <Badge tone={insight.tone}>{insight.tone}</Badge>
            </div>
            <p className="text-sm leading-6 text-slate-500">{insight.detail}</p>
          </div>
        ))}
      </div>
    </Card>
  );
}
