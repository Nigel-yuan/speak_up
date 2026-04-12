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
  sessionId: string | null;
  socketStatus: "idle" | "connecting" | "connected" | "closed";
}

interface TranscriptStateRef {
  active: TranscriptChunk | null;
  committed: TranscriptChunk[];
}

interface FlushResult {
  active: TranscriptChunk | null;
  committed: TranscriptChunk[];
}

const idleSessionState: SessionState = {
  error: null,
  isConnecting: false,
  isFinalizing: false,
  sessionId: null,
  socketStatus: "idle",
};

const DEBUG_RECORDER_TIMESLICE_MS = 1500;
const PCM_CHANNELS = 1;
const PCM_CHUNK_DURATION_MS = 100;
const PCM_SAMPLE_RATE = 16000;
const PCM_WORKLET_MODULE_PATH = "/audio/pcm-capture.worklet.js";
const PARTIAL_FILLER_TOKENS = {
  en: new Set(["um", "uh", "well", "so"]),
  zh: new Set(["嗯", "啊", "额", "呃", "然后", "就是", "哦", "诶", "欸", "哎", "唉"]),
};
const PARTIAL_NOISE_PATTERN = /^[\s,.!?，。！？、…]+$/;
const SHORT_PARTIAL_WORDS_MAX = 3;
const SHORT_PARTIAL_CHARS_MAX = 4;

function createEmptyTranscriptState(): TranscriptStateRef {
  return {
    active: null,
    committed: [],
  };
}

function formatTimestampLabel(elapsedMs: number) {
  const totalSeconds = Math.max(Math.floor(elapsedMs / 1000), 0);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes.toString().padStart(2, "0")}:${seconds.toString().padStart(2, "0")}`;
}

function buildElapsedMs(sessionStartedAtMs: number | null) {
  if (sessionStartedAtMs === null) {
    return 0;
  }

  return Math.max(Date.now() - sessionStartedAtMs, 0);
}

function normalizeComparisonText(text: string) {
  return text
    .trim()
    .toLowerCase()
    .replace(/[\s,.!?，。！？、…:：;；"'“”‘’（）()\-]/g, "");
}

function encodeBase64(bytes: Uint8Array) {
  let binary = "";
  const chunkSize = 0x8000;

  for (let index = 0; index < bytes.length; index += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(index, index + chunkSize));
  }

  return window.btoa(binary);
}

function float32ToPcm16(samples: Float32Array) {
  const pcm16 = new Int16Array(samples.length);

  for (let index = 0; index < samples.length; index += 1) {
    const value = Math.max(-1, Math.min(1, samples[index] ?? 0));
    pcm16[index] = value < 0 ? value * 0x8000 : value * 0x7fff;
  }

  return pcm16;
}

function resampleFloat32(samples: Float32Array, sourceRate: number, targetRate: number) {
  if (sourceRate === targetRate) {
    return samples;
  }

  const ratio = sourceRate / targetRate;
  const targetLength = Math.max(1, Math.round(samples.length / ratio));
  const resampled = new Float32Array(targetLength);

  for (let index = 0; index < targetLength; index += 1) {
    const sourceIndex = index * ratio;
    const lowerIndex = Math.floor(sourceIndex);
    const upperIndex = Math.min(lowerIndex + 1, samples.length - 1);
    const weight = sourceIndex - lowerIndex;
    const lowerValue = samples[lowerIndex] ?? 0;
    const upperValue = samples[upperIndex] ?? lowerValue;
    resampled[index] = lowerValue * (1 - weight) + upperValue * weight;
  }

  return resampled;
}

function isFillerPartial(partialText: string, language: SessionSetup["language"]) {
  const normalized = normalizeComparisonText(partialText);
  if (!normalized) {
    return false;
  }

  return PARTIAL_FILLER_TOKENS[language].has(normalized);
}

function isIgnorableBoundaryChar(char: string) {
  return /[\s,.!?，。！？、…:：;；"'“”‘’（）()\-]/.test(char);
}

function extractSuffixAfterLoosePrefix(fullText: string, prefixText: string) {
  let fullIndex = 0;
  let prefixIndex = 0;

  while (fullIndex < fullText.length && prefixIndex < prefixText.length) {
    const fullChar = fullText[fullIndex] ?? "";
    const prefixChar = prefixText[prefixIndex] ?? "";

    if (isIgnorableBoundaryChar(fullChar)) {
      fullIndex += 1;
      continue;
    }

    if (isIgnorableBoundaryChar(prefixChar)) {
      prefixIndex += 1;
      continue;
    }

    if (fullChar.toLowerCase() !== prefixChar.toLowerCase()) {
      return null;
    }

    fullIndex += 1;
    prefixIndex += 1;
  }

  while (prefixIndex < prefixText.length && isIgnorableBoundaryChar(prefixText[prefixIndex] ?? "")) {
    prefixIndex += 1;
  }

  if (prefixIndex < prefixText.length) {
    return null;
  }

  while (fullIndex < fullText.length && isIgnorableBoundaryChar(fullText[fullIndex] ?? "")) {
    fullIndex += 1;
  }

  return fullText.slice(fullIndex).trim();
}

function buildActiveTranscriptChunk(text: string, previousChunk: TranscriptChunk | null, startMs: number): TranscriptChunk {
  return {
    id: previousChunk?.id ?? `active-${Date.now()}`,
    speaker: "user",
    text,
    timestampLabel: previousChunk?.timestampLabel ?? formatTimestampLabel(startMs),
    startMs: previousChunk?.startMs ?? startMs,
    endMs: previousChunk?.endMs ?? startMs,
  };
}

function isShortPartial(partialText: string, language: SessionSetup["language"]) {
  if (language === "zh") {
    return partialText.replace(/\s+/g, "").length <= SHORT_PARTIAL_CHARS_MAX;
  }

  return partialText
    .trim()
    .split(/\s+/)
    .filter(Boolean).length <= SHORT_PARTIAL_WORDS_MAX;
}

function derivePreviewTextFromLastCommitted(
  partialText: string,
  latestCommittedChunk: TranscriptChunk | undefined,
  language: SessionSetup["language"],
) {
  const trimmedPartial = partialText.trim();
  if (!trimmedPartial) {
    return null;
  }

  const latestCommittedText = latestCommittedChunk?.speaker === "user" ? latestCommittedChunk.text.trim() : "";
  if (!latestCommittedText) {
    return trimmedPartial;
  }

  const suffix = extractSuffixAfterLoosePrefix(trimmedPartial, latestCommittedText);
  if (suffix !== null) {
    return !suffix || isWeakStandalonePartial(suffix, language) ? null : suffix;
  }

  return trimmedPartial;
}

function cleanPartialTranscript(partialText: string, activeChunk: TranscriptChunk | null, language: SessionSetup["language"]) {
  const trimmedPartial = partialText.trim();
  if (!trimmedPartial) {
    return null;
  }

  if (PARTIAL_NOISE_PATTERN.test(trimmedPartial)) {
    return null;
  }

  if (!activeChunk) {
    return trimmedPartial;
  }

  const activeText = activeChunk.text.trim();
  if (!activeText) {
    return trimmedPartial;
  }

  if (trimmedPartial.startsWith(activeText)) {
    return trimmedPartial;
  }

  if (activeText.startsWith(trimmedPartial) || activeText.endsWith(trimmedPartial)) {
    return activeText;
  }

  if (isFillerPartial(trimmedPartial, language) || isShortPartial(trimmedPartial, language)) {
    return language === "zh" ? `${activeText}${trimmedPartial}` : `${activeText} ${trimmedPartial}`.trim();
  }

  return trimmedPartial;
}

function isWeakStandalonePartial(partialText: string, language: SessionSetup["language"]) {
  const trimmedPartial = partialText.trim();
  if (!trimmedPartial) {
    return true;
  }

  if (PARTIAL_NOISE_PATTERN.test(trimmedPartial)) {
    return true;
  }

  return isFillerPartial(trimmedPartial, language);
}


export function useMockSession(setup: SessionSetup) {
  const socketRef = useRef<WebSocket | null>(null);
  const mediaTimerRef = useRef<number | null>(null);
  const videoFrameProviderRef = useRef<(() => string | null) | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const audioStreamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const sourceNodeRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const workletNodeRef = useRef<AudioWorkletNode | null>(null);
  const monitorGainNodeRef = useRef<GainNode | null>(null);
  const recordedChunksRef = useRef<Blob[]>([]);
  const recorderMimeTypeRef = useRef("audio/webm");
  const pendingChunkTasksRef = useRef<Set<Promise<void>>>(new Set());
  const sessionStartedAtRef = useRef<number | null>(null);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [isRunning, setIsRunning] = useState(false);
  const [transcript, setTranscript] = useState<TranscriptChunk[]>([]);
  const [activeTranscript, setActiveTranscript] = useState<TranscriptChunk | null>(null);
  const [insights, setInsights] = useState<LiveInsight[]>([]);
  const [sessionState, setSessionState] = useState<SessionState>(idleSessionState);
  const transcriptStateRef = useRef<TranscriptStateRef>(createEmptyTranscriptState());

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
    transcriptStateRef.current = createEmptyTranscriptState();
    sessionStartedAtRef.current = null;
    setIsRunning(false);
    setElapsedSeconds(0);
    setTranscript([]);
    setActiveTranscript(null);
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

  const sendVideoFrameEvent = useCallback(() => {
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

  const stopRealtimePcmCapture = useCallback(async () => {
    const workletNode = workletNodeRef.current;
    const sourceNode = sourceNodeRef.current;
    const monitorGainNode = monitorGainNodeRef.current;
    const audioContext = audioContextRef.current;

    workletNodeRef.current = null;
    sourceNodeRef.current = null;
    monitorGainNodeRef.current = null;
    audioContextRef.current = null;

    workletNode?.port.close();

    try {
      workletNode?.disconnect();
    } catch {
      // ignore disconnect errors during teardown
    }

    try {
      sourceNode?.disconnect();
    } catch {
      // ignore disconnect errors during teardown
    }

    try {
      monitorGainNode?.disconnect();
    } catch {
      // ignore disconnect errors during teardown
    }

    if (audioContext && audioContext.state !== "closed") {
      await audioContext.close();
    }
  }, []);

  const stopAudioCapture = useCallback(async () => {
    const recorder = recorderRef.current;
    const stream = audioStreamRef.current;

    recorderRef.current = null;
    audioStreamRef.current = null;

    await stopRealtimePcmCapture();

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
  }, [buildRecordedAudioBlob, stopRealtimePcmCapture]);

  const discardAudioCapture = useCallback(async () => {
    await stopAudioCapture();
    await waitForPendingChunkTasks();
    resetRecordedAudio();
  }, [resetRecordedAudio, stopAudioCapture, waitForPendingChunkTasks]);

  const clearActiveTranscript = useCallback(() => {
    transcriptStateRef.current = {
      ...transcriptStateRef.current,
      active: null,
    };
    setActiveTranscript(null);
  }, []);

  const applyFinalTranscriptChunk = useCallback(
    (incomingChunk: TranscriptChunk, replacePrevious: boolean) => {
      const currentState = transcriptStateRef.current;
      const activeChunk = currentState.active;
      const fallbackStartMs = activeChunk?.startMs || buildElapsedMs(sessionStartedAtRef.current);
      const nextStartMs = incomingChunk.startMs > 0 ? incomingChunk.startMs : fallbackStartMs;
      const nextEndMs = incomingChunk.endMs > 0 ? Math.max(incomingChunk.endMs, nextStartMs) : nextStartMs + 1;

      const nextChunk: TranscriptChunk = {
        ...incomingChunk,
        id:
          replacePrevious && currentState.committed.length > 0
            ? currentState.committed[currentState.committed.length - 1]?.id ?? incomingChunk.id
            : incomingChunk.id,
        startMs: nextStartMs,
        endMs: nextEndMs,
        timestampLabel:
          incomingChunk.timestampLabel && incomingChunk.timestampLabel !== "00:00"
            ? incomingChunk.timestampLabel
            : formatTimestampLabel(nextStartMs),
      };

      const nextCommitted = [...currentState.committed];
      if (replacePrevious && nextCommitted.length > 0) {
        nextCommitted[nextCommitted.length - 1] = nextChunk;
      } else {
        const lastCommitted = nextCommitted[nextCommitted.length - 1];
        if (lastCommitted && lastCommitted.text.trim() === nextChunk.text.trim()) {
          nextCommitted[nextCommitted.length - 1] = nextChunk;
        } else {
          nextCommitted.push(nextChunk);
        }
      }

      transcriptStateRef.current = {
        active: null,
        committed: nextCommitted,
      };
      setTranscript(nextCommitted);
      setActiveTranscript(null);
    },
    [],
  );

  const flushTranscript = useCallback((): FlushResult => {
    const active = transcriptStateRef.current.active;
    if (!active || !active.text.trim() || isWeakStandalonePartial(active.text, setup.language)) {
      return {
        active: null,
        committed: transcriptStateRef.current.committed,
      };
    }

    return {
      active,
      committed: transcriptStateRef.current.committed,
    };
  }, [setup.language]);

  const finalizeAudioCapture = useCallback(
    async (reason: "pause" | "finish", sessionId: string | null) => {
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
    },
    [resetRecordedAudio, setup.debugEnabled, stopAudioCapture, waitForPendingChunkTasks],
  );

  const sendPcmChunk = useCallback(
    (samples: Float32Array, sourceRate: number) => {
      const task = Promise.resolve().then(() => {
        const normalizedSamples =
          sourceRate === PCM_SAMPLE_RATE ? samples : resampleFloat32(samples, sourceRate, PCM_SAMPLE_RATE);

        if (normalizedSamples.length === 0) {
          return;
        }

        const pcm16 = float32ToPcm16(normalizedSamples);
        const payload = encodeBase64(new Uint8Array(pcm16.buffer));

        sendRealtimeMessage({
          type: "audio_chunk",
          timestamp_ms: Date.now(),
          payload,
          mime_type: "audio/pcm",
          sample_rate_hz: PCM_SAMPLE_RATE,
          channels: PCM_CHANNELS,
        });
      });

      pendingChunkTasksRef.current.add(task);
      void task.finally(() => {
        pendingChunkTasksRef.current.delete(task);
      });
    },
    [sendRealtimeMessage],
  );

  const startAudioCapture = useCallback(async () => {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
    audioStreamRef.current = stream;
    resetRecordedAudio();

    if (setup.debugEnabled) {
      if (typeof MediaRecorder === "undefined") {
        stream.getTracks().forEach((track) => track.stop());
        throw new Error("当前浏览器不支持调试录音");
      }

      const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus"
        : "audio/webm";
      recorderMimeTypeRef.current = mimeType;

      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      recorderRef.current = recorder;
      recorder.addEventListener("dataavailable", (event) => {
        if (!event.data || event.data.size === 0) {
          return;
        }

        recordedChunksRef.current.push(event.data);
      });
      recorder.start(DEBUG_RECORDER_TIMESLICE_MS);
    }

    try {
      const audioContext = new AudioContext({ sampleRate: PCM_SAMPLE_RATE });
      audioContextRef.current = audioContext;

      await audioContext.audioWorklet.addModule(PCM_WORKLET_MODULE_PATH);

      const sourceNode = audioContext.createMediaStreamSource(stream);
      const workletNode = new AudioWorkletNode(audioContext, "pcm-capture-processor", {
        channelCount: PCM_CHANNELS,
        channelCountMode: "explicit",
        numberOfInputs: 1,
        numberOfOutputs: 1,
        outputChannelCount: [PCM_CHANNELS],
        processorOptions: {
          chunkFrames: Math.max(1, Math.round((audioContext.sampleRate * PCM_CHUNK_DURATION_MS) / 1000)),
        },
      });
      const monitorGainNode = audioContext.createGain();
      monitorGainNode.gain.value = 0;

      workletNode.port.onmessage = (event: MessageEvent<Float32Array | ArrayBuffer>) => {
        const value = event.data;
        const samples = value instanceof Float32Array ? value : new Float32Array(value);
        sendPcmChunk(samples, audioContext.sampleRate);
      };

      sourceNode.connect(workletNode);
      workletNode.connect(monitorGainNode);
      monitorGainNode.connect(audioContext.destination);

      sourceNodeRef.current = sourceNode;
      workletNodeRef.current = workletNode;
      monitorGainNodeRef.current = monitorGainNode;

      await audioContext.resume();
    } catch (error) {
      recorderRef.current?.stop();
      recorderRef.current = null;
      audioStreamRef.current?.getTracks().forEach((track) => track.stop());
      audioStreamRef.current = null;
      await stopRealtimePcmCapture();
      resetRecordedAudio();
      throw error;
    }
  }, [resetRecordedAudio, sendPcmChunk, setup.debugEnabled, stopRealtimePcmCapture]);

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
      sessionId: null,
      socketStatus: "connecting",
    });

    try {
      const session = await startRealtimeSession(setup.scenarioId, setup.language, setup.debugEnabled);
      const socket = new WebSocket(session.websocketUrl);
      socketRef.current = socket;

      socket.addEventListener("open", async () => {
        sessionStartedAtRef.current = Date.now();
        setSessionState({
          error: null,
          isConnecting: false,
          isFinalizing: false,
          sessionId: session.sessionId,
          socketStatus: "connected",
        });
        setIsRunning(true);
        sendRealtimeMessage({ type: "start_stream" });
        sendVideoFrameEvent();
        mediaTimerRef.current = window.setInterval(sendVideoFrameEvent, 4000);

        try {
          await startAudioCapture();
        } catch (error) {
          clearMediaTimer();
          clearSocket();
          setIsRunning(false);
          setSessionState((previous) => ({
            ...previous,
            error: error instanceof Error ? error.message : "麦克风启动失败",
          }));
        }
      });

      socket.addEventListener("message", (event) => {
        const payload = JSON.parse(event.data) as RealtimeEvent;
        const partialText = payload.text ?? null;
        const transcriptChunk = payload.chunk;
        const liveInsight = payload.insight;

        if (payload.type === "transcript_partial" && partialText) {
          const currentState = transcriptStateRef.current;
          const activeChunk = currentState.active;
          const latestCommittedChunk = currentState.committed[currentState.committed.length - 1];
          const previewText = activeChunk
            ? cleanPartialTranscript(partialText, activeChunk, setup.language)
            : derivePreviewTextFromLastCommitted(partialText, latestCommittedChunk, setup.language);
          if (!previewText || isWeakStandalonePartial(previewText, setup.language)) {
            return;
          }

          const nextChunk = buildActiveTranscriptChunk(
            previewText,
            activeChunk,
            activeChunk?.startMs ?? buildElapsedMs(sessionStartedAtRef.current),
          );
          transcriptStateRef.current = {
            ...transcriptStateRef.current,
            active: nextChunk,
          };
          setActiveTranscript(nextChunk);
          return;
        }

        if (payload.type === "transcript_final" && transcriptChunk) {
          applyFinalTranscriptChunk(transcriptChunk, payload.replacePrevious === true);
          return;
        }

        if (payload.type === "live_insight" && liveInsight) {
          setInsights((previous) => [liveInsight, ...previous].slice(0, 4));
          return;
        }

        if (payload.type === "session_status" && payload.status === "finished") {
          clearActiveTranscript();
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
        sessionId: null,
        socketStatus: "closed",
      });
    }
  }, [
    clearMediaTimer,
    clearSessionView,
    clearSocket,
    applyFinalTranscriptChunk,
    clearActiveTranscript,
    discardAudioCapture,
    sendRealtimeMessage,
    sendVideoFrameEvent,
    sessionState.isConnecting,
    sessionState.isFinalizing,
    setup.debugEnabled,
    setup.language,
    setup.scenarioId,
    startAudioCapture,
  ]);

  const pause = useCallback(async () => {
    clearActiveTranscript();
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
  }, [clearActiveTranscript, clearMediaTimer, finalizeAudioCapture, sessionState.sessionId]);

  const finish = useCallback(async () => {
    clearActiveTranscript();
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
  }, [clearActiveTranscript, clearMediaTimer, clearSocket, finalizeAudioCapture, sessionState.sessionId]);

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
      return "正在连接后端实时识别通道...";
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
    activeTranscript,
    sessionId: sessionState.sessionId,
    socketStatus: sessionState.socketStatus,
    statusText,
    transcript,
    flushTranscript,
    registerVideoFrameProvider,
    start,
    pause,
    reset,
  };
}
