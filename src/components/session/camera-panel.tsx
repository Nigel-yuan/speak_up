"use client";

import { useEffect, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";

interface CameraPanelProps {
  children: React.ReactNode;
  isRunning: boolean;
  elapsedSeconds: number;
  onFrameCaptureReady?: (capture: () => string | null) => void;
}

function formatTime(totalSeconds: number) {
  const minutes = String(Math.floor(totalSeconds / 60)).padStart(2, "0");
  const seconds = String(totalSeconds % 60).padStart(2, "0");
  return `${minutes}:${seconds}`;
}

export function CameraPanel({ children, isRunning, elapsedSeconds, onFrameCaptureReady }: CameraPanelProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [permissionState, setPermissionState] = useState<"idle" | "granted" | "denied">("idle");

  useEffect(() => {
    let stream: MediaStream | null = null;

    async function enableCamera() {
      try {
        stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
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
            <video ref={videoRef} autoPlay playsInline muted className="h-full w-full object-cover opacity-85" />
            <canvas ref={canvasRef} className="hidden" />
            <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top,rgba(168,85,247,0.25),transparent_35%),linear-gradient(to_top,rgba(2,6,23,0.7),transparent_38%)]" />
            <div className="absolute left-5 right-5 top-5 flex items-start justify-between gap-3">
              <div className="rounded-2xl bg-black/40 px-4 py-3 text-sm text-slate-100 backdrop-blur">
                镜头表现 · 视线自然 / 表情稳定 / 手势待加强
              </div>
            </div>
            <div className="absolute bottom-5 left-5 right-5 flex flex-col gap-3">
              <div className="max-w-2xl rounded-2xl bg-black/40 px-5 py-4 backdrop-blur">
                <p className="text-xs uppercase tracking-[0.22em] text-violet-200">当前提示</p>
                <p className="mt-2 text-sm leading-6 text-slate-100">
                  开头先给出主旨，再用一个例子承接。把每个重点句的结尾稍微放慢一点，会更有说服力。
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
