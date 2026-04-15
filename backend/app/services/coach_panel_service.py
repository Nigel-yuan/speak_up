from dataclasses import dataclass

from app.schemas import (
    CoachPanelPatch,
    CoachPanelPatchDimension,
    CoachDimensionState,
    CoachPanelState,
    CoachSummary,
    InsightTone,
    LanguageOption,
    LiveInsight,
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
        next_panel = session.panel.model_copy(
            update={
                "voicePacing": self._build_dimension(
                    "voice_pacing",
                    voice_status,
                    voice_headline,
                    voice_detail,
                    updated_at_ms,
                    "speech-rule",
                ),
                "contentExpression": self._build_dimension(
                    "content_expression",
                    content_status,
                    content_headline,
                    content_detail,
                    updated_at_ms,
                    "speech-rule",
                ),
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

        for dimension_patch in patch.dimensions:
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
            )
            next_panel = self._set_dimension(next_panel, next_dimension)

        return self._commit_panel(session_id, next_panel)

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
            ),
            voicePacing=self._build_dimension(
                "voice_pacing",
                "analyzing",
                self._text(language, "正在更新语音反馈", "Updating vocal pacing"),
                self._text(language, "保持当前节奏", "Keep your current rhythm"),
                0,
                "system",
            ),
            contentExpression=self._build_dimension(
                "content_expression",
                "analyzing",
                self._text(language, "正在更新内容反馈", "Updating content clarity"),
                self._text(language, "继续往下讲，稍后更新这一项反馈", "Keep going and this card will update shortly"),
                0,
                "system",
            ),
        )

    @staticmethod
    def build_debug_insight_from_patch(patch: CoachPanelPatch, insight_id: str) -> LiveInsight | None:
        if not patch.dimensions:
            return None

        priority_order = {
            "adjust_now": 3,
            "stable": 2,
            "doing_well": 1,
            "analyzing": 0,
        }
        chosen = max(
            patch.dimensions,
            key=lambda item: (priority_order.get(item.status, 0), -CoachPanelService._dimension_sort_index(item)),
        )
        if chosen.status == "analyzing":
            return None

        return LiveInsight(
            id=insight_id,
            title=chosen.headline,
            detail=chosen.detail,
            tone=CoachPanelService._map_display_status_to_tone(chosen.status),
            source="omni-coach",
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
    def _map_tone_to_display_status(tone: InsightTone) -> str:
        if tone == "warning":
            return "adjust_now"
        if tone == "positive":
            return "doing_well"
        return "stable"

    @staticmethod
    def _map_display_status_to_tone(status: str) -> InsightTone:
        if status == "adjust_now":
            return "warning"
        if status == "doing_well":
            return "positive"
        return "neutral"

    def _classify_omni_dimension(self, insight: LiveInsight, language: LanguageOption) -> str:
        normalized = self._normalize(insight.title + " " + insight.detail)
        body_keywords = (
            "镜头",
            "肩",
            "头肩",
            "上身",
            "身体",
            "手势",
            "表情",
            "眼神",
            "画面",
            "居中",
            "camera",
            "frame",
            "posture",
            "shoulder",
            "gesture",
            "body",
            "eye",
        )
        voice_keywords = (
            "语速",
            "节奏",
            "语气",
            "吐字",
            "声音",
            "重音",
            "停顿",
            "起伏",
            "卡",
            "tone",
            "pace",
            "voice",
            "pause",
            "emphasis",
            "clear",
            "vocal",
        )
        content_keywords = (
            "内容",
            "主线",
            "结构",
            "逻辑",
            "观点",
            "表达",
            "重复",
            "口头禅",
            "推进",
            "message",
            "structure",
            "content",
            "point",
            "logic",
        )

        if any(keyword in normalized for keyword in body_keywords):
            return "body_expression"
        if any(keyword in normalized for keyword in voice_keywords):
            return "voice_pacing"
        if any(keyword in normalized for keyword in content_keywords):
            return "content_expression"
        return "voice_pacing" if language == "en" else "content_expression"

    @staticmethod
    def _dimension_sort_index(dimension: CoachPanelPatchDimension) -> int:
        order = {
            "body_expression": 0,
            "voice_pacing": 1,
            "content_expression": 2,
        }
        return order.get(dimension.id, 99)

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
    ) -> CoachDimensionState:
        return CoachDimensionState(
            id=dimension_id,
            status=status,
            headline=headline,
            detail=detail,
            updatedAtMs=updated_at_ms,
            source=source,
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

        if status == "adjust_now" and self._looks_resolved_or_positive(normalized_detail):
            return (
                status,
                normalized_headline,
                self._fallback_adjust_detail(language, dimension_id, normalized_headline),
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

    def _fallback_adjust_detail(
        self,
        language: LanguageOption,
        dimension_id: str,
        headline: str,
    ) -> str:
        if language == "en":
            if dimension_id == "body_expression":
                return "Fix this first, then keep going."
            if dimension_id == "voice_pacing":
                return "Adjust this on the next line."
            return "Make this change in the next sentence."

        if dimension_id == "body_expression":
            if "手" in headline or "脸" in headline:
                return "先把手离开脸，再继续讲。"
            if "镜头" in headline or "回正" in headline or "居中" in headline:
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
