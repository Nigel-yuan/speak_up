import { Card } from "@/components/ui/card";
import type { SuggestionItem } from "@/types/report";

export function ReportSuggestions({ suggestions }: { suggestions: SuggestionItem[] }) {
  return (
    <Card className="p-6">
      <div className="mb-4">
        <p className="text-sm text-slate-500">行动建议</p>
        <h3 className="text-xl font-semibold text-slate-950">下一轮可以重点打磨的地方</h3>
      </div>

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
    </Card>
  );
}
