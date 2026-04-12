import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import type { LiveInsight, PoseDebugState, PoseSnapshot } from "@/types/session";

function formatValue(value: number | null | undefined, digits = 2) {
  return Number.isFinite(value ?? Number.NaN) ? (value as number).toFixed(digits) : "--";
}

export function LiveAnalysisPanel({
  currentInsight,
  insights,
  lastPoseSnapshotAt,
  latestPoseSnapshot,
  poseDebug,
  poseDebugEnabled,
  poseSnapshotCount,
}: {
  currentInsight: LiveInsight | null;
  insights: LiveInsight[];
  lastPoseSnapshotAt?: number | null;
  latestPoseSnapshot?: PoseSnapshot | null;
  poseDebug?: PoseDebugState | null;
  poseDebugEnabled?: boolean;
  poseSnapshotCount?: number;
}) {
  return (
    <Card className="flex h-full min-h-0 flex-col rounded-[28px] border-white/60 bg-white/85 p-5 shadow-[0_18px_45px_rgba(15,23,42,0.08)] backdrop-blur">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <p className="text-sm text-slate-500">同步分析</p>
          <h3 className="text-lg font-semibold text-slate-950">AI Live Coach</h3>
        </div>
        <Badge tone={currentInsight?.tone ?? "neutral"}>实时观察</Badge>
      </div>

      <div className="rounded-2xl bg-slate-950 px-4 py-4 text-white">
        <p className="text-sm font-semibold text-slate-100">
          {currentInsight?.title ?? "等待演讲开始"}
        </p>
        <p className="mt-2 text-sm leading-6 text-slate-300">
          {currentInsight?.detail ?? "AI 会根据视频状态与文字稿，持续给出即时反馈。"}
        </p>
      </div>

      {poseDebugEnabled ? (
        <div className="mt-4 rounded-2xl border border-sky-100 bg-sky-50/80 px-4 py-4 text-slate-700">
          <div className="mb-3 flex items-center justify-between">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-sky-700">Pose Debug · Server</p>
            <Badge tone={poseDebug?.selectedRuleTone ?? "neutral"}>
              {poseDebug?.selectedRuleKey ?? "waiting"}
            </Badge>
          </div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs leading-5">
            <span>frontend snapshots</span>
            <span className="text-right">{poseSnapshotCount ?? 0}</span>
            <span>last sent</span>
            <span className="text-right">{lastPoseSnapshotAt ? new Date(lastPoseSnapshotAt).toLocaleTimeString() : "--"}</span>
            <span>selected rule</span>
            <span className="text-right">{poseDebug?.selectedRuleTitle ?? "--"}</span>
            <span>close-up mode</span>
            <span className="text-right">{poseDebug?.closeUpMode ? "yes" : "no"}</span>
            <span>body ratio</span>
            <span className="text-right">{formatValue(poseDebug?.bodyPresenceRatio)}</span>
            <span>face ratio</span>
            <span className="text-right">{formatValue(poseDebug?.faceVisibilityRatio)}</span>
            <span>hands ratio</span>
            <span className="text-right">{formatValue(poseDebug?.handsVisibilityRatio)}</span>
            <span>shoulder ratio</span>
            <span className="text-right">{formatValue(poseDebug?.shoulderVisibilityRatio)}</span>
            <span>hip ratio</span>
            <span className="text-right">{formatValue(poseDebug?.hipVisibilityRatio)}</span>
            <span>body scale</span>
            <span className="text-right">{formatValue(poseDebug?.averageBodyScale, 3)}</span>
            <span>center offset</span>
            <span className="text-right">{formatValue(poseDebug?.averageCenterOffsetX, 3)}</span>
            <span>shoulder tilt</span>
            <span className="text-right">{formatValue(poseDebug?.averageShoulderTiltDeg, 1)}°</span>
            <span>torso tilt</span>
            <span className="text-right">{formatValue(poseDebug?.averageTorsoTiltDeg, 1)}°</span>
            <span>gesture</span>
            <span className="text-right">{formatValue(poseDebug?.averageGestureActivity)}</span>
            <span>stability</span>
            <span className="text-right">{formatValue(poseDebug?.averageStabilityScore)}</span>
            <span>latest local mode</span>
            <span className="text-right">
              {latestPoseSnapshot?.shoulderVisible
                ? latestPoseSnapshot.hipVisible
                  ? "full-body"
                  : "upper-body"
                : "missing"}
            </span>
          </div>
        </div>
      ) : null}

      <div className="mt-4 min-h-0 space-y-3 overflow-y-auto pr-1">
        {insights.map((insight) => (
          <div key={insight.id} className="rounded-2xl border border-slate-200 px-4 py-3">
            <div className="mb-2 flex items-center justify-between">
              <p className="text-sm font-semibold text-slate-700">{insight.title}</p>
              <Badge tone={insight.tone}>{insight.tone}</Badge>
            </div>
            <p className="text-sm leading-6 text-slate-500">{insight.detail}</p>
          </div>
        ))}
      </div>
    </Card>
  );
}
