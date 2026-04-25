from dataclasses import dataclass

from app.schemas import (
    CoachPanelPatch,
    CoachPanelPatchDimension,
    CoachDimensionState,
    CoachPanelState,
    CoachSummary,
    LanguageOption,
)
from app.services.speech_analysis_service import SpeechPanelUpdate


@dataclass
class CoachPanelSessionState:
    language: LanguageOption
    panel: CoachPanelState
    signature: str


class CoachPanelService:
    def __init__(self) -> None:
        self.sessions: dict[str, CoachPanelSessionState] = {}

    def close_session(self, session_id: str) -> None:
        self.sessions.pop(session_id, None)

    def get_or_create_panel(self, session_id: str, language: LanguageOption) -> CoachPanelState:
        state = self.sessions.get(session_id)
        if state is not None:
            return state.panel

        panel = self._build_initial_panel(language)
        self.sessions[session_id] = CoachPanelSessionState(
            language=language,
            panel=panel,
            signature=self._signature(panel),
        )
        return panel

    def update_from_speech(
        self,
        session_id: str,
        language: LanguageOption,
        update: SpeechPanelUpdate,
        updated_at_ms: int,
        *,
        allow_replace_omni: bool = True,
    ) -> CoachPanelState | None:
        session = self._ensure_session(session_id, language)
        voice_status, voice_headline, voice_detail = self._sanitize_dimension_copy(
            language,
            "voice_pacing",
            update.voice.status,
            update.voice.headline,
            update.voice.detail,
        )
        content_status, content_headline, content_detail = self._sanitize_dimension_copy(
            language,
            "content_expression",
            update.content.status,
            update.content.headline,
            update.content.detail,
        )
        next_voice = (
            session.panel.voicePacing
            if not allow_replace_omni and session.panel.voicePacing.source == "omni-coach"
            else self._build_dimension(
                "voice_pacing",
                voice_status,
                voice_headline,
                voice_detail,
                updated_at_ms,
                "speech-rule",
                sub_dimension_id=None,
                signal_polarity=None,
                severity=None,
                confidence=None,
                evidence_text=None,
            )
        )
        next_content = (
            session.panel.contentExpression
            if not allow_replace_omni and session.panel.contentExpression.source == "omni-coach"
            else self._build_dimension(
                "content_expression",
                content_status,
                content_headline,
                content_detail,
                updated_at_ms,
                "speech-rule",
                sub_dimension_id=None,
                signal_polarity=None,
                severity=None,
                confidence=None,
                evidence_text=None,
            )
        )
        next_panel = session.panel.model_copy(
            update={
                "voicePacing": next_voice,
                "contentExpression": next_content,
            }
        )
        return self._commit_panel(session_id, next_panel)

    def update_from_omni_patch(
        self,
        session_id: str,
        language: LanguageOption,
        patch: CoachPanelPatch,
        updated_at_ms: int,
    ) -> CoachPanelState | None:
        if not patch.dimensions:
            return None

        session = self._ensure_session(session_id, language)
        next_panel = session.panel

        for dimension_patch in self.filter_omni_patch(patch, language).dimensions:
            status, headline, detail = self._sanitize_dimension_copy(
                language,
                dimension_patch.id,
                dimension_patch.status,
                dimension_patch.headline,
                dimension_patch.detail,
            )
            next_dimension = self._build_dimension(
                dimension_patch.id,
                status,
                headline,
                detail,
                updated_at_ms,
                "omni-coach",
                sub_dimension_id=dimension_patch.subDimensionId,
                signal_polarity=dimension_patch.signalPolarity,
                severity=dimension_patch.severity,
                confidence=dimension_patch.confidence,
                evidence_text=dimension_patch.evidenceText,
            )
            next_panel = self._set_dimension(next_panel, next_dimension)

        return self._commit_panel(session_id, next_panel)

    def filter_omni_patch(self, patch: CoachPanelPatch, language: LanguageOption) -> CoachPanelPatch:
        if not patch.dimensions:
            return patch
        filtered_dimensions: list[CoachPanelPatchDimension] = []
        for dimension in patch.dimensions:
            if self._should_drop_omni_dimension_patch(dimension):
                replacement = self._build_neutral_body_dimension_patch(dimension, language)
                if replacement is not None:
                    filtered_dimensions.append(replacement)
                continue
            filtered_dimensions.append(dimension)

        return CoachPanelPatch(dimensions=filtered_dimensions)

    def _build_neutral_body_dimension_patch(
        self,
        dimension_patch: CoachPanelPatchDimension,
        language: LanguageOption,
    ) -> CoachPanelPatchDimension | None:
        if dimension_patch.id != "body_expression":
            return None

        combined = f"{dimension_patch.headline} {dimension_patch.detail} {dimension_patch.evidenceText or ''}"
        if self._looks_screen_gaze_warning(combined):
            return CoachPanelPatchDimension(
                id="body_expression",
                status="stable",
                headline=self._text(language, "屏幕前状态稳定", "Screen-facing posture is stable"),
                detail=self._text(language, "看屏幕不算低头。", "Looking at the screen is fine."),
                subDimensionId="facial_or_eye_engagement",
                signalPolarity="neutral",
                severity="low",
                confidence=dimension_patch.confidence,
                evidenceText=dimension_patch.evidenceText,
            )
        return CoachPanelPatchDimension(
            id="body_expression",
            status="stable",
            headline=self._text(language, "肢体基本稳定", "Body is mostly stable"),
            detail=self._text(language, "先保持当前姿态。", "Keep the current posture."),
            subDimensionId=dimension_patch.subDimensionId,
            signalPolarity="neutral",
            severity="low",
            confidence=dimension_patch.confidence,
            evidenceText=dimension_patch.evidenceText,
        )

    def _should_drop_omni_dimension_patch(self, dimension_patch: CoachPanelPatchDimension) -> bool:
        if dimension_patch.id != "body_expression" or dimension_patch.status != "adjust_now":
            return False

        confidence = dimension_patch.confidence
        if confidence is not None and confidence < 0.68:
            return True

        combined = f"{dimension_patch.headline} {dimension_patch.detail} {dimension_patch.evidenceText or ''}"
        if self._looks_face_blocking_signal(combined):
            return confidence is None or confidence < 0.84

        if self._looks_uncertain_hand_height_warning(dimension_patch.headline, dimension_patch.detail):
            return confidence is None or confidence < 0.84

        if self._looks_screen_gaze_warning(combined):
            return (
                confidence is None
                or confidence < 0.92
                or not self._looks_strong_head_down_evidence(combined)
            )

        return False

    def _ensure_session(self, session_id: str, language: LanguageOption) -> CoachPanelSessionState:
        existing = self.sessions.get(session_id)
        if existing is not None:
            return existing

        panel = self._build_initial_panel(language)
        state = CoachPanelSessionState(language=language, panel=panel, signature=self._signature(panel))
        self.sessions[session_id] = state
        return state

    def _commit_panel(self, session_id: str, panel: CoachPanelState) -> CoachPanelState | None:
        session = self.sessions[session_id]
        next_summary = self._build_summary(session.language, panel)
        next_panel = panel.model_copy(update={"summary": next_summary})
        next_signature = self._signature(next_panel)

        if next_signature == session.signature:
            return None

        session.panel = next_panel
        session.signature = next_signature
        return next_panel

    def _build_initial_panel(self, language: LanguageOption) -> CoachPanelState:
        return CoachPanelState(
            summary=CoachSummary(
                title=self._text(language, "继续演讲，AI 正在同步更新反馈", "Keep speaking while AI updates your coaching"),
                detail=self._text(language, "右侧三项反馈会随着你的声音、画面和内容持续更新。", "The three cards on the right will update as your voice, framing, and content change."),
                sourceDimension=None,
                updatedAtMs=0,
            ),
            bodyExpression=self._build_dimension(
                "body_expression",
                "analyzing",
                self._text(language, "正在更新肢体反馈", "Updating body delivery"),
                self._text(language, "保持当前节奏", "Keep your current rhythm"),
                0,
                "system",
                sub_dimension_id=None,
                signal_polarity=None,
                severity=None,
                confidence=None,
                evidence_text=None,
            ),
            voicePacing=self._build_dimension(
                "voice_pacing",
                "analyzing",
                self._text(language, "正在更新语音反馈", "Updating vocal pacing"),
                self._text(language, "保持当前节奏", "Keep your current rhythm"),
                0,
                "system",
                sub_dimension_id=None,
                signal_polarity=None,
                severity=None,
                confidence=None,
                evidence_text=None,
            ),
            contentExpression=self._build_dimension(
                "content_expression",
                "analyzing",
                self._text(language, "正在更新内容反馈", "Updating content clarity"),
                self._text(language, "继续往下讲，稍后更新这一项反馈", "Keep going and this card will update shortly"),
                0,
                "system",
                sub_dimension_id=None,
                signal_polarity=None,
                severity=None,
                confidence=None,
                evidence_text=None,
            ),
        )

    def _build_summary(
        self,
        language: LanguageOption,
        panel: CoachPanelState,
    ) -> CoachSummary:
        dimensions = [
            panel.bodyExpression,
            panel.voicePacing,
            panel.contentExpression,
        ]
        reference_time_ms = max(dimension.updatedAtMs for dimension in dimensions)
        adjust_candidates = [item for item in dimensions if item.status == "adjust_now"]
        if adjust_candidates:
            chosen = max(adjust_candidates, key=lambda item: item.updatedAtMs)
            return CoachSummary(
                title=chosen.headline,
                detail=chosen.detail,
                sourceDimension=chosen.id,
                updatedAtMs=chosen.updatedAtMs,
            )

        positive_candidates = [item for item in dimensions if item.status == "doing_well"]
        if positive_candidates:
            chosen = max(positive_candidates, key=lambda item: item.updatedAtMs)
            return CoachSummary(
                title=chosen.headline,
                detail=chosen.detail,
                sourceDimension=chosen.id,
                updatedAtMs=chosen.updatedAtMs,
            )

        stable_candidates = [item for item in dimensions if item.status == "stable"]
        if stable_candidates:
            return CoachSummary(
                title=self._text(language, "整体基本稳定", "Overall delivery is stable"),
                detail=self._text(
                    language,
                    "继续表达，出现明显变化时会更新当前重点。",
                    "Keep going. The top cue will update when a clearer change appears.",
                ),
                sourceDimension=None,
                updatedAtMs=reference_time_ms,
            )

        return CoachSummary(
            title=self._text(language, "继续演讲，AI 正在同步更新反馈", "Keep speaking while AI updates your coaching"),
            detail=self._text(
                language,
                "右侧三项反馈会随着你的声音、画面和内容持续更新。",
                "The three cards on the right will keep updating as your voice, framing, and content change.",
            ),
            sourceDimension=None,
            updatedAtMs=reference_time_ms,
        )

    @staticmethod
    def _set_dimension(panel: CoachPanelState, dimension: CoachDimensionState) -> CoachPanelState:
        if dimension.id == "body_expression":
            return panel.model_copy(update={"bodyExpression": dimension})
        if dimension.id == "voice_pacing":
            return panel.model_copy(update={"voicePacing": dimension})
        return panel.model_copy(update={"contentExpression": dimension})

    @staticmethod
    def _build_dimension(
        dimension_id: str,
        status: str,
        headline: str,
        detail: str,
        updated_at_ms: int,
        source: str,
        *,
        sub_dimension_id: str | None,
        signal_polarity: str | None,
        severity: str | None,
        confidence: float | None,
        evidence_text: str | None,
    ) -> CoachDimensionState:
        return CoachDimensionState(
            id=dimension_id,
            status=status,
            headline=headline,
            detail=detail,
            updatedAtMs=updated_at_ms,
            source=source,
            subDimensionId=sub_dimension_id,
            signalPolarity=signal_polarity,
            severity=severity,
            confidence=confidence,
            evidenceText=evidence_text,
        )

    @staticmethod
    def _signature(panel: CoachPanelState) -> str:
        return panel.model_dump_json()

    @staticmethod
    def _normalize(text: str) -> str:
        return text.strip().lower()

    @staticmethod
    def _text(language: LanguageOption, zh: str, en: str) -> str:
        return en if language == "en" else zh

    def _sanitize_dimension_copy(
        self,
        language: LanguageOption,
        dimension_id: str,
        status: str,
        headline: str,
        detail: str,
    ) -> tuple[str, str, str]:
        normalized_headline = headline.strip()
        normalized_detail = detail.strip()

        if not normalized_headline or not normalized_detail:
            return status, normalized_headline, normalized_detail

        if (
            status == "adjust_now"
            and dimension_id == "body_expression"
            and not self._looks_face_blocking_signal(f"{normalized_headline} {normalized_detail}")
            and self._looks_uncertain_hand_height_warning(normalized_headline, normalized_detail)
        ):
            return (
                "stable",
                self._text(language, "肢体基本稳定", "Body is mostly stable"),
                self._text(language, "先保持当前姿态。", "Keep the current posture."),
            )

        if status == "adjust_now" and self._looks_resolved_or_positive(normalized_detail):
            return (
                status,
                normalized_headline,
                self._fallback_adjust_detail(language, dimension_id, normalized_headline, normalized_detail),
            )

        if status in {"doing_well", "stable"} and self._looks_issue_or_action(normalized_headline, normalized_detail):
            return (
                status,
                self._fallback_nonwarning_headline(language, dimension_id, status),
                self._fallback_nonwarning_detail(language, status),
            )

        return status, normalized_headline, normalized_detail

    @staticmethod
    def _looks_resolved_or_positive(text: str) -> bool:
        normalized = text.strip().lower()
        positive_markers = (
            "已经",
            "已",
            "继续讲",
            "继续保持",
            "继续说",
            "没问题",
            "比较稳",
            "稳定",
            "不错",
            "自然",
            "回来了",
            "整体ok",
            "all good",
            "already",
            "keep going",
            "looks good",
            "stable now",
        )
        return any(marker in normalized for marker in positive_markers)

    @staticmethod
    def _looks_issue_or_action(headline: str, detail: str) -> bool:
        combined = f"{headline} {detail}".strip().lower()
        issue_markers = (
            "先把",
            "别",
            "不要",
            "回到",
            "摆正",
            "放慢",
            "离开",
            "收回",
            "停一下",
            "讲结论",
            "定住",
            "adjust",
            "move",
            "stop",
            "slow",
            "lead with",
            "keep your hand off",
            "move back",
        )
        return any(marker in combined for marker in issue_markers)

    @staticmethod
    def _looks_face_blocking_signal(text: str) -> bool:
        normalized = text.strip().lower().replace(" ", "")
        blocking_markers = (
            "挡脸",
            "遮脸",
            "捂脸",
            "盖脸",
            "挡住脸",
            "遮住脸",
            "盖住脸",
            "挡住嘴",
            "遮住嘴",
            "挡住眼",
            "遮住眼",
            "挡住鼻",
            "遮住鼻",
            "手挡脸",
            "手遮脸",
            "手捂脸",
            "handcoverstheface",
            "handcoveringtheface",
            "handiscoveringtheface",
            "handblockstheface",
            "handisblockingtheface",
            "coveringtheface",
            "blockstheface",
            "blockingtheface",
            "coveringmouth",
            "blockingmouth",
            "coveringeyes",
            "blockingeyes",
            "coveringnose",
            "blockingnose",
        )
        return any(marker in normalized for marker in blocking_markers)

    @staticmethod
    def _looks_uncertain_hand_height_warning(headline: str, detail: str) -> bool:
        combined = f"{headline} {detail}".strip().lower().replace(" ", "")
        hand_markers = ("手", "hand")
        height_markers = (
            "耳边",
            "耳旁",
            "耳朵",
            "举",
            "抬",
            "放下",
            "太高",
            "byyourear",
            "nearyourear",
            "atyourear",
            "raisedhand",
            "handraised",
            "loweryourhand",
            "putyourhanddown",
            "handdown",
        )
        return any(marker in combined for marker in hand_markers) and any(
            marker in combined for marker in height_markers
        )

    @staticmethod
    def _looks_screen_gaze_warning(text: str) -> bool:
        normalized = text.strip().lower().replace(" ", "")
        gaze_markers = (
            "头先抬",
            "抬头",
            "抬起头",
            "头抬起来",
            "把头抬",
            "看镜头",
            "看摄像头",
            "视线回到镜头",
            "视线回到摄像头",
            "低头",
            "头低",
            "raise your head".replace(" ", ""),
            "lift your head".replace(" ", ""),
            "look at the camera".replace(" ", ""),
            "look into the camera".replace(" ", ""),
            "bring your gaze back to the camera".replace(" ", ""),
            "head down".replace(" ", ""),
            "downward gaze".replace(" ", ""),
        )
        return any(marker in normalized for marker in gaze_markers)

    @staticmethod
    def _looks_strong_head_down_evidence(text: str) -> bool:
        normalized = text.strip().lower().replace(" ", "")
        strong_markers = (
            "持续低头",
            "长时间低头",
            "明显低头",
            "一直低头",
            "下巴内收",
            "下巴贴近",
            "脸明显朝下",
            "整张脸朝下",
            "headstaysdown",
            "sustainedheaddown",
            "clearlyheaddown",
            "clearlyloweredhead",
            "chintucked",
            "faceangleddownward",
            "sustaineddownwardgaze",
        )
        return any(marker in normalized for marker in strong_markers)

    def _fallback_adjust_detail(
        self,
        language: LanguageOption,
        dimension_id: str,
        headline: str,
        detail: str = "",
    ) -> str:
        combined = f"{headline} {detail}"
        if language == "en":
            if dimension_id == "body_expression":
                normalized = combined.strip().lower()
                if self._looks_face_blocking_signal(combined):
                    return "Move the hand fully away from your face."
                if "hand" in normalized or "gesture" in normalized:
                    return "Bring the gesture back near your chest."
                if "face" in normalized or "gaze" in normalized or "eye" in normalized:
                    return "Bring your gaze back near the top of the screen."
                return "Fix this first, then keep going."
            if dimension_id == "voice_pacing":
                return "Adjust this on the next line."
            return "Make this change in the next sentence."

        if dimension_id == "body_expression":
            if self._looks_face_blocking_signal(combined):
                return "手先离开脸外。"
            if "手" in combined or "动作" in combined or "手势" in combined:
                return "手势先收回胸前。"
            if "眼" in combined or "脸" in combined or "表情" in combined or "视线" in combined:
                return "视线回到屏幕上方。"
            if "镜头" in combined or "回正" in combined or "居中" in combined:
                return "先把位置调回镜头中间。"
            return "先按上面这一步调整。"

        if dimension_id == "voice_pacing":
            return "下一句先按这一步调整。"

        return "下一句先按这一步修改。"

    def _fallback_nonwarning_headline(
        self,
        language: LanguageOption,
        dimension_id: str,
        status: str,
    ) -> str:
        if language == "en":
            if status == "doing_well":
                return {
                    "body_expression": "Body looks solid",
                    "voice_pacing": "Pacing is working",
                    "content_expression": "Message is clear",
                }.get(dimension_id, "This part is working")
            return {
                "body_expression": "Body is mostly stable",
                "voice_pacing": "Pacing is mostly stable",
                "content_expression": "The message is mostly clear",
            }.get(dimension_id, "This part is mostly stable")

        if status == "doing_well":
            return {
                "body_expression": "肢体状态不错",
                "voice_pacing": "语音节奏不错",
                "content_expression": "内容表达清楚",
            }.get(dimension_id, "这一项做得不错")

        return {
            "body_expression": "肢体基本稳定",
            "voice_pacing": "语音基本稳定",
            "content_expression": "内容基本稳定",
        }.get(dimension_id, "这一项基本稳定")

    def _fallback_nonwarning_detail(self, language: LanguageOption, status: str) -> str:
        if language == "en":
            return "Keep going with this direction." if status == "doing_well" else "No obvious issue right now."
        return "继续保持这个状态。" if status == "doing_well" else "当前没有明显问题。"
