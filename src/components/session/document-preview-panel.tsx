"use client";

import { useMemo } from "react";

import { Card } from "@/components/ui/card";
import type { TrainingDocumentAsset } from "@/types/session";

interface MarkdownBlock {
  id: string;
  type: "heading-1" | "heading-2" | "heading-3" | "paragraph" | "unordered-list" | "ordered-list" | "blockquote" | "code";
  lines: string[];
}

function renderInlineMarkdown(text: string) {
  const segments = text.split(/(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)/g).filter(Boolean);

  return segments.map((segment, index) => {
    if (segment.startsWith("**") && segment.endsWith("**")) {
      return <strong key={`${segment}-${index}`}>{segment.slice(2, -2)}</strong>;
    }

    if (segment.startsWith("*") && segment.endsWith("*")) {
      return <em key={`${segment}-${index}`}>{segment.slice(1, -1)}</em>;
    }

    if (segment.startsWith("`") && segment.endsWith("`")) {
      return (
        <code
          key={`${segment}-${index}`}
          className="rounded-md bg-slate-200 px-1.5 py-0.5 text-[0.95em] text-slate-800"
        >
          {segment.slice(1, -1)}
        </code>
      );
    }

    return segment;
  });
}

function parseMarkdownBlocks(source: string) {
  const lines = source.replace(/\r\n/g, "\n").split("\n");
  const blocks: MarkdownBlock[] = [];
  let paragraphBuffer: string[] = [];
  let listBuffer: { ordered: boolean; items: string[] } | null = null;
  let quoteBuffer: string[] = [];
  let inCodeBlock = false;
  let codeFenceLanguage = "";
  let codeBuffer: string[] = [];

  const flushParagraph = () => {
    if (paragraphBuffer.length === 0) {
      return;
    }

    blocks.push({
      id: `paragraph-${blocks.length}`,
      type: "paragraph",
      lines: [paragraphBuffer.join(" ")],
    });
    paragraphBuffer = [];
  };

  const flushList = () => {
    if (!listBuffer || listBuffer.items.length === 0) {
      listBuffer = null;
      return;
    }

    blocks.push({
      id: `list-${blocks.length}`,
      type: listBuffer.ordered ? "ordered-list" : "unordered-list",
      lines: listBuffer.items,
    });
    listBuffer = null;
  };

  const flushQuote = () => {
    if (quoteBuffer.length === 0) {
      return;
    }

    blocks.push({
      id: `quote-${blocks.length}`,
      type: "blockquote",
      lines: [quoteBuffer.join(" ")],
    });
    quoteBuffer = [];
  };

  const flushCode = () => {
    blocks.push({
      id: `code-${blocks.length}`,
      type: "code",
      lines: codeFenceLanguage ? [codeFenceLanguage, ...codeBuffer] : codeBuffer,
    });
    codeBuffer = [];
    codeFenceLanguage = "";
  };

  for (const rawLine of lines) {
    const line = rawLine.trimEnd();

    if (inCodeBlock) {
      if (line.startsWith("```")) {
        inCodeBlock = false;
        flushCode();
      } else {
        codeBuffer.push(rawLine);
      }
      continue;
    }

    if (line.startsWith("```")) {
      flushParagraph();
      flushList();
      flushQuote();
      inCodeBlock = true;
      codeFenceLanguage = line.slice(3).trim();
      codeBuffer = [];
      continue;
    }

    if (line.trim() === "") {
      flushParagraph();
      flushList();
      flushQuote();
      continue;
    }

    const headingMatch = line.match(/^(#{1,3})\s+(.+)$/);
    if (headingMatch) {
      flushParagraph();
      flushList();
      flushQuote();
      blocks.push({
        id: `heading-${blocks.length}`,
        type: (`heading-${headingMatch[1].length}` as MarkdownBlock["type"]),
        lines: [headingMatch[2].trim()],
      });
      continue;
    }

    const unorderedMatch = line.match(/^[-*]\s+(.+)$/);
    if (unorderedMatch) {
      flushParagraph();
      flushQuote();
      if (!listBuffer || listBuffer.ordered) {
        flushList();
        listBuffer = { ordered: false, items: [] };
      }
      listBuffer.items.push(unorderedMatch[1].trim());
      continue;
    }

    const orderedMatch = line.match(/^\d+\.\s+(.+)$/);
    if (orderedMatch) {
      flushParagraph();
      flushQuote();
      if (!listBuffer || !listBuffer.ordered) {
        flushList();
        listBuffer = { ordered: true, items: [] };
      }
      listBuffer.items.push(orderedMatch[1].trim());
      continue;
    }

    const quoteMatch = line.match(/^>\s?(.+)$/);
    if (quoteMatch) {
      flushParagraph();
      flushList();
      quoteBuffer.push(quoteMatch[1].trim());
      continue;
    }

    flushList();
    flushQuote();
    paragraphBuffer.push(line.trim());
  }

  flushParagraph();
  flushList();
  flushQuote();

  return blocks;
}

function MarkdownPreview({ source }: { source: string }) {
  const blocks = useMemo(() => parseMarkdownBlocks(source), [source]);

  return (
    <div className="mx-auto max-w-4xl space-y-5 text-slate-700">
      {blocks.map((block) => {
        switch (block.type) {
          case "heading-1":
            return <h1 key={block.id} className="text-3xl font-semibold tracking-tight text-slate-950">{renderInlineMarkdown(block.lines[0] ?? "")}</h1>;
          case "heading-2":
            return <h2 key={block.id} className="text-2xl font-semibold tracking-tight text-slate-900">{renderInlineMarkdown(block.lines[0] ?? "")}</h2>;
          case "heading-3":
            return <h3 key={block.id} className="text-xl font-semibold text-slate-900">{renderInlineMarkdown(block.lines[0] ?? "")}</h3>;
          case "unordered-list":
            return (
              <ul key={block.id} className="space-y-2 pl-5 text-[15px] leading-7 text-slate-700">
                {block.lines.map((line, index) => (
                  <li key={`${block.id}-${index}`} className="list-disc">{renderInlineMarkdown(line)}</li>
                ))}
              </ul>
            );
          case "ordered-list":
            return (
              <ol key={block.id} className="space-y-2 pl-5 text-[15px] leading-7 text-slate-700">
                {block.lines.map((line, index) => (
                  <li key={`${block.id}-${index}`} className="list-decimal">{renderInlineMarkdown(line)}</li>
                ))}
              </ol>
            );
          case "blockquote":
            return (
              <blockquote key={block.id} className="rounded-2xl border border-slate-200 bg-slate-50 px-5 py-4 text-[15px] leading-7 text-slate-600">
                {renderInlineMarkdown(block.lines[0] ?? "")}
              </blockquote>
            );
          case "code": {
            const [language, ...lines] = block.lines;
            return (
              <div key={block.id} className="overflow-hidden rounded-2xl border border-slate-200 bg-slate-950 text-slate-100 shadow-[0_18px_45px_rgba(15,23,42,0.14)]">
                {language ? (
                  <div className="border-b border-white/10 px-4 py-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">
                    {language}
                  </div>
                ) : null}
                <pre className="overflow-x-auto px-4 py-4 text-sm leading-6">
                  <code>{lines.join("\n")}</code>
                </pre>
              </div>
            );
          }
          default:
            return (
              <p key={block.id} className="text-[15px] leading-8 text-slate-700">
                {renderInlineMarkdown(block.lines[0] ?? "")}
              </p>
            );
        }
      })}
    </div>
  );
}

function PdfPreview({ objectUrl }: { objectUrl: string }) {
  return (
    <object data={objectUrl} type="application/pdf" className="h-full w-full">
      <div className="flex h-full flex-col items-center justify-center gap-3 text-center text-sm text-slate-500">
        <p>当前浏览器无法内嵌预览这份 PDF。</p>
        <a
          href={objectUrl}
          target="_blank"
          rel="noreferrer"
          className="rounded-full bg-slate-950 px-5 py-3 font-semibold text-white hover:bg-slate-800"
        >
          新窗口打开 PDF
        </a>
      </div>
    </object>
  );
}

export function DocumentPreviewPanel({
  documentAsset,
}: {
  documentAsset: TrainingDocumentAsset | null;
}) {
  return (
    <Card className="flex h-full min-h-0 flex-col overflow-hidden rounded-[28px] border-white/70 bg-[#efece3] shadow-[0_18px_45px_rgba(15,23,42,0.12)]">
      <div className="relative min-h-0 flex-1 overflow-hidden">
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top,rgba(255,255,255,0.55),transparent_30%),linear-gradient(to_bottom,rgba(255,255,255,0.32),transparent_18%)]" />
        <div className="h-full overflow-y-auto px-6 pb-6 pt-6">
          {documentAsset ? (
            <div className="mx-auto min-h-full max-w-[980px] rounded-[30px] border border-white/90 bg-white/95 p-7 shadow-[0_24px_60px_rgba(15,23,42,0.08)]">
              <div className="mb-6 border-b border-slate-200/90 pb-4">
                <p className="text-xs uppercase tracking-[0.2em] text-slate-400">Current Document</p>
                <h3 className="mt-1 truncate text-xl font-semibold text-slate-950">{documentAsset.name}</h3>
                <p className="mt-2 text-xs font-medium text-slate-500">
                  {documentAsset.kind === "pdf"
                    ? "PDF 保持原文预览，问答会使用 PDF 正文。"
                    : "Markdown 保持正文预览，问答会使用文档内容。"}
                </p>
              </div>

              <div className="min-h-0">
                {documentAsset.kind === "pdf" && documentAsset.objectUrl ? (
                  <div className="h-[calc(100vh-270px)] min-h-[560px] overflow-hidden rounded-[24px] border border-slate-200 bg-slate-50">
                    <PdfPreview objectUrl={documentAsset.objectUrl} />
                  </div>
                ) : documentAsset.markdownSource ? (
                  <MarkdownPreview source={documentAsset.markdownSource} />
                ) : (
                  <div className="rounded-2xl border border-dashed border-slate-200 px-5 py-10 text-center text-sm text-slate-500">
                    当前文档暂时没有可预览内容。
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="flex h-full items-center justify-center rounded-[28px] border border-dashed border-slate-300 bg-white/72 p-8 text-center text-sm leading-7 text-slate-500 shadow-[0_20px_50px_rgba(15,23,42,0.06)]">
              问答模式下如果没有文档材料，AI 会优先基于已讲内容来提问。
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}
