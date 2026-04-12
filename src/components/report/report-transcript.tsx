import { Card } from "@/components/ui/card";
import type { TranscriptChunk } from "@/types/session";

export function ReportTranscript({ transcript }: { transcript: TranscriptChunk[] }) {
  return (
    <Card className="p-6">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-sm text-slate-500">完整文字稿</p>
          <h3 className="mt-1 text-xl font-semibold text-slate-950">Full Transcript</h3>
        </div>
        <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-500">
          {transcript.length} 段
        </span>
      </div>

      <div className="mt-5 space-y-3">
        {transcript.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-slate-200 px-4 py-8 text-sm leading-7 text-slate-400">
            本次练习还没有生成完整文字稿。
          </div>
        ) : null}

        {transcript.map((item) => (
          <div key={item.id} className="rounded-2xl bg-slate-50 px-4 py-3">
            <div className="mb-2 flex items-center justify-between text-xs text-slate-400">
              <span>{item.speaker === "user" ? "你" : "AI"}</span>
              <span>{item.timestampLabel}</span>
            </div>
            <p className="text-sm leading-6 text-slate-700">{item.text}</p>
          </div>
        ))}
      </div>
    </Card>
  );
}
