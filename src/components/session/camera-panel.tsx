"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { usePoseTracker } from "@/hooks/usePoseTracker";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import type { PoseSnapshot } from "@/types/session";

interface CameraPanelProps {
  children: React.ReactNode;
  isRunning: boolean;
  elapsedSeconds: number;
  latestPoseSnapshot?: PoseSnapshot | null;
  onFrameCaptureReady?: (capture: () => string | null) => void;
  onPoseSnapshotReady?: (capture: () => PoseSnapshot | null) => void;
  poseDebugEnabled?: boolean;
}

function formatPoseNumber(value: number, digits = 2) {
  return Number.isFinite(value) ? value.toFixed(digits) : "--";
}

type PoseCameraMode = "missing" | "upper-body" | "full-body";

function getPoseCameraMode(snapshot: PoseSnapshot | null): PoseCameraMode {
  if (!snapshot?.shoulderVisible) {
    return "missing";
  }

  return snapshot.hipVisible ? "full-body" : "upper-body";
}

function isUpperBodyMode(snapshot: PoseSnapshot | null) {
  return getPoseCameraMode(snapshot) === "upper-body";
}

function hasCenterOffsetIssue(snapshot: PoseSnapshot | null) {
  return Boolean(snapshot && Math.abs(snapshot.centerOffsetX) > 0.18);
}

function hasTiltIssue(snapshot: PoseSnapshot | null) {
  return Boolean(snapshot && (Math.abs(snapshot.torsoTiltDeg) > 8 || Math.abs(snapshot.shoulderTiltDeg) > 7));
}

function hasLowGestureIssue(snapshot: PoseSnapshot | null) {
  return Boolean(snapshot && !snapshot.handsVisible && snapshot.gestureActivity < 0.06);
}

function hasStabilityIssue(snapshot: PoseSnapshot | null) {
  return Boolean(snapshot && snapshot.stabilityScore < 0.45);
}

function formatTime(totalSeconds: number) {
  const minutes = String(Math.floor(totalSeconds / 60)).padStart(2, "0");
  const seconds = String(totalSeconds % 60).padStart(2, "0");
  return `${minutes}:${seconds}`;
}

function buildPoseStageTitle(snapshot: PoseSnapshot | null, error: string | null) {
  if (error) {
    return "镜头表现 · 姿态模型暂不可用";
  }

  if (!snapshot) {
    return "镜头表现 · 等待姿态跟踪";
  }

  if (!snapshot.bodyPresent) {
    return "镜头表现 · 请把头肩收回画面";
  }

  if (hasCenterOffsetIssue(snapshot)) {
    return "镜头表现 · 身体偏离画面中心";
  }

  if (hasTiltIssue(snapshot)) {
    return isUpperBodyMode(snapshot) ? "镜头表现 · 肩线有些倾斜" : "镜头表现 · 身体有些歪斜";
  }

  if (hasLowGestureIssue(snapshot)) {
    return "镜头表现 · 手势偏少";
  }

  if (hasStabilityIssue(snapshot)) {
    return isUpperBodyMode(snapshot) ? "镜头表现 · 上身略有晃动" : "镜头表现 · 身体略有晃动";
  }

  return isUpperBodyMode(snapshot) ? "镜头表现 · 上身姿态稳定" : "镜头表现 · 姿态稳定";
}

function buildPoseStageDetail(snapshot: PoseSnapshot | null, error: string | null) {
  if (error) {
    return "本地姿态检测当前不可用，实时字幕和音频链路不受影响。";
  }

  if (!snapshot) {
    return "开始演讲后，系统会持续跟踪站姿、居中程度和手势活跃度。";
  }

  if (!snapshot.bodyPresent) {
    return "尽量让头部和肩膀稳定进入镜头中央，系统才能持续判断你的近景姿态。";
  }

  if (hasCenterOffsetIssue(snapshot)) {
    return "把身体稍微往镜头中心收一点，画面会更稳，观众也更容易跟上你的表达。";
  }

  if (hasTiltIssue(snapshot)) {
    return isUpperBodyMode(snapshot)
      ? "你的头肩区域有些倾斜。把肩线放平一点，镜头里的上身会更稳，也更有交流感。"
      : "保持肩膀和躯干更垂直一些，会让整体气场更稳，表达也更可信。";
  }

  if (hasLowGestureIssue(snapshot)) {
    return "当前手势参与感偏低。讲重点句时可以加入少量自然手势，增强表达支撑。";
  }

  if (hasStabilityIssue(snapshot)) {
    return isUpperBodyMode(snapshot)
      ? "你的上身细小晃动有点多。重点句前先把头肩位置稳住，镜头表现会更沉着。"
      : "身体的细小晃动有点多。重点句前先站稳，再开口，听感会更有力量。";
  }

  return isUpperBodyMode(snapshot)
    ? "当前近景上身姿态比较稳，可以继续把注意力放在语气、节奏和内容推进上。"
    : "当前姿态基础不错，可以继续把注意力放在语气、节奏和内容推进上。";
}

export function CameraPanel({
  children,
  isRunning,
  elapsedSeconds,
  latestPoseSnapshot,
  onFrameCaptureReady,
  onPoseSnapshotReady,
  poseDebugEnabled = false,
}: CameraPanelProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [videoElement, setVideoElement] = useState<HTMLVideoElement | null>(null);
  const [permissionState, setPermissionState] = useState<"idle" | "granted" | "denied">("idle");
  const { error: poseTrackerError, getLatestSnapshot, snapshot } = usePoseTracker({
    enabled: isRunning && permissionState === "granted",
    videoElement,
  });
  const handleVideoRef = useCallback((node: HTMLVideoElement | null) => {
    videoRef.current = node;
    setVideoElement(node);
  }, []);

  useEffect(() => {
    let stream: MediaStream | null = null;

    async function enableCamera() {
      try {
        stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          void videoRef.current.play().catch(() => {
            // The browser may delay playback until metadata is ready.
          });
        }
        setPermissionState("granted");
      } catch {
        setPermissionState("denied");
      }
    }

    enableCamera();

    return () => {
      stream?.getTracks().forEach((track) => track.stop());
    };
  }, []);

  useEffect(() => {
    if (!onFrameCaptureReady) {
      return;
    }

    onFrameCaptureReady(() => {
      const video = videoRef.current;
      const canvas = canvasRef.current;

      if (!video || !canvas || video.videoWidth === 0 || video.videoHeight === 0) {
        return null;
      }

      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      const context = canvas.getContext("2d");
      if (!context) {
        return null;
      }

      context.drawImage(video, 0, 0, canvas.width, canvas.height);
      return canvas.toDataURL("image/jpeg", 0.72);
    });
  }, [onFrameCaptureReady]);

  useEffect(() => {
    if (!onPoseSnapshotReady) {
      return;
    }

    onPoseSnapshotReady(() => getLatestSnapshot());
  }, [getLatestSnapshot, onPoseSnapshotReady]);

  const activePoseSnapshot = isRunning ? snapshot : latestPoseSnapshot ?? null;
  const stageTitle = buildPoseStageTitle(activePoseSnapshot, poseTrackerError);
  const stageDetail = buildPoseStageDetail(activePoseSnapshot, poseTrackerError);

  return (
    <Card className="flex h-full min-h-0 flex-col overflow-hidden rounded-[28px] border-white/60 bg-slate-950 text-white shadow-[0_18px_45px_rgba(15,23,42,0.18)]">
      <div className="flex items-center justify-between border-b border-white/10 px-5 py-4">
        <div>
          <p className="text-xs uppercase tracking-[0.22em] text-slate-400">Camera Stage</p>
          <p className="mt-1 text-lg font-semibold">屏幕主视区</p>
        </div>
        <div className="flex items-center gap-3">
          <Badge tone={isRunning ? "positive" : "neutral"}>{isRunning ? "进行中" : "待开始"}</Badge>
          <span className="text-sm font-medium text-slate-200">{formatTime(elapsedSeconds)}</span>
        </div>
      </div>

      <div className="relative min-h-0 flex-1">
        {permissionState === "denied" ? (
          <div className="flex h-full flex-col items-center justify-center gap-4 px-8 text-center">
            <div className="rounded-full bg-white/10 px-4 py-2 text-sm text-slate-300">摄像头未授权</div>
            <p className="max-w-md text-sm leading-7 text-slate-400">
              当前先展示原型占位态。后续接真实训练时，这里会保留用户视频、姿态观察和镜头表现分析。
            </p>
          </div>
        ) : (
          <>
            <video ref={handleVideoRef} autoPlay playsInline muted className="h-full w-full object-cover opacity-85" />
            <canvas ref={canvasRef} className="hidden" />
            <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top,rgba(168,85,247,0.25),transparent_35%),linear-gradient(to_top,rgba(2,6,23,0.7),transparent_38%)]" />
            <div className="absolute left-5 right-5 top-5 flex items-start justify-between gap-3">
              <div className="rounded-2xl bg-black/40 px-4 py-3 text-sm text-slate-100 backdrop-blur">
                {stageTitle}
              </div>
              {poseDebugEnabled ? (
                <div className="w-[320px] rounded-2xl bg-black/55 px-4 py-3 text-xs text-slate-100 backdrop-blur">
                  <p className="font-semibold uppercase tracking-[0.18em] text-sky-200">Pose Debug · Local</p>
                  <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-[11px] leading-5">
                    <span>model ready</span>
                    <span className="text-right">{poseTrackerError ? "error" : snapshot ? "running" : "waiting"}</span>
                    <span>body present</span>
                    <span className="text-right">{activePoseSnapshot?.bodyPresent ? "yes" : "no"}</span>
                    <span>face visible</span>
                    <span className="text-right">{activePoseSnapshot?.faceVisible ? "yes" : "no"}</span>
                    <span>shoulder visible</span>
                    <span className="text-right">{activePoseSnapshot?.shoulderVisible ? "yes" : "no"}</span>
                    <span>hip visible</span>
                    <span className="text-right">{activePoseSnapshot?.hipVisible ? "yes" : "no"}</span>
                    <span>hands visible</span>
                    <span className="text-right">{activePoseSnapshot?.handsVisible ? "yes" : "no"}</span>
                    <span>camera mode</span>
                    <span className="text-right">
                      {getPoseCameraMode(activePoseSnapshot)}
                    </span>
                    <span>body scale</span>
                    <span className="text-right">{formatPoseNumber(activePoseSnapshot?.bodyScale ?? Number.NaN, 3)}</span>
                    <span>center offset</span>
                    <span className="text-right">{formatPoseNumber(activePoseSnapshot?.centerOffsetX ?? Number.NaN, 3)}</span>
                    <span>shoulder tilt</span>
                    <span className="text-right">{formatPoseNumber(activePoseSnapshot?.shoulderTiltDeg ?? Number.NaN, 1)}°</span>
                    <span>torso tilt</span>
                    <span className="text-right">{formatPoseNumber(activePoseSnapshot?.torsoTiltDeg ?? Number.NaN, 1)}°</span>
                    <span>gesture</span>
                    <span className="text-right">{formatPoseNumber(activePoseSnapshot?.gestureActivity ?? Number.NaN, 2)}</span>
                    <span>stability</span>
                    <span className="text-right">{formatPoseNumber(activePoseSnapshot?.stabilityScore ?? Number.NaN, 2)}</span>
                  </div>
                </div>
              ) : null}
            </div>
            <div className="absolute bottom-5 left-5 right-5 flex flex-col gap-3">
              <div className="max-w-2xl rounded-2xl bg-black/40 px-5 py-4 backdrop-blur">
                <p className="text-xs uppercase tracking-[0.22em] text-violet-200">当前提示</p>
                <p className="mt-2 text-sm leading-6 text-slate-100">
                  {stageDetail}
                </p>
              </div>
              <div>{children}</div>
            </div>
          </>
        )}
      </div>
    </Card>
  );
}
