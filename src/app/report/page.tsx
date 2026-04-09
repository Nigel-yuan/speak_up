"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { HistoryComparison } from "@/components/report/history-comparison";
import { ReportRadarChart } from "@/components/report/report-radar-chart";
import { ReportSuggestions } from "@/components/report/report-suggestions";
import { ReportSummary } from "@/components/report/report-summary";
import { useSessionResult } from "@/components/session/session-provider";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

export default function ReportPage() {
  const router = useRouter();
  const { history, report, reportLoading, setup } = useSessionResult();

  useEffect(() => {
    if (!reportLoading && !report && !setup) {
      router.replace("/");
    }
  }, [report, reportLoading, router, setup]);

  if (reportLoading) {
    return (
      <main className="mx-auto flex min-h-screen w-full max-w-7xl items-center justify-center px-6 py-10 md:px-10">
        <Card className="px-6 py-5 text-base font-medium text-slate-600">报告生成中...</Card>
      </main>
    );
  }

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
        <ReportSummary report={report} />

        <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr]">
          <ReportRadarChart metrics={report.radarMetrics} />
          <ReportSuggestions suggestions={report.suggestions} />
        </div>

        <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr]">
          <HistoryComparison history={history.filter((item) => item.scenarioId === setup.scenarioId)} />
          <Card className="p-6">
            <p className="text-sm text-slate-500">进步趋势</p>
            <h3 className="mt-1 text-xl font-semibold text-slate-950">和历史记录相比</h3>
            <p className="mt-4 text-base leading-8 text-slate-600">{report.comparisonSummary}</p>
          </Card>
        </div>
      </div>
    </main>
  );
}
