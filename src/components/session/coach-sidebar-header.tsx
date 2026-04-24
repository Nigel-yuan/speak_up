"use client";

import Image from "next/image";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import type { CoachProfile } from "@/lib/coach-profiles";

interface CoachSidebarHeaderProps {
  coachLocked: boolean;
  coachProfile: CoachProfile | null;
  coachProfiles: CoachProfile[];
  isRunning: boolean;
  onCoachProfileChange: (coachProfileId: string) => void;
}

export function CoachSidebarHeader({
  coachLocked,
  coachProfile,
  coachProfiles,
  isRunning,
  onCoachProfileChange,
}: CoachSidebarHeaderProps) {
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <Card className="relative z-30 overflow-visible rounded-[28px] border-white/60 bg-white/88 p-4 shadow-[0_18px_45px_rgba(15,23,42,0.08)] backdrop-blur">
      <div className="flex items-center gap-3">
        <div className="relative h-16 w-16 overflow-hidden rounded-[20px] border border-violet-100 bg-violet-50">
          {coachProfile ? (
            <Image
              src={coachProfile.avatarSrc}
              alt={coachProfile.name}
              fill
              className="object-cover"
              sizes="64px"
            />
          ) : null}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <p className="truncate text-base font-semibold text-slate-950">
              {coachProfile?.name ?? "AI 教练"}
            </p>
            {coachProfile ? <Badge tone="neutral">{coachProfile.personaType}</Badge> : null}
          </div>
          <p
            className={`mt-2 truncate text-sm font-semibold leading-6 text-slate-900 ${
              isRunning ? "coach-status-shimmer" : ""
            }`}
          >
            {coachProfile?.liveStatus ?? "教练正在认真倾听..."}
          </p>
        </div>
        <button
          type="button"
          disabled={coachLocked}
          onClick={() => setMenuOpen((value) => !value)}
          className="rounded-full border border-slate-200 bg-slate-50 px-3 py-2 text-xs font-semibold text-slate-700 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {coachLocked ? "问答中已锁定" : "切换教练"}
        </button>
      </div>

      {menuOpen && !coachLocked ? (
        <div className="absolute inset-x-4 top-[calc(100%-6px)] z-[140] mt-3 grid gap-2 rounded-[24px] border border-white/75 bg-white/82 p-3 shadow-[0_24px_60px_rgba(15,23,42,0.18)] backdrop-blur-xl">
          {coachProfiles.map((profile) => (
            <button
              key={profile.id}
              type="button"
              onClick={() => {
                onCoachProfileChange(profile.id);
                setMenuOpen(false);
              }}
              className={`flex items-center gap-3 rounded-[20px] border px-3 py-3 text-left transition ${
                coachProfile?.id === profile.id
                  ? "border-violet-200 bg-violet-50"
                  : "border-slate-200 bg-slate-50 hover:bg-slate-100"
              }`}
            >
              <div className="relative h-12 w-12 overflow-hidden rounded-[16px] border border-white bg-white">
                <Image
                  src={profile.avatarSrc}
                  alt={profile.name}
                  fill
                  className="object-cover"
                  sizes="48px"
                />
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold text-slate-900">{profile.name}</p>
                <p className="mt-1 truncate text-xs text-slate-500">{profile.slogan}</p>
              </div>
            </button>
          ))}
        </div>
      ) : null}
    </Card>
  );
}
