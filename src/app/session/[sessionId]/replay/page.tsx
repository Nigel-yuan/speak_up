"use client";

import Link from "next/link";
import { use, useEffect, useMemo, useRef, useState } from "react";

import { getSessionReplay } from "@/lib/api";
import type { SessionReplay, TranscriptChunk } from "@/types/session";
import { Card } from "@/components/ui/card";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

function resolveMediaUrl(mediaUrl: string | null) {
  if (!mediaUrl) {
    return null;
  }

  if (mediaUrl.startsWith("http")) {
    return mediaUrl;
  }

  return `${API_BASE_URL}${mediaUrl}`;
}

function findActiveTranscript(transcript: TranscriptChunk[], currentTime: number) {
  const currentMs = currentTime * 1000;
  return transcript.find((item) => currentMs >= item.startMs && currentMs <= item.endMs)?.id ?? transcript.at(-1)?.id ?? null;
}

function buildDemoReplay(sessionId: string): SessionReplay {
  return {
    sessionId,
    scenarioId: "host",
    language: "zh",
    mediaUrl: null,
    mediaType: null,
    transcript: [
      {
        id: "demo-1",
        speaker: "user",
        text: "大家好，今天我想用三分钟介绍一下这个项目目前的进展。",
        timestampLabel: "00:03",
        startMs: 3000,
        endMs: 7000,
      },
      {
        id: "demo-2",
        speaker: "user",
        text: "先讲结果，再讲过程，最后我会说明接下来的风险和计划。",
        timestampLabel: "00:09",
        startMs: 9000,
        endMs: 14000,
      },
      {
        id: "demo-3",
        speaker: "user",
        text: "如果从听感上优化，我觉得开头可以更直接，停顿也可以更稳定。",
        timestampLabel: "00:16",
        startMs: 16000,
        endMs: 22000,
      },
    ],
  };
}

export default function SessionReplayPage({ params }: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = use(params);
  const mediaRef = useRef<HTMLAudioElement | HTMLVideoElement | null>(null);
  const [replay, setReplay] = useState<SessionReplay | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [currentTime, setCurrentTime] = useState(0);

  useEffect(() => {
    let active = true;

    void getSessionReplay(sessionId)
      .then((nextReplay) => {
        if (!active) {
          return;
        }

        setReplay(nextReplay);
        setError(null);
      })
      .catch(() => {
        if (!active) {
          return;
        }

        setReplay(buildDemoReplay(sessionId));
        setError(null);
      })
      .finally(() => {
        if (active) {
          setLoading(false);
        }
      });

    return () => {
      active = false;
    };
  }, [sessionId]);

  const mediaUrl = useMemo(() => resolveMediaUrl(replay?.mediaUrl ?? null), [replay?.mediaUrl]);
  const orderedTranscript = useMemo(() => [...(replay?.transcript ?? [])].reverse(), [replay?.transcript]);
  const activeTranscriptId = useMemo(
    () => findActiveTranscript(replay?.transcript ?? [], currentTime),
    [currentTime, replay?.transcript],
  );

  const seekToTranscript = (item: TranscriptChunk) => {
    const media = mediaRef.current;
    if (!media) {
      return;
    }

    media.currentTime = item.startMs / 1000;
    setCurrentTime(media.currentTime);
  };

  if (loading) {
    return (
      <main className="mx-auto flex min-h-screen w-full max-w-7xl items-center justify-center px-6 py-10 md:px-10">
        <Card className="px-6 py-5 text-base font-medium text-slate-600">回放加载中...</Card>
      </main>
    );
  }

  if (error || !replay) {
    return (
      <main className="mx-auto min-h-screen w-full max-w-7xl px-6 py-10 md:px-10">
        <Link href="/report" className="text-sm font-semibold text-slate-500">
          ← 返回报告
        </Link>
        <Card className="mt-8 p-6 text-base font-medium text-slate-600">{error ?? "回放不存在"}</Card>
      </main>
    );
  }

  return (
    <main className="mx-auto min-h-screen w-full max-w-7xl px-6 py-10 md:px-10">
      <div className="mb-8 flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div>
          <Link href="/report" className="text-sm font-semibold text-slate-500">
            ← 返回报告
          </Link>
          <p className="mt-3 text-sm font-semibold text-violet-600">Session Replay</p>
          <h1 className="mt-2 text-3xl font-semibold text-slate-950">回看本次练习</h1>
          <p className="mt-2 text-sm text-slate-500">
            {replay.language === "zh" ? "中文" : "English"} · {replay.scenarioId}
          </p>
        </div>
        <Link
          href={`/session?scenario=${replay.scenarioId}&language=${replay.language}`}
          className="inline-flex items-center justify-center rounded-full bg-violet-600 px-5 py-3 text-sm font-semibold text-white transition hover:bg-violet-500"
        >
          再来一轮
        </Link>
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.1fr)_420px]">
        <Card className="overflow-hidden bg-slate-950 p-6 text-white">
          <div className="mb-5">
            <p className="text-sm text-slate-300">媒体回放</p>
            <h2 className="mt-1 text-2xl font-semibold">先音频回放，后续升级视频</h2>
          </div>

          {mediaUrl ? (
            replay.mediaType === "video" ? (
              <video
                ref={mediaRef as React.RefObject<HTMLVideoElement>}
                controls
                className="aspect-video w-full rounded-3xl bg-black"
                src={mediaUrl}
                onTimeUpdate={(event) => setCurrentTime(event.currentTarget.currentTime)}
              />
            ) : (
              <div className="rounded-3xl bg-white/8 p-6">
                <div className="mb-8 flex aspect-video items-center justify-center rounded-3xl bg-gradient-to-br from-violet-500/30 to-slate-800">
                  <div className="text-center">
                    <p className="text-sm font-semibold text-violet-100">Audio Replay</p>
                    <p className="mt-2 text-4xl font-semibold tabular-nums text-white">
                      {Math.floor(currentTime / 60).toString().padStart(2, "0")}:
                      {Math.floor(currentTime % 60).toString().padStart(2, "0")}
                    </p>
                  </div>
                </div>
                <audio
                  ref={mediaRef as React.RefObject<HTMLAudioElement>}
                  controls
                  className="w-full"
                  src={mediaUrl}
                  onTimeUpdate={(event) => setCurrentTime(event.currentTarget.currentTime)}
                />
              </div>
            )
          ) : (
            <div className="flex aspect-video items-center justify-center rounded-3xl border border-dashed border-white/20 bg-white/5 px-6 text-center text-sm leading-7 text-slate-300">
              当前会话还没有可播放媒体。这一版回放先保证文字稿时间轴可用，真实音视频回放链路后续接入。
            </div>
          )}
        </Card>

        <Card className="flex max-h-[calc(100vh-180px)] min-h-[560px] flex-col p-6">
          <div className="mb-5 flex items-center justify-between gap-3">
            <div>
              <p className="text-sm text-slate-500">完整文字稿</p>
              <h2 className="mt-1 text-xl font-semibold text-slate-950">Transcript Timeline</h2>
            </div>
            <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-500">
              {replay.transcript.length} 段
            </span>
          </div>

          <div className="min-h-0 flex-1 space-y-3 overflow-y-auto pr-1">
            {replay.transcript.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-slate-200 px-4 py-8 text-sm leading-7 text-slate-400">
                本次练习还没有生成完整文字稿。
              </div>
            ) : null}

            {orderedTranscript.map((item) => {
              const active = item.id === activeTranscriptId;

              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => seekToTranscript(item)}
                  className={`w-full rounded-2xl px-4 py-3 text-left transition ${
                    active ? "bg-violet-600 text-white shadow-[0_16px_34px_rgba(109,40,217,0.22)]" : "bg-slate-50 hover:bg-slate-100"
                  }`}
                >
                  <div className={`mb-2 flex items-center justify-between text-xs ${active ? "text-violet-100" : "text-slate-400"}`}>
                    <span>{item.speaker === "user" ? "你" : "AI"}</span>
                    <span>{item.timestampLabel}</span>
                  </div>
                  <p className={`text-sm leading-6 ${active ? "text-white" : "text-slate-700"}`}>{item.text}</p>
                </button>
              );
            })}
          </div>
        </Card>
      </div>
    </main>
  );
}
