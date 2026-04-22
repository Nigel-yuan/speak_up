import { Card } from "@/components/ui/card";
import type { SuggestionItem } from "@/types/report";
import { ReportPendingState } from "@/components/report/report-pending-state";

export function ReportSuggestions({
  suggestions,
  ready,
  detail,
}: {
  suggestions: SuggestionItem[];
  ready: boolean;
  detail?: string;
}) {
  return (
    <Card className="p-6">
      <div className="mb-4">
        <p className="text-sm text-slate-500">行动建议</p>
        <h3 className="text-xl font-semibold text-slate-950">下一轮可以重点打磨的地方</h3>
      </div>

      {ready && suggestions.length > 0 ? (
        <div className="space-y-4">
          {suggestions.map((item, index) => (
            <div key={item.title} className="rounded-2xl border border-slate-200 px-4 py-4">
              <p className="text-sm font-semibold text-slate-800">
                0{index + 1}. {item.title}
              </p>
              <p className="mt-2 text-sm leading-7 text-slate-500">{item.detail}</p>
            </div>
          ))}
        </div>
      ) : ready ? (
        <div className="rounded-2xl border border-dashed border-slate-200 px-4 py-6">
          <p className="text-sm text-slate-500">行动建议暂未生成。</p>
        </div>
      ) : (
        <div className="rounded-2xl border border-dashed border-slate-200 px-4 py-6">
          <ReportPendingState
            label="AI 分析中"
            detail={detail ?? "完整报告生成完成后，这里会自动更新。"}
          />
        </div>
      )}
    </Card>
  );
}
