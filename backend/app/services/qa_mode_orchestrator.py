import asyncio
import logging
import os
import re
from dataclasses import dataclass, field
from time import monotonic

from app.schemas import (
    LanguageOption,
    QAQuestion,
    QAQuestionEvent,
    QAState,
    QAStateEvent,
    QAVoiceProfilesEvent,
    ScenarioType,
    TrainingMode,
    TranscriptChunk,
)
from app.services.content_brief_service import ContentBriefService
from app.services.content_source_service import ContentSourceService
from app.services.qa_brain_service import (
    AliyunQABrainService,
    GeneratedQuestion,
    ReferenceBrief,
)
from app.services.qa_omni_realtime_service import AliyunQAOmniRealtimeService
from app.services.voice_profile_service import VoiceProfileService

logger = logging.getLogger("speak_up.qa")
logger.setLevel(logging.INFO)


@dataclass
class QATurnRecord:
    turn_id: str
    question: GeneratedQuestion
    question_index: int
    round_index: int
    answer_text: str | None = None


@dataclass(frozen=True)
class QANextTurnPlan:
    action: str
    question_index: int
    round_index: int


@dataclass(frozen=True)
class QAQuestionFocus:
    title: str
    summary: str
    key_points: list[str]
    follow_up_angles: list[str]


@dataclass
class QASessionState:
    session_id: str
    scenario_id: ScenarioType
    language: LanguageOption
    enabled: bool = False
    training_mode: TrainingMode = "free_speech"
    voice_profile_id: str = "duojiong_he"
    document_name: str | None = None
    document_text: str | None = None
    manual_text: str | None = None
    phase: str = "idle"
    current_turn_id: str | None = None
    current_question: GeneratedQuestion | None = None
    current_answer_chunks: list[str] = field(default_factory=list)
    current_live_partial_answer: str | None = None
    latest_feedback: str | None = None
    brief: ReferenceBrief | None = None
    turns: list[QATurnRecord] = field(default_factory=list)
    question_focuses: list[QAQuestionFocus] = field(default_factory=list)
    max_question_topics: int = 3
    max_follow_ups_per_question: int = 3
    current_question_index: int = 0
    current_round_index: int = 0
    next_turn_action: str = "next_question"
    next_question_index: int = 1
    next_round_index: int = 1
    prewarm_training_mode: TrainingMode = "free_speech"
    prewarm_document_name: str | None = None
    prewarm_document_text: str | None = None
    prewarm_manual_text: str | None = None
    prewarm_signature: str = ""
    prewarm_brief: ReferenceBrief | None = None
    prewarm_source_chars: int = 0
    prewarm_transcript_count: int = 0
    prewarm_build_count: int = 0
    prewarm_updated_at: float = 0.0
    prewarm_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)


class QAModeOrchestrator:
    def __init__(self) -> None:
        self.voice_profile_service = VoiceProfileService()
        self.qa_brain_service = AliyunQABrainService()
        self.qa_omni_service = AliyunQAOmniRealtimeService()
        self.content_source_service = ContentSourceService()
        self.content_brief_service = ContentBriefService(self.qa_brain_service)
        self.sessions: dict[str, QASessionState] = {}
        self.prewarm_min_chars = max(80, int(os.getenv("QA_PREWARM_MIN_CHARS", "120")))
        self.prewarm_min_delta_chars = max(40, int(os.getenv("QA_PREWARM_MIN_DELTA_CHARS", "40")))
        self.max_question_topics = max(1, int(os.getenv("QA_MAX_QUESTION_TOPICS", "3")))
        self.max_follow_ups_per_question = max(
            0,
            int(os.getenv("QA_MAX_FOLLOW_UPS_PER_QUESTION", os.getenv("QA_MAX_ROUNDS_PER_QUESTION", "3"))),
        )

    def register_session(
        self,
        session_id: str,
        scenario_id: ScenarioType,
        language: LanguageOption,
        voice_profile_id: str | None = None,
    ) -> None:
        resolved_voice_profile_id = self.voice_profile_service.get(voice_profile_id).profile.id
        self.sessions[session_id] = QASessionState(
            session_id=session_id,
            scenario_id=scenario_id,
            language=language,
            voice_profile_id=resolved_voice_profile_id,
            max_question_topics=self.max_question_topics,
            max_follow_ups_per_question=self.max_follow_ups_per_question,
        )

    def close_session(self, session_id: str) -> None:
        self.sessions.pop(session_id, None)

    def list_voice_profiles(self) -> list:
        return self.voice_profile_service.list_profiles()

    def build_voice_profiles_event(self) -> QAVoiceProfilesEvent:
        return QAVoiceProfilesEvent(voiceProfiles=self.list_voice_profiles())

    def get_audio_path(self, session_id: str, turn_id: str):
        return self.qa_omni_service.get_audio_path(session_id, turn_id)

    def get_state(self, session_id: str) -> QAState:
        session = self.sessions.get(session_id)
        if session is None:
            return QAState()
        return self._to_state(session)

    def get_voice_profile_config(self, session_id: str):
        session = self.sessions[session_id]
        return self.voice_profile_service.get(session.voice_profile_id)

    def is_enabled(self, session_id: str) -> bool:
        session = self.sessions.get(session_id)
        return bool(session and session.enabled)

    def is_user_answering(self, session_id: str) -> bool:
        session = self.sessions.get(session_id)
        return bool(session and session.enabled and session.phase == "user_answering")

    def is_ai_asking(self, session_id: str) -> bool:
        session = self.sessions.get(session_id)
        return bool(session and session.enabled and session.phase == "ai_asking")

    def configure_prewarm_context(
        self,
        *,
        session_id: str,
        training_mode: TrainingMode,
        document_name: str | None,
        document_text: str | None,
        manual_text: str | None,
    ) -> None:
        session = self.sessions[session_id]
        signature = self._context_signature(
            training_mode=training_mode,
            document_name=document_name,
            document_text=document_text,
            manual_text=manual_text,
        )
        if signature != session.prewarm_signature:
            self._reset_prewarm_cache(session)

        session.prewarm_training_mode = training_mode
        session.prewarm_document_name = document_name
        session.prewarm_document_text = document_text
        session.prewarm_manual_text = manual_text
        session.prewarm_signature = signature

    async def prewarm_question_cache(
        self,
        *,
        session_id: str,
        transcript_chunks: list[TranscriptChunk],
    ) -> None:
        session = self.sessions.get(session_id)
        if session is None:
            return

        async with session.prewarm_lock:
            bundle = self.content_source_service.build_bundle(
                training_mode=session.prewarm_training_mode,
                document_name=session.prewarm_document_name,
                document_text=session.prewarm_document_text,
                manual_text=session.prewarm_manual_text,
                transcript_chunks=transcript_chunks,
            )
            combined_chars = len(bundle.combined_text)
            if combined_chars < self.prewarm_min_chars:
                logger.info("qa.prewarm.skip session=%s reason=too_short combined_chars=%s", session_id, combined_chars)
                return
            if combined_chars - session.prewarm_source_chars < self.prewarm_min_delta_chars:
                logger.info(
                    "qa.prewarm.skip session=%s reason=small_delta combined_chars=%s previous_chars=%s",
                    session_id,
                    combined_chars,
                    session.prewarm_source_chars,
                )
                return

            started_at = monotonic()
            logger.info(
                "qa.prewarm.begin session=%s mode=%s transcript_chunks=%s combined_chars=%s cached_builds=%s",
                session_id,
                session.prewarm_training_mode,
                len(transcript_chunks),
                combined_chars,
                session.prewarm_build_count,
            )
            brief = await self.content_brief_service.build_reference_brief(
                scenario_id=session.scenario_id,
                language=session.language,
                training_mode=session.prewarm_training_mode,
                bundle=bundle,
            )
            session.prewarm_brief = self._merge_cached_brief(session.prewarm_brief, brief)
            session.prewarm_source_chars = combined_chars
            session.prewarm_transcript_count = len(transcript_chunks)
            session.prewarm_build_count += 1
            session.prewarm_updated_at = monotonic()
            if session.enabled and session.prewarm_brief is not None:
                session.brief = session.prewarm_brief
            logger.info(
                "qa.prewarm.done session=%s elapsed_ms=%s topics=%s",
                session_id,
                int((monotonic() - started_at) * 1000),
                len(session.prewarm_brief.main_topics) if session.prewarm_brief else 0,
            )

    def prepare_start_qa(
        self,
        *,
        session_id: str,
        training_mode: TrainingMode,
        voice_profile_id: str | None,
        document_name: str | None,
        document_text: str | None,
        manual_text: str | None,
    ) -> list[QAStateEvent]:
        session = self.sessions[session_id]
        logger.info(
            "qa.prepare_start session=%s mode=%s voice=%s has_document=%s has_manual=%s",
            session_id,
            training_mode,
            voice_profile_id or "default",
            bool(document_text),
            bool(manual_text),
        )
        signature = self._context_signature(
            training_mode=training_mode,
            document_name=document_name,
            document_text=document_text,
            manual_text=manual_text,
        )
        if signature != session.prewarm_signature:
            self._reset_prewarm_cache(session)
            session.prewarm_signature = signature
        session.enabled = True
        session.training_mode = training_mode
        session.voice_profile_id = self.voice_profile_service.get(voice_profile_id).profile.id
        session.document_name = document_name
        session.document_text = document_text
        session.manual_text = manual_text
        session.prewarm_training_mode = training_mode
        session.prewarm_document_name = document_name
        session.prewarm_document_text = document_text
        session.prewarm_manual_text = manual_text
        self._reset_current_turn(session)
        session.brief = session.prewarm_brief
        session.turns = []
        session.question_focuses = self._build_question_focuses(session, session.brief)
        session.current_question_index = 0
        session.current_round_index = 0
        session.next_turn_action = "next_question"
        session.next_question_index = 1
        session.next_round_index = 1
        session.phase = "preparing_context"
        logger.info(
            "qa.focus_plan session=%s focuses=%s",
            session_id,
            [focus.title for focus in session.question_focuses],
        )
        return [QAStateEvent(qaState=self._to_state(session))]

    def stop_qa(self, *, session_id: str) -> list[QAStateEvent]:
        session = self.sessions[session_id]
        session.enabled = False
        session.phase = "idle"
        self._reset_current_turn(session)
        session.brief = session.prewarm_brief
        session.turns = []
        session.question_focuses = []
        session.current_question_index = 0
        session.current_round_index = 0
        session.next_turn_action = "next_question"
        session.next_question_index = 1
        session.next_round_index = 1
        return [QAStateEvent(qaState=self._to_state(session))]

    def prepare_next_question(self, *, session_id: str) -> list[QAStateEvent]:
        session = self.sessions[session_id]
        next_question_index = session.current_question_index + 1 if session.current_question_index else 1
        session.next_turn_action = "next_question"
        session.next_question_index = min(next_question_index, session.max_question_topics)
        session.next_round_index = 1
        return self.begin_waiting_for_next_response(session_id=session_id)

    def begin_waiting_for_next_response(self, *, session_id: str) -> list[QAStateEvent]:
        session = self.sessions[session_id]
        self._flush_current_answer(session)
        self._reset_current_turn(session)
        session.phase = "preparing_context"
        return [QAStateEvent(qaState=self._to_state(session))]

    def prepare_after_answer(self, *, session_id: str) -> tuple[QANextTurnPlan, list]:
        session = self.sessions[session_id]
        answer_text = self._flush_current_answer(session)
        plan = self._build_next_turn_plan(session, answer_text)
        logger.info(
            "qa.plan_next_turn session=%s current_question=%s current_round=%s action=%s next_question=%s next_round=%s answer_chars=%s",
            session_id,
            session.current_question_index,
            session.current_round_index,
            plan.action,
            plan.question_index,
            plan.round_index,
            len(answer_text),
        )
        return self._apply_turn_plan(session, plan)

    def prepare_after_silence_timeout(self, *, session_id: str) -> tuple[QANextTurnPlan, list]:
        session = self.sessions[session_id]
        answer_text = self._flush_current_answer(session)
        plan = self._build_timeout_next_turn_plan(session)
        logger.info(
            "qa.plan_timeout_next_turn session=%s current_question=%s current_round=%s action=%s next_question=%s next_round=%s answer_chars=%s",
            session_id,
            session.current_question_index,
            session.current_round_index,
            plan.action,
            plan.question_index,
            plan.round_index,
            len(answer_text),
        )
        return self._apply_turn_plan(session, plan)

    def _apply_turn_plan(self, session: QASessionState, plan: QANextTurnPlan) -> tuple[QANextTurnPlan, list]:
        if plan.action == "end_qa":
            closing_text = (
                f"本轮问答已完成，共 {session.max_question_topics} 个问题，"
                f"每题最多追问 {session.max_follow_ups_per_question} 次。"
            )
            session.current_turn_id = None
            session.current_question = GeneratedQuestion(
                question_text=closing_text,
                goal="问答结束",
                expected_points=[],
                follow_up=False,
            )
            session.current_answer_chunks = []
            session.current_live_partial_answer = None
            session.latest_feedback = closing_text
            session.phase = "completed"
            session.next_turn_action = "end_qa"
            session.next_question_index = plan.question_index
            session.next_round_index = plan.round_index
            return plan, [
                QAQuestionEvent(
                    question=QAQuestion(
                        turnId="qa-completed",
                        questionText=closing_text,
                        goal="问答结束",
                        followUp=False,
                        expectedPoints=[],
                    )
                ),
                QAStateEvent(qaState=self._to_state(session)),
            ]

        session.next_turn_action = plan.action
        session.next_question_index = plan.question_index
        session.next_round_index = plan.round_index
        self._reset_current_turn(session)
        session.phase = "preparing_context"
        return plan, [QAStateEvent(qaState=self._to_state(session))]

    def select_voice_profile(self, *, session_id: str, voice_profile_id: str | None) -> list[QAStateEvent]:
        session = self.sessions[session_id]
        session.voice_profile_id = self.voice_profile_service.get(voice_profile_id).profile.id
        return [QAStateEvent(qaState=self._to_state(session))]

    def ingest_transcript_chunk(self, session_id: str, chunk: TranscriptChunk) -> None:
        session = self.sessions.get(session_id)
        if session is None or not session.enabled or session.phase != "user_answering":
            return
        if chunk.speaker != "user" or not chunk.text.strip():
            return
        session.current_answer_chunks.append(chunk.text.strip())
        session.current_live_partial_answer = None

    def replace_last_transcript_chunk(self, session_id: str, chunk: TranscriptChunk) -> None:
        session = self.sessions.get(session_id)
        if session is None or not session.enabled or session.phase != "user_answering":
            return
        if chunk.speaker != "user" or not chunk.text.strip():
            return
        if session.current_answer_chunks:
            session.current_answer_chunks[-1] = chunk.text.strip()
        else:
            session.current_answer_chunks.append(chunk.text.strip())
        session.current_live_partial_answer = None

    def update_live_partial_answer(self, session_id: str, text: str) -> None:
        session = self.sessions.get(session_id)
        if session is None or not session.enabled or session.phase != "user_answering":
            return
        normalized = text.strip()
        if not normalized:
            return
        session.current_live_partial_answer = normalized

    def clear_live_partial_answer(self, session_id: str) -> None:
        session = self.sessions.get(session_id)
        if session is None:
            return
        session.current_live_partial_answer = None

    def current_answer_text(self, session_id: str) -> str:
        session = self.sessions.get(session_id)
        if session is None:
            return ""
        return self._compose_current_answer_text(session)

    def handle_assistant_turn_started(self, *, session_id: str, turn_id: str) -> list[QAStateEvent]:
        session = self.sessions[session_id]
        self._flush_current_answer(session)
        if session.prewarm_brief is not None:
            session.brief = session.prewarm_brief
        follow_up = session.next_turn_action == "follow_up"
        self._reset_current_turn(session)
        session.current_question_index = session.next_question_index
        session.current_round_index = session.next_round_index
        session.current_turn_id = turn_id
        session.current_question = GeneratedQuestion(
            question_text="",
            goal=self._default_question_goal(
                session,
                follow_up=follow_up,
                question_index=session.current_question_index,
                round_index=session.current_round_index,
            ),
            expected_points=self._expected_points_for_question(session, session.current_question_index),
            follow_up=follow_up,
        )
        session.phase = "ai_asking"
        if session.turns and session.turns[-1].turn_id == turn_id:
            session.turns[-1].question = session.current_question
        else:
            session.turns.append(
                QATurnRecord(
                    turn_id=turn_id,
                    question=session.current_question,
                    question_index=session.current_question_index,
                    round_index=session.current_round_index,
                )
            )
        logger.info(
            "qa.realtime.turn_started session=%s turn=%s question=%s round=%s follow_up=%s",
            session_id,
            turn_id,
            session.current_question_index,
            session.current_round_index,
            follow_up,
        )
        return [QAStateEvent(qaState=self._to_state(session))]

    def handle_assistant_transcript(
        self,
        *,
        session_id: str,
        turn_id: str,
        text: str,
        is_final: bool,
    ) -> list:
        session = self.sessions[session_id]
        if session.current_turn_id != turn_id:
            self.handle_assistant_turn_started(session_id=session_id, turn_id=turn_id)
        normalized = text.strip()
        if session.current_question is None:
            session.current_question = GeneratedQuestion(
                question_text=normalized,
                goal=self._default_question_goal(
                    session,
                    follow_up=session.next_turn_action == "follow_up",
                    question_index=session.current_question_index or session.next_question_index or 1,
                    round_index=session.current_round_index or session.next_round_index or 1,
                ),
                expected_points=self._expected_points_for_question(
                    session,
                    session.current_question_index or session.next_question_index or 1,
                ),
                follow_up=session.next_turn_action == "follow_up",
            )
        else:
            session.current_question = GeneratedQuestion(
                question_text=normalized,
                goal=session.current_question.goal,
                expected_points=session.current_question.expected_points,
                follow_up=session.current_question.follow_up,
            )
        if session.turns and session.turns[-1].turn_id == turn_id:
            session.turns[-1].question = session.current_question

        events: list = [
            QAQuestionEvent(
                question=QAQuestion(
                    turnId=turn_id,
                    questionText=normalized,
                    goal=session.current_question.goal,
                    followUp=session.current_question.follow_up,
                    expectedPoints=session.current_question.expected_points,
                )
            )
        ]
        if is_final:
            session.phase = "user_answering"
            events.append(QAStateEvent(qaState=self._to_state(session)))
        return events

    def build_realtime_instructions(
        self,
        *,
        session_id: str,
        transcript_chunks: list[TranscriptChunk],
    ) -> str:
        session = self.sessions[session_id]
        bundle = self.content_source_service.build_bundle(
            training_mode=session.training_mode,
            document_name=session.document_name,
            document_text=session.document_text,
            manual_text=session.manual_text,
            transcript_chunks=transcript_chunks,
        )
        brief = session.prewarm_brief or session.brief or self.qa_brain_service._fallback_brief(bundle)  # type: ignore[attr-defined]
        session.brief = brief
        self._ensure_question_focuses(session, brief)
        profile = self.voice_profile_service.get(session.voice_profile_id)
        summary = (brief.source_summary or bundle.combined_text[:520]).strip() or "当前上下文较少，请先从一个具体判断或最近提到的信息开始提问。"
        topics = "；".join(brief.main_topics[:6]) or "具体判断、支撑依据、表达结构、听众收获"
        key_points = "；".join(brief.key_points[:8]) or "先给一个具体判断，再给依据，再说明和听众有什么关系。"
        latest_context = self._latest_user_transcript(transcript_chunks) or "无"
        language_name = "中文" if session.language == "zh" else "English"
        progress_instruction = self._build_turn_progress_instruction(session)
        focus_instruction = self._build_focus_instruction(session)
        return (
            f"你是 Speak Up 的实时 AI interviewer/评委/教练，请始终使用{language_name}和用户对话。"
            f"{profile.instructions_for(session.language)}"
            "这是一个演讲后的问答训练，不是闲聊。"
            f"当前训练场景是：{session.scenario_id}；训练模式是：{session.training_mode}。"
            f"硬性限制：整轮最多 {session.max_question_topics} 个问题主题，每个问题主题最多追问 {session.max_follow_ups_per_question} 次。"
            f"{progress_instruction}"
            f"{focus_instruction}"
            "你的工作方式："
            "第一，进入会话后立刻主动发起第一问，不要等用户先提问，不要寒暄。"
            "第二，此后每次在用户回答结束后，只输出下一条你要问的问题。"
            "第三，如果用户回答太短、太空、太泛、没有落点，就追问同一个点；如果回答已经成形，就自然切到下一题。"
            "第四，每次只问一个问题，不要打分，不要长反馈，不要总结规则，不要列点。"
            "第五，问题必须适合直接口播，短、清楚、专业、可回答。"
            "补充要求：所有问题都必须是用户直接能听懂的自然表达，"
            "禁止出现维度反馈、系统检测、模型判断、置信度、覆盖率、评分机制等内部术语，"
            "也不要说 rhythm、vocal_tone、content_quality、expression_structure、facial_expression、body 这类内部维度名。"
            "不要反复追问“表达核心是什么”“核心结论是什么”这类泛问题；"
            "如果上下文足够，就围绕最近提到的具体信息、证据、听众收获、取舍或下一步追问。"
            "第六，绝对不要自问自答，绝对不要替用户回答，绝对不要在问题后补充参考答案、提示语、解释、点评或过渡总结。"
            "第七，说出第一个完整问题后立刻停下，本轮输出必须结束。"
            f"你可参考的背景摘要：{summary}。"
            f"主要话题：{topics}。"
            f"关键点：{key_points}。"
            f"进入问答前用户最近一次表达的摘要：{latest_context}。"
            "如果用户停顿、语气词很多、表达零散，你要自己抓主线继续追问。"
            "如果用户已经回答得比较完整，你就提高难度或换到下一个关键点。"
            "永远把输出控制为一条自然口语化的问题。"
        )

    def _flush_current_answer(self, session: QASessionState) -> str:
        if session.current_turn_id is None or not session.turns:
            return ""
        answer_text = self._compose_current_answer_text(session)
        if answer_text and session.turns[-1].turn_id == session.current_turn_id:
            session.turns[-1].answer_text = answer_text
        session.current_live_partial_answer = None
        return answer_text

    @staticmethod
    def _compose_current_answer_text(session: QASessionState) -> str:
        chunks = [chunk.strip() for chunk in session.current_answer_chunks if chunk.strip()]
        live_partial = (session.current_live_partial_answer or "").strip()
        if not live_partial:
            return " ".join(chunks).strip()
        if not chunks:
            return live_partial

        committed_answer = " ".join(chunks).strip()
        if live_partial == chunks[-1] or live_partial in chunks:
            return committed_answer
        if live_partial.startswith(chunks[-1]):
            return " ".join([*chunks[:-1], live_partial]).strip()
        if live_partial.startswith(committed_answer):
            return live_partial
        return f"{committed_answer} {live_partial}".strip()

    def _build_next_turn_plan(self, session: QASessionState, answer_text: str) -> QANextTurnPlan:
        current_question_index = session.current_question_index or 1
        current_round_index = max(session.current_round_index, 1)
        max_round_index = self._max_round_index(session)
        if current_question_index >= session.max_question_topics:
            if current_round_index < max_round_index and self._should_follow_up(session, answer_text):
                return QANextTurnPlan(
                    action="follow_up",
                    question_index=current_question_index,
                    round_index=current_round_index + 1,
                )
            return QANextTurnPlan(
                action="end_qa",
                question_index=current_question_index,
                round_index=current_round_index,
            )

        if current_round_index < max_round_index and self._should_follow_up(session, answer_text):
            return QANextTurnPlan(
                action="follow_up",
                question_index=current_question_index,
                round_index=current_round_index + 1,
            )

        return QANextTurnPlan(
            action="next_question",
            question_index=current_question_index + 1,
            round_index=1,
        )

    def _build_timeout_next_turn_plan(self, session: QASessionState) -> QANextTurnPlan:
        current_question_index = session.current_question_index or 1
        current_round_index = max(session.current_round_index, 1)

        if current_question_index < session.max_question_topics:
            return QANextTurnPlan(
                action="next_question",
                question_index=current_question_index + 1,
                round_index=1,
            )

        return QANextTurnPlan(
            action="end_qa",
            question_index=current_question_index,
            round_index=current_round_index,
        )

    def _should_follow_up(self, session: QASessionState, answer_text: str) -> bool:
        if session.current_round_index >= self._max_round_index(session):
            return False
        if not answer_text.strip():
            return True

        compact_answer = re.sub(r"\s+", "", answer_text)
        if session.language == "zh":
            if len(compact_answer) < 30:
                return True
        else:
            if len(re.findall(r"\b\w+\b", answer_text)) < 12:
                return True

        question = session.current_question
        if question is None or not question.expected_points:
            return False

        normalized_answer = self._normalize_text(answer_text)
        expected_hits = 0
        for point in question.expected_points[:3]:
            fragments = [
                fragment.strip()
                for fragment in re.split(r"[，,；;、/|]", point)
                if fragment.strip()
            ]
            if not fragments:
                fragments = [point.strip()]
            matched = False
            for fragment in fragments:
                normalized_fragment = self._normalize_text(fragment)
                if normalized_fragment and normalized_fragment in normalized_answer:
                    matched = True
                    break
            if matched:
                expected_hits += 1

        if expected_hits == 0 and len(compact_answer) < 50:
            return True
        if expected_hits < min(2, len(question.expected_points)) and len(compact_answer) < 35:
            return True
        return False

    @staticmethod
    def _normalize_text(text: str) -> str:
        return re.sub(r"[\s,.!?，。！？、…:：;；\"'“”‘’（）()\-\u3000]+", "", text).lower()

    @staticmethod
    def _reset_current_turn(session: QASessionState) -> None:
        session.current_turn_id = None
        session.current_question = None
        session.current_answer_chunks = []
        session.current_live_partial_answer = None
        session.latest_feedback = None

    @staticmethod
    def _reset_prewarm_cache(session: QASessionState) -> None:
        session.prewarm_brief = None
        session.prewarm_source_chars = 0
        session.prewarm_transcript_count = 0
        session.prewarm_build_count = 0
        session.prewarm_updated_at = 0.0

    def _build_turn_progress_instruction(self, session: QASessionState) -> str:
        focus = self._question_focus(session, session.next_question_index)
        focus_label = f"“{focus.title}”" if focus else "当前主题"
        if session.next_turn_action == "follow_up":
            follow_up_index = max(session.next_round_index - 1, 1)
            return (
                f"下一轮必须围绕第 {session.next_question_index} 个问题的主题{focus_label}继续追问，"
                f"这是该问题的第 {follow_up_index} 次追问，不得切换到新问题。"
            )
        if session.next_turn_action == "next_question":
            previous_focus = self._question_focus(session, max(session.next_question_index - 1, 1))
            previous_label = f"“{previous_focus.title}”" if previous_focus else "上一题"
            return (
                f"下一轮必须切换到第 {session.next_question_index} 个新问题，主题必须换成{focus_label}，"
                f"不要继续围绕{previous_label}追问。"
            )
        return "问答上限已到，不要再提问。"

    @staticmethod
    def _max_round_index(session: QASessionState) -> int:
        return max(1, session.max_follow_ups_per_question + 1)

    def _merge_cached_brief(self, existing: ReferenceBrief | None, incoming: ReferenceBrief) -> ReferenceBrief:
        if existing is None:
            return self._compress_cached_brief(incoming)
        return self._compress_cached_brief(
            ReferenceBrief(
                title=incoming.title or existing.title,
                source_summary=(incoming.source_summary or existing.source_summary)[:520],
                main_topics=self._merge_unique(existing.main_topics, incoming.main_topics, limit=10),
                key_points=self._merge_unique(existing.key_points, incoming.key_points, limit=14),
                factual_claims=self._merge_unique(existing.factual_claims, incoming.factual_claims, limit=10),
                assumptions=self._merge_unique(existing.assumptions, incoming.assumptions, limit=8),
                risk_points=self._merge_unique(existing.risk_points, incoming.risk_points, limit=8),
                open_questions=self._merge_unique(existing.open_questions, incoming.open_questions, limit=8),
                challengeable_points=self._merge_unique(existing.challengeable_points, incoming.challengeable_points, limit=10),
                notable_numbers=self._merge_unique(existing.notable_numbers, incoming.notable_numbers, limit=8),
                topic_sections=[*existing.topic_sections, *incoming.topic_sections][-6:],
            )
        )

    @staticmethod
    def _compress_cached_brief(brief: ReferenceBrief | None) -> ReferenceBrief | None:
        if brief is None:
            return None
        return ReferenceBrief(
            title=brief.title,
            source_summary=brief.source_summary[:520],
            main_topics=brief.main_topics[-8:],
            key_points=brief.key_points[-12:],
            factual_claims=brief.factual_claims[-8:],
            assumptions=brief.assumptions[-8:],
            risk_points=brief.risk_points[-8:],
            open_questions=brief.open_questions[-8:],
            challengeable_points=brief.challengeable_points[-8:],
            notable_numbers=brief.notable_numbers[-8:],
            topic_sections=brief.topic_sections[-5:],
        )

    @staticmethod
    def _merge_unique(existing: list[str], incoming: list[str], *, limit: int) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()
        for item in [*existing, *incoming]:
            normalized = item.strip()
            key = normalized.lower()
            if not normalized or key in seen:
                continue
            seen.add(key)
            merged.append(normalized)
        return merged[-limit:]

    @staticmethod
    def _context_signature(
        *,
        training_mode: TrainingMode,
        document_name: str | None,
        document_text: str | None,
        manual_text: str | None,
    ) -> str:
        return "|".join(
            [
                training_mode,
                document_name or "",
                str(hash(document_text or "")),
                str(hash(manual_text or "")),
            ]
        )

    @staticmethod
    def _latest_user_transcript(transcript_chunks: list[TranscriptChunk]) -> str | None:
        for chunk in reversed(transcript_chunks):
            if chunk.speaker == "user" and chunk.text.strip():
                return chunk.text.strip()
        return None

    @staticmethod
    def _default_expected_points(brief: ReferenceBrief | None) -> list[str]:
        if brief and brief.key_points:
            return brief.key_points[:3]
        return ["具体判断", "关键依据", "听众收获"]

    def _expected_points_for_question(self, session: QASessionState, question_index: int) -> list[str]:
        focus = self._question_focus(session, question_index)
        if focus and focus.key_points:
            return focus.key_points[:3]
        return self._default_expected_points(session.brief)

    def _default_question_goal(
        self,
        session: QASessionState,
        *,
        follow_up: bool,
        question_index: int,
        round_index: int,
    ) -> str:
        question_prefix = f"第 {question_index} 个问题"
        focus = self._question_focus(session, question_index)
        focus_label = f"“{focus.title}”" if focus else "当前主题"
        if follow_up:
            follow_up_index = max(round_index - 1, 1)
            return f"{question_prefix}围绕{focus_label}的第 {follow_up_index} 次追问，继续深挖。"
        if session.training_mode == "document_speech":
            return f"{question_prefix}聚焦{focus_label}，确认用户是否讲清这一部分。"
        return f"{question_prefix}聚焦{focus_label}，从新的方面继续问答。"

    def _ensure_question_focuses(self, session: QASessionState, brief: ReferenceBrief | None) -> None:
        if len(session.question_focuses) >= session.max_question_topics:
            return
        session.question_focuses = self._build_question_focuses(session, brief)

    def _build_question_focuses(self, session: QASessionState, brief: ReferenceBrief | None) -> list[QAQuestionFocus]:
        defaults = self._default_focus_templates(session.training_mode)
        focus_by_axis = defaults.copy()
        matched_axes: list[str] = []

        for candidate in self._iter_focus_candidates(brief):
            axis = self._classify_focus_axis(
                " ".join([candidate.title, candidate.summary, *candidate.key_points, *candidate.follow_up_angles])
            )
            if axis is None or axis in matched_axes:
                continue
            matched_axes.append(axis)
            default_focus = focus_by_axis[axis]
            focus_by_axis[axis] = QAQuestionFocus(
                title=candidate.title or default_focus.title,
                summary=candidate.summary or default_focus.summary,
                key_points=candidate.key_points[:3] or default_focus.key_points,
                follow_up_angles=candidate.follow_up_angles[:3] or default_focus.follow_up_angles,
            )

        ordered_axes = [*matched_axes, *[axis for axis in ("content", "voice", "body") if axis not in matched_axes]]
        return [focus_by_axis[axis] for axis in ordered_axes[: session.max_question_topics]]

    @staticmethod
    def _iter_focus_candidates(brief: ReferenceBrief | None) -> list[QAQuestionFocus]:
        if brief is None:
            return []

        candidates: list[QAQuestionFocus] = []
        for section in brief.topic_sections:
            title = section.title.strip()
            if not title:
                continue
            candidates.append(
                QAQuestionFocus(
                    title=title,
                    summary=section.summary.strip(),
                    key_points=[item.strip() for item in section.key_points if item.strip()][:3],
                    follow_up_angles=[item.strip() for item in section.follow_up_angles if item.strip()][:3],
                )
            )

        for topic in brief.main_topics:
            normalized = topic.strip()
            if not normalized:
                continue
            candidates.append(
                QAQuestionFocus(
                    title=normalized,
                    summary="",
                    key_points=brief.key_points[:3],
                    follow_up_angles=brief.open_questions[:3],
                )
            )
        return candidates

    @staticmethod
    def _classify_focus_axis(text: str) -> str | None:
        normalized = text.lower()
        keyword_groups = {
            "body": ("肢体", "姿态", "手势", "站姿", "眼神", "表情", "镜头", "动作", "body", "gesture", "posture", "camera", "expression"),
            "voice": ("语音", "语速", "语调", "停顿", "节奏", "发声", "声音", "重音", "voice", "pace", "tone", "pause", "intonation"),
            "content": ("内容", "逻辑", "结构", "主线", "观点", "结论", "论据", "材料", "信息", "表达", "content", "logic", "structure", "argument", "message"),
        }
        for axis, keywords in keyword_groups.items():
            if any(keyword in normalized for keyword in keywords):
                return axis
        return None

    @staticmethod
    def _default_focus_templates(training_mode: TrainingMode) -> dict[str, QAQuestionFocus]:
        content_summary = (
            "围绕演讲内容本身，确认表达落点、观点、论据和听众收获是否说清楚。"
            if training_mode == "document_speech"
            else "围绕刚才表达的内容落点，确认观点、论据和听众收获是否清楚。"
        )
        return {
            "content": QAQuestionFocus(
                title="表达落点",
                summary=content_summary,
                key_points=["具体判断", "支撑依据", "听众收获"],
                follow_up_angles=["主线是否清晰", "论据是否站得住", "落点是否对听众有价值"],
            ),
            "voice": QAQuestionFocus(
                title="语音表达",
                summary="围绕语速、停顿、重音和语气设计，确认声音是否有感染力、是否便于理解。",
                key_points=["语速节奏", "停顿重音", "语气层次"],
                follow_up_angles=["哪里该慢一点", "哪里该强调", "如何让听众更容易跟上"],
            ),
            "body": QAQuestionFocus(
                title="肢体表现",
                summary="围绕站姿、手势、眼神和镜头感，确认肢体是否稳定、自然并服务表达。",
                key_points=["姿态稳定", "手势匹配", "眼神与镜头交流"],
                follow_up_angles=["哪些动作有效", "哪些动作会分散注意力", "如何让肢体更好服务内容"],
            ),
        }

    def _build_focus_instruction(self, session: QASessionState) -> str:
        focus = self._question_focus(session, session.next_question_index)
        if focus is None:
            return ""

        covered = [item.title for index, item in enumerate(session.question_focuses, start=1) if index < session.next_question_index]
        remaining = [item.title for index, item in enumerate(session.question_focuses, start=1) if index >= session.next_question_index]
        key_points = "；".join(focus.key_points[:3]) or "具体判断、关键依据、听众收获"
        angles = "；".join(focus.follow_up_angles[:3]) or "先挑一个判断、补充依据、说明和听众有什么关系"
        covered_text = "；".join(covered) if covered else "无"
        remaining_text = "；".join(remaining) if remaining else focus.title
        return (
            f"本轮题目规划如下：已完成主题 {covered_text}；接下来可覆盖主题 {remaining_text}。"
            f"当前第 {session.next_question_index} 个问题的主题必须是“{focus.title}”。"
            f"主题说明：{focus.summary}"
            f"这一题优先覆盖：{key_points}。"
            f"如果继续追问，优先深挖这些角度：{angles}。"
        )

    @staticmethod
    def _question_focus(session: QASessionState, question_index: int) -> QAQuestionFocus | None:
        if question_index <= 0 or question_index > len(session.question_focuses):
            return None
        return session.question_focuses[question_index - 1]

    @staticmethod
    def _to_state(session: QASessionState) -> QAState:
        return QAState(
            enabled=session.enabled,
            phase=session.phase,
            currentTurnId=session.current_turn_id,
            currentQuestion=session.current_question.question_text if session.current_question else None,
            currentQuestionGoal=session.current_question.goal if session.current_question else None,
            latestFeedback=session.latest_feedback,
            speaking=False,
            voiceProfileId=session.voice_profile_id,
        )
