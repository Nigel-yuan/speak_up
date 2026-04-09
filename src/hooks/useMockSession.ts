"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  startRealtimeSession,
  type OutboundRealtimeMessage,
  type RealtimeEvent,
} from "@/lib/api";
import type { LiveInsight, SessionSetup, TranscriptChunk } from "@/types/session";

interface SessionState {
  error: string | null;
  isConnecting: boolean;
  partialTranscript: string | null;
  sessionId: string | null;
  socketStatus: "idle" | "connecting" | "connected" | "closed";
}

const idleSessionState: SessionState = {
  error: null,
  isConnecting: false,
  partialTranscript: null,
  sessionId: null,
  socketStatus: "idle",
};

export function useMockSession(setup: SessionSetup) {
  const socketRef = useRef<WebSocket | null>(null);
  const mediaTimerRef = useRef<number | null>(null);
  const videoFrameProviderRef = useRef<(() => string | null) | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const audioStreamRef = useRef<MediaStream | null>(null);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [isRunning, setIsRunning] = useState(false);
  const [transcript, setTranscript] = useState<TranscriptChunk[]>([]);
  const [insights, setInsights] = useState<LiveInsight[]>([]);
  const [sessionState, setSessionState] = useState<SessionState>(idleSessionState);

  const clearSocket = useCallback(() => {
    socketRef.current?.close();
    socketRef.current = null;
  }, []);

  const clearMediaTimer = useCallback(() => {
    if (mediaTimerRef.current !== null) {
      window.clearInterval(mediaTimerRef.current);
      mediaTimerRef.current = null;
    }
  }, []);

  const stopAudioCapture = useCallback(() => {
    recorderRef.current?.stop();
    recorderRef.current = null;
    audioStreamRef.current?.getTracks().forEach((track) => track.stop());
    audioStreamRef.current = null;
  }, []);

  const clearSessionView = useCallback(() => {
    setIsRunning(false);
    setElapsedSeconds(0);
    setTranscript([]);
    setInsights([]);
    setSessionState(idleSessionState);
  }, []);

  const sendRealtimeMessage = useCallback((message: OutboundRealtimeMessage) => {
    const socket = socketRef.current;

    if (!socket || socket.readyState !== WebSocket.OPEN) {
      return;
    }

    socket.send(JSON.stringify(message));
  }, []);

  const sendVideoDebugEvent = useCallback(() => {
    const timestamp = Date.now();
    sendRealtimeMessage({
      type: "video_frame",
      timestamp_ms: timestamp,
      image_base64: videoFrameProviderRef.current?.() ?? undefined,
    });
  }, [sendRealtimeMessage]);

  const startAudioCapture = useCallback(async () => {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
    audioStreamRef.current = stream;
    const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
      ? "audio/webm;codecs=opus"
      : "audio/webm";
    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    recorderRef.current = recorder;

    recorder.addEventListener("dataavailable", async (event) => {
      if (!event.data || event.data.size === 0) {
        return;
      }

      const payload = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onloadend = () => {
          if (typeof reader.result === "string") {
            resolve(reader.result);
            return;
          }
          reject(new Error("audio chunk read failed"));
        };
        reader.onerror = () => reject(reader.error ?? new Error("audio chunk read failed"));
        reader.readAsDataURL(event.data);
      });

      sendRealtimeMessage({
        type: "audio_chunk",
        timestamp_ms: Date.now(),
        payload,
        mime_type: event.data.type || "audio/webm",
      });
    });

    recorder.start(1500);
  }, [sendRealtimeMessage]);

  useEffect(() => {
    if (!isRunning) {
      return;
    }

    const timer = window.setInterval(() => {
      setElapsedSeconds((previous) => previous + 1);
    }, 1000);

    return () => {
      window.clearInterval(timer);
    };
  }, [isRunning]);

  const start = useCallback(async () => {
    if (sessionState.isConnecting) {
      return;
    }

    clearMediaTimer();
    clearSocket();
    stopAudioCapture();
    clearSessionView();
    setSessionState({
      error: null,
      isConnecting: true,
      partialTranscript: null,
      sessionId: null,
      socketStatus: "connecting",
    });

    try {
      const session = await startRealtimeSession(setup.scenarioId, setup.language);
      const socket = new WebSocket(session.websocketUrl);
      socketRef.current = socket;

      socket.addEventListener("open", async () => {
        setSessionState({
          error: null,
          isConnecting: false,
          partialTranscript: null,
          sessionId: session.sessionId,
          socketStatus: "connected",
        });
        setIsRunning(true);
        sendRealtimeMessage({ type: "start_stream" });
        sendVideoDebugEvent();
        mediaTimerRef.current = window.setInterval(sendVideoDebugEvent, 4000);

        try {
          await startAudioCapture();
        } catch {
          setSessionState((previous) => ({
            ...previous,
            error: "麦克风启动失败",
          }));
        }
      });

      socket.addEventListener("message", (event) => {
        const payload = JSON.parse(event.data) as RealtimeEvent;
        const partialText = payload.text ?? null;
        const transcriptChunk = payload.chunk;
        const liveInsight = payload.insight;

        if (payload.type === "transcript_partial" && partialText) {
          setSessionState((previous) => ({ ...previous, partialTranscript: partialText }));
          return;
        }

        if (payload.type === "transcript_final" && transcriptChunk) {
          setTranscript((previous) => [...previous, transcriptChunk]);
          setSessionState((previous) => ({ ...previous, partialTranscript: null }));
          return;
        }

        if (payload.type === "live_insight" && liveInsight) {
          setInsights((previous) => [liveInsight, ...previous].slice(0, 4));
          return;
        }

        if (payload.type === "session_status" && payload.status === "finished") {
          setIsRunning(false);
          clearMediaTimer();
          stopAudioCapture();
          return;
        }

        if (payload.type === "error" && payload.message) {
          setSessionState((previous) => ({ ...previous, error: payload.message }));
        }
      });

      socket.addEventListener("close", () => {
        clearMediaTimer();
        stopAudioCapture();
        setIsRunning(false);
        setSessionState((previous) => ({ ...previous, isConnecting: false, socketStatus: "closed" }));
      });

      socket.addEventListener("error", () => {
        clearMediaTimer();
        stopAudioCapture();
        setIsRunning(false);
        setSessionState((previous) => ({
          ...previous,
          error: "实时连接失败",
          isConnecting: false,
          socketStatus: "closed",
        }));
      });
    } catch {
      setSessionState({
        error: "实时会话启动失败",
        isConnecting: false,
        partialTranscript: null,
        sessionId: null,
        socketStatus: "closed",
      });
    }
  }, [
    clearMediaTimer,
    clearSessionView,
    clearSocket,
    sendRealtimeMessage,
    sendVideoDebugEvent,
    sessionState.isConnecting,
    setup.language,
    setup.scenarioId,
    startAudioCapture,
    stopAudioCapture,
  ]);

  const pause = useCallback(() => {
    setIsRunning(false);
    clearMediaTimer();
    stopAudioCapture();
  }, [clearMediaTimer, stopAudioCapture]);

  const reset = useCallback(() => {
    clearMediaTimer();
    clearSocket();
    stopAudioCapture();
    clearSessionView();
  }, [clearMediaTimer, clearSessionView, clearSocket, stopAudioCapture]);

  const currentInsight = insights[0] ?? null;

  const registerVideoFrameProvider = useCallback((provider: () => string | null) => {
    videoFrameProviderRef.current = provider;
  }, []);

  const statusText = useMemo(() => {
    if (sessionState.error) {
      return sessionState.error;
    }

    if (sessionState.isConnecting) {
      return "正在连接后端实时调试通道...";
    }

    if (sessionState.sessionId) {
      return `Debug Session: ${sessionState.sessionId}`;
    }

    return null;
  }, [sessionState.error, sessionState.isConnecting, sessionState.sessionId]);

  return {
    currentInsight,
    elapsedSeconds,
    insights,
    isLoading: sessionState.isConnecting,
    error: sessionState.error,
    isRunning,
    partialTranscript: sessionState.partialTranscript,
    sessionId: sessionState.sessionId,
    socketStatus: sessionState.socketStatus,
    statusText,
    transcript,
    registerVideoFrameProvider,
    start,
    pause,
    reset,
  };
}
