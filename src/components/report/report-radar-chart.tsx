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

export function ReportRadarChart({ metrics }: { metrics: RadarMetric[] }) {
  return (
    <Card className="p-6">
      <div className="mb-4">
        <p className="text-sm text-slate-500">能力雷达图</p>
        <h3 className="text-xl font-semibold text-slate-950">核心能力分布</h3>
      </div>

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
    </Card>
  );
}
