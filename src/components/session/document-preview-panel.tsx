"use client";

import { DocumentAssetPreview } from "@/components/session/document-viewer";
import { Card } from "@/components/ui/card";
import type { TrainingDocumentAsset } from "@/types/session";

export function DocumentPreviewPanel({
  documentAsset,
}: {
  documentAsset: TrainingDocumentAsset | null;
}) {
  return (
    <Card className="flex h-full min-h-0 flex-col overflow-hidden rounded-[28px] border-white/70 bg-white shadow-[0_18px_45px_rgba(15,23,42,0.08)]">
      <div className="relative min-h-0 flex-1 overflow-hidden">
        <div className="h-full overflow-y-auto p-3">
          {documentAsset ? (
            <div className="mx-auto flex h-full max-w-[1320px] flex-col rounded-[30px] border border-slate-100 bg-white p-3 shadow-[0_24px_60px_rgba(15,23,42,0.06)]">
              <DocumentAssetPreview documentAsset={documentAsset} />
            </div>
          ) : (
            <div className="flex h-full items-center justify-center rounded-[28px] border border-dashed border-slate-200 bg-white p-8 text-center text-sm leading-7 text-slate-500 shadow-[0_20px_50px_rgba(15,23,42,0.06)]">
              问答模式下如果没有文档材料，AI 会优先基于已讲内容来提问。
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}
