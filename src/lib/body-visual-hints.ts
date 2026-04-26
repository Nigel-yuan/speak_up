import type { FaceLandmarker, HandLandmarker, ImageSource, NormalizedLandmark } from "@mediapipe/tasks-vision";

import type { BodyVisualHint } from "@/types/session";

const MEDIAPIPE_WASM_URL = "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.34/wasm";
const FACE_LANDMARKER_MODEL_URL =
  "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task";
const HAND_LANDMARKER_MODEL_URL =
  "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task";

const MOUTH_LANDMARKS = [
  0, 13, 14, 17, 37, 39, 40, 61, 78, 80, 81, 82, 84, 87, 88, 91, 95, 146, 178,
  181, 191, 267, 269, 270, 291, 308, 310, 311, 312, 314, 317, 318, 321, 324,
  375, 402, 405, 415,
];
const LEFT_EYE_LANDMARKS = [7, 33, 133, 144, 145, 153, 154, 155, 157, 158, 159, 160, 161, 163, 173, 246];
const RIGHT_EYE_LANDMARKS = [249, 263, 362, 373, 374, 380, 381, 382, 384, 385, 386, 387, 388, 390, 398, 466];
const NOSE_LANDMARKS = [1, 2, 4, 5, 6, 19, 94, 97, 98, 168, 195, 197, 326, 327];
const PALM_LANDMARKS = [0, 1, 5, 9, 13, 17];
const HEAD_TILT_ADJUST_DEGREES = 20;
const HEAD_TILT_HIGH_DEGREES = 28;
const HEAD_TILT_EXTREME_DEGREES = 34;
const HEAD_TILT_RESET_DEGREES = 14;
const HEAD_TILT_STRONG_STREAK = 2;
const HEAD_TILT_NORMAL_STREAK = 3;
const HEAD_TILT_STREAK_RESET_MS = 2800;
const HEAD_TILT_EMIT_COOLDOWN_MS = 7000;
const MEDIAPIPE_CONSOLE_FILTER_MARKER = "__speakUpMediapipeNoiseFilter";

interface LandmarkBounds {
  left: number;
  right: number;
  top: number;
  bottom: number;
  width: number;
  height: number;
}

interface BodyVisualDetectors {
  faceLandmarker: FaceLandmarker;
  handLandmarker: HandLandmarker;
}

interface HeadTiltState {
  direction: -1 | 0 | 1;
  streak: number;
  lastAtMs: number;
  lastEmittedAtMs: number;
}

let detectorsPromise: Promise<BodyVisualDetectors | null> | null = null;
let detectorInitFailed = false;
let headTiltState: HeadTiltState = {
  direction: 0,
  streak: 0,
  lastAtMs: 0,
  lastEmittedAtMs: 0,
};

export async function analyzeBodyVisualHint(image: ImageSource): Promise<BodyVisualHint | null> {
  installMediapipeConsoleNoiseFilter();
  const detectors = await getBodyVisualDetectors();
  if (!detectors) {
    return null;
  }

  try {
    const timestamp = Math.round(performance.now());
    const faceResult = detectors.faceLandmarker.detectForVideo(image, timestamp);
    const handResult = detectors.handLandmarker.detectForVideo(image, timestamp);
    const face = faceResult.faceLandmarks[0];
    const hands = handResult.landmarks;
    if (!face) {
      resetHeadTiltState();
      return null;
    }

    const handFaceIssue = hands.length > 0 ? detectHandFaceIssue(face, hands) : null;
    const alignmentIssue = detectFaceAlignmentIssue(face);
    if (handFaceIssue?.issue === "face_occlusion") {
      return handFaceIssue;
    }
    if (alignmentIssue && (!handFaceIssue || alignmentIssue.confidence >= 0.86)) {
      return alignmentIssue;
    }
    return handFaceIssue ?? alignmentIssue;
  } catch {
    return null;
  }
}

async function getBodyVisualDetectors(): Promise<BodyVisualDetectors | null> {
  if (detectorInitFailed) {
    return null;
  }

  detectorsPromise ??= initializeBodyVisualDetectors();
  return detectorsPromise;
}

async function initializeBodyVisualDetectors(): Promise<BodyVisualDetectors | null> {
  try {
    installMediapipeConsoleNoiseFilter();
    const { FaceLandmarker, FilesetResolver, HandLandmarker } = await import("@mediapipe/tasks-vision");
    const vision = await FilesetResolver.forVisionTasks(MEDIAPIPE_WASM_URL);
    try {
      return await createBodyVisualDetectors(FaceLandmarker, HandLandmarker, vision, "GPU");
    } catch {
      return await createBodyVisualDetectors(FaceLandmarker, HandLandmarker, vision, "CPU");
    }
  } catch {
    detectorInitFailed = true;
    return null;
  }
}

async function createBodyVisualDetectors(
  FaceLandmarkerClass: typeof FaceLandmarker,
  HandLandmarkerClass: typeof HandLandmarker,
  vision: Awaited<ReturnType<typeof import("@mediapipe/tasks-vision").FilesetResolver.forVisionTasks>>,
  delegate: "CPU" | "GPU",
): Promise<BodyVisualDetectors> {
  const [faceLandmarker, handLandmarker] = await Promise.all([
    FaceLandmarkerClass.createFromOptions(vision, {
      baseOptions: {
        modelAssetPath: FACE_LANDMARKER_MODEL_URL,
        delegate,
      },
      runningMode: "VIDEO",
      numFaces: 1,
      minFaceDetectionConfidence: 0.55,
      minFacePresenceConfidence: 0.55,
      minTrackingConfidence: 0.55,
    }),
    HandLandmarkerClass.createFromOptions(vision, {
      baseOptions: {
        modelAssetPath: HAND_LANDMARKER_MODEL_URL,
        delegate,
      },
      runningMode: "VIDEO",
      numHands: 2,
      minHandDetectionConfidence: 0.5,
      minHandPresenceConfidence: 0.5,
      minTrackingConfidence: 0.5,
    }),
  ]);

  return { faceLandmarker, handLandmarker };
}

type ConsoleErrorWithMarker = typeof console.error & {
  [MEDIAPIPE_CONSOLE_FILTER_MARKER]?: true;
};

function installMediapipeConsoleNoiseFilter() {
  if (typeof window === "undefined") {
    return;
  }

  const currentError = console.error as ConsoleErrorWithMarker;
  if (currentError[MEDIAPIPE_CONSOLE_FILTER_MARKER]) {
    return;
  }

  const originalError = console.error.bind(console);
  const filteredError: ConsoleErrorWithMarker = (...args: unknown[]) => {
    if (isKnownMediapipeConsoleNoise(args)) {
      return;
    }
    originalError(...args);
  };
  filteredError[MEDIAPIPE_CONSOLE_FILTER_MARKER] = true;
  console.error = filteredError;
}

function isKnownMediapipeConsoleNoise(args: unknown[]) {
  return args.some((arg) => {
    if (typeof arg !== "string") {
      return false;
    }
    return arg.includes("Created TensorFlow Lite XNNPACK delegate for CPU");
  });
}

function detectHandFaceIssue(face: NormalizedLandmark[], hands: NormalizedLandmark[][]): BodyVisualHint | null {
  const faceBounds = buildBounds(face, allIndices(face.length), 0, 0);
  if (!faceBounds) {
    return null;
  }

  const mouthBounds = buildBounds(face, MOUTH_LANDMARKS, faceBounds.width * 0.1, faceBounds.height * 0.08);
  const leftEyeBounds = buildBounds(face, LEFT_EYE_LANDMARKS, faceBounds.width * 0.08, faceBounds.height * 0.08);
  const rightEyeBounds = buildBounds(face, RIGHT_EYE_LANDMARKS, faceBounds.width * 0.08, faceBounds.height * 0.08);
  const noseBounds = buildBounds(face, NOSE_LANDMARKS, faceBounds.width * 0.08, faceBounds.height * 0.08);
  const expandedFaceBounds = expandBounds(faceBounds, faceBounds.width * 0.08, faceBounds.height * 0.08);

  for (const hand of hands) {
    const handFaceHits = countLandmarksInBounds(hand, expandedFaceBounds);
    const mouthHits = mouthBounds ? countLandmarksInBounds(hand, mouthBounds) : 0;
    const eyeHits =
      (leftEyeBounds ? countLandmarksInBounds(hand, leftEyeBounds) : 0) +
      (rightEyeBounds ? countLandmarksInBounds(hand, rightEyeBounds) : 0);
    const noseHits = noseBounds ? countLandmarksInBounds(hand, noseBounds) : 0;
    const palmCenter = averageLandmarks(hand, PALM_LANDMARKS);
    const palmOnFace = Boolean(palmCenter && isPointInBounds(palmCenter, expandedFaceBounds));

    if (mouthHits >= 1 || eyeHits >= 2 || noseHits >= 1 || (handFaceHits >= 6 && (mouthHits + eyeHits + noseHits) >= 1)) {
      return {
        issue: "face_occlusion",
        confidence: clampConfidence(0.78 + Math.min(0.16, (mouthHits + eyeHits + noseHits) * 0.03)),
        evidence_text: "local_visual_hint: hand landmarks overlap mouth, eyes, or nose",
      };
    }

    if ((palmOnFace && handFaceHits >= 5) || handFaceHits >= 9) {
      return {
        issue: "hand_on_face",
        confidence: clampConfidence(0.74 + Math.min(0.14, handFaceHits * 0.012)),
        evidence_text: "local_visual_hint: hand landmarks stay on the face area",
      };
    }
  }

  return null;
}

function detectFaceAlignmentIssue(face: NormalizedLandmark[]): BodyVisualHint | null {
  const leftEyeCenter = averageLandmarks(face, LEFT_EYE_LANDMARKS);
  const rightEyeCenter = averageLandmarks(face, RIGHT_EYE_LANDMARKS);
  if (!leftEyeCenter || !rightEyeCenter) {
    return null;
  }

  const dx = rightEyeCenter.x - leftEyeCenter.x;
  const dy = rightEyeCenter.y - leftEyeCenter.y;
  if (Math.abs(dx) < 0.015) {
    resetHeadTiltState();
    return null;
  }

  const signedRollDegrees = (Math.atan2(dy, Math.abs(dx)) * 180) / Math.PI;
  const rollDegrees = Math.abs(signedRollDegrees);
  if (rollDegrees < HEAD_TILT_RESET_DEGREES) {
    resetHeadTiltState();
    return null;
  }

  const nowMs = performance.now();
  const direction = signedRollDegrees < 0 ? -1 : 1;
  if (direction !== headTiltState.direction || nowMs - headTiltState.lastAtMs > HEAD_TILT_STREAK_RESET_MS) {
    headTiltState = {
      ...headTiltState,
      direction,
      streak: 0,
    };
  }
  headTiltState.streak += 1;
  headTiltState.lastAtMs = nowMs;

  if (rollDegrees < HEAD_TILT_ADJUST_DEGREES) {
    return null;
  }

  const requiredStreak =
    rollDegrees >= HEAD_TILT_EXTREME_DEGREES
      ? 1
      : rollDegrees >= HEAD_TILT_HIGH_DEGREES
        ? HEAD_TILT_STRONG_STREAK
        : HEAD_TILT_NORMAL_STREAK;
  if (headTiltState.streak < requiredStreak) {
    return null;
  }

  if (nowMs - headTiltState.lastEmittedAtMs < HEAD_TILT_EMIT_COOLDOWN_MS) {
    return null;
  }
  headTiltState.lastEmittedAtMs = nowMs;

  const confidenceBase = rollDegrees >= HEAD_TILT_HIGH_DEGREES ? 0.86 : 0.76;
  return {
    issue: "head_tilt",
    confidence: clampConfidence(confidenceBase + Math.min(0.12, (rollDegrees - HEAD_TILT_ADJUST_DEGREES) * 0.015)),
    evidence_text: `local_visual_hint: sustained eye line tilt ${Math.round(rollDegrees)}deg`,
  };
}

function resetHeadTiltState() {
  headTiltState = {
    ...headTiltState,
    direction: 0,
    streak: 0,
    lastAtMs: 0,
  };
}

function buildBounds(
  landmarks: NormalizedLandmark[],
  indices: number[],
  paddingX: number,
  paddingY: number,
): LandmarkBounds | null {
  const selected = indices
    .map((index) => landmarks[index])
    .filter((landmark): landmark is NormalizedLandmark => Boolean(landmark));
  if (selected.length === 0) {
    return null;
  }

  const left = Math.min(...selected.map((landmark) => landmark.x)) - paddingX;
  const right = Math.max(...selected.map((landmark) => landmark.x)) + paddingX;
  const top = Math.min(...selected.map((landmark) => landmark.y)) - paddingY;
  const bottom = Math.max(...selected.map((landmark) => landmark.y)) + paddingY;

  return {
    left,
    right,
    top,
    bottom,
    width: Math.max(right - left, 0.001),
    height: Math.max(bottom - top, 0.001),
  };
}

function expandBounds(bounds: LandmarkBounds, paddingX: number, paddingY: number): LandmarkBounds {
  const left = bounds.left - paddingX;
  const right = bounds.right + paddingX;
  const top = bounds.top - paddingY;
  const bottom = bounds.bottom + paddingY;
  return {
    left,
    right,
    top,
    bottom,
    width: Math.max(right - left, 0.001),
    height: Math.max(bottom - top, 0.001),
  };
}

function countLandmarksInBounds(landmarks: NormalizedLandmark[], bounds: LandmarkBounds) {
  return landmarks.filter((landmark) => isPointInBounds(landmark, bounds)).length;
}

function isPointInBounds(point: NormalizedLandmark, bounds: LandmarkBounds) {
  return point.x >= bounds.left && point.x <= bounds.right && point.y >= bounds.top && point.y <= bounds.bottom;
}

function averageLandmarks(landmarks: NormalizedLandmark[], indices: number[]): NormalizedLandmark | null {
  const selected = indices
    .map((index) => landmarks[index])
    .filter((landmark): landmark is NormalizedLandmark => Boolean(landmark));
  if (selected.length === 0) {
    return null;
  }

  return {
    x: selected.reduce((sum, landmark) => sum + landmark.x, 0) / selected.length,
    y: selected.reduce((sum, landmark) => sum + landmark.y, 0) / selected.length,
    z: selected.reduce((sum, landmark) => sum + landmark.z, 0) / selected.length,
    visibility: 1,
  };
}

function allIndices(length: number) {
  return Array.from({ length }, (_, index) => index);
}

function clampConfidence(value: number) {
  return Math.max(0, Math.min(0.98, value));
}
