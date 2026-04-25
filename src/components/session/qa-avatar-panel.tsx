"use client";

import Image from "next/image";
import { useEffect, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import type { QAPhase } from "@/types/session";

function getPhaseLabel(phase: QAPhase) {
  switch (phase) {
    case "preparing_context":
      return "整理上下文";
    case "ai_asking":
      return "AI 提问中";
    case "user_answering":
      return "等待回答";
    case "evaluating_answer":
      return "正在评价";
    case "ready_next_turn":
      return "可进入下一题";
    case "completed":
      return "问答结束";
    default:
      return "待命";
  }
}

function getPhaseTone(phase: QAPhase) {
  switch (phase) {
    case "ai_asking":
    case "user_answering":
      return "positive" as const;
    case "evaluating_answer":
      return "warning" as const;
    default:
      return "neutral" as const;
  }
}

interface QAAvatarPanelProps {
  audioUrl: string | null;
  autoPlayAudio: boolean;
  avatarSrc: string;
  phase: QAPhase;
  questionText: string | null;
  speaking: boolean;
  turnId: string | null;
  onAudioPlaybackEnded?: (turnId: string) => void;
  onAudioPlaybackStarted?: (turnId: string) => void;
  onSpeakingChange: (speaking: boolean) => void;
}

export function QAAvatarPanel({
  audioUrl,
  autoPlayAudio,
  avatarSrc,
  phase,
  questionText,
  speaking,
  turnId,
  onAudioPlaybackEnded,
  onAudioPlaybackStarted,
  onSpeakingChange,
}: QAAvatarPanelProps) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [blockedAudioUrl, setBlockedAudioUrl] = useState<string | null>(null);
  const playbackBlocked = !!audioUrl && blockedAudioUrl === audioUrl;

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio || !audioUrl || !autoPlayAudio) {
      return;
    }

    audio.load();
    void audio
      .play()
      .then(() => {
        setBlockedAudioUrl((current) => (current === audioUrl ? null : current));
      })
      .catch(() => {
        setBlockedAudioUrl(audioUrl);
        onSpeakingChange(false);
      });
  }, [audioUrl, autoPlayAudio, onSpeakingChange]);

  return (
    <Card className="relative flex h-full min-h-0 flex-col overflow-hidden rounded-[28px] border-white/70 bg-[#121827] text-white shadow-[0_22px_55px_rgba(15,23,42,0.22)]">
      {audioUrl ? (
        <audio
          ref={audioRef}
          key={audioUrl}
          className="hidden"
          onEnded={() => {
            onSpeakingChange(false);
            if (turnId) {
              onAudioPlaybackEnded?.(turnId);
            }
          }}
          onError={() => {
            onSpeakingChange(false);
            if (turnId) {
              onAudioPlaybackEnded?.(turnId);
            }
          }}
          onPause={() => onSpeakingChange(false)}
          onPlay={() => {
            onSpeakingChange(true);
            if (turnId) {
              onAudioPlaybackStarted?.(turnId);
            }
          }}
          src={audioUrl}
        />
      ) : null}

      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top,rgba(248,250,252,0.18),transparent_32%),linear-gradient(180deg,rgba(99,102,241,0.1),transparent_28%)]" />

      <div className="relative min-h-0 flex-1 px-5 pb-5 pt-5">
        <div className="flex h-full min-h-0 flex-col gap-4">
          <div
            className={`relative overflow-hidden rounded-[28px] border ${
              speaking ? "border-sky-300/50 shadow-[0_0_0_1px_rgba(125,211,252,0.22)]" : "border-white/10"
            } bg-gradient-to-b from-slate-800 to-slate-950 px-4 py-5 transition`}
          >
            <div className="relative mx-auto aspect-[4/5] max-h-[236px] overflow-hidden rounded-[24px] border border-white/10 bg-[linear-gradient(180deg,#334155_0%,#111827_100%)]">
              <div className="absolute right-3 top-3 z-10">
                <Badge className="shadow-[0_8px_20px_rgba(15,23,42,0.22)]" tone={getPhaseTone(phase)}>
                  {getPhaseLabel(phase)}
                </Badge>
              </div>
              <Image
                src={avatarSrc}
                alt="AI coach avatar"
                width={640}
                height={800}
                className="h-full w-full object-cover"
                priority={false}
              />
            </div>

            {audioUrl ? (
              <div className="mt-3 flex justify-end">
                <button
                  type="button"
                  onClick={() => {
                    const audio = audioRef.current;
                    if (!audio) {
                      return;
                    }
                    void audio
                      .play()
                      .then(() => setBlockedAudioUrl(null))
                      .catch(() => setBlockedAudioUrl(audioUrl));
                  }}
                  className="rounded-full bg-sky-400 px-3 py-1 text-xs font-semibold text-slate-950"
                >
                  {playbackBlocked ? "继续播放" : "重播提问"}
                </button>
              </div>
            ) : null}

          </div>

          <div className="min-h-0 space-y-3">
            <div className="rounded-[24px] border border-slate-700/70 bg-slate-950/72 px-4 py-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]">
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Current Question</p>
              <p className="mt-3 text-sm font-medium leading-7 text-slate-200">
                {questionText ?? "开启问答后，AI 会基于文档或已讲内容主动提问。"}
              </p>
            </div>
          </div>
        </div>
      </div>
    </Card>
  );
}
