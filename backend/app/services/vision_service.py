from collections import deque
from dataclasses import dataclass, field
from time import monotonic

from app.schemas import LanguageOption, LiveInsight, PoseDebugState, PoseSnapshot

POSE_WINDOW_SIZE = 6
MIN_SNAPSHOTS_FOR_EVAL = 3
OUT_OF_FRAME_SHOULDER_RATIO = 0.25
OUT_OF_FRAME_FACE_RATIO = 0.35
OUT_OF_FRAME_BODY_SCALE = 0.045
FACE_VISIBLE_WARNING_RATIO = 0.22
CENTER_OFFSET_WARNING = 0.18
SHOULDER_TILT_WARNING_DEG = 7.0
TORSO_TILT_WARNING_DEG = 8.0
STABILITY_WARNING_SCORE = 0.45
STABILITY_GOOD_SCORE = 0.58
CENTER_OFFSET_GOOD = 0.12
HANDS_VISIBLE_LOW_RATIO = 0.3
HANDS_VISIBLE_CLOSE_UP_FLOOR = 0.15
GESTURE_LOW_SCORE = 0.06
GESTURE_ENGAGED_SCORE = 0.16
CLOSE_UP_SHOULDER_RATIO = 0.75
CLOSE_UP_HIP_RATIO = 0.35
CLOSE_UP_FACE_RATIO = 0.45
CLOSE_UP_BODY_SCALE = 0.04


@dataclass
class PoseSessionState:
    snapshots: deque[PoseSnapshot] = field(default_factory=lambda: deque(maxlen=POSE_WINDOW_SIZE))
    last_insight_key: str | None = None
    last_emitted_at: float = 0.0


@dataclass
class PoseWindowMetrics:
    body_presence_ratio: float
    face_visibility_ratio: float
    hands_visibility_ratio: float
    shoulder_visibility_ratio: float
    hip_visibility_ratio: float
    average_body_scale: float
    average_center_offset: float
    average_shoulder_tilt: float
    average_torso_tilt: float
    average_gesture_activity: float
    average_stability: float
    close_up_mode: bool


class PostureVisionService:
    def __init__(self) -> None:
        self.pose_sessions: dict[str, PoseSessionState] = {}

    @staticmethod
    def acknowledge_video_frame(frame_count: int) -> str:
        return f"video frame #{frame_count} received"

    def close_session(self, session_id: str) -> None:
        self.pose_sessions.pop(session_id, None)

    def process_pose_snapshot(
        self,
        session_id: str,
        language: LanguageOption,
        snapshot: PoseSnapshot,
    ) -> tuple[LiveInsight | None, PoseDebugState]:
        state = self.pose_sessions.setdefault(session_id, PoseSessionState())
        state.snapshots.append(snapshot)

        debug_state, issue = self._evaluate_snapshots(language, list(state.snapshots))

        if issue is None:
            return None, debug_state

        now = monotonic()
        cooldown_seconds = 6.0 if issue["tone"] == "positive" else 4.0
        if state.last_insight_key == issue["key"] and now - state.last_emitted_at < cooldown_seconds:
            return None, debug_state
        if state.last_insight_key != issue["key"] and now - state.last_emitted_at < 2.0:
            return None, debug_state

        state.last_insight_key = issue["key"]
        state.last_emitted_at = now

        return (
            LiveInsight(
                id=f"pose-{session_id}-{int(now * 1000)}",
                title=issue["title"],
                detail=issue["detail"],
                tone=issue["tone"],
            ),
            debug_state,
        )

    def _evaluate_snapshots(self, language: LanguageOption, snapshots: list[PoseSnapshot]) -> tuple[PoseDebugState, dict | None]:
        metrics = self._calculate_metrics(snapshots)
        issue: dict | None = None

        if len(snapshots) < MIN_SNAPSHOTS_FOR_EVAL:
            debug_state = self._build_debug_state(
                snapshots,
                None,
                metrics,
            )
            return debug_state, None

        if (
            metrics.shoulder_visibility_ratio < OUT_OF_FRAME_SHOULDER_RATIO
            and metrics.face_visibility_ratio < OUT_OF_FRAME_FACE_RATIO
            and metrics.average_body_scale < OUT_OF_FRAME_BODY_SCALE
        ):
            issue = self._build_issue(
                language,
                "out_of_frame",
                "先回到镜头里",
                "你的上半身暂时没有稳定进入画面，后续姿态反馈会不准。把头部、肩膀和上半身重新收回镜头中央。",
                "Step Back Into Frame",
                "Your upper body is slipping out of frame. Bring your head and shoulders back to the center so posture feedback stays reliable.",
                "warning",
            )
        elif metrics.face_visibility_ratio < FACE_VISIBLE_WARNING_RATIO:
            issue = self._build_issue(
                language,
                "face_not_visible",
                "头部位置再稳一点",
                "头部可见度偏低，容易让镜头表现显得不够稳定。保持头肩都在画面里，会更有交流感。",
                "Keep Your Head Visible",
                "Your head is dropping out of view. Keep your head and shoulders consistently visible to maintain audience connection.",
                "warning",
            )
        elif abs(metrics.average_center_offset) > CENTER_OFFSET_WARNING:
            issue = self._build_issue(
                language,
                "off_center",
                "上身偏离镜头中心" if metrics.close_up_mode else "身体偏离镜头中心",
                "你的上半身现在有点偏向画面一侧。往镜头中心收一点，近景交流感会更自然。"
                if metrics.close_up_mode
                else "你的人体重心现在有点偏向画面一侧。往镜头中心收一点，整体会更稳，也更像在正面交流。",
                "Re-Center Your Upper Body" if metrics.close_up_mode else "Re-Center Your Body",
                "Your upper body is drifting to one side of the frame. Move back toward center so the close-up feels more direct."
                if metrics.close_up_mode
                else "Your body is drifting to one side of the frame. Move back toward center so the delivery feels more grounded and direct.",
                "warning",
            )
        elif abs(metrics.average_shoulder_tilt) > SHOULDER_TILT_WARNING_DEG or (
            not metrics.close_up_mode and abs(metrics.average_torso_tilt) > TORSO_TILT_WARNING_DEG
        ):
            issue = self._build_issue(
                language,
                "tilted_posture",
                "肩线有些倾斜" if metrics.close_up_mode else "身体有些歪斜",
                "当前更像桌前近景，主要是肩线有些倾斜。把头肩摆正一点，镜头里的上身会更稳。"
                if metrics.close_up_mode
                else "肩膀和躯干略有倾斜，画面气场会变弱。把身体重新立直，表达会更有可信度。",
                "Level Your Shoulders" if metrics.close_up_mode else "Straighten Your Posture",
                "This looks like a close-up view and your shoulder line is tilted. Level your head-and-shoulder posture so the frame feels steadier."
                if metrics.close_up_mode
                else "Your shoulders and torso are tilted. Straightening up will make the delivery look steadier and more confident.",
                "warning",
            )
        elif metrics.average_stability < STABILITY_WARNING_SCORE:
            issue = self._build_issue(
                language,
                "unstable_posture",
                "上身有些晃动" if metrics.close_up_mode else "身体有些晃动",
                "你的头肩位置有些晃，近景画面会显得不够稳。重点句前先把上身定住。"
                if metrics.close_up_mode
                else "当前站姿的小幅摆动偏多。重点句之前先站稳，再开口，声音和肢体会更有力量。",
                "Reduce Upper-Body Sway" if metrics.close_up_mode else "Reduce Body Sway",
                "Your head-and-shoulder position is moving around a bit. Settle before key lines so the close-up feels steadier."
                if metrics.close_up_mode
                else "Your stance is moving around a bit. Settle before key lines so both your voice and posture land with more force.",
                "neutral",
            )
        elif (
            metrics.average_gesture_activity >= GESTURE_ENGAGED_SCORE
            and metrics.average_stability >= 0.55
            and metrics.body_presence_ratio >= 0.75
        ):
            issue = self._build_issue(
                language,
                "engaged_posture",
                "上身参与感不错" if metrics.close_up_mode else "姿态参与感不错",
                "你的近景头肩状态比较稳定，表达参与感也不错，继续保持这种自然打开的感觉。"
                if metrics.close_up_mode
                else "你的身体参与感和稳定性都还不错，继续保持这种打开但不过度的表达状态。",
                "Engaged Upper-Body Posture" if metrics.close_up_mode else "Engaged Posture",
                "Your head-and-shoulder posture looks engaged and steady. Keep that open but controlled close-up delivery."
                if metrics.close_up_mode
                else "Your posture looks engaged and reasonably steady. Keep that open but controlled delivery.",
                "positive",
            )
        elif (
            (not metrics.close_up_mode or metrics.hands_visibility_ratio >= HANDS_VISIBLE_CLOSE_UP_FLOOR)
            and metrics.hands_visibility_ratio < HANDS_VISIBLE_LOW_RATIO
            and metrics.average_gesture_activity < GESTURE_LOW_SCORE
        ):
            issue = self._build_issue(
                language,
                "low_gesture_activity",
                "手势参与感偏低",
                "你的手势目前比较少，整段表达会显得略收。讲重点句时加入少量自然手势，会更有支撑感。",
                "Use a Little More Gesture",
                "Your gestures are very limited right now. Adding a few natural hand movements on key lines will support the message better.",
                "neutral",
            )
        elif (
            metrics.average_stability > STABILITY_GOOD_SCORE
            and abs(metrics.average_center_offset) < CENTER_OFFSET_GOOD
            and metrics.average_body_scale > 0.06
        ):
            issue = self._build_issue(
                language,
                "stable_posture",
                "当前上身姿态比较稳" if metrics.close_up_mode else "当前姿态比较稳",
                "你现在的头肩位置比较稳，近景镜头感不错，可以继续把注意力放在语气和内容推进上。"
                if metrics.close_up_mode
                else "你现在的身体居中和稳定性都不错，可以继续把注意力放在语气和内容推进上。",
                "Upper-Body Posture Looks Stable" if metrics.close_up_mode else "Posture Looks Stable",
                "Your head-and-shoulder position is centered and steady. Keep that base and shift your attention to pacing and emphasis."
                if metrics.close_up_mode
                else "Your body position is centered and steady. Keep that base and shift your attention to pacing and emphasis.",
                "positive",
            )
        elif metrics.close_up_mode:
            issue = self._build_issue(
                language,
                "close_up_ready",
                "近景姿态跟踪已开始",
                "当前更像坐姿近景或桌前演讲，系统会以头肩区域为主做姿态判断，不把它当成异常离镜。",
                "Close-Up Tracking Active",
                "This looks like a close-up seated delivery. The system will evaluate posture mainly from your head and shoulders instead of treating it as out of frame.",
                "neutral",
            )
        elif metrics.body_presence_ratio >= 0.75:
            issue = self._build_issue(
                language,
                "tracking_ready",
                "姿态跟踪已开始",
                "系统已经稳定识别到你的上半身。你可以继续讲，后续会根据姿态变化补充更具体的提醒。",
                "Posture Tracking Active",
                "The system is now tracking your upper body reliably. Keep speaking and you will get more specific posture guidance as things change.",
                "neutral",
            )

        debug_state = self._build_debug_state(
            snapshots,
            issue,
            metrics,
        )
        return debug_state, issue

    def _calculate_metrics(self, snapshots: list[PoseSnapshot]) -> PoseWindowMetrics:
        shoulder_visibility_ratio = self._mean(1.0 if snapshot.shoulderVisible else 0.0 for snapshot in snapshots)
        hip_visibility_ratio = self._mean(1.0 if snapshot.hipVisible else 0.0 for snapshot in snapshots)
        face_visibility_ratio = self._mean(1.0 if snapshot.faceVisible else 0.0 for snapshot in snapshots)

        return PoseWindowMetrics(
            body_presence_ratio=self._mean(1.0 if snapshot.bodyPresent else 0.0 for snapshot in snapshots),
            face_visibility_ratio=face_visibility_ratio,
            hands_visibility_ratio=self._mean(1.0 if snapshot.handsVisible else 0.0 for snapshot in snapshots),
            shoulder_visibility_ratio=shoulder_visibility_ratio,
            hip_visibility_ratio=hip_visibility_ratio,
            average_body_scale=self._mean(snapshot.bodyScale for snapshot in snapshots),
            average_center_offset=self._mean(snapshot.centerOffsetX for snapshot in snapshots),
            average_shoulder_tilt=self._mean(snapshot.shoulderTiltDeg for snapshot in snapshots),
            average_torso_tilt=self._mean(snapshot.torsoTiltDeg for snapshot in snapshots),
            average_gesture_activity=self._mean(snapshot.gestureActivity for snapshot in snapshots),
            average_stability=self._mean(snapshot.stabilityScore for snapshot in snapshots),
            close_up_mode=(
                shoulder_visibility_ratio >= CLOSE_UP_SHOULDER_RATIO
                and hip_visibility_ratio < CLOSE_UP_HIP_RATIO
                and face_visibility_ratio >= CLOSE_UP_FACE_RATIO
                and self._mean(snapshot.bodyScale for snapshot in snapshots) >= CLOSE_UP_BODY_SCALE
            ),
        )

    @staticmethod
    def _build_issue(
        language: LanguageOption,
        key: str,
        zh_title: str,
        zh_detail: str,
        en_title: str,
        en_detail: str,
        tone: str,
    ) -> dict[str, str]:
        if language == "en":
            return {
                "key": key,
                "title": en_title,
                "detail": en_detail,
                "tone": tone,
            }

        return {
            "key": key,
            "title": zh_title,
            "detail": zh_detail,
            "tone": tone,
        }

    @staticmethod
    def _build_debug_state(
        snapshots: list[PoseSnapshot],
        issue: dict | None,
        metrics: PoseWindowMetrics,
    ) -> PoseDebugState:
        return PoseDebugState(
            snapshotCount=len(snapshots),
            closeUpMode=metrics.close_up_mode,
            selectedRuleKey=issue["key"] if issue else None,
            selectedRuleTitle=issue["title"] if issue else None,
            selectedRuleTone=issue["tone"] if issue else None,
            bodyPresenceRatio=metrics.body_presence_ratio,
            faceVisibilityRatio=metrics.face_visibility_ratio,
            handsVisibilityRatio=metrics.hands_visibility_ratio,
            shoulderVisibilityRatio=metrics.shoulder_visibility_ratio,
            hipVisibilityRatio=metrics.hip_visibility_ratio,
            averageBodyScale=metrics.average_body_scale,
            averageCenterOffsetX=metrics.average_center_offset,
            averageShoulderTiltDeg=metrics.average_shoulder_tilt,
            averageTorsoTiltDeg=metrics.average_torso_tilt,
            averageGestureActivity=metrics.average_gesture_activity,
            averageStabilityScore=metrics.average_stability,
        )

    @staticmethod
    def _mean(values) -> float:
        values_list = list(values)
        if len(values_list) == 0:
            return 0.0
        return sum(values_list) / len(values_list)
