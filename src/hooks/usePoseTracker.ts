"use client";

import { useEffect, useRef, useState } from "react";

import type { PoseSnapshot } from "@/types/session";

const POSE_WASM_BASE_URL = "/mediapipe/wasm";
const POSE_MODEL_ASSET_URL = "/models/pose_landmarker_lite.task";
const POSE_CAPTURE_INTERVAL_MS = 150;
const MIN_LANDMARK_VISIBILITY = 0.35;
const HISTORY_WINDOW_MS = 2500;
const MIN_SHOULDER_WIDTH = 0.04;
const MIN_HIP_WIDTH = 0.04;
const MIN_CLOSE_UP_BODY_SCALE = 0.08;
const LEFT_SHOULDER_INDEX = 11;
const RIGHT_SHOULDER_INDEX = 12;
const LEFT_WRIST_INDEX = 15;
const RIGHT_WRIST_INDEX = 16;
const LEFT_HIP_INDEX = 23;
const RIGHT_HIP_INDEX = 24;
const FACE_LANDMARK_INDICES = [0, 1, 2, 3, 4, 5, 6, 7, 8] as const;

interface Point2D {
  x: number;
  y: number;
}

interface PoseHistorySample {
  timestampMs: number;
  torsoCenter: Point2D;
  shoulderWidth: number;
  wrists: {
    left: Point2D | null;
    right: Point2D | null;
  };
}

interface UsePoseTrackerOptions {
  enabled: boolean;
  videoElement: HTMLVideoElement | null;
}

type PoseLandmarkerModule = typeof import("@mediapipe/tasks-vision");
type PoseLandmarkerInstance = Awaited<ReturnType<PoseLandmarkerModule["PoseLandmarker"]["createFromOptions"]>>;
type PoseLandmarkerResult = import("@mediapipe/tasks-vision").PoseLandmarkerResult;
type NormalizedLandmark = import("@mediapipe/tasks-vision").NormalizedLandmark;

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

function average(values: number[]) {
  if (values.length === 0) {
    return 0;
  }

  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function computeStdDev(values: number[]) {
  if (values.length <= 1) {
    return 0;
  }

  const mean = average(values);
  const variance = average(values.map((value) => (value - mean) ** 2));
  return Math.sqrt(variance);
}

function getLandmark(landmarks: NormalizedLandmark[], index: number) {
  const landmark = landmarks[index];
  if (!landmark || landmark.visibility < MIN_LANDMARK_VISIBILITY) {
    return null;
  }

  return landmark;
}

function getPoint(landmarks: NormalizedLandmark[], index: number): Point2D | null {
  const landmark = getLandmark(landmarks, index);
  if (!landmark) {
    return null;
  }

  return { x: landmark.x, y: landmark.y };
}

function averagePoint(points: Array<Point2D | null>) {
  const validPoints = points.filter((point): point is Point2D => point !== null);
  if (validPoints.length === 0) {
    return null;
  }

  return {
    x: average(validPoints.map((point) => point.x)),
    y: average(validPoints.map((point) => point.y)),
  };
}

function distance(left: Point2D | null, right: Point2D | null) {
  if (!left || !right) {
    return 0;
  }

  return Math.hypot(left.x - right.x, left.y - right.y);
}

function averageVisibility(landmarks: NormalizedLandmark[], indices: readonly number[]) {
  const values = indices
    .map((index) => landmarks[index]?.visibility ?? 0)
    .filter((value) => Number.isFinite(value));
  return average(values);
}

function computeShoulderTiltDeg(leftShoulder: Point2D | null, rightShoulder: Point2D | null) {
  if (!leftShoulder || !rightShoulder) {
    return 0;
  }

  const deltaY = rightShoulder.y - leftShoulder.y;
  const deltaX = rightShoulder.x - leftShoulder.x;
  const horizontalMagnitude = Math.abs(deltaX);
  if (horizontalMagnitude <= 0.0001) {
    return deltaY >= 0 ? 90 : -90;
  }

  const magnitude = (Math.atan2(Math.abs(deltaY), horizontalMagnitude) * 180) / Math.PI;
  return deltaY >= 0 ? magnitude : -magnitude;
}

function computeTorsoTiltDeg(shoulderCenter: Point2D | null, hipCenter: Point2D | null) {
  if (!shoulderCenter || !hipCenter) {
    return 0;
  }

  const deltaX = shoulderCenter.x - hipCenter.x;
  const deltaY = hipCenter.y - shoulderCenter.y;
  if (deltaY <= 0) {
    return 0;
  }

  return (Math.atan2(deltaX, deltaY) * 180) / Math.PI;
}

function computeGestureActivity(historySamples: PoseHistorySample[], shoulderWidth: number) {
  if (historySamples.length <= 1 || shoulderWidth <= 0.0001) {
    return 0;
  }

  const movementValues: number[] = [];
  for (let index = 1; index < historySamples.length; index += 1) {
    const previous = historySamples[index - 1];
    const current = historySamples[index];
    if (!previous || !current) {
      continue;
    }

    const leftMovement = distance(previous.wrists.left, current.wrists.left);
    const rightMovement = distance(previous.wrists.right, current.wrists.right);
    const maxMovement = Math.max(leftMovement, rightMovement);
    if (maxMovement > 0) {
      movementValues.push(maxMovement / shoulderWidth);
    }
  }

  return clamp(average(movementValues) * 2.4, 0, 1);
}

function computeStabilityScore(historySamples: PoseHistorySample[], shoulderWidth: number) {
  if (historySamples.length <= 1 || shoulderWidth <= 0.0001) {
    return 1;
  }

  const xValues = historySamples.map((sample) => sample.torsoCenter.x);
  const yValues = historySamples.map((sample) => sample.torsoCenter.y);
  const jitter = Math.hypot(computeStdDev(xValues), computeStdDev(yValues)) / shoulderWidth;
  return clamp(1 - jitter / 0.18, 0, 1);
}

function buildEmptySnapshot(): PoseSnapshot {
  return {
    bodyPresent: false,
    faceVisible: false,
    handsVisible: false,
    shoulderVisible: false,
    hipVisible: false,
    bodyScale: 0,
    centerOffsetX: 0,
    shoulderTiltDeg: 0,
    torsoTiltDeg: 0,
    gestureActivity: 0,
    stabilityScore: 0,
  };
}

function buildPoseSnapshot(
  result: PoseLandmarkerResult,
  timestampMs: number,
  historySamplesRef: React.MutableRefObject<PoseHistorySample[]>,
): PoseSnapshot {
  const landmarks = result.landmarks[0];
  if (!landmarks || landmarks.length === 0) {
    historySamplesRef.current = [];
    return buildEmptySnapshot();
  }

  const leftShoulder = getPoint(landmarks, LEFT_SHOULDER_INDEX);
  const rightShoulder = getPoint(landmarks, RIGHT_SHOULDER_INDEX);
  const leftHip = getPoint(landmarks, LEFT_HIP_INDEX);
  const rightHip = getPoint(landmarks, RIGHT_HIP_INDEX);
  const leftWrist = getPoint(landmarks, LEFT_WRIST_INDEX);
  const rightWrist = getPoint(landmarks, RIGHT_WRIST_INDEX);
  const shoulderCenter = averagePoint([leftShoulder, rightShoulder]);
  const hipCenter = averagePoint([leftHip, rightHip]);
  const shoulderWidth = distance(leftShoulder, rightShoulder);
  const hipWidth = distance(leftHip, rightHip);
  const bodyScale = Math.max(shoulderWidth, hipWidth);
  const faceVisible = averageVisibility(landmarks, FACE_LANDMARK_INDICES) >= 0.4;
  const handsVisible = Boolean(leftWrist || rightWrist);
  const shoulderVisible = Boolean(shoulderCenter && shoulderWidth >= MIN_SHOULDER_WIDTH);
  const hipVisible = Boolean(hipCenter && hipWidth >= MIN_HIP_WIDTH);
  const torsoCenter = hipCenter ? averagePoint([shoulderCenter, hipCenter]) : shoulderCenter;
  const bodyPresent = Boolean(shoulderVisible && (hipVisible || faceVisible || bodyScale >= MIN_CLOSE_UP_BODY_SCALE));

  if (!bodyPresent || !torsoCenter) {
    historySamplesRef.current = [];
    return {
      ...buildEmptySnapshot(),
      faceVisible,
      handsVisible,
      shoulderVisible,
      hipVisible,
      bodyScale,
    };
  }

  const nextHistorySamples = [
    ...historySamplesRef.current,
    {
      timestampMs,
      torsoCenter,
      shoulderWidth: Math.max(shoulderWidth, 0.0001),
      wrists: {
        left: leftWrist,
        right: rightWrist,
      },
    },
  ].filter((sample) => timestampMs - sample.timestampMs <= HISTORY_WINDOW_MS);
  historySamplesRef.current = nextHistorySamples;

  return {
    bodyPresent,
    faceVisible,
    handsVisible,
    shoulderVisible,
    hipVisible,
    bodyScale,
    centerOffsetX: torsoCenter.x - 0.5,
    shoulderTiltDeg: computeShoulderTiltDeg(leftShoulder, rightShoulder),
    torsoTiltDeg: computeTorsoTiltDeg(shoulderCenter, hipCenter),
    gestureActivity: computeGestureActivity(nextHistorySamples, Math.max(shoulderWidth, 0.0001)),
    stabilityScore: computeStabilityScore(nextHistorySamples, Math.max(shoulderWidth, 0.0001)),
  };
}

export function usePoseTracker({ enabled, videoElement }: UsePoseTrackerOptions) {
  const poseLandmarkerRef = useRef<PoseLandmarkerInstance | null>(null);
  const captureTimerRef = useRef<number | null>(null);
  const historySamplesRef = useRef<PoseHistorySample[]>([]);
  const latestSnapshotRef = useRef<PoseSnapshot | null>(null);
  const initRequestRef = useRef<Promise<void> | null>(null);
  const [isReady, setIsReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [snapshot, setSnapshot] = useState<PoseSnapshot | null>(null);

  useEffect(() => {
    let cancelled = false;

    if (!initRequestRef.current) {
      initRequestRef.current = (async () => {
        try {
          const { FilesetResolver, PoseLandmarker } = await import("@mediapipe/tasks-vision");
          const vision = await FilesetResolver.forVisionTasks(POSE_WASM_BASE_URL);
          const poseLandmarker = await PoseLandmarker.createFromOptions(vision, {
            baseOptions: {
              modelAssetPath: POSE_MODEL_ASSET_URL,
            },
            runningMode: "VIDEO",
            numPoses: 1,
            minPoseDetectionConfidence: 0.5,
            minPosePresenceConfidence: 0.5,
            minTrackingConfidence: 0.5,
          });

          if (cancelled) {
            poseLandmarker.close();
            return;
          }

          poseLandmarkerRef.current = poseLandmarker;
          setIsReady(true);
          setError(null);
        } catch (initError) {
          if (!cancelled) {
            setError(initError instanceof Error ? initError.message : "姿态模型初始化失败");
          }
        }
      })();
    }

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (captureTimerRef.current !== null) {
      window.clearInterval(captureTimerRef.current);
      captureTimerRef.current = null;
    }

    if (!enabled) {
      latestSnapshotRef.current = null;
      historySamplesRef.current = [];
      return;
    }

    if (!isReady || !videoElement || !poseLandmarkerRef.current) {
      return;
    }

    const detectPose = () => {
      if (videoElement.readyState < HTMLMediaElement.HAVE_CURRENT_DATA || videoElement.videoWidth === 0 || videoElement.videoHeight === 0) {
        return;
      }

      try {
        const timestampMs = performance.now();
        const result = poseLandmarkerRef.current?.detectForVideo(videoElement, timestampMs);
        if (!result) {
          return;
        }

        const nextSnapshot = buildPoseSnapshot(result, timestampMs, historySamplesRef);
        latestSnapshotRef.current = nextSnapshot;
        setSnapshot(nextSnapshot);
        result.close();
        setError(null);
      } catch (detectError) {
        setError(detectError instanceof Error ? detectError.message : "姿态识别失败");
      }
    };

    detectPose();
    captureTimerRef.current = window.setInterval(detectPose, POSE_CAPTURE_INTERVAL_MS);

    return () => {
      if (captureTimerRef.current !== null) {
        window.clearInterval(captureTimerRef.current);
        captureTimerRef.current = null;
      }
    };
  }, [enabled, isReady, videoElement]);

  useEffect(() => {
    return () => {
      if (captureTimerRef.current !== null) {
        window.clearInterval(captureTimerRef.current);
      }
      poseLandmarkerRef.current?.close();
      poseLandmarkerRef.current = null;
    };
  }, []);

  return {
    error,
    getLatestSnapshot: () => latestSnapshotRef.current,
    isReady,
    snapshot,
  };
}
