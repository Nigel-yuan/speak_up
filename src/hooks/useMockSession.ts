"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  finishRealtimeSession,
  startRealtimeSession,
  uploadSessionFullAudio,
  type OutboundRealtimeMessage,
  type RealtimeEvent,
} from "@/lib/api";
import type { LiveInsight, SessionSetup, TranscriptChunk } from "@/types/session";

interface SessionState {
  error: string | null;
  isConnecting: boolean;
  isFinalizing: boolean;
  partialTranscript: string | null;
  sessionId: string | null;
  socketStatus: "idle" | "connecting" | "connected" | "closed";
}

const idleSessionState: SessionState = {
  error: null,
  isConnecting: false,
  isFinalizing: false,
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
  const recordedChunksRef = useRef<Blob[]>([]);
  const recorderMimeTypeRef = useRef("audio/webm");
  const pendingChunkTasksRef = useRef<Set<Promise<void>>>(new Set());
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

  const resetRecordedAudio = useCallback(() => {
    recordedChunksRef.current = [];
    recorderMimeTypeRef.current = "audio/webm";
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

  const buildRecordedAudioBlob = useCallback(() => {
    if (recordedChunksRef.current.length === 0) {
      return null;
    }

    return new Blob(recordedChunksRef.current, {
      type: recorderMimeTypeRef.current || "audio/webm",
    });
  }, []);

  const waitForPendingChunkTasks = useCallback(async () => {
    const tasks = Array.from(pendingChunkTasksRef.current);
    if (tasks.length === 0) {
      return;
    }

    await Promise.allSettled(tasks);
  }, []);

  const stopAudioCapture = useCallback(async () => {
    const recorder = recorderRef.current;
    const stream = audioStreamRef.current;

    recorderRef.current = null;
    audioStreamRef.current = null;

    const stopTracks = () => {
      stream?.getTracks().forEach((track) => track.stop());
    };

    if (!recorder) {
      stopTracks();
      return buildRecordedAudioBlob();
    }

    if (recorder.state === "inactive") {
      stopTracks();
      return buildRecordedAudioBlob();
    }

    const stopPromise = new Promise<Blob | null>((resolve) => {
      recorder.addEventListener(
        "stop",
        () => {
          stopTracks();
          resolve(buildRecordedAudioBlob());
        },
        { once: true },
      );
    });

    recorder.stop();
    return stopPromise;
  }, [buildRecordedAudioBlob]);

  const discardAudioCapture = useCallback(async () => {
    await stopAudioCapture();
    await waitForPendingChunkTasks();
    resetRecordedAudio();
  }, [resetRecordedAudio, stopAudioCapture, waitForPendingChunkTasks]);

  const finalizeAudioCapture = useCallback(async (reason: "pause" | "finish", sessionId: string | null) => {
    const audioBlob = await stopAudioCapture();
    await waitForPendingChunkTasks();

    if (!setup.debugEnabled) {
      resetRecordedAudio();
      return;
    }

    if (!audioBlob || audioBlob.size === 0) {
      resetRecordedAudio();
      return;
    }

    if (!sessionId) {
      resetRecordedAudio();
      return;
    }

    try {
      await uploadSessionFullAudio(sessionId, audioBlob, reason);
    } catch {
      throw new Error("完整调试录音保存失败");
    } finally {
      resetRecordedAudio();
    }
  }, [resetRecordedAudio, setup.debugEnabled, stopAudioCapture, waitForPendingChunkTasks]);

  const startAudioCapture = useCallback(async () => {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
    audioStreamRef.current = stream;
    const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
      ? "audio/webm;codecs=opus"
      : "audio/webm";
    resetRecordedAudio();
    recorderMimeTypeRef.current = mimeType;
    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    recorderRef.current = recorder;

    recorder.addEventListener("dataavailable", async (event) => {
      if (!event.data || event.data.size === 0) {
        return;
      }

      if (setup.debugEnabled) {
        recordedChunksRef.current.push(event.data);
      }

      const task = (async () => {
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
      })();

      pendingChunkTasksRef.current.add(task);
      void task.finally(() => {
        pendingChunkTasksRef.current.delete(task);
      });
    });

    recorder.start(1500);
  }, [resetRecordedAudio, sendRealtimeMessage, setup.debugEnabled]);

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
    if (sessionState.isConnecting || sessionState.isFinalizing) {
      return;
    }

    clearMediaTimer();
    await discardAudioCapture();
    clearSocket();
    clearSessionView();
    setSessionState({
      error: null,
      isConnecting: true,
      isFinalizing: false,
      partialTranscript: null,
      sessionId: null,
      socketStatus: "connecting",
    });

    try {
      const session = await startRealtimeSession(setup.scenarioId, setup.language, setup.debugEnabled);
      const socket = new WebSocket(session.websocketUrl);
      socketRef.current = socket;

      socket.addEventListener("open", async () => {
        setSessionState({
          error: null,
          isConnecting: false,
          isFinalizing: false,
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
          void discardAudioCapture();
          return;
        }

        if (payload.type === "error" && payload.message) {
          setSessionState((previous) => ({ ...previous, error: payload.message }));
        }
      });

      socket.addEventListener("close", () => {
        clearMediaTimer();
        void discardAudioCapture();
        setIsRunning(false);
        setSessionState((previous) => ({ ...previous, isConnecting: false, socketStatus: "closed" }));
      });

      socket.addEventListener("error", () => {
        clearMediaTimer();
        void discardAudioCapture();
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
        isFinalizing: false,
        partialTranscript: null,
        sessionId: null,
        socketStatus: "closed",
      });
    }
  }, [
    clearMediaTimer,
    clearSessionView,
    clearSocket,
    discardAudioCapture,
    sendRealtimeMessage,
    sendVideoDebugEvent,
    sessionState.isConnecting,
    sessionState.isFinalizing,
    setup.language,
    setup.scenarioId,
    setup.debugEnabled,
    startAudioCapture,
  ]);

  const pause = useCallback(async () => {
    setIsRunning(false);
    clearMediaTimer();
    setSessionState((previous) => ({ ...previous, error: null, isFinalizing: true }));

    try {
      await finalizeAudioCapture("pause", sessionState.sessionId);
    } catch (error) {
      const message = error instanceof Error ? error.message : "完整调试录音保存失败";
      setSessionState((previous) => ({ ...previous, error: message }));
      throw error;
    } finally {
      setSessionState((previous) => ({ ...previous, isFinalizing: false }));
    }
  }, [clearMediaTimer, finalizeAudioCapture, sessionState.sessionId]);

  const finish = useCallback(async () => {
    setIsRunning(false);
    clearMediaTimer();
    setSessionState((previous) => ({ ...previous, error: null, isFinalizing: true }));

    try {
      await finalizeAudioCapture("finish", sessionState.sessionId);
      if (sessionState.sessionId) {
        await finishRealtimeSession(sessionState.sessionId);
      }
      clearSocket();
    } catch (error) {
      const message = error instanceof Error ? error.message : "结束会话失败";
      setSessionState((previous) => ({ ...previous, error: message }));
      throw error;
    } finally {
      setSessionState((previous) => ({ ...previous, isFinalizing: false }));
    }
  }, [clearMediaTimer, clearSocket, finalizeAudioCapture, sessionState.sessionId]);

  const reset = useCallback(async () => {
    clearMediaTimer();
    await discardAudioCapture();
    clearSocket();
    clearSessionView();
  }, [clearMediaTimer, clearSessionView, clearSocket, discardAudioCapture]);

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

    if (sessionState.isFinalizing) {
      return setup.debugEnabled ? "正在保存完整调试录音..." : "正在结束会话...";
    }

    if (sessionState.sessionId) {
      return setup.debugEnabled ? `Debug Session: ${sessionState.sessionId}` : `Session: ${sessionState.sessionId}`;
    }

    return null;
  }, [sessionState.error, sessionState.isConnecting, sessionState.isFinalizing, sessionState.sessionId, setup.debugEnabled]);

  useEffect(() => {
    return () => {
      clearMediaTimer();
      clearSocket();
      void discardAudioCapture();
    };
  }, [clearMediaTimer, clearSocket, discardAudioCapture]);

  return {
    currentInsight,
    elapsedSeconds,
    insights,
    isLoading: sessionState.isConnecting || sessionState.isFinalizing,
    error: sessionState.error,
    finish,
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
