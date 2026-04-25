"use client";

import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { ReportGenerationProgress } from "@/components/report/report-generation-progress";
import { ReportPendingState } from "@/components/report/report-pending-state";
import { ReportRadarChart } from "@/components/report/report-radar-chart";
import { ReportSuggestions } from "@/components/report/report-suggestions";
import { ReportSummary } from "@/components/report/report-summary";
import { useSessionResult } from "@/components/session/session-provider";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { getCoachProfileById, getDefaultCoachProfileId } from "@/lib/coach-profiles";
import { getSessionReport } from "@/lib/api";
import type { SessionReport } from "@/types/report";
import type { CoachProfileId, ScenarioType, SessionSetup } from "@/types/session";

export interface ReportRouteState {
  sessionId: string | null;
  scenarioId: ScenarioType | null;
  coachProfileId: CoachProfileId | null;
}

function ReportProcessingOverview() {
  return (
    <Card className="overflow-hidden border-violet-100 bg-white/90 p-5 shadow-[0_16px_40px_rgba(109,40,217,0.08)] md:p-6">
      <div className="max-w-3xl">
        <p className="text-sm font-semibold uppercase tracking-[0.2em] text-violet-600">报告生成中</p>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight text-slate-950 md:text-3xl">
          报告正在整理，完成后会自动显示
        </h1>
        <p className="mt-3 text-sm leading-7 text-slate-600">
          生成时间可能会比较长。你可以留在这里等待，也可以先去回放复盘。
        </p>
      </div>

      <div className="mt-5 grid gap-3 md:grid-cols-3">
        {[
          ["总结重点", "提炼本轮表现中的关键亮点和主要问题。"],
          ["能力画像", "整理表达、内容、节奏等维度的综合判断。"],
          ["下一步建议", "生成下一轮练习最值得优先打磨的动作。"],
        ].map(([title, detail]) => (
          <div key={title} className="rounded-2xl border border-violet-100 bg-violet-50/55 px-4 py-3">
            <div className="h-1.5 w-14 overflow-hidden rounded-full bg-violet-100">
              <div className="report-waiting-line h-full w-1/2 rounded-full bg-violet-500" />
            </div>
            <p className="mt-3 text-sm font-semibold text-slate-900">{title}</p>
            <p className="mt-2 text-sm leading-6 text-slate-500">{detail}</p>
          </div>
        ))}
      </div>
    </Card>
  );
}

export function ReportClient({ initialRouteState }: { initialRouteState: ReportRouteState }) {
  const router = useRouter();
  const { replaySessionId, report, setup } = useSessionResult();
  const [fallbackReport, setFallbackReport] = useState<SessionReport | null>(null);
  const [fallbackLoadError, setFallbackLoadError] = useState<string | null>(null);
  const [showReplayHint, setShowReplayHint] = useState(true);
  const { coachProfileId, scenarioId, sessionId } = initialRouteState;

  const activeReport = report ?? fallbackReport;
  const fallbackSetup = useMemo<SessionSetup>(() => {
    return {
      scenarioId: scenarioId ?? "general",
      language: "zh",
      coachProfileId: coachProfileId ?? getDefaultCoachProfileId(),
    };
  }, [coachProfileId, scenarioId]);
  const activeSetup = setup ?? fallbackSetup;
  const activeCoachProfileId =
    setup?.coachProfileId ??
    coachProfileId ??
    activeReport?.coachProfileId ??
    getDefaultCoachProfileId();
  const activeCoachProfile = getCoachProfileById(activeCoachProfileId);
  const activeReplaySessionId = replaySessionId ?? sessionId;
  const replayHref = activeReplaySessionId
    ? `/session/${activeReplaySessionId}/replay?coach=${activeCoachProfileId}`
    : null;
  const reportProcessing = activeReport?.status === "processing";

  useEffect(() => {
    if (!report && !setup && !sessionId) {
      router.replace("/");
    }
  }, [report, router, sessionId, setup]);

  useEffect(() => {
    if (report || !sessionId) {
      return;
    }

    let active = true;
    void getSessionReport(sessionId)
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
  }, [report, sessionId]);

  useEffect(() => {
    if (report || !sessionId || fallbackReport?.status !== "processing") {
      return;
    }

    const timer = window.setInterval(() => {
      void getSessionReport(sessionId)
        .then((nextReport) => {
          setFallbackReport(nextReport);
          setFallbackLoadError(null);
        })
        .catch(() => undefined);
    }, 1200);

    return () => {
      window.clearInterval(timer);
    };
  }, [fallbackReport?.status, report, sessionId]);

  useEffect(() => {
    if (!reportProcessing || !replayHref || !showReplayHint) {
      return;
    }

    const timer = window.setTimeout(() => setShowReplayHint(false), 9000);
    return () => {
      window.clearTimeout(timer);
    };
  }, [reportProcessing, replayHref, showReplayHint]);

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
    <main className="mx-auto min-h-screen w-full max-w-[1440px] px-4 py-5 text-slate-950 md:px-6 lg:px-8">
      <div className="mb-4 rounded-[26px] border border-white/80 bg-white/90 px-4 py-3 shadow-[0_18px_45px_rgba(15,23,42,0.06)]">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex min-w-0 flex-col gap-3 md:flex-row md:items-center">
            <Link
              href="/"
              className="inline-flex w-fit items-center justify-center rounded-full border border-slate-300 bg-slate-100 px-4 py-2 text-sm font-semibold text-slate-950 shadow-[0_8px_18px_rgba(15,23,42,0.06)] transition hover:border-slate-400 hover:bg-slate-200"
            >
              ← 返回首页
            </Link>
            {activeCoachProfile ? (
              <div className="inline-flex min-w-0 items-center gap-3 rounded-[20px] border border-violet-100 bg-white/90 px-3 py-2 shadow-[0_12px_28px_rgba(15,23,42,0.05)]">
                <div className="relative h-11 w-11 shrink-0 overflow-hidden rounded-[15px] border border-violet-100 bg-violet-50">
                  <Image
                    src={activeCoachProfile.avatarSrc}
                    alt={activeCoachProfile.name}
                    fill
                    className="object-cover"
                    sizes="44px"
                  />
                </div>
                <div className="min-w-0">
                  <p className="text-xs font-semibold uppercase tracking-[0.16em] text-violet-500">AI Coach</p>
                  <p className="truncate text-sm font-semibold text-slate-950">
                    {activeCoachProfile.name}
                    <span className="ml-2 font-medium text-slate-500">{activeCoachProfile.personaType}</span>
                  </p>
                </div>
              </div>
            ) : null}
          </div>
          <div className="flex flex-wrap justify-start gap-2 lg:justify-end">
            {replayHref ? (
              <div className="relative">
                <Button
                  className={
                    reportProcessing
                      ? "report-replay-cta relative overflow-hidden border border-violet-500 bg-violet-600 text-white shadow-[0_16px_34px_rgba(109,40,217,0.28)] hover:bg-violet-500"
                      : "border border-slate-900 bg-slate-900 text-white shadow-[0_12px_24px_rgba(15,23,42,0.16)] hover:bg-slate-800"
                  }
                  onClick={() => router.push(replayHref)}
                  type="button"
                >
                  {reportProcessing ? "先去回放复盘" : "回放复盘"}
                </Button>
                {reportProcessing && replayHref && showReplayHint ? (
                  <div className="report-replay-hint absolute right-0 top-[calc(100%+10px)] z-20 w-[280px] rounded-2xl border border-violet-100 bg-white px-4 py-3 text-sm leading-6 text-slate-600 shadow-[0_18px_45px_rgba(15,23,42,0.14)]">
                    报告生成可能需要一会儿，可以先去回放复盘。
                  </div>
                ) : null}
              </div>
            ) : null}
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
      </div>

      <div className="space-y-4">
        {reportProcessing ? (
          <ReportGenerationProgress progress={activeReport.progress} />
        ) : null}

        {reportProcessing ? (
          <ReportProcessingOverview />
        ) : (
          <>
            <ReportSummary report={activeReport} />

            <div className="grid gap-4 lg:grid-cols-[1.16fr_0.84fr]">
              <ReportRadarChart
                metrics={activeReport.radarMetrics}
                ready={activeReport.sectionStatus.radar === "ready"}
                detail="完整报告生成完成后，这里会自动更新。"
              />
              <ReportSuggestions
                suggestions={activeReport.suggestions}
                ready={activeReport.sectionStatus.suggestions === "ready"}
                detail="完整报告生成完成后，这里会自动更新。"
              />
            </div>
          </>
        )}
      </div>
    </main>
  );
}
