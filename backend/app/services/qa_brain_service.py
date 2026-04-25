import json
import logging
import os
import re
from dataclasses import dataclass

import httpx

from app.schemas import LanguageOption, ScenarioType, TrainingMode
from app.services.content_source_service import ReferenceBundle

logger = logging.getLogger("speak_up.qa")


SCENARIO_LABELS: dict[ScenarioType, str] = {
    "general": "通用表达训练",
    "host": "通用表达训练",
    "guest-sharing": "嘉宾分享、主题演讲、路演",
    "standup": "脱口秀、高密度表达、强节奏输出",
}


@dataclass(frozen=True)
class TopicSection:
    title: str
    summary: str
    key_points: list[str]
    follow_up_angles: list[str]


@dataclass(frozen=True)
class ReferenceBrief:
    title: str | None
    source_summary: str
    main_topics: list[str]
    key_points: list[str]
    factual_claims: list[str]
    assumptions: list[str]
    risk_points: list[str]
    open_questions: list[str]
    challengeable_points: list[str]
    notable_numbers: list[str]
    topic_sections: list[TopicSection]


@dataclass(frozen=True)
class GeneratedQuestion:
    question_text: str
    goal: str
    expected_points: list[str]
    follow_up: bool


@dataclass(frozen=True)
class PreparedQAPack:
    brief: ReferenceBrief
    questions: list[GeneratedQuestion]


@dataclass(frozen=True)
class AnswerEvaluation:
    feedback_text: str
    strengths: list[str]
    missed_points: list[str]
    next_action: str


class AliyunQABrainService:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("DASHSCOPE_API_KEY")
        self.model = model or os.getenv("ALIYUN_QA_BRAIN_MODEL", "qwen3.6-plus")
        self.base_url = base_url or os.getenv(
            "ALIYUN_OPENAI_COMPAT_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        self.timeout_seconds = max(5.0, float(os.getenv("ALIYUN_QA_BRAIN_TIMEOUT_SECONDS", "15")))

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def build_reference_brief(
        self,
        *,
        scenario_id: ScenarioType,
        language: LanguageOption,
        training_mode: TrainingMode,
        bundle: ReferenceBundle,
    ) -> ReferenceBrief:
        fallback = self._fallback_brief(bundle)
        if not self.is_configured or not bundle.combined_text.strip():
            return fallback

        system_prompt = (
            "你是演讲训练产品里的问答准备助手。"
            "请把输入材料整理成紧凑、结构化、可追问的摘要。"
            "只输出 JSON，不要输出解释。"
        )
        user_prompt = json.dumps(
            {
                "language": language,
                "scenario": SCENARIO_LABELS[scenario_id],
                "training_mode": training_mode,
                "bundle_text": bundle.combined_text,
                "output_schema": {
                    "title": "string | null",
                    "source_summary": "string",
                    "main_topics": ["string"],
                    "key_points": ["string"],
                    "factual_claims": ["string"],
                    "assumptions": ["string"],
                    "risk_points": ["string"],
                    "open_questions": ["string"],
                    "challengeable_points": ["string"],
                    "notable_numbers": ["string"],
                    "topic_sections": [
                        {
                            "title": "string",
                            "summary": "string",
                            "key_points": ["string"],
                            "follow_up_angles": ["string"],
                        }
                    ],
                },
            },
            ensure_ascii=False,
        )

        try:
            content = await self._chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
            )
            parsed = self._parse_json(content)
            if not parsed:
                return fallback
            return self._brief_from_dict(parsed, fallback)
        except Exception as error:
            logger.warning("qa.brain.prepare_pack_failed model=%s timeout_s=%s error=%s", self.model, self.timeout_seconds, error)
            return fallback

    async def generate_question(
        self,
        *,
        scenario_id: ScenarioType,
        language: LanguageOption,
        training_mode: TrainingMode,
        brief: ReferenceBrief,
        previous_questions: list[str],
        previous_feedback: list[str],
        latest_transcript: str | None,
        prefer_follow_up: bool,
    ) -> GeneratedQuestion:
        fallback = self._fallback_question(
            scenario_id=scenario_id,
            training_mode=training_mode,
            brief=brief,
            latest_transcript=latest_transcript,
            prefer_follow_up=prefer_follow_up,
        )
        if not self.is_configured:
            return fallback

        system_prompt = (
            "你是 Speak Up 的 AI interviewer。"
            "请基于给定 brief 生成一条适合当下轮次的问题。"
            "问题必须直接、专业、可回答。"
            "只输出 JSON。"
        )
        user_prompt = json.dumps(
            {
                "language": language,
                "scenario": SCENARIO_LABELS[scenario_id],
                "training_mode": training_mode,
                "prefer_follow_up": prefer_follow_up,
                "brief": self._brief_to_dict(brief),
                "previous_questions": previous_questions[-4:],
                "previous_feedback": previous_feedback[-4:],
                "latest_transcript": latest_transcript,
                "output_schema": {
                    "question_text": "string",
                    "goal": "string",
                    "expected_points": ["string"],
                    "follow_up": "boolean",
                },
            },
            ensure_ascii=False,
        )

        try:
            content = await self._chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.45,
            )
            parsed = self._parse_json(content)
            if not parsed:
                return fallback
            return GeneratedQuestion(
                question_text=self._coerce_str(parsed.get("question_text"), fallback.question_text),
                goal=self._coerce_str(parsed.get("goal"), fallback.goal),
                expected_points=self._coerce_list(parsed.get("expected_points"), fallback.expected_points),
                follow_up=bool(parsed.get("follow_up", fallback.follow_up)),
            )
        except Exception:
            return fallback

    async def prepare_qa_pack(
        self,
        *,
        scenario_id: ScenarioType,
        language: LanguageOption,
        training_mode: TrainingMode,
        bundle: ReferenceBundle,
        previous_brief: ReferenceBrief | None,
        previous_questions: list[str],
        latest_transcript: str | None,
        question_count: int = 3,
    ) -> PreparedQAPack:
        fallback_brief = self._fallback_brief(bundle)
        if previous_brief is not None:
            fallback_brief = self._merge_briefs(previous_brief, fallback_brief)
        fallback_question = self._fallback_question(
            scenario_id=scenario_id,
            training_mode=training_mode,
            brief=fallback_brief,
            latest_transcript=latest_transcript,
            prefer_follow_up=False,
        )
        fallback = PreparedQAPack(brief=fallback_brief, questions=[fallback_question])
        if not self.is_configured or not bundle.combined_text.strip():
            return fallback

        system_prompt = (
            "你是 Speak Up 的离线问答预构建助手。"
            "请根据不断增长的演讲材料，更新一个紧凑 brief，并提前准备数个 interviewer 问题。"
            "问题要适合后续直接口播，短、清楚、可回答。"
            "只输出 JSON。"
        )
        user_prompt = json.dumps(
            {
                "language": language,
                "scenario": SCENARIO_LABELS[scenario_id],
                "training_mode": training_mode,
                "latest_bundle_text": bundle.combined_text,
                "previous_brief": self._brief_to_dict(previous_brief) if previous_brief else None,
                "previous_questions": previous_questions[-8:],
                "latest_transcript": latest_transcript,
                "question_count": max(1, min(question_count, 4)),
                "output_schema": {
                    "brief": {
                        "title": "string | null",
                        "source_summary": "string",
                        "main_topics": ["string"],
                        "key_points": ["string"],
                        "factual_claims": ["string"],
                        "assumptions": ["string"],
                        "risk_points": ["string"],
                        "open_questions": ["string"],
                        "challengeable_points": ["string"],
                        "notable_numbers": ["string"],
                        "topic_sections": [
                            {
                                "title": "string",
                                "summary": "string",
                                "key_points": ["string"],
                                "follow_up_angles": ["string"],
                            }
                        ],
                    },
                    "questions": [
                        {
                            "question_text": "string",
                            "goal": "string",
                            "expected_points": ["string"],
                            "follow_up": "boolean",
                        }
                    ],
                },
            },
            ensure_ascii=False,
        )

        try:
            content = await self._chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.35,
            )
            parsed = self._parse_json(content)
            if not parsed:
                return fallback

            brief_payload = parsed.get("brief")
            brief = self._brief_from_dict(brief_payload, fallback_brief) if isinstance(brief_payload, dict) else fallback_brief
            questions = self._questions_from_payload(parsed.get("questions"), fallback_question)
            return PreparedQAPack(brief=brief, questions=questions)
        except Exception:
            return fallback

    async def evaluate_answer(
        self,
        *,
        language: LanguageOption,
        question: GeneratedQuestion,
        answer_text: str,
        brief: ReferenceBrief,
    ) -> AnswerEvaluation:
        fallback = self._fallback_evaluation(question=question, answer_text=answer_text)
        if not self.is_configured:
            return fallback

        system_prompt = (
            "你是 Speak Up 的 AI interviewer review assistant。"
            "请评估用户是否答到点，并输出简洁、可执行的反馈。"
            "只输出 JSON。"
        )
        user_prompt = json.dumps(
            {
                "language": language,
                "question": {
                    "question_text": question.question_text,
                    "goal": question.goal,
                    "expected_points": question.expected_points,
                },
                "answer_text": answer_text,
                "brief": self._brief_to_dict(brief),
                "output_schema": {
                    "feedback_text": "string",
                    "strengths": ["string"],
                    "missed_points": ["string"],
                    "next_action": "follow_up | next_question | end_qa",
                },
            },
            ensure_ascii=False,
        )

        try:
            content = await self._chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
            )
            parsed = self._parse_json(content)
            if not parsed:
                return fallback
            next_action = self._coerce_str(parsed.get("next_action"), fallback.next_action)
            if next_action not in {"follow_up", "next_question", "end_qa"}:
                next_action = fallback.next_action
            return AnswerEvaluation(
                feedback_text=self._coerce_str(parsed.get("feedback_text"), fallback.feedback_text),
                strengths=self._coerce_list(parsed.get("strengths"), fallback.strengths),
                missed_points=self._coerce_list(parsed.get("missed_points"), fallback.missed_points),
                next_action=next_action,
            )
        except Exception:
            return fallback

    async def _chat(self, *, messages: list[dict[str, str]], temperature: float) -> str:
        response = None
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                f"{self.base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": temperature,
                },
            )
        response.raise_for_status()
        payload = response.json()
        message = payload["choices"][0]["message"]["content"]
        if isinstance(message, list):
            return "".join(item.get("text", "") for item in message if isinstance(item, dict))
        return str(message)

    def _fallback_brief(self, bundle: ReferenceBundle) -> ReferenceBrief:
        source_text = bundle.combined_text.strip()
        lines = [line.strip("- ").strip() for line in source_text.splitlines() if line.strip()]
        key_points = lines[:4] or ["当前还没有清晰材料，可以先从一个具体判断开始。"]
        summary = " ".join(lines[:3])[:220] or "当前上下文较少，建议先让用户讲出一个具体判断。"
        sections = [
            TopicSection(
                title="当前重点",
                summary=summary,
                key_points=key_points[:3],
                follow_up_angles=["挑一个具体判断", "补一条依据", "说明和听众有什么关系"],
            )
        ]
        return ReferenceBrief(
            title=None,
            source_summary=summary,
            main_topics=key_points[:3],
            key_points=key_points,
            factual_claims=key_points[:2],
            assumptions=[],
            risk_points=[],
            open_questions=["用户最希望听众带走哪一个具体判断？"],
            challengeable_points=key_points[:2],
            notable_numbers=[],
            topic_sections=sections,
        )

    def _fallback_question(
        self,
        *,
        scenario_id: ScenarioType,
        training_mode: TrainingMode,
        brief: ReferenceBrief,
        latest_transcript: str | None,
        prefer_follow_up: bool,
    ) -> GeneratedQuestion:
        if prefer_follow_up and latest_transcript:
            return GeneratedQuestion(
                question_text=f"你刚才提到“{latest_transcript[:28]}”，请把这个点再讲具体一点。",
                goal="确认用户是否能把刚才提到的点讲清楚。",
                expected_points=["结论", "原因", "例子"],
                follow_up=True,
            )

        if training_mode == "document_speech" and brief.key_points:
            return GeneratedQuestion(
                question_text=f"请从这份材料里挑一个最需要听众带走的判断，再补两条支撑点。",
                goal="确认用户是否抓住了文档主线。",
                expected_points=brief.key_points[:3] or ["具体判断", "支撑点 1", "支撑点 2"],
                follow_up=False,
            )

        if latest_transcript:
            return GeneratedQuestion(
                question_text=f"你刚才讲到“{latest_transcript[:24]}”，如果要让听众更快听懂，你会怎么先说结论？",
                goal="确认用户能否把刚才的表达收束成更直接的回答。",
                expected_points=["先讲结论", "再补原因"],
                follow_up=False,
            )

        scenario_label = SCENARIO_LABELS.get(scenario_id, "通用表达训练")
        return GeneratedQuestion(
            question_text=f"这次{scenario_label}里，你最想让听众带走哪一个具体判断？",
            goal="确认用户是否能给出清楚的表达落点。",
            expected_points=["具体判断", "为什么重要"],
            follow_up=False,
        )

    def _fallback_evaluation(self, *, question: GeneratedQuestion, answer_text: str) -> AnswerEvaluation:
        normalized = answer_text.strip()
        if not normalized:
            return AnswerEvaluation(
                feedback_text="这一题我还没有听到有效回答。先直接回答问题本身，再补理由。",
                strengths=[],
                missed_points=question.expected_points[:2] or ["直接回答问题"],
                next_action="follow_up",
            )

        strengths: list[str] = []
        missed_points: list[str] = []
        lower_answer = normalized.lower()
        for expected in question.expected_points:
            if expected and expected.lower() in lower_answer:
                strengths.append(f"提到了{expected}")
            elif expected:
                missed_points.append(f"没有明确提到{expected}")

        if len(normalized) >= 36:
            strengths.append("回答长度基本够展开")
        else:
            missed_points.append("回答还偏短，可以再补一层")

        feedback = "回答方向基本对，但可以先给一个具体判断，再补 2 个关键信息点。"
        if not strengths:
            feedback = "回答还没有直接回应问题。建议先直接回答，再补例子或依据。"

        next_action = "follow_up" if missed_points else "next_question"
        return AnswerEvaluation(
            feedback_text=feedback,
            strengths=strengths[:3],
            missed_points=missed_points[:3],
            next_action=next_action,
        )

    @staticmethod
    def _parse_json(content: str) -> dict | None:
        stripped = content.strip()
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass

        match = re.search(r"\{.*\}", stripped, re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _coerce_str(value: object, fallback: str) -> str:
        text = str(value).strip() if value is not None else ""
        return text or fallback

    @staticmethod
    def _coerce_list(value: object, fallback: list[str]) -> list[str]:
        if not isinstance(value, list):
            return fallback
        cleaned = [str(item).strip() for item in value if str(item).strip()]
        return cleaned or fallback

    def _brief_from_dict(self, payload: dict, fallback: ReferenceBrief) -> ReferenceBrief:
        sections_payload = payload.get("topic_sections")
        sections: list[TopicSection] = []
        if isinstance(sections_payload, list):
            for item in sections_payload[:4]:
                if not isinstance(item, dict):
                    continue
                sections.append(
                    TopicSection(
                        title=self._coerce_str(item.get("title"), "当前主题"),
                        summary=self._coerce_str(item.get("summary"), fallback.source_summary),
                        key_points=self._coerce_list(item.get("key_points"), fallback.key_points[:3]),
                        follow_up_angles=self._coerce_list(item.get("follow_up_angles"), ["先讲结论", "再补依据"]),
                    )
                )

        return ReferenceBrief(
            title=str(payload.get("title")).strip() if payload.get("title") else None,
            source_summary=self._coerce_str(payload.get("source_summary"), fallback.source_summary),
            main_topics=self._coerce_list(payload.get("main_topics"), fallback.main_topics),
            key_points=self._coerce_list(payload.get("key_points"), fallback.key_points),
            factual_claims=self._coerce_list(payload.get("factual_claims"), fallback.factual_claims),
            assumptions=self._coerce_list(payload.get("assumptions"), fallback.assumptions),
            risk_points=self._coerce_list(payload.get("risk_points"), fallback.risk_points),
            open_questions=self._coerce_list(payload.get("open_questions"), fallback.open_questions),
            challengeable_points=self._coerce_list(payload.get("challengeable_points"), fallback.challengeable_points),
            notable_numbers=self._coerce_list(payload.get("notable_numbers"), fallback.notable_numbers),
            topic_sections=sections or fallback.topic_sections,
        )

    def _questions_from_payload(self, payload: object, fallback: GeneratedQuestion) -> list[GeneratedQuestion]:
        if not isinstance(payload, list):
            return [fallback]

        questions: list[GeneratedQuestion] = []
        for item in payload[:4]:
            if not isinstance(item, dict):
                continue
            question_text = self._coerce_str(item.get("question_text"), "")
            goal = self._coerce_str(item.get("goal"), "")
            if not question_text or not goal:
                continue
            questions.append(
                GeneratedQuestion(
                    question_text=question_text,
                    goal=goal,
                    expected_points=self._coerce_list(item.get("expected_points"), fallback.expected_points),
                    follow_up=bool(item.get("follow_up", False)),
                )
            )

        return questions or [fallback]

    def _merge_briefs(self, existing: ReferenceBrief, incoming: ReferenceBrief) -> ReferenceBrief:
        return ReferenceBrief(
            title=incoming.title or existing.title,
            source_summary=(incoming.source_summary or existing.source_summary)[:420],
            main_topics=self._merge_unique(existing.main_topics, incoming.main_topics, limit=8),
            key_points=self._merge_unique(existing.key_points, incoming.key_points, limit=12),
            factual_claims=self._merge_unique(existing.factual_claims, incoming.factual_claims, limit=8),
            assumptions=self._merge_unique(existing.assumptions, incoming.assumptions, limit=8),
            risk_points=self._merge_unique(existing.risk_points, incoming.risk_points, limit=8),
            open_questions=self._merge_unique(existing.open_questions, incoming.open_questions, limit=8),
            challengeable_points=self._merge_unique(existing.challengeable_points, incoming.challengeable_points, limit=8),
            notable_numbers=self._merge_unique(existing.notable_numbers, incoming.notable_numbers, limit=8),
            topic_sections=[*existing.topic_sections, *incoming.topic_sections][-6:],
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
    def _brief_to_dict(brief: ReferenceBrief) -> dict:
        return {
            "title": brief.title,
            "source_summary": brief.source_summary,
            "main_topics": brief.main_topics,
            "key_points": brief.key_points,
            "factual_claims": brief.factual_claims,
            "assumptions": brief.assumptions,
            "risk_points": brief.risk_points,
            "open_questions": brief.open_questions,
            "challengeable_points": brief.challengeable_points,
            "notable_numbers": brief.notable_numbers,
            "topic_sections": [
                {
                    "title": section.title,
                    "summary": section.summary,
                    "key_points": section.key_points,
                    "follow_up_angles": section.follow_up_angles,
                }
                for section in brief.topic_sections
            ],
        }
