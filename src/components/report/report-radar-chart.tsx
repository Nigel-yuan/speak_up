"use client";

import {
  PolarAngleAxis,
  PolarGrid,
  Radar,
  RadarChart,
  ResponsiveContainer,
} from "recharts";

import { Card } from "@/components/ui/card";
import type { RadarMetric } from "@/types/report";
import { ReportPendingState } from "@/components/report/report-pending-state";

export function ReportRadarChart({
  metrics,
  ready,
  detail,
}: {
  metrics: RadarMetric[];
  ready: boolean;
  detail?: string;
}) {
  return (
    <Card className="p-6">
      <div className="mb-4">
        <p className="text-sm text-slate-500">能力雷达图</p>
        <h3 className="text-xl font-semibold text-slate-950">核心能力分布</h3>
      </div>

      {ready && metrics.length > 0 ? (
        <div className="h-[320px] w-full">
          <ResponsiveContainer>
            <RadarChart data={metrics} outerRadius="76%">
              <PolarGrid stroke="#cbd5e1" />
              <PolarAngleAxis dataKey="subject" tick={{ fill: "#475569", fontSize: 12 }} />
              <Radar
                dataKey="score"
                stroke="#7c3aed"
                fill="#8b5cf6"
                fillOpacity={0.35}
                strokeWidth={2}
              />
            </RadarChart>
          </ResponsiveContainer>
        </div>
      ) : ready ? (
        <div className="flex h-[320px] items-center justify-center rounded-2xl border border-dashed border-slate-200 px-6">
          <p className="text-sm text-slate-500">能力雷达图暂未生成。</p>
        </div>
      ) : (
        <div className="flex h-[320px] items-center justify-center rounded-2xl border border-dashed border-slate-200 px-6">
          <ReportPendingState
            label="AI 分析中"
            detail={detail ?? "完整报告生成完成后，这里会自动更新。"}
            center
          />
        </div>
      )}
    </Card>
  );
}
