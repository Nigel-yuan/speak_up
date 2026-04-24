"use client";

import Image from "next/image";

import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import type { CoachProfile } from "@/lib/coach-profiles";

interface CoachEntryDialogProps {
  coachProfiles: CoachProfile[];
  selectedCoachProfileId: string;
  onSelect: (coachProfileId: string) => void;
  onConfirm: () => void;
}

export function CoachEntryDialog({
  coachProfiles,
  selectedCoachProfileId,
  onSelect,
  onConfirm,
}: CoachEntryDialogProps) {
  const activeCoach =
    coachProfiles.find((profile) => profile.id === selectedCoachProfileId) ?? coachProfiles[0] ?? null;

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-slate-950/42 px-4 py-8 backdrop-blur-[4px]">
      <Card className="w-full max-w-[1180px] overflow-hidden rounded-[36px] border-white/70 bg-white/95 shadow-[0_30px_80px_rgba(15,23,42,0.18)]">
        <div className="grid gap-0 lg:grid-cols-[minmax(0,1fr)_420px]">
          <div className="p-7">
            <div className="grid gap-4 md:grid-cols-2">
              {coachProfiles.map((profile) => {
                const active = profile.id === selectedCoachProfileId;
                return (
                  <button
                    key={profile.id}
                    type="button"
                    onClick={() => onSelect(profile.id)}
                    className={`rounded-[28px] border p-4 text-left transition ${
                      active
                        ? "border-violet-300 bg-violet-50 shadow-[0_18px_45px_rgba(109,40,217,0.12)]"
                        : "border-slate-200 bg-white hover:bg-slate-50"
                    }`}
                  >
                    <div className="relative h-48 overflow-hidden rounded-[22px] border border-slate-100 bg-slate-100">
                      <Image
                        src={profile.avatarSrc}
                        alt={profile.name}
                        fill
                        className="object-cover"
                        sizes="420px"
                      />
                    </div>
                    <div className="mt-4 flex items-center gap-2">
                      <p className="text-lg font-semibold text-slate-950">{profile.name}</p>
                      <Badge tone={active ? "positive" : "neutral"}>{profile.personaType}</Badge>
                    </div>
                    <p className="mt-3 text-sm font-semibold text-slate-800">{profile.slogan}</p>
                    <p className="mt-2 text-sm leading-6 text-slate-500">{profile.bio}</p>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="bg-[radial-gradient(circle_at_top,rgba(139,92,246,0.18),transparent_48%),linear-gradient(180deg,#faf5ff_0%,#ffffff_100%)] p-8">
            <h2 className="max-w-[360px] text-[2rem] font-semibold leading-tight tracking-tight text-slate-950">
              阁下谈吐非凡，准备选
              <span className="block">哪位“嘴替”陪你练练？</span>
            </h2>
            <p className="mt-4 max-w-[360px] text-sm leading-7 text-slate-500">
              是想在炅炅的酒窝里溺水，还是在星姐的毒舌下求生？请开始你的翻牌表演！
            </p>

            {activeCoach ? (
              <div className="mt-8 rounded-[28px] border border-violet-100 bg-white/90 p-5 shadow-[0_18px_45px_rgba(15,23,42,0.06)]">
                <div className="relative h-[300px] overflow-hidden rounded-[24px] border border-violet-100 bg-violet-50">
                  <Image
                    src={activeCoach.avatarSrc}
                    alt={activeCoach.name}
                    fill
                    className="object-cover"
                    sizes="360px"
                  />
                </div>
                <div className="mt-5 flex items-center gap-2">
                  <p className="text-xl font-semibold text-slate-950">{activeCoach.name}</p>
                  <Badge tone="neutral">{activeCoach.personaType}</Badge>
                </div>
                <p className="mt-3 text-sm font-semibold text-violet-700">{activeCoach.slogan}</p>
                <p className="mt-3 text-sm leading-7 text-slate-600">{activeCoach.bio}</p>
                <button
                  type="button"
                  onClick={onConfirm}
                  className="mt-6 inline-flex w-full items-center justify-center rounded-full bg-violet-600 px-5 py-3 text-sm font-semibold text-white shadow-[0_12px_28px_rgba(109,40,217,0.24)] transition hover:bg-violet-500"
                >
                  选定离手！
                </button>
              </div>
            ) : null}
          </div>
        </div>
      </Card>
    </div>
  );
}
