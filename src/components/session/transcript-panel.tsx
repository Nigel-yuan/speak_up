import { Card } from "@/components/ui/card";
import type { TranscriptChunk } from "@/types/session";

export function TranscriptPanel({
  transcript,
  partialTranscript,
}: {
  transcript: TranscriptChunk[];
  partialTranscript?: string | null;
}) {
  return (
    <Card className="flex h-full min-h-0 flex-col rounded-[28px] border-white/60 bg-white/85 p-5 shadow-[0_18px_45px_rgba(15,23,42,0.08)] backdrop-blur">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <p className="text-sm text-slate-500">实时文字稿</p>
          <h3 className="text-lg font-semibold text-slate-950">Live Transcript</h3>
        </div>
        <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-500">
          {transcript.length} 段
        </span>
      </div>

      <div className="min-h-0 space-y-3 overflow-y-auto pr-1">
        {transcript.length === 0 && !partialTranscript ? (
          <div className="rounded-2xl border border-dashed border-slate-200 px-4 py-8 text-sm leading-7 text-slate-400">
            点击开始后，这里会像实时转写一样滚动出现文字内容。
          </div>
        ) : null}

        {partialTranscript ? (
          <div className="rounded-2xl border border-violet-200 bg-violet-50 px-4 py-3">
            <div className="mb-2 flex items-center justify-between text-xs text-violet-500">
              <span>识别中</span>
              <span>partial</span>
            </div>
            <p className="text-sm leading-6 text-violet-900">{partialTranscript}</p>
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
