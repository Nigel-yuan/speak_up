"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { ReportGenerationProgress } from "@/components/report/report-generation-progress";
import { ReportRadarChart } from "@/components/report/report-radar-chart";
import { ReportSuggestions } from "@/components/report/report-suggestions";
import { ReportSummary } from "@/components/report/report-summary";
import { ReportPendingState } from "@/components/report/report-pending-state";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useSessionResult } from "@/components/session/session-provider";
import { getSessionReport } from "@/lib/api";
import type { SessionReport } from "@/types/report";
import type { LanguageOption, ScenarioType, SessionSetup } from "@/types/session";

const VALID_SCENARIOS = new Set<ScenarioType>(["host", "guest-sharing", "standup"]);
const VALID_LANGUAGES = new Set<LanguageOption>(["zh", "en"]);

function parseScenario(value: string | null): ScenarioType | null {
  return value && VALID_SCENARIOS.has(value as ScenarioType) ? (value as ScenarioType) : null;
}

function parseLanguage(value: string | null): LanguageOption | null {
  return value && VALID_LANGUAGES.has(value as LanguageOption) ? (value as LanguageOption) : null;
}

export default function ReportPage() {
  const router = useRouter();
  const { replaySessionId, report, setup } = useSessionResult();
  const [fallbackReport, setFallbackReport] = useState<SessionReport | null>(null);
  const [fallbackLoadError, setFallbackLoadError] = useState<string | null>(null);
  const routeState = useMemo<{
    ready: boolean;
    sessionId: string | null;
    scenarioId: ScenarioType | null;
    language: LanguageOption | null;
  }>(() => {
    if (typeof window === "undefined") {
      return {
        ready: false,
        sessionId: null,
        scenarioId: null,
        language: null,
      };
    }

    const searchParams = new URLSearchParams(window.location.search);
    return {
      ready: true,
      sessionId: searchParams.get("sessionId"),
      scenarioId: parseScenario(searchParams.get("scenario")),
      language: parseLanguage(searchParams.get("language")),
    };
  }, []);

  const activeReport = report ?? fallbackReport;
  const fallbackSetup = useMemo<SessionSetup | null>(() => {
    if (!routeState.scenarioId || !routeState.language) {
      return null;
    }
    return {
      scenarioId: routeState.scenarioId,
      language: routeState.language,
    };
  }, [routeState.language, routeState.scenarioId]);
  const activeSetup = setup ?? fallbackSetup;
  const activeReplaySessionId = replaySessionId ?? routeState.sessionId;
  const replayHref = activeReplaySessionId && activeSetup
    ? `/session/${activeReplaySessionId}/replay`
    : null;

  useEffect(() => {
    if (!routeState.ready) {
      return;
    }
    if (!report && !setup && !routeState.sessionId) {
      router.replace("/");
    }
  }, [report, routeState.ready, routeState.sessionId, router, setup]);

  useEffect(() => {
    if (report || !routeState.ready || !routeState.sessionId) {
      return;
    }

    let active = true;
    void getSessionReport(routeState.sessionId)
      .then((nextReport) => {
        if (!active) {
          return;
        }
        setFallbackReport(nextReport);
        setFallbackLoadError(null);
      })
      .catch((loadError) => {
        if (!active) {
          return;
        }
        setFallbackLoadError(loadError instanceof Error ? loadError.message : "报告加载失败");
      });

    return () => {
      active = false;
    };
  }, [report, routeState.ready, routeState.sessionId]);

  useEffect(() => {
    if (report || !routeState.sessionId || fallbackReport?.status !== "processing") {
      return;
    }

    const timer = window.setInterval(() => {
      void getSessionReport(routeState.sessionId!)
        .then((nextReport) => {
          setFallbackReport(nextReport);
          setFallbackLoadError(null);
        })
        .catch(() => undefined);
    }, 1200);

    return () => {
      window.clearInterval(timer);
    };
  }, [fallbackReport?.status, report, routeState.sessionId]);

  if ((!activeReport || !activeSetup) && !routeState.ready) {
    return null;
  }

  if (fallbackLoadError && !activeReport) {
    return (
      <main className="mx-auto min-h-screen w-full max-w-7xl px-6 py-10 md:px-10">
        <Card className="px-6 py-5">
          <ReportPendingState
            label="报告加载失败"
            detail={fallbackLoadError}
          />
        </Card>
      </main>
    );
  }

  if (!activeReport || !activeSetup) {
    return (
      <main className="mx-auto min-h-screen w-full max-w-7xl px-6 py-10 md:px-10">
        <Card className="px-6 py-5">
          <ReportPendingState
            label="报告加载中..."
            detail="正在恢复这次会话的报告内容。"
          />
        </Card>
      </main>
    );
  }

  return (
    <main className="mx-auto min-h-screen w-full max-w-7xl px-6 py-10 md:px-10">
      <div className="mb-8 flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div>
          <Link href="/" className="text-sm font-semibold text-slate-500">
            ← 返回首页
          </Link>
          <p className="mt-3 text-sm text-violet-600">
            训练报告 · {activeSetup.language === "zh" ? "中文" : "English"}
          </p>
        </div>
        <div className="flex flex-wrap gap-3">
          {replayHref ? (
            <Button
              className="border border-slate-900 bg-slate-900 text-white shadow-[0_12px_24px_rgba(15,23,42,0.16)] hover:bg-slate-800"
              onClick={() => router.push(replayHref)}
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
            onClick={() => router.push(`/session?scenario=${activeSetup.scenarioId}&language=${activeSetup.language}`)}
          >
            再来一轮
          </Button>
        </div>
      </div>

      <div className="space-y-6">
        {activeReport.status === "processing" ? (
          <ReportGenerationProgress progress={activeReport.progress} />
        ) : null}

        {activeReport.status === "processing" && replayHref ? (
          <Card className="border-violet-100 bg-violet-50/70 p-5 shadow-[0_12px_30px_rgba(109,40,217,0.08)]">
            <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
              <div>
                <p className="text-sm font-semibold text-violet-700">报告还在生成</p>
                <p className="mt-2 text-sm leading-7 text-slate-600">
                  你可以先去看回放复盘，先看视频、文字稿和 AI Live Coach 时间线，用这段时间缓冲报告生成；报告完成后再回来查看完整结果。
                </p>
              </div>
              <Button
                className="bg-violet-600 text-white shadow-[0_12px_24px_rgba(109,40,217,0.18)] hover:bg-violet-500"
                onClick={() => router.push(replayHref)}
                type="button"
              >
                先去回放复盘
              </Button>
            </div>
          </Card>
        ) : null}

        <ReportSummary report={activeReport} />

        <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr]">
          <ReportRadarChart
            metrics={activeReport.radarMetrics}
            ready={activeReport.sectionStatus.radar === "ready"}
            detail={activeReport.progress.detail ?? `当前步骤：${activeReport.progress.currentLabel}`}
          />
          <ReportSuggestions
            suggestions={activeReport.suggestions}
            ready={activeReport.sectionStatus.suggestions === "ready"}
            detail={activeReport.progress.detail ?? `当前步骤：${activeReport.progress.currentLabel}`}
          />
        </div>
      </div>
    </main>
  );
}
