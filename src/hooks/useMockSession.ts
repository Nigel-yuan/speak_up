"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  finishRealtimeSession,
  startRealtimeSession,
  type OutboundRealtimeMessage,
  type RealtimeEvent,
} from "@/lib/api";
import { getApiBaseUrl } from "@/lib/api-base";
import type {
  CoachPanelState,
  CapturedVideoFrame,
  QAFeedback,
  QAQuestion,
  QAState,
  SessionSetup,
  TrainingMode,
  TranscriptChunk,
} from "@/types/session";

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

interface MainSpeakerAudioGateState {
  dominantRms: number;
  noiseFloorRms: number;
  lastAcceptedAtMs: number;
  acceptedFrames: number;
  suppressedFrames: number;
  voiceprintProfile: Float32Array | null;
  voiceprintBootstrapSum: Float32Array | null;
  voiceprintBootstrapFrames: number;
  voiceprintAcceptedFrames: number;
  voiceprintSuppressedFrames: number;
  voiceprintMismatchFrames: number;
  lastVoiceprintAcceptedAtMs: number;
}

const idleSessionState: SessionState = {
  error: null,
  isConnecting: false,
  isFinalizing: false,
  sessionId: null,
  socketStatus: "idle",
};

const PCM_CHANNELS = 1;
const PCM_CHUNK_DURATION_MS = 100;
const PCM_SAMPLE_RATE = 16000;
const PCM_WORKLET_MODULE_PATH = "/audio/pcm-capture.worklet.js";
const VIDEO_FRAME_INTERVAL_MS = 1000;
const AUDIO_CAPTURE_CONSTRAINTS: MediaStreamConstraints = {
  audio: {
    channelCount: { ideal: PCM_CHANNELS },
    echoCancellation: { ideal: true },
    noiseSuppression: { ideal: true },
    autoGainControl: { ideal: true },
    sampleRate: { ideal: PCM_SAMPLE_RATE },
    sampleSize: { ideal: 16 },
  },
  video: false,
};
const MAIN_SPEAKER_GATE_ABSOLUTE_SILENCE_RMS = 0.0025;
const MAIN_SPEAKER_GATE_MIN_VOICE_RMS = 0.006;
const MAIN_SPEAKER_GATE_DOMINANT_RATIO = 0.32;
const MAIN_SPEAKER_GATE_NOISE_RATIO = 2.4;
const MAIN_SPEAKER_GATE_TRAILING_RATIO = 0.62;
const MAIN_SPEAKER_GATE_TRAILING_MS = 650;
const MAIN_SPEAKER_GATE_DOMINANT_DECAY = 0.996;
const MAIN_SPEAKER_VOICEPRINT_FREQUENCIES_HZ = [
  140, 190, 260, 350, 470, 630, 850, 1150, 1550, 2100, 2850, 3850, 5200,
] as const;
const MAIN_SPEAKER_VOICEPRINT_BOOTSTRAP_FRAMES = 14;
const MAIN_SPEAKER_VOICEPRINT_MIN_RMS = 0.009;
const MAIN_SPEAKER_VOICEPRINT_MATCH_THRESHOLD = 0.58;
const MAIN_SPEAKER_VOICEPRINT_RECENT_MATCH_THRESHOLD = 0.46;
const MAIN_SPEAKER_VOICEPRINT_ADAPT_THRESHOLD = 0.78;
const MAIN_SPEAKER_VOICEPRINT_MISMATCH_GRACE_FRAMES = 2;
const MAIN_SPEAKER_VOICEPRINT_RECENT_ACCEPT_MS = 700;
const MAIN_SPEAKER_VOICEPRINT_ADAPT_RATE = 0.035;
const PARTIAL_FILLER_TOKENS = {
  en: new Set(["um", "uh", "well", "so", "hmm", "hm", "hmmm", "mhm", "mm"]),
  zh: new Set(["嗯", "啊", "额", "呃", "然后", "就是", "哦", "诶", "欸", "哎", "唉", "hmm", "hm", "hmmm", "mhm", "mm"]),
};
const PARTIAL_NOISE_PATTERN = /^[\s,.!?，。！？、…]+$/;
const SHORT_PARTIAL_WORDS_MAX = 3;
const SHORT_PARTIAL_CHARS_MAX = 4;
const ACTIVE_TRANSCRIPT_STALE_MS = 12000;
const idleQAState: QAState = {
  enabled: false,
  phase: "idle",
  currentTurnId: null,
  currentQuestion: null,
  currentQuestionGoal: null,
  latestFeedback: null,
  speaking: false,
  voiceProfileId: null,
};

function createEmptyTranscriptState(): TranscriptStateRef {
  return {
    active: null,
    committed: [],
  };
}

function createMainSpeakerAudioGateState(): MainSpeakerAudioGateState {
  return {
    dominantRms: 0,
    noiseFloorRms: MAIN_SPEAKER_GATE_ABSOLUTE_SILENCE_RMS,
    lastAcceptedAtMs: 0,
    acceptedFrames: 0,
    suppressedFrames: 0,
    voiceprintProfile: null,
    voiceprintBootstrapSum: null,
    voiceprintBootstrapFrames: 0,
    voiceprintAcceptedFrames: 0,
    voiceprintSuppressedFrames: 0,
    voiceprintMismatchFrames: 0,
    lastVoiceprintAcceptedAtMs: 0,
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

function decodeBase64ToBytes(payload: string) {
  const binary = window.atob(payload);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
}

function pcm16BytesToFloat32(bytes: Uint8Array) {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const sampleCount = Math.floor(bytes.byteLength / 2);
  const samples = new Float32Array(sampleCount);

  for (let index = 0; index < sampleCount; index += 1) {
    samples[index] = view.getInt16(index * 2, true) / 0x8000;
  }

  return samples;
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

function calculateRms(samples: Float32Array) {
  if (samples.length === 0) {
    return 0;
  }

  let sum = 0;
  for (let index = 0; index < samples.length; index += 1) {
    const sample = samples[index] ?? 0;
    sum += sample * sample;
  }

  return Math.sqrt(sum / samples.length);
}

function updateMainSpeakerNoiseFloor(state: MainSpeakerAudioGateState, rms: number) {
  const boundedRms = Math.max(rms, MAIN_SPEAKER_GATE_ABSOLUTE_SILENCE_RMS);
  const nextNoiseFloor = state.noiseFloorRms * 0.94 + boundedRms * 0.06;
  state.noiseFloorRms = Math.min(
    Math.max(nextNoiseFloor, MAIN_SPEAKER_GATE_ABSOLUTE_SILENCE_RMS),
    MAIN_SPEAKER_GATE_MIN_VOICE_RMS * 1.5,
  );
}

function acceptMainSpeakerFrame(state: MainSpeakerAudioGateState, rms: number, nowMs: number) {
  const attack = rms >= state.dominantRms ? 0.28 : 0.04;
  state.dominantRms = state.dominantRms * (1 - attack) + rms * attack;
  state.noiseFloorRms = Math.min(
    state.noiseFloorRms * 0.995 + MAIN_SPEAKER_GATE_ABSOLUTE_SILENCE_RMS * 0.005,
    Math.max(state.dominantRms * 0.5, MAIN_SPEAKER_GATE_ABSOLUTE_SILENCE_RMS),
  );
  state.lastAcceptedAtMs = nowMs;
  state.acceptedFrames += 1;
}

function calculateZeroCrossingRate(samples: Float32Array) {
  if (samples.length < 2) {
    return 0;
  }

  let crossings = 0;
  let previous = samples[0] ?? 0;
  for (let index = 1; index < samples.length; index += 1) {
    const current = samples[index] ?? 0;
    if ((previous < 0 && current >= 0) || (previous >= 0 && current < 0)) {
      crossings += 1;
    }
    previous = current;
  }

  return crossings / (samples.length - 1);
}

function calculateGoertzelPower(samples: Float32Array, sampleRate: number, frequencyHz: number) {
  const omega = (2 * Math.PI * frequencyHz) / sampleRate;
  const coefficient = 2 * Math.cos(omega);
  const lastIndex = Math.max(samples.length - 1, 1);
  let previous = 0;
  let previous2 = 0;

  for (let index = 0; index < samples.length; index += 1) {
    const windowValue = 0.5 - 0.5 * Math.cos((2 * Math.PI * index) / lastIndex);
    const value = (samples[index] ?? 0) * windowValue + coefficient * previous - previous2;
    previous2 = previous;
    previous = value;
  }

  return previous2 * previous2 + previous * previous - coefficient * previous * previous2;
}

function normalizeFeatureVector(values: number[]) {
  const mean = values.reduce((sum, value) => sum + value, 0) / values.length;
  let squaredSum = 0;
  const normalized = new Float32Array(values.length);

  for (let index = 0; index < values.length; index += 1) {
    const value = values[index] - mean;
    normalized[index] = value;
    squaredSum += value * value;
  }

  const length = Math.sqrt(squaredSum);
  if (length <= 1e-6) {
    return null;
  }

  for (let index = 0; index < normalized.length; index += 1) {
    normalized[index] /= length;
  }

  return normalized;
}

function extractMainSpeakerVoiceprintFeature(samples: Float32Array) {
  const rms = calculateRms(samples);
  if (rms < MAIN_SPEAKER_VOICEPRINT_MIN_RMS) {
    return null;
  }

  const rawPowers = MAIN_SPEAKER_VOICEPRINT_FREQUENCIES_HZ.map((frequencyHz) => {
    const lowerPower = calculateGoertzelPower(samples, PCM_SAMPLE_RATE, frequencyHz * 0.92);
    const centerPower = calculateGoertzelPower(samples, PCM_SAMPLE_RATE, frequencyHz);
    const upperPower = calculateGoertzelPower(samples, PCM_SAMPLE_RATE, frequencyHz * 1.08);
    return lowerPower + centerPower + upperPower;
  });
  const totalPower = rawPowers.reduce((sum, power) => sum + power, 0) + 1e-9;
  const spectralShape = rawPowers.map((power) =>
    Math.log1p((power / totalPower) * MAIN_SPEAKER_VOICEPRINT_FREQUENCIES_HZ.length),
  );
  const zeroCrossingRate = calculateZeroCrossingRate(samples);

  return normalizeFeatureVector([...spectralShape, zeroCrossingRate * 2.5]);
}

function cosineSimilarity(left: Float32Array, right: Float32Array) {
  const length = Math.min(left.length, right.length);
  let sum = 0;
  for (let index = 0; index < length; index += 1) {
    sum += (left[index] ?? 0) * (right[index] ?? 0);
  }
  return sum;
}

function addVoiceprintBootstrapFrame(state: MainSpeakerAudioGateState, feature: Float32Array) {
  if (!state.voiceprintBootstrapSum) {
    state.voiceprintBootstrapSum = new Float32Array(feature.length);
  }

  for (let index = 0; index < feature.length; index += 1) {
    state.voiceprintBootstrapSum[index] += feature[index] ?? 0;
  }
  state.voiceprintBootstrapFrames += 1;

  if (state.voiceprintBootstrapFrames >= MAIN_SPEAKER_VOICEPRINT_BOOTSTRAP_FRAMES) {
    const averaged = new Float32Array(state.voiceprintBootstrapSum.length);
    for (let index = 0; index < averaged.length; index += 1) {
      averaged[index] = (state.voiceprintBootstrapSum[index] ?? 0) / state.voiceprintBootstrapFrames;
    }
    const normalized = normalizeFeatureVector(Array.from(averaged));
    if (normalized) {
      state.voiceprintProfile = normalized;
      state.lastVoiceprintAcceptedAtMs = typeof performance !== "undefined" ? performance.now() : Date.now();
    }
  }
}

function adaptMainSpeakerVoiceprintProfile(state: MainSpeakerAudioGateState, feature: Float32Array) {
  if (!state.voiceprintProfile) {
    return;
  }

  const adapted = new Array<number>(state.voiceprintProfile.length);
  for (let index = 0; index < state.voiceprintProfile.length; index += 1) {
    adapted[index] =
      (state.voiceprintProfile[index] ?? 0) * (1 - MAIN_SPEAKER_VOICEPRINT_ADAPT_RATE) +
      (feature[index] ?? 0) * MAIN_SPEAKER_VOICEPRINT_ADAPT_RATE;
  }

  const normalized = normalizeFeatureVector(adapted);
  if (normalized) {
    state.voiceprintProfile = normalized;
  }
}

function applyMainSpeakerVoiceprintGate(
  samples: Float32Array,
  state: MainSpeakerAudioGateState,
  nowMs = typeof performance !== "undefined" ? performance.now() : Date.now(),
) {
  if (samples.length === 0 || calculateRms(samples) < MAIN_SPEAKER_VOICEPRINT_MIN_RMS) {
    return samples;
  }

  const feature = extractMainSpeakerVoiceprintFeature(samples);
  if (!feature) {
    return new Float32Array(samples.length);
  }

  if (!state.voiceprintProfile) {
    addVoiceprintBootstrapFrame(state, feature);
    state.voiceprintAcceptedFrames += 1;
    state.lastVoiceprintAcceptedAtMs = nowMs;
    return samples;
  }

  const similarity = cosineSimilarity(feature, state.voiceprintProfile);
  const recentlyAccepted = nowMs - state.lastVoiceprintAcceptedAtMs <= MAIN_SPEAKER_VOICEPRINT_RECENT_ACCEPT_MS;
  const accepted =
    similarity >= MAIN_SPEAKER_VOICEPRINT_MATCH_THRESHOLD ||
    (recentlyAccepted && similarity >= MAIN_SPEAKER_VOICEPRINT_RECENT_MATCH_THRESHOLD);

  if (!accepted) {
    state.voiceprintMismatchFrames += 1;
    if (state.voiceprintMismatchFrames <= MAIN_SPEAKER_VOICEPRINT_MISMATCH_GRACE_FRAMES) {
      return samples;
    }
    state.voiceprintSuppressedFrames += 1;
    return new Float32Array(samples.length);
  }

  state.voiceprintMismatchFrames = 0;
  state.voiceprintAcceptedFrames += 1;
  state.lastVoiceprintAcceptedAtMs = nowMs;
  if (similarity >= MAIN_SPEAKER_VOICEPRINT_ADAPT_THRESHOLD) {
    adaptMainSpeakerVoiceprintProfile(state, feature);
  }
  return samples;
}

function applyMainSpeakerAudioGate(
  samples: Float32Array,
  state: MainSpeakerAudioGateState,
  nowMs = typeof performance !== "undefined" ? performance.now() : Date.now(),
) {
  if (samples.length === 0) {
    return samples;
  }

  const rms = calculateRms(samples);
  state.dominantRms = Math.max(
    state.dominantRms * MAIN_SPEAKER_GATE_DOMINANT_DECAY,
    MAIN_SPEAKER_GATE_MIN_VOICE_RMS,
  );

  if (rms <= MAIN_SPEAKER_GATE_ABSOLUTE_SILENCE_RMS) {
    updateMainSpeakerNoiseFloor(state, rms);
    state.suppressedFrames += 1;
    return new Float32Array(samples.length);
  }

  const threshold = Math.max(
    MAIN_SPEAKER_GATE_MIN_VOICE_RMS,
    state.noiseFloorRms * MAIN_SPEAKER_GATE_NOISE_RATIO,
    state.dominantRms * MAIN_SPEAKER_GATE_DOMINANT_RATIO,
  );
  const recentlyAccepted = nowMs - state.lastAcceptedAtMs <= MAIN_SPEAKER_GATE_TRAILING_MS;
  const accepted =
    rms >= threshold || (recentlyAccepted && rms >= threshold * MAIN_SPEAKER_GATE_TRAILING_RATIO);

  if (!accepted) {
    updateMainSpeakerNoiseFloor(state, rms);
    state.suppressedFrames += 1;
    return new Float32Array(samples.length);
  }

  acceptMainSpeakerFrame(state, rms, nowMs);
  return samples;
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

function resolveApiUrl(url: string | null | undefined) {
  if (!url) {
    return null;
  }

  if (url.startsWith("http")) {
    return url;
  }

  return `${getApiBaseUrl()}${url}`;
}

export function useMockSession(setup: SessionSetup) {
  const socketRef = useRef<WebSocket | null>(null);
  const mediaTimerRef = useRef<number | null>(null);
  const videoFrameProviderRef = useRef<(() => Promise<CapturedVideoFrame | null>) | null>(null);
  const videoFrameSendInFlightRef = useRef(false);
  const audioStreamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const sourceNodeRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const workletNodeRef = useRef<AudioWorkletNode | null>(null);
  const monitorGainNodeRef = useRef<GainNode | null>(null);
  const replayAudioDestinationRef = useRef<MediaStreamAudioDestinationNode | null>(null);
  const replayInputGainNodeRef = useRef<GainNode | null>(null);
  const pendingChunkTasksRef = useRef<Set<Promise<void>>>(new Set());
  const sessionStartedAtRef = useRef<number | null>(null);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [isRunning, setIsRunning] = useState(false);
  const [audioCaptureStream, setAudioCaptureStream] = useState<MediaStream | null>(null);
  const [transcript, setTranscript] = useState<TranscriptChunk[]>([]);
  const [activeTranscript, setActiveTranscript] = useState<TranscriptChunk | null>(null);
  const activeTranscriptExpiryTimerRef = useRef<number | null>(null);
  const [coachPanel, setCoachPanel] = useState<CoachPanelState | null>(null);
  const [qaState, setQAState] = useState<QAState>(idleQAState);
  const [qaQuestion, setQAQuestion] = useState<QAQuestion | null>(null);
  const [qaFeedback, setQAFeedback] = useState<QAFeedback | null>(null);
  const [qaAudioUrl, setQAAudioUrl] = useState<string | null>(null);
  const [qaAudioAutoPlay, setQAAudioAutoPlay] = useState(false);
  const qaAudioContextRef = useRef<AudioContext | null>(null);
  const qaAudioSourceNodesRef = useRef<Set<AudioBufferSourceNode>>(new Set());
  const qaAudioPlaybackTimeRef = useRef(0);
  const qaAudioTurnRef = useRef<string | null>(null);
  const qaAudioEndTimerRef = useRef<number | null>(null);
  const qaAudioLiveChunkCountRef = useRef(0);
  const qaAudioShouldFallbackToFileRef = useRef(false);
  const qaPlaybackStateRef = useRef<{ turnId: string | null; playing: boolean }>({
    turnId: null,
    playing: false,
  });
  const interviewerSpeakingRef = useRef(false);
  const [interviewerSpeaking, setInterviewerSpeakingState] = useState(false);
  const qaStateRef = useRef<QAState>(idleQAState);
  const [sessionState, setSessionState] = useState<SessionState>(idleSessionState);
  const transcriptStateRef = useRef<TranscriptStateRef>(createEmptyTranscriptState());
  const mainSpeakerAudioGateRef = useRef<MainSpeakerAudioGateState>(createMainSpeakerAudioGateState());

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

  const ensureQAAudioContext = useCallback(() => {
    let audioContext = audioContextRef.current ?? qaAudioContextRef.current;
    if (!audioContext || audioContext.state === "closed") {
      audioContext = new AudioContext({ sampleRate: 24000 });
    }
    qaAudioContextRef.current = audioContext;

    void audioContext.resume().catch(() => {
      qaAudioShouldFallbackToFileRef.current = true;
    });

    return audioContext;
  }, []);

  const stopQAAudioPlayback = useCallback(() => {
    if (qaAudioEndTimerRef.current !== null) {
      window.clearTimeout(qaAudioEndTimerRef.current);
      qaAudioEndTimerRef.current = null;
    }
    for (const source of qaAudioSourceNodesRef.current) {
      try {
        source.stop();
      } catch {
        // ignore stop races while tearing down playback
      }
      try {
        source.disconnect();
      } catch {
        // ignore disconnect races while tearing down playback
      }
    }
    qaAudioSourceNodesRef.current.clear();
    qaAudioTurnRef.current = null;
    qaAudioPlaybackTimeRef.current = 0;
    qaAudioLiveChunkCountRef.current = 0;
    qaAudioShouldFallbackToFileRef.current = false;
    qaPlaybackStateRef.current = { turnId: null, playing: false };
    interviewerSpeakingRef.current = false;
    setInterviewerSpeakingState(false);
  }, []);

  const destroyQAAudioOutput = useCallback(() => {
    stopQAAudioPlayback();
    const audioContext = qaAudioContextRef.current;
    qaAudioContextRef.current = null;
    if (audioContext && audioContext !== audioContextRef.current && audioContext.state !== "closed") {
      void audioContext.close();
    }
  }, [stopQAAudioPlayback]);

  const clearSessionView = useCallback(() => {
    destroyQAAudioOutput();
    transcriptStateRef.current = createEmptyTranscriptState();
    mainSpeakerAudioGateRef.current = createMainSpeakerAudioGateState();
    sessionStartedAtRef.current = null;
    setIsRunning(false);
    setAudioCaptureStream(null);
    setElapsedSeconds(0);
    setTranscript([]);
    setActiveTranscript(null);
    setCoachPanel(null);
    setQAState(idleQAState);
    setQAQuestion(null);
    setQAFeedback(null);
    setQAAudioUrl(null);
    setQAAudioAutoPlay(false);
    qaStateRef.current = idleQAState;
    setSessionState(idleSessionState);
  }, [destroyQAAudioOutput]);

  const sendRealtimeMessage = useCallback((message: OutboundRealtimeMessage) => {
    const socket = socketRef.current;

    if (!socket || socket.readyState !== WebSocket.OPEN) {
      return;
    }

    socket.send(JSON.stringify(message));
  }, []);

  const notifyQAAudioPlaybackStarted = useCallback((turnId: string) => {
    const current = qaPlaybackStateRef.current;
    if (current.turnId === turnId && current.playing) {
      return;
    }

    qaPlaybackStateRef.current = { turnId, playing: true };
    sendRealtimeMessage({
      type: "qa_audio_playback_started",
      turn_id: turnId,
      timestamp_ms: Date.now(),
    });
  }, [sendRealtimeMessage]);

  const notifyQAAudioPlaybackEnded = useCallback((turnId: string) => {
    const current = qaPlaybackStateRef.current;
    if (current.turnId === turnId && !current.playing) {
      return;
    }

    qaPlaybackStateRef.current = { turnId, playing: false };
    sendRealtimeMessage({
      type: "qa_audio_playback_ended",
      turn_id: turnId,
      timestamp_ms: Date.now(),
    });
  }, [sendRealtimeMessage]);

  const startQAAudioStream = useCallback((turnId: string) => {
    stopQAAudioPlayback();
    const audioContext = ensureQAAudioContext();
    qaAudioPlaybackTimeRef.current = audioContext.currentTime;
    qaAudioTurnRef.current = turnId;
    qaAudioLiveChunkCountRef.current = 0;
    qaAudioShouldFallbackToFileRef.current = false;
    interviewerSpeakingRef.current = true;
    setInterviewerSpeakingState(true);
    notifyQAAudioPlaybackStarted(turnId);
  }, [ensureQAAudioContext, notifyQAAudioPlaybackStarted, stopQAAudioPlayback]);

  const appendQAAudioStreamDelta = useCallback((turnId: string, audioBase64: string, sampleRateHz: number) => {
    const audioContext = qaAudioContextRef.current;
    if (!audioContext || qaAudioTurnRef.current !== turnId || !audioBase64) {
      return;
    }

    const samples = pcm16BytesToFloat32(decodeBase64ToBytes(audioBase64));
    if (samples.length === 0) {
      return;
    }

    const buffer = audioContext.createBuffer(1, samples.length, sampleRateHz);
    buffer.copyToChannel(samples, 0);

    const source = audioContext.createBufferSource();
    source.buffer = buffer;
    source.connect(audioContext.destination);
    if (replayAudioDestinationRef.current) {
      source.connect(replayAudioDestinationRef.current);
    }
    qaAudioSourceNodesRef.current.add(source);
    source.onended = () => {
      qaAudioSourceNodesRef.current.delete(source);
      try {
        source.disconnect();
      } catch {
        // ignore disconnect races after playback completion
      }
    };

    const startAt = Math.max(audioContext.currentTime + 0.02, qaAudioPlaybackTimeRef.current);
    source.start(startAt);
    qaAudioPlaybackTimeRef.current = startAt + buffer.duration;
    qaAudioLiveChunkCountRef.current += 1;
  }, []);

  const finishQAAudioStream = useCallback((turnId: string) => {
    const audioContext = qaAudioContextRef.current;
    if (!audioContext || qaAudioTurnRef.current !== turnId) {
      notifyQAAudioPlaybackEnded(turnId);
      stopQAAudioPlayback();
      return;
    }

    const remainingMs = Math.max((qaAudioPlaybackTimeRef.current - audioContext.currentTime) * 1000, 0);
    if (qaAudioEndTimerRef.current !== null) {
      window.clearTimeout(qaAudioEndTimerRef.current);
    }
    qaAudioEndTimerRef.current = window.setTimeout(() => {
      notifyQAAudioPlaybackEnded(turnId);
      stopQAAudioPlayback();
    }, remainingMs + 120);
  }, [notifyQAAudioPlaybackEnded, stopQAAudioPlayback]);

  const sendVideoFrameEvent = useCallback(() => {
    if (videoFrameSendInFlightRef.current) {
      return;
    }

    videoFrameSendInFlightRef.current = true;
    void (async () => {
      try {
        const timestamp = Date.now();
        const frame = (await videoFrameProviderRef.current?.()) ?? null;
        sendRealtimeMessage({
          type: "video_frame",
          timestamp_ms: timestamp,
          image_base64: frame?.imageBase64,
          body_visual_hint: frame?.bodyVisualHint,
        });
      } finally {
        videoFrameSendInFlightRef.current = false;
      }
    })();
  }, [sendRealtimeMessage]);

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
    const replayAudioDestination = replayAudioDestinationRef.current;
    const replayInputGainNode = replayInputGainNodeRef.current;
    const audioContext = audioContextRef.current;

    workletNodeRef.current = null;
    sourceNodeRef.current = null;
    monitorGainNodeRef.current = null;
    replayAudioDestinationRef.current = null;
    replayInputGainNodeRef.current = null;
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

    try {
      replayInputGainNode?.disconnect();
    } catch {
      // ignore disconnect errors during teardown
    }

    try {
      replayAudioDestination?.disconnect();
    } catch {
      // ignore disconnect errors during teardown
    }

    if (audioContext && audioContext.state !== "closed") {
      await audioContext.close();
    }
  }, []);

  const stopAudioCapture = useCallback(async () => {
    const stream = audioStreamRef.current;

    audioStreamRef.current = null;
    setAudioCaptureStream(null);

    await stopRealtimePcmCapture();
    stream?.getTracks().forEach((track) => track.stop());
  }, [stopRealtimePcmCapture]);

  const discardAudioCapture = useCallback(async () => {
    await stopAudioCapture();
    await waitForPendingChunkTasks();
  }, [stopAudioCapture, waitForPendingChunkTasks]);

  const clearActiveTranscriptExpiryTimer = useCallback(() => {
    if (activeTranscriptExpiryTimerRef.current !== null) {
      window.clearTimeout(activeTranscriptExpiryTimerRef.current);
      activeTranscriptExpiryTimerRef.current = null;
    }
  }, []);

  const clearActiveTranscript = useCallback(() => {
    clearActiveTranscriptExpiryTimer();
    transcriptStateRef.current = {
      ...transcriptStateRef.current,
      active: null,
    };
    setActiveTranscript(null);
  }, [clearActiveTranscriptExpiryTimer]);

  const scheduleActiveTranscriptExpiry = useCallback(
    (chunk: TranscriptChunk) => {
      clearActiveTranscriptExpiryTimer();
      activeTranscriptExpiryTimerRef.current = window.setTimeout(() => {
        const currentActive = transcriptStateRef.current.active;
        if (currentActive?.id !== chunk.id || currentActive.text !== chunk.text) {
          return;
        }
        transcriptStateRef.current = {
          ...transcriptStateRef.current,
          active: null,
        };
        setActiveTranscript(null);
        activeTranscriptExpiryTimerRef.current = null;
      }, ACTIVE_TRANSCRIPT_STALE_MS);
    },
    [clearActiveTranscriptExpiryTimer],
  );

  const applyFinalTranscriptChunk = useCallback(
    (incomingChunk: TranscriptChunk, replacePrevious: boolean) => {
      clearActiveTranscriptExpiryTimer();
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
    [clearActiveTranscriptExpiryTimer],
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

  const flushActiveTranscript = useCallback((): FlushResult => {
    const result = flushTranscript();
    if (!result.active) {
      clearActiveTranscript();
      return result;
    }

    const nextCommitted = [...result.committed];
    const lastCommitted = nextCommitted[nextCommitted.length - 1];
    if (lastCommitted && lastCommitted.text.trim() === result.active.text.trim()) {
      nextCommitted[nextCommitted.length - 1] = result.active;
    } else {
      nextCommitted.push(result.active);
    }

    clearActiveTranscriptExpiryTimer();
    transcriptStateRef.current = {
      active: null,
      committed: nextCommitted,
    };
    setTranscript(nextCommitted);
    setActiveTranscript(null);
    return {
      active: result.active,
      committed: nextCommitted,
    };
  }, [clearActiveTranscript, clearActiveTranscriptExpiryTimer, flushTranscript]);

  const sendPcmChunk = useCallback(
    (samples: Float32Array, sourceRate: number) => {
      const task = Promise.resolve().then(() => {
        const normalizedSamples =
          sourceRate === PCM_SAMPLE_RATE ? samples : resampleFloat32(samples, sourceRate, PCM_SAMPLE_RATE);

        if (normalizedSamples.length === 0) {
          return;
        }

        if (
          qaStateRef.current.enabled &&
          (qaStateRef.current.phase === "preparing_context" || qaStateRef.current.phase === "ai_asking")
        ) {
          return;
        }

        if (interviewerSpeakingRef.current) {
          return;
        }

        const energyGatedSamples = applyMainSpeakerAudioGate(normalizedSamples, mainSpeakerAudioGateRef.current);
        const gatedSamples = applyMainSpeakerVoiceprintGate(energyGatedSamples, mainSpeakerAudioGateRef.current);
        const pcm16 = float32ToPcm16(gatedSamples);
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
    mainSpeakerAudioGateRef.current = createMainSpeakerAudioGateState();
    const stream = await navigator.mediaDevices.getUserMedia(AUDIO_CAPTURE_CONSTRAINTS);
    audioStreamRef.current = stream;

    try {
      const audioContext = new AudioContext({ sampleRate: PCM_SAMPLE_RATE });
      audioContextRef.current = audioContext;
      qaAudioContextRef.current = audioContext;

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
      const replayAudioDestination = audioContext.createMediaStreamDestination();
      const replayInputGainNode = audioContext.createGain();
      monitorGainNode.gain.value = 0;
      replayInputGainNode.gain.value = 1;

      workletNode.port.onmessage = (event: MessageEvent<Float32Array | ArrayBuffer>) => {
        const value = event.data;
        const samples = value instanceof Float32Array ? value : new Float32Array(value);
        sendPcmChunk(samples, audioContext.sampleRate);
      };

      sourceNode.connect(workletNode);
      sourceNode.connect(replayInputGainNode);
      workletNode.connect(monitorGainNode);
      replayInputGainNode.connect(replayAudioDestination);
      monitorGainNode.connect(audioContext.destination);

      sourceNodeRef.current = sourceNode;
      workletNodeRef.current = workletNode;
      monitorGainNodeRef.current = monitorGainNode;
      replayAudioDestinationRef.current = replayAudioDestination;
      replayInputGainNodeRef.current = replayInputGainNode;
      setAudioCaptureStream(replayAudioDestination.stream);

      await audioContext.resume();
    } catch (error) {
      audioStreamRef.current?.getTracks().forEach((track) => track.stop());
      audioStreamRef.current = null;
      setAudioCaptureStream(null);
      await stopRealtimePcmCapture();
      throw error;
    }
  }, [sendPcmChunk, stopRealtimePcmCapture]);

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
      const session = await startRealtimeSession(setup.scenarioId, setup.language, setup.coachProfileId);
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
        sendRealtimeMessage({
          type: "start_stream",
          training_mode: setup.trainingMode ?? "free_speech",
          document_name: setup.documentName ?? undefined,
          document_text: setup.documentText ?? undefined,
          manual_text: setup.manualText ?? undefined,
        });
        sendVideoFrameEvent();
        mediaTimerRef.current = window.setInterval(sendVideoFrameEvent, VIDEO_FRAME_INTERVAL_MS);

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
          scheduleActiveTranscriptExpiry(nextChunk);
          return;
        }

        if (payload.type === "transcript_final" && transcriptChunk) {
          applyFinalTranscriptChunk(transcriptChunk, payload.replacePrevious === true);
          return;
        }

        if (payload.type === "coach_panel" && payload.coachPanel) {
          setCoachPanel(payload.coachPanel);
          return;
        }

        if (payload.type === "qa_state" && payload.qaState) {
          qaStateRef.current = payload.qaState;
          if (payload.qaState.phase === "preparing_context") {
            stopQAAudioPlayback();
            setQAAudioUrl(null);
            setQAAudioAutoPlay(false);
          }
          setQAState(payload.qaState);
          return;
        }

        if (payload.type === "qa_question" && payload.question) {
          setQAAudioUrl((current) => (payload.question?.turnId && current ? null : current));
          setQAAudioAutoPlay(false);
          setQAQuestion(payload.question);
          return;
        }

        if (payload.type === "qa_feedback" && payload.feedback) {
          setQAFeedback(payload.feedback);
          return;
        }

        if (payload.type === "qa_audio_stream_start" && payload.turnId) {
          setQAAudioUrl(null);
          setQAAudioAutoPlay(false);
          startQAAudioStream(payload.turnId);
          return;
        }

        if (payload.type === "qa_audio_stream_delta" && payload.turnId && payload.audioBase64) {
          appendQAAudioStreamDelta(payload.turnId, payload.audioBase64, payload.sampleRateHz ?? 24000);
          return;
        }

        if (payload.type === "qa_audio_stream_end" && payload.turnId) {
          finishQAAudioStream(payload.turnId);
          if (payload.audioUrl) {
            setQAAudioUrl(resolveApiUrl(payload.audioUrl));
            setQAAudioAutoPlay(
              qaAudioLiveChunkCountRef.current === 0 || qaAudioShouldFallbackToFileRef.current,
            );
          }
          return;
        }

        if (payload.type === "qa_audio" && payload.audioUrl) {
          setQAAudioUrl(resolveApiUrl(payload.audioUrl));
          setQAAudioAutoPlay(true);
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
    scheduleActiveTranscriptExpiry,
    discardAudioCapture,
    sendRealtimeMessage,
    sendVideoFrameEvent,
    sessionState.isConnecting,
    sessionState.isFinalizing,
    setup.documentName,
    setup.documentText,
    setup.coachProfileId,
    setup.language,
    setup.manualText,
    setup.scenarioId,
    setup.trainingMode,
    startQAAudioStream,
    appendQAAudioStreamDelta,
    finishQAAudioStream,
    stopQAAudioPlayback,
    startAudioCapture,
  ]);

  const finish = useCallback(async () => {
    clearActiveTranscript();
    setIsRunning(false);
    clearMediaTimer();
    setSessionState((previous) => ({ ...previous, error: null, isFinalizing: true }));

    try {
      await stopAudioCapture();
      await waitForPendingChunkTasks();
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
  }, [clearActiveTranscript, clearMediaTimer, clearSocket, sessionState.sessionId, stopAudioCapture, waitForPendingChunkTasks]);

  const registerVideoFrameProvider = useCallback((provider: () => Promise<CapturedVideoFrame | null>) => {
    videoFrameProviderRef.current = provider;
  }, []);

  const startQA = useCallback((payload: {
    trainingMode: TrainingMode;
    voiceProfileId: string;
    documentName?: string | null;
    documentText?: string | null;
    manualText?: string | null;
  }) => {
    const nextState: QAState = {
      ...qaStateRef.current,
      enabled: true,
      phase: "preparing_context",
      currentTurnId: null,
      currentQuestion: null,
      currentQuestionGoal: null,
      latestFeedback: null,
      speaking: false,
      voiceProfileId: payload.voiceProfileId,
    };
    qaStateRef.current = nextState;
    setQAState(nextState);
    setQAQuestion(null);
    setQAFeedback(null);
    setQAAudioUrl(null);
    setQAAudioAutoPlay(false);
    sendRealtimeMessage({
      type: "start_qa",
      training_mode: payload.trainingMode,
      voice_profile_id: payload.voiceProfileId,
      document_name: payload.documentName ?? undefined,
      document_text: payload.documentText ?? undefined,
      manual_text: payload.manualText ?? undefined,
    });
  }, [sendRealtimeMessage]);

  const updateQAPrewarmContext = useCallback((payload: {
    trainingMode: TrainingMode;
    documentName?: string | null;
    documentText?: string | null;
    manualText?: string | null;
  }) => {
    sendRealtimeMessage({
      type: "qa_prewarm_context",
      training_mode: payload.trainingMode,
      document_name: payload.documentName ?? undefined,
      document_text: payload.documentText ?? undefined,
      manual_text: payload.manualText ?? undefined,
    });
  }, [sendRealtimeMessage]);

  const stopQA = useCallback(() => {
    stopQAAudioPlayback();
    setQAState(idleQAState);
    setQAAudioUrl(null);
    setQAAudioAutoPlay(false);
    setQAQuestion(null);
    setQAFeedback(null);
    qaStateRef.current = idleQAState;
    sendRealtimeMessage({ type: "stop_qa" });
  }, [sendRealtimeMessage, stopQAAudioPlayback]);

  const selectVoiceProfile = useCallback((voiceProfileId: string) => {
    sendRealtimeMessage({
      type: "qa_select_voice_profile",
      voice_profile_id: voiceProfileId,
    });
  }, [sendRealtimeMessage]);

  const setInterviewerSpeaking = useCallback((value: boolean) => {
    interviewerSpeakingRef.current = value;
    setInterviewerSpeakingState(value);
  }, []);

  const silenceInterviewer = useCallback(() => {
    stopQAAudioPlayback();
    setQAAudioUrl(null);
    setQAAudioAutoPlay(false);
  }, [stopQAAudioPlayback]);

  const statusText = useMemo(() => {
    if (sessionState.error) {
      return sessionState.error;
    }

    if (sessionState.isConnecting) {
      return "正在连接后端实时识别通道...";
    }

    if (sessionState.isFinalizing) {
      return "正在结束会话...";
    }

    return null;
  }, [sessionState.error, sessionState.isConnecting, sessionState.isFinalizing]);

  useEffect(() => {
    return () => {
      clearActiveTranscriptExpiryTimer();
      clearMediaTimer();
      clearSocket();
      stopQAAudioPlayback();
      void discardAudioCapture();
    };
  }, [clearActiveTranscriptExpiryTimer, clearMediaTimer, clearSocket, discardAudioCapture, stopQAAudioPlayback]);

  return {
    audioCaptureStream,
    coachPanel,
    elapsedSeconds,
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
    flushActiveTranscript,
    qaState,
    qaQuestion,
    qaFeedback,
    qaAudioUrl,
    qaAudioAutoPlay,
    interviewerSpeaking,
    notifyQAAudioPlaybackEnded,
    notifyQAAudioPlaybackStarted,
    setInterviewerSpeaking,
    silenceInterviewer,
    startQA,
    updateQAPrewarmContext,
    stopQA,
    selectVoiceProfile,
    registerVideoFrameProvider,
    start,
  };
}
