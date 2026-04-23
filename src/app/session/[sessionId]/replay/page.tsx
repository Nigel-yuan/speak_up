"use client";

import Link from "next/link";
import { use, useEffect, useMemo, useRef, useState } from "react";

import { Card } from "@/components/ui/card";
import { getSessionReplay, resolveApiUrl } from "@/lib/api";
import type { ReplayCoachInsight, SessionReplay, TranscriptChunk } from "@/types/session";

type ReplayTimelineItem =
  | {
      id: string;
      type: "transcript";
      startMs: number;
      endMs: number;
      payload: TranscriptChunk;
    }
  | {
      id: string;
      type: "coach";
      startMs: number;
      endMs: number;
      payload: ReplayCoachInsight;
    };

function resolveMediaUrl(mediaUrl: string | null) {
  if (!mediaUrl) {
    return null;
  }
  return resolveApiUrl(mediaUrl);
}

function formatClock(ms: number) {
  const totalSeconds = Math.max(Math.floor(ms / 1000), 0);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes.toString().padStart(2, "0")}:${seconds.toString().padStart(2, "0")}`;
}

function clampMs(value: number, max: number) {
  return Math.max(0, Math.min(value, max));
}

function buildTimelineItems(replay: SessionReplay | null) {
  if (!replay) {
    return [] as ReplayTimelineItem[];
  }

  const transcriptItems: ReplayTimelineItem[] = replay.transcript.map((item) => ({
    id: item.id,
    type: "transcript",
    startMs: item.startMs,
    endMs: Math.max(item.endMs, item.startMs + 500),
    payload: item,
  }));
  const coachItems: ReplayTimelineItem[] = replay.coachInsights.map((item) => ({
    id: item.id,
    type: "coach",
    startMs: item.startMs,
    endMs: Math.max(item.endMs, item.startMs + 1200),
    payload: item,
  }));

  return [...transcriptItems, ...coachItems].sort((left, right) => {
    if (left.startMs !== right.startMs) {
      return left.startMs - right.startMs;
    }
    if (left.type === right.type) {
      return left.id.localeCompare(right.id);
    }
    return left.type === "transcript" ? -1 : 1;
  });
}

function findActiveItemId(items: ReplayTimelineItem[], currentTimeMs: number) {
  let activeId: string | null = null;

  for (const item of items) {
    if (currentTimeMs >= item.startMs && currentTimeMs <= item.endMs) {
      activeId = item.id;
    }
    if (item.startMs > currentTimeMs) {
      break;
    }
  }

  if (activeId) {
    return activeId;
  }

  for (let index = items.length - 1; index >= 0; index -= 1) {
    if (items[index]!.startMs <= currentTimeMs) {
      return items[index]!.id;
    }
  }

  return items[0]?.id ?? null;
}

function getCoachToneClasses(insight: ReplayCoachInsight, active: boolean) {
  if (active) {
    return "border-violet-500 bg-violet-600 text-white shadow-[0_18px_40px_rgba(109,40,217,0.22)]";
  }
  if (insight.polarity === "positive") {
    return "border-emerald-200 bg-emerald-50 text-emerald-950";
  }
  if (insight.polarity === "negative") {
    return "border-amber-200 bg-amber-50 text-amber-950";
  }
  return "border-slate-200 bg-slate-50 text-slate-900";
}

function buildReportHref(sessionId: string, replay: SessionReplay) {
  return `/report?sessionId=${sessionId}&scenario=${replay.scenarioId}&language=${replay.language}`;
}

export default function SessionReplayPage({ params }: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = use(params);
  const mediaRef = useRef<HTMLAudioElement | HTMLVideoElement | null>(null);
  const timelineItemRefs = useRef<Record<string, HTMLButtonElement | null>>({});
  const [replay, setReplay] = useState<SessionReplay | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [currentTimeMs, setCurrentTimeMs] = useState(0);

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
      .catch((loadError) => {
        if (!active) {
          return;
        }

        setReplay(null);
        setError(loadError instanceof Error ? loadError.message : "回放不存在");
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
  const timelineItems = useMemo(() => buildTimelineItems(replay), [replay]);
  const durationMs = useMemo(
    () => Math.max(replay?.durationMs ?? 0, timelineItems[timelineItems.length - 1]?.endMs ?? 0),
    [replay?.durationMs, timelineItems],
  );
  const activeTimelineId = useMemo(
    () => findActiveItemId(timelineItems, currentTimeMs),
    [currentTimeMs, timelineItems],
  );

  useEffect(() => {
    if (!activeTimelineId) {
      return;
    }

    timelineItemRefs.current[activeTimelineId]?.scrollIntoView({
      block: "nearest",
      behavior: "smooth",
    });
  }, [activeTimelineId]);

  const seekTo = (nextTimeMs: number) => {
    const clampedTimeMs = clampMs(nextTimeMs, durationMs);
    const media = mediaRef.current;

    if (media) {
      media.currentTime = clampedTimeMs / 1000;
    }
    setCurrentTimeMs(clampedTimeMs);
  };

  if (loading) {
    return (
      <main className="mx-auto flex min-h-screen w-full max-w-7xl items-center justify-center px-6 py-10 md:px-10">
        <Card className="px-6 py-5 text-base font-medium text-slate-600">回放复盘加载中...</Card>
      </main>
    );
  }

  if (error || !replay) {
    return (
      <main className="mx-auto min-h-screen w-full max-w-7xl px-6 py-10 md:px-10">
        <Link href="/" className="text-sm font-semibold text-slate-500">
          ← 返回首页
        </Link>
        <Card className="mt-8 p-6 text-base font-medium text-slate-600">{error ?? "回放不存在"}</Card>
      </main>
    );
  }

  const reportHref = buildReportHref(sessionId, replay);

  return (
    <main className="mx-auto min-h-screen w-full max-w-[1800px] px-4 py-6 md:px-8 xl:px-10">
      <div className="mb-8 flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div>
          <Link href={reportHref} className="text-sm font-semibold text-slate-500">
            ← 返回报告
          </Link>
          <p className="mt-3 text-sm font-semibold text-violet-600">回放复盘</p>
          <h1 className="mt-2 text-3xl font-semibold text-slate-950 xl:text-[2.35rem]">按时间轴回看这次练习</h1>
          <p className="mt-2 max-w-3xl text-sm leading-7 text-slate-500">
            {replay.language === "zh" ? "中文" : "English"} · {replay.scenarioId} · {timelineItems.length} 个时间点
          </p>
        </div>
        <Link
          href={`/session?scenario=${replay.scenarioId}&language=${replay.language}`}
          className="inline-flex items-center justify-center rounded-full bg-violet-600 px-5 py-3 text-sm font-semibold text-white transition hover:bg-violet-500"
        >
          再来一轮
        </Link>
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.55fr)_minmax(500px,0.9fr)] 2xl:grid-cols-[minmax(0,1.7fr)_620px]">
        <Card className="overflow-hidden border-slate-200 bg-white p-7 shadow-[0_24px_60px_rgba(15,23,42,0.08)]">
          <div className="mb-5 flex items-center justify-between gap-4">
            <div>
              <p className="text-sm text-slate-500">媒体回放</p>
              <h2 className="mt-1 text-2xl font-semibold text-slate-950 xl:text-[2rem]">左侧视频，右侧同步复盘</h2>
            </div>
            <div className="rounded-full bg-violet-50 px-3 py-1 text-xs font-semibold text-violet-700">
              当前时间 {formatClock(currentTimeMs)}
            </div>
          </div>

          {mediaUrl ? (
            replay.mediaType === "video" ? (
              <video
                ref={mediaRef as React.RefObject<HTMLVideoElement>}
                controls
                playsInline
                className="h-[min(72vh,860px)] w-full rounded-[32px] object-cover object-center shadow-[0_18px_50px_rgba(15,23,42,0.16)]"
                src={mediaUrl}
                onTimeUpdate={(event) => setCurrentTimeMs(Math.round(event.currentTarget.currentTime * 1000))}
              />
            ) : (
              <div className="rounded-[32px] bg-slate-100 p-6">
                <div className="mb-8 flex h-[min(72vh,860px)] items-center justify-center rounded-[28px] bg-gradient-to-br from-violet-200 via-violet-100 to-slate-200">
                  <div className="text-center">
                    <p className="text-sm font-semibold text-violet-700">Audio Replay</p>
                    <p className="mt-2 text-5xl font-semibold tabular-nums text-slate-950">{formatClock(currentTimeMs)}</p>
                  </div>
                </div>
                <audio
                  ref={mediaRef as React.RefObject<HTMLAudioElement>}
                  controls
                  className="w-full"
                  src={mediaUrl}
                  onTimeUpdate={(event) => setCurrentTimeMs(Math.round(event.currentTarget.currentTime * 1000))}
                />
              </div>
            )
          ) : (
            <div className="flex h-[min(72vh,860px)] items-center justify-center rounded-[32px] border border-dashed border-slate-300 bg-slate-50 px-8 text-center text-sm leading-7 text-slate-500">
              这次会话还没有可播放视频，当前先按时间轴查看文字稿和 AI Live Coach 建议。
            </div>
          )}
        </Card>

        <Card className="flex max-h-[calc(100vh-190px)] min-h-[760px] flex-col p-7 shadow-[0_24px_60px_rgba(15,23,42,0.08)]">
          <div className="mb-5 flex items-center justify-between gap-3">
            <div>
              <p className="text-sm text-slate-500">右侧时间线</p>
              <h2 className="mt-1 text-2xl font-semibold text-slate-950">文字稿 + AI Live Coach</h2>
            </div>
            <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-500">
              {replay.transcript.length} 段文字稿 · {replay.coachInsights.length} 条建议
            </span>
          </div>

          <div className="min-h-0 flex-1 space-y-3 overflow-y-auto pr-1">
            {timelineItems.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-slate-200 px-4 py-8 text-sm leading-7 text-slate-400">
                本次练习还没有生成可回放时间线。
              </div>
            ) : null}

            {timelineItems.map((item) => {
              const active = item.id === activeTimelineId;

              if (item.type === "transcript") {
                return (
                  <button
                    key={item.id}
                    ref={(node) => {
                      timelineItemRefs.current[item.id] = node;
                    }}
                    type="button"
                    onClick={() => seekTo(item.startMs)}
                    className={`w-full rounded-2xl border px-4 py-3 text-left transition ${
                      active
                        ? "border-violet-500 bg-violet-600 text-white shadow-[0_18px_40px_rgba(109,40,217,0.22)]"
                        : "border-slate-200 bg-slate-50 text-slate-900 hover:bg-slate-100"
                    }`}
                  >
                    <div className={`mb-2 flex items-center justify-between text-xs ${active ? "text-violet-100" : "text-slate-400"}`}>
                      <span>文字稿</span>
                      <span>{item.payload.timestampLabel}</span>
                    </div>
                    <p className={`text-sm leading-6 ${active ? "text-white" : "text-slate-700"}`}>{item.payload.text}</p>
                  </button>
                );
              }

              return (
                <button
                  key={item.id}
                  ref={(node) => {
                    timelineItemRefs.current[item.id] = node;
                  }}
                  type="button"
                  onClick={() => seekTo(item.startMs)}
                  className={`w-full rounded-2xl border px-4 py-3 text-left transition ${getCoachToneClasses(item.payload, active)}`}
                >
                  <div className={`mb-2 flex items-center justify-between text-xs ${active ? "text-violet-100" : "text-slate-500"}`}>
                    <span>AI Live Coach</span>
                    <span>{formatClock(item.startMs)}</span>
                  </div>
                  <p className="text-sm font-semibold leading-6">{item.payload.title}</p>
                  <p className={`mt-2 text-sm leading-6 ${active ? "text-violet-50" : "text-current/80"}`}>{item.payload.message}</p>
                  {item.payload.evidenceText ? (
                    <p className={`mt-2 text-xs leading-5 ${active ? "text-violet-100" : "text-current/65"}`}>
                      证据：{item.payload.evidenceText}
                    </p>
                  ) : null}
                </button>
              );
            })}
          </div>
        </Card>
      </div>
    </main>
  );
}
