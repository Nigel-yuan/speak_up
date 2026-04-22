const PRIME_SAMPLE_RATE = 22050;
const FADE_OUT_SECONDS = 0.45;

type WebAudioCtor = typeof AudioContext;

export interface AudioPlaybackHandle {
  stop: (smooth: boolean) => void;
}

let audioContextInstance: AudioContext | null = null;

function getAudioContextCtor(): WebAudioCtor | null {
  if (typeof window === "undefined") {
    return null;
  }
  return window.AudioContext ?? null;
}

async function ensureAudioContext() {
  const AudioContextCtor = getAudioContextCtor();
  if (!AudioContextCtor) {
    throw new Error("当前浏览器不支持 AudioContext");
  }
  if (!audioContextInstance) {
    audioContextInstance = new AudioContextCtor();
  }
  if (audioContextInstance.state === "suspended") {
    await audioContextInstance.resume();
  }
  return audioContextInstance;
}

function cleanupNodes(source: AudioBufferSourceNode, gainNode: GainNode) {
  try {
    source.disconnect();
  } catch {
    // noop
  }
  try {
    gainNode.disconnect();
  } catch {
    // noop
  }
}

export function primeAudioPlayback() {
  if (typeof window === "undefined") {
    return;
  }
  void ensureAudioContext()
    .then((context) => {
      const buffer = context.createBuffer(1, 1, PRIME_SAMPLE_RATE);
      const source = context.createBufferSource();
      const gainNode = context.createGain();
      gainNode.gain.value = 0;
      source.buffer = buffer;
      source.connect(gainNode);
      gainNode.connect(context.destination);
      source.start();
      source.stop(context.currentTime + 0.001);
      source.onended = () => {
        cleanupNodes(source, gainNode);
      };
    })
    .catch(() => undefined);
}

export async function playBufferedAudioFromUrl(
  url: string,
  options?: {
    volume?: number;
    onEnded?: () => void;
  },
): Promise<AudioPlaybackHandle> {
  const context = await ensureAudioContext();
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`音频下载失败: ${response.status}`);
  }
  const bytes = await response.arrayBuffer();
  const audioBuffer = await context.decodeAudioData(bytes.slice(0));

  const source = context.createBufferSource();
  const gainNode = context.createGain();
  gainNode.gain.value = options?.volume ?? 1;
  source.buffer = audioBuffer;
  source.connect(gainNode);
  gainNode.connect(context.destination);

  let stopped = false;
  source.onended = () => {
    cleanupNodes(source, gainNode);
    if (!stopped) {
      options?.onEnded?.();
    }
  };

  source.start();

  return {
    stop(smooth: boolean) {
      if (stopped) {
        return;
      }
      stopped = true;
      const stopAt = smooth ? context.currentTime + FADE_OUT_SECONDS : context.currentTime;
      try {
        if (smooth) {
          gainNode.gain.cancelScheduledValues(context.currentTime);
          gainNode.gain.setValueAtTime(gainNode.gain.value, context.currentTime);
          gainNode.gain.linearRampToValueAtTime(0, stopAt);
        }
        source.stop(stopAt);
      } catch {
        cleanupNodes(source, gainNode);
      }
    },
  };
}

export function scheduleAudioPlaybackRetry(retry: () => void) {
  if (typeof window === "undefined") {
    return () => undefined;
  }

  let cleaned = false;
  const options: AddEventListenerOptions = { capture: true };
  const onGesture = () => {
    cleanup();
    retry();
  };

  const cleanup = () => {
    if (cleaned) {
      return;
    }
    cleaned = true;
    window.removeEventListener("pointerdown", onGesture, options);
    window.removeEventListener("keydown", onGesture, options);
    window.removeEventListener("touchstart", onGesture, options);
  };

  window.addEventListener("pointerdown", onGesture, options);
  window.addEventListener("keydown", onGesture, options);
  window.addEventListener("touchstart", onGesture, options);
  return cleanup;
}
