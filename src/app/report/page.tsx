"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { ReportGenerationProgress } from "@/components/report/report-generation-progress";
import { ReportRadarChart } from "@/components/report/report-radar-chart";
import { ReportSuggestions } from "@/components/report/report-suggestions";
import { ReportSummary } from "@/components/report/report-summary";
import { Button } from "@/components/ui/button";
import { useSessionResult } from "@/components/session/session-provider";

export default function ReportPage() {
  const router = useRouter();
  const { replaySessionId, report, setup } = useSessionResult();

  useEffect(() => {
    if (!report && !setup) {
      router.replace("/");
    }
  }, [report, router, setup]);

  if (!report || !setup) {
    return null;
  }

  return (
    <main className="mx-auto min-h-screen w-full max-w-7xl px-6 py-10 md:px-10">
      <div className="mb-8 flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div>
          <Link href="/" className="text-sm font-semibold text-slate-500">
            ← 返回首页
          </Link>
          <p className="mt-3 text-sm text-violet-600">
            训练报告 · {setup.language === "zh" ? "中文" : "English"}
          </p>
        </div>
        <div className="flex flex-wrap gap-3">
          {replaySessionId ? (
            <Button
              className="border border-slate-900 bg-slate-900 text-white shadow-[0_12px_24px_rgba(15,23,42,0.16)] hover:bg-slate-800"
              onClick={() => router.push(`/session/${replaySessionId}/replay`)}
              type="button"
            >
              回放复盘
            </Button>
          ) : null}
          <Button
            className="bg-slate-900 text-white shadow-[0_12px_24px_rgba(15,23,42,0.16)] hover:bg-slate-800"
            type="button"
          >
            分享报告
          </Button>
          <Button
            className="bg-violet-600 text-white shadow-[0_12px_24px_rgba(109,40,217,0.22)] hover:bg-violet-500"
            onClick={() => router.push(`/session?scenario=${setup.scenarioId}&language=${setup.language}`)}
          >
            再来一轮
          </Button>
        </div>
      </div>

      <div className="space-y-6">
        {report.status === "processing" ? (
          <ReportGenerationProgress progress={report.progress} />
        ) : null}

        <ReportSummary report={report} />

        <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr]">
          <ReportRadarChart
            metrics={report.radarMetrics}
            ready={report.sectionStatus.radar === "ready"}
            detail={report.progress.detail ?? `当前步骤：${report.progress.currentLabel}`}
          />
          <ReportSuggestions
            suggestions={report.suggestions}
            ready={report.sectionStatus.suggestions === "ready"}
            detail={report.progress.detail ?? `当前步骤：${report.progress.currentLabel}`}
          />
        </div>
      </div>
    </main>
  );
}
