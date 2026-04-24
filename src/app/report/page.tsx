"use client";

import Image from "next/image";
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
import { getCoachProfileById, getDefaultCoachProfileId, isCoachProfileId } from "@/lib/coach-profiles";
import { getSessionReport } from "@/lib/api";
import type { SessionReport } from "@/types/report";
import type { ScenarioType, SessionSetup } from "@/types/session";

const VALID_SCENARIOS = new Set<ScenarioType>(["general", "host", "guest-sharing", "standup"]);

function parseScenario(value: string | null): ScenarioType | null {
  return value && VALID_SCENARIOS.has(value as ScenarioType) ? (value as ScenarioType) : null;
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
    coachProfileId: string | null;
  }>(() => {
    if (typeof window === "undefined") {
      return {
        ready: false,
        sessionId: null,
        scenarioId: null,
        coachProfileId: null,
      };
    }

    const searchParams = new URLSearchParams(window.location.search);
    const coachProfileId = searchParams.get("coach");
    return {
      ready: true,
      sessionId: searchParams.get("sessionId"),
      scenarioId: parseScenario(searchParams.get("scenario")),
      coachProfileId: isCoachProfileId(coachProfileId) ? coachProfileId : null,
    };
  }, []);

  const activeReport = report ?? fallbackReport;
  const fallbackSetup = useMemo<SessionSetup>(() => {
    return {
      scenarioId: routeState.scenarioId ?? "general",
      language: "zh",
      coachProfileId: routeState.coachProfileId ?? getDefaultCoachProfileId(),
    };
  }, [routeState.coachProfileId, routeState.scenarioId]);
  const activeSetup = setup ?? fallbackSetup;
  const activeCoachProfileId =
    activeSetup?.coachProfileId ??
    routeState.coachProfileId ??
    activeReport?.coachProfileId ??
    getDefaultCoachProfileId();
  const activeCoachProfile = getCoachProfileById(activeCoachProfileId);
  const activeReplaySessionId = replaySessionId ?? routeState.sessionId;
  const replayHref = activeReplaySessionId
    ? `/session/${activeReplaySessionId}/replay?coach=${activeCoachProfileId}`
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

  if (!activeReport) {
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
          <p className="mt-3 text-sm text-violet-600">训练报告</p>
          {activeCoachProfile ? (
            <div className="mt-4 inline-flex items-center gap-3 rounded-[24px] border border-violet-100 bg-white/90 px-4 py-3 shadow-[0_14px_34px_rgba(15,23,42,0.06)]">
              <div className="relative h-14 w-14 overflow-hidden rounded-[18px] border border-violet-100 bg-violet-50">
                <Image
                  src={activeCoachProfile.avatarSrc}
                  alt={activeCoachProfile.name}
                  fill
                  className="object-cover"
                  sizes="56px"
                />
              </div>
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.2em] text-violet-500">AI Coach</p>
                <p className="mt-1 text-base font-semibold text-slate-950">
                  {activeCoachProfile.name}
                  <span className="ml-2 text-sm font-medium text-slate-500">{activeCoachProfile.personaType}</span>
                </p>
                <p className="mt-1 text-sm text-slate-500">{activeCoachProfile.slogan}</p>
              </div>
            </div>
          ) : null}
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
            onClick={() =>
              router.push(
                `/session?scenario=${activeSetup.scenarioId}&coach=${activeCoachProfileId}`,
              )
            }
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
