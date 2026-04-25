from __future__ import annotations

import json
import logging
import os
import re
from collections import defaultdict
from datetime import datetime, timezone

import httpx

from app.schemas import (
    LanguageOption,
    RadarMetric,
    ReportEvidenceRef,
    ReportSubDimensionScore,
    ReportTopDimensionScore,
    ReportWindowPack,
    ScenarioType,
    SessionReport,
    SuggestionItem,
    TopDimensionId,
)
from app.services.report_domain import (
    TOP_DIMENSION_ORDER,
    scenario_weights,
    sub_dimension_label,
    top_dimension_label,
)
from app.services.report_signal_service import ReportSignalBundle
from app.services.voice_profile_service import VoiceProfileService


SCENARIO_LABELS: dict[ScenarioType, str] = {
    "general": "通用表达训练",
    "host": "通用表达训练",
    "guest-sharing": "主题分享场景",
    "standup": "脱口秀 / 即兴表达场景",
}

SCORE_RUBRIC_ZH = [
    "90-100：非常出色，表达清楚、有吸引力，问题只剩精修。",
    "80-89：表现稳定，有明确优点，少量短板不影响整体完成度。",
    "70-79：基本可用，听众能跟上，但亮点不够稳定或问题较明显。",
    "60-69：勉强过线，能听懂一部分，但短板已经影响说服力。",
    "40-59：问题明显，结构、节奏、内容或呈现至少有一项拖垮体验。",
    "0-39：严重失效，听众很难获得清晰信息，必须先重建基本表达。",
]
SCORE_RUBRIC_EN = [
    "90-100: Excellent. Clear, engaging, and only needs refinement.",
    "80-89: Strong and stable, with clear strengths and manageable issues.",
    "70-79: Usable, but strengths are not stable or issues are easy to notice.",
    "60-69: Barely passing. Some meaning lands, but weak areas hurt persuasion.",
    "40-59: Clear problems. Structure, rhythm, content, or delivery hurts the experience.",
    "0-39: Severely ineffective. The audience struggles to get a clear message.",
]

logger = logging.getLogger("speak_up.session")


class ReportBrainService:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        window_model: str | None = None,
        final_model: str | None = None,
        fallback_model: str | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("DASHSCOPE_API_KEY")
        self.base_url = base_url or os.getenv(
            "ALIYUN_OPENAI_COMPAT_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        self.window_model = window_model or os.getenv("ALIYUN_REPORT_WINDOW_MODEL", "qwen-flash")
        self.final_model = final_model or os.getenv("ALIYUN_REPORT_BRAIN_MODEL", "qwen-flash")
        self.fallback_model = fallback_model or os.getenv("ALIYUN_REPORT_BRAIN_FALLBACK_MODEL", "qwen-plus-latest")
        self.window_timeout_seconds = max(10.0, float(os.getenv("ALIYUN_REPORT_WINDOW_TIMEOUT_SECONDS", "30")))
        self.final_timeout_seconds = max(15.0, float(os.getenv("ALIYUN_REPORT_BRAIN_TIMEOUT_SECONDS", "45")))
        self.window_max_tokens = max(800, int(os.getenv("ALIYUN_REPORT_WINDOW_MAX_TOKENS", "1600")))
        self.final_max_tokens = max(1200, int(os.getenv("ALIYUN_REPORT_BRAIN_MAX_TOKENS", "2600")))
        self.enable_thinking = os.getenv("ALIYUN_REPORT_ENABLE_THINKING", "false").strip().lower() == "true"
        self.voice_profile_service = VoiceProfileService()

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def build_window_pack(
        self,
        *,
        session_id: str,
        scenario_id: ScenarioType,
        language: LanguageOption,
        window_id: str,
        window_start_ms: int,
        window_end_ms: int,
        bundle: ReportSignalBundle,
    ) -> ReportWindowPack:
        fallback = self._fallback_window_pack(
            session_id=session_id,
            scenario_id=scenario_id,
            language=language,
            window_id=window_id,
            window_start_ms=window_start_ms,
            window_end_ms=window_end_ms,
            bundle=bundle,
        )
        if not self.is_configured:
            return fallback

        system_prompt = (
            "你是 Speak Up 的离线报告窗口评估助手。"
            "你要评估一个时间窗口内的表现。"
            "不要输出整场最终结论，只输出当前窗口的结构化评估。"
            "评分要严格使用 0-100 全量刻度，不能把 60-80 当安全区。"
            "证据差就给低分，证据好就给高分；不要为了鼓励用户而保底 60。"
            "每个维度的 strengths / weaknesses 必须和 score 一致：低于 70 必须指出明确问题，低于 60 不要写泛泛的表扬。"
            "必须输出 JSON。"
        )
        user_prompt = json.dumps(
            {
                "language": language,
                "scenario": SCENARIO_LABELS[scenario_id],
                "score_rubric": self._score_rubric(language),
                "window": {
                    "start_ms": window_start_ms,
                    "end_ms": window_end_ms,
                },
                "transcript_chunks": [chunk.model_dump() for chunk in bundle.transcript_chunks],
                "transcript_stats": bundle.transcript_stats,
                "qa_questions": bundle.qa_questions,
                "coach_signals": bundle.coach_signals,
                "top_dimensions": list(TOP_DIMENSION_ORDER),
                "output_schema": {
                    "top_dimension_scores": [
                        {
                            "id": "body | facial_expression | vocal_tone | rhythm | content_quality | expression_structure",
                            "score": "0-100",
                            "strengths": ["string"],
                            "weaknesses": ["string"],
                            "sub_dimensions": [
                                {"id": "string", "score": "0-100", "reason": "string"}
                            ],
                            "evidence_refs": [
                                {
                                    "timestamp_ms": "number",
                                    "quote": "string | null",
                                    "sub_dimension_id": "string | null",
                                }
                            ],
                        }
                    ],
                    "candidate_suggestions": [{"title": "string", "detail": "string"}],
                    "confidence": "0-1",
                },
            },
            ensure_ascii=False,
        )

        try:
            content = await self._chat(
                model=self.window_model,
                timeout_seconds=self.window_timeout_seconds,
                max_tokens=self.window_max_tokens,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
            )
            parsed = self._parse_json(content)
            if not parsed:
                return fallback
            return self._window_pack_from_payload(
                payload=parsed,
                session_id=session_id,
                language=language,
                window_id=window_id,
                window_start_ms=window_start_ms,
                window_end_ms=window_end_ms,
                fallback=fallback,
            )
        except Exception:
            return fallback

    def build_fallback_report(
        self,
        *,
        session_id: str,
        scenario_id: ScenarioType,
        language: LanguageOption,
        coach_profile_id: str | None,
        window_packs: list[ReportWindowPack],
        tail_bundle: ReportSignalBundle | None,
    ) -> SessionReport:
        coach_profile = self.voice_profile_service.get(coach_profile_id)
        logger.info(
            "report.final.style_applied session=%s source=fallback requested_coach=%s resolved_coach=%s coach_name=%s persona=%s instruction=%s",
            session_id,
            coach_profile_id,
            coach_profile.profile.id,
            coach_profile.coach_name,
            coach_profile.persona_type,
            coach_profile.report_instruction_zh[:120],
        )
        return self._fallback_final_report(
            session_id=session_id,
            scenario_id=scenario_id,
            language=language,
            coach_profile_id=coach_profile_id,
            window_packs=window_packs,
            tail_bundle=tail_bundle,
        )

    async def build_final_report(
        self,
        *,
        session_id: str,
        scenario_id: ScenarioType,
        language: LanguageOption,
        coach_profile_id: str | None,
        window_packs: list[ReportWindowPack],
        tail_bundle: ReportSignalBundle | None,
    ) -> SessionReport:
        fallback = self._fallback_final_report(
            session_id=session_id,
            scenario_id=scenario_id,
            language=language,
            coach_profile_id=coach_profile_id,
            window_packs=window_packs,
            tail_bundle=tail_bundle,
        )
        if not self.is_configured:
            coach_profile = self.voice_profile_service.get(coach_profile_id)
            logger.info(
                "report.final.style_applied session=%s source=fallback reason=brain_unconfigured requested_coach=%s resolved_coach=%s coach_name=%s persona=%s instruction=%s",
                session_id,
                coach_profile_id,
                coach_profile.profile.id,
                coach_profile.coach_name,
                coach_profile.persona_type,
                coach_profile.report_instruction_zh[:120],
            )
            return fallback

        coach_profile = self.voice_profile_service.get(coach_profile_id)
        logger.info(
            "report.final.style_applied session=%s source=llm requested_coach=%s resolved_coach=%s coach_name=%s persona=%s instruction=%s",
            session_id,
            coach_profile_id,
            coach_profile.profile.id,
            coach_profile.coach_name,
            coach_profile.persona_type,
            coach_profile.report_instruction_zh[:120],
        )

        system_prompt = (
            "你是 Speak Up 的报告生成助手。"
            "你要基于历史窗口评估包和最后一个未覆盖尾窗的原始数据，生成一份完整、统一、去重后的整场报告。"
            "不要重复窗口建议，要做整合。"
            "你只能评价用户的演讲表现。"
            "不要描述系统检测过程、模型能力、覆盖率、置信度、维度完整性、报告生成流程。"
            "不要使用内部维度 id 或机制术语，例如 rhythm、vocal_tone、content_quality、expression_structure、body、facial_expression、维度反馈。"
            "如果要给建议，必须改写成用户能直接理解的自然表达。"
            f"当前报告要采用“{coach_profile.coach_name}”这位教练的人设口吻，但仍然必须保持专业、克制、面向用户。"
            "允许适度玩梗或用轻微口语类比，但最多一两处，不能喧宾夺主，不能攻击用户人格，不能把报告写成段子。"
            "如果提供了 coach_report_style_reference，它只是风格案例，不是固定语料；不要逐句照抄。"
            "你要学习案例里的语气、比喻密度和边界感，并迁移到其他维度或子维度上。"
            "评分要严格使用 0-100 全量刻度，不能把 60-80 当安全区。"
            "用户讲得差就直说差在哪里，讲得好就大胆夸具体好在哪里；分数、标题、总结、亮点和建议必须同向一致。"
            "低于 60 的报告要直接指出关键问题，不要写成鼓励稿；80 以上要明确承认亮点，不要吝啬赞美。"
            "headline 必须直接说重点，像给用户的一句话提醒；不要写教练名，不要把标题包装成“某某报告”，不要带冒号标题，也不要写“阶段调整”“关键优化”这类抽象包装。"
            "headline 不能写评分口径或内部评语，例如“问题明显”“别粉饰”“勉强过线”“严重失效”；必须写成用户下一轮能执行的动作。"
            "中文 headline 控制在 18 个字以内，优先使用“先把逻辑理顺”“先把节奏稳住”“内容再讲实”这类用户一眼能懂的说法。"
            f"{coach_profile.report_instruction_zh}"
            "必须输出 JSON。"
        )
        user_prompt = json.dumps(
            {
                "language": language,
                "scenario": SCENARIO_LABELS[scenario_id],
                "weights": scenario_weights(scenario_id),
                "score_rubric": self._score_rubric(language),
                "style_rules": [
                    "score < 60: direct criticism and concrete repair steps; do not praise generically",
                    "60 <= score < 70: acknowledge barely passing, then name the main blocker",
                    "70 <= score < 80: balanced but specific; note usable parts and visible gaps",
                    "score >= 80: praise concrete strengths clearly, then give refinement advice",
                    "memes or jokes are allowed only as a small seasoning, not as the main content",
                ],
                "coach_report_style_reference": {
                    "coach_name": coach_profile.coach_name,
                    "persona_type": coach_profile.persona_type,
                    "usage_rule": (
                        "These are style examples only. Do not copy them verbatim. "
                        "Infer the same coach style for dimensions or sub-dimensions not listed."
                    ),
                    "dimension_examples": coach_profile.report_style_examples,
                },
                "window_packs": [pack.model_dump() for pack in window_packs],
                "tail_window": self._tail_payload(tail_bundle),
                "top_dimensions": list(TOP_DIMENSION_ORDER),
                "output_schema": {
                    "headline": "direct short coaching point, no coach name, no report label, no colon",
                    "encouragement": "string",
                    "summary_paragraph": "string",
                    "highlights": ["string"],
                    "suggestions": [{"title": "string", "detail": "string"}],
                    "dimensions": [
                        {
                            "id": "body | facial_expression | vocal_tone | rhythm | content_quality | expression_structure",
                            "score": "0-100",
                            "strengths": ["string"],
                            "weaknesses": ["string"],
                            "sub_dimensions": [
                                {"id": "string", "score": "0-100", "reason": "string"}
                            ],
                            "evidence_refs": [
                                {
                                    "timestamp_ms": "number",
                                    "quote": "string | null",
                                    "sub_dimension_id": "string | null",
                                }
                            ],
                        }
                    ],
                },
            },
            ensure_ascii=False,
        )

        for model_name in (self.final_model, self.fallback_model):
            try:
                logger.info(
                    "report.final.model_attempt session=%s model=%s coach=%s persona=%s windows=%s tail_chunks=%s tail_questions=%s tail_signals=%s",
                    session_id,
                    model_name,
                    coach_profile.coach_name,
                    coach_profile.persona_type,
                    len(window_packs),
                    len(tail_bundle.transcript_chunks) if tail_bundle else 0,
                    len(tail_bundle.qa_questions) if tail_bundle else 0,
                    len(tail_bundle.coach_signals) if tail_bundle else 0,
                )
                content = await self._chat(
                    model=model_name,
                    timeout_seconds=self.final_timeout_seconds,
                    max_tokens=self.final_max_tokens,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.2,
                )
                parsed = self._parse_json(content)
                if not parsed:
                    logger.warning(
                        "report.final.model_invalid_json session=%s model=%s coach=%s persona=%s",
                        session_id,
                        model_name,
                        coach_profile.coach_name,
                        coach_profile.persona_type,
                    )
                    continue
                logger.info(
                    "report.final.model_success session=%s model=%s coach=%s persona=%s",
                    session_id,
                    model_name,
                    coach_profile.coach_name,
                    coach_profile.persona_type,
                )
                return self._final_report_from_payload(
                    payload=parsed,
                    session_id=session_id,
                    coach_profile_id=coach_profile.profile.id,
                    scenario_id=scenario_id,
                    language=language,
                    fallback=fallback,
                )
            except Exception as error:
                logger.warning(
                    "report.final.model_failed session=%s model=%s coach=%s persona=%s error=%s",
                    session_id,
                    model_name,
                    coach_profile.coach_name,
                    coach_profile.persona_type,
                    error,
                )
                continue
        logger.warning(
            "report.final.fallback session=%s reason=all_models_failed requested_coach=%s resolved_coach=%s coach_name=%s persona=%s",
            session_id,
            coach_profile_id,
            coach_profile.profile.id,
            coach_profile.coach_name,
            coach_profile.persona_type,
        )
        return fallback

    async def _chat(
        self,
        *,
        model: str,
        timeout_seconds: float,
        max_tokens: int,
        messages: list[dict[str, str]],
        temperature: float,
    ) -> str:
        body: dict[str, object] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if self._supports_thinking_toggle(model):
            body["enable_thinking"] = self.enable_thinking
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post(
                f"{self.base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
        response.raise_for_status()
        payload = response.json()
        message = payload["choices"][0]["message"]["content"]
        if isinstance(message, list):
            return "".join(item.get("text", "") for item in message if isinstance(item, dict))
        return str(message)

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
    def _tail_payload(tail_bundle: ReportSignalBundle | None) -> dict[str, object] | None:
        if tail_bundle is None:
            return None
        return {
            "transcript_chunks": [chunk.model_dump() for chunk in tail_bundle.transcript_chunks],
            "transcript_stats": tail_bundle.transcript_stats,
            "qa_questions": tail_bundle.qa_questions,
            "coach_signals": tail_bundle.coach_signals,
        }

    def _window_pack_from_payload(
        self,
        *,
        payload: dict,
        session_id: str,
        language: LanguageOption,
        window_id: str,
        window_start_ms: int,
        window_end_ms: int,
        fallback: ReportWindowPack,
    ) -> ReportWindowPack:
        top_dimension_scores = self._dimension_scores_from_payload(
            payload.get("top_dimension_scores"),
            language=language,
            fallback=fallback.topDimensionScores,
        )
        candidate_suggestions = self._suggestions_from_payload(
            payload.get("candidate_suggestions"),
            fallback.candidateSuggestions,
            language=language,
        )
        evidence_refs = self._flatten_evidence_refs(top_dimension_scores)
        confidence = self._coerce_confidence(payload.get("confidence"), fallback.confidence)
        return ReportWindowPack(
            sessionId=session_id,
            windowId=window_id,
            windowStartMs=window_start_ms,
            windowEndMs=window_end_ms,
            topDimensionScores=top_dimension_scores,
            candidateSuggestions=candidate_suggestions,
            evidenceRefs=evidence_refs,
            confidence=confidence,
            createdAt=self._now_iso(),
        )

    def _final_report_from_payload(
        self,
        *,
        payload: dict,
        session_id: str,
        coach_profile_id: str | None,
        scenario_id: ScenarioType,
        language: LanguageOption,
        fallback: SessionReport,
    ) -> SessionReport:
        dimensions = self._dimension_scores_from_payload(payload.get("dimensions"), language=language, fallback=fallback.dimensions)
        overall_score = self._weighted_score(scenario_id, dimensions) if dimensions else fallback.overallScore
        strengths_ranked = sorted(dimensions, key=lambda item: item.score, reverse=True)
        weakness_ranked = sorted(dimensions, key=lambda item: item.score)
        best_dimension = strengths_ranked[0] if strengths_ranked else None
        weakest_dimension = weakness_ranked[0] if weakness_ranked else None
        headline = self._sanitize_report_headline(
            language=language,
            headline=self._coerce_str(payload.get("headline"), fallback.headline),
            fallback=fallback.headline,
        )
        encouragement = self._coerce_str(payload.get("encouragement"), fallback.encouragement)
        summary_paragraph = self._coerce_str(payload.get("summary_paragraph"), fallback.summaryParagraph)
        headline, encouragement, summary_paragraph = self._align_report_copy_with_score(
            language=language,
            overall_score=overall_score,
            headline=headline,
            encouragement=encouragement,
            summary_paragraph=summary_paragraph,
            best_dimension=best_dimension,
            weakest_dimension=weakest_dimension,
        )
        highlights = self._sanitize_highlights(
            language=language,
            payload=self._coerce_list(payload.get("highlights"), fallback.highlights),
            dimensions=dimensions,
            fallback=fallback.highlights,
        )
        suggestions = self._suggestions_from_payload(
            payload.get("suggestions"),
            fallback.suggestions,
            language=language,
        )
        return SessionReport(
            sessionId=session_id,
            coachProfileId=coach_profile_id,
            status="ready",
            overallScore=overall_score,
            headline=headline,
            encouragement=encouragement,
            summaryParagraph=summary_paragraph,
            highlights=highlights,
            suggestions=suggestions,
            radarMetrics=self._radar_metrics_from_dimensions(dimensions),
            dimensions=dimensions,
            generatedAt=self._now_iso(),
        )

    def _fallback_window_pack(
        self,
        *,
        session_id: str,
        scenario_id: ScenarioType,
        language: LanguageOption,
        window_id: str,
        window_start_ms: int,
        window_end_ms: int,
        bundle: ReportSignalBundle,
    ) -> ReportWindowPack:
        dimensions = self._fallback_dimensions(
            scenario_id=scenario_id,
            language=language,
            transcript_stats=bundle.transcript_stats,
            coach_signals=bundle.coach_signals,
        )
        return ReportWindowPack(
            sessionId=session_id,
            windowId=window_id,
            windowStartMs=window_start_ms,
            windowEndMs=window_end_ms,
            topDimensionScores=dimensions,
            candidateSuggestions=self._fallback_suggestions(language, dimensions),
            evidenceRefs=self._flatten_evidence_refs(dimensions),
            confidence=0.62,
            createdAt=self._now_iso(),
        )

    def _fallback_final_report(
        self,
        *,
        session_id: str,
        scenario_id: ScenarioType,
        language: LanguageOption,
        coach_profile_id: str | None,
        window_packs: list[ReportWindowPack],
        tail_bundle: ReportSignalBundle | None,
    ) -> SessionReport:
        all_dimensions: dict[TopDimensionId, list[tuple[int, int, ReportTopDimensionScore]]] = defaultdict(list)
        for pack in window_packs:
            duration = max(pack.windowEndMs - pack.windowStartMs, 1)
            for dimension in pack.topDimensionScores:
                all_dimensions[dimension.id].append((duration, duration, dimension))

        if tail_bundle is not None and (tail_bundle.transcript_chunks or tail_bundle.coach_signals):
            tail_dimensions = self._fallback_dimensions(
                scenario_id=scenario_id,
                language=language,
                transcript_stats=tail_bundle.transcript_stats,
                coach_signals=tail_bundle.coach_signals,
            )
            duration = max(tail_bundle.latest_timestamp_ms, 1)
            for dimension in tail_dimensions:
                all_dimensions[dimension.id].append((duration, duration, dimension))

        merged_dimensions: list[ReportTopDimensionScore] = []
        for dimension_id in TOP_DIMENSION_ORDER:
            candidates = all_dimensions.get(dimension_id)
            if not candidates:
                merged_dimensions.append(
                    ReportTopDimensionScore(
                        id=dimension_id,
                        label=top_dimension_label(dimension_id, language),
                        score=50,
                        weight=scenario_weights(scenario_id)[dimension_id],
                        strengths=[],
                        weaknesses=[
                            self._text(
                                language,
                                "这一项缺少足够有效表现，不能按稳定发挥处理。",
                                "There is not enough effective evidence to treat this as a stable performance.",
                            )
                        ],
                    )
                )
                continue
            total_duration = sum(weight for _, weight, _ in candidates)
            weighted_score = round(
                sum(dimension.score * weight for _, weight, dimension in candidates) / max(total_duration, 1)
            )
            strengths = self._merge_strings([dimension.strengths for _, _, dimension in candidates], limit=3)
            weaknesses = self._merge_strings([dimension.weaknesses for _, _, dimension in candidates], limit=3)
            sub_dimensions = self._merge_sub_dimensions([dimension.subDimensions for _, _, dimension in candidates], language)
            evidence_refs = self._merge_evidence_refs([dimension.evidenceRefs for _, _, dimension in candidates], limit=4)
            merged_dimensions.append(
                ReportTopDimensionScore(
                    id=dimension_id,
                    label=top_dimension_label(dimension_id, language),
                    score=weighted_score,
                    weight=scenario_weights(scenario_id)[dimension_id],
                    strengths=strengths,
                    weaknesses=weaknesses,
                    subDimensions=sub_dimensions,
                    evidenceRefs=evidence_refs,
                )
            )

        overall_score = self._weighted_score(scenario_id, merged_dimensions)
        strengths_ranked = sorted(merged_dimensions, key=lambda item: item.score, reverse=True)
        weakness_ranked = sorted(merged_dimensions, key=lambda item: item.score)
        best_dimension = strengths_ranked[0]
        weakest_dimension = weakness_ranked[0]
        return SessionReport(
            sessionId=session_id,
            coachProfileId=coach_profile_id,
            status="ready",
            overallScore=overall_score,
            headline=self._build_headline(language, overall_score, best_dimension.label, weakest_dimension.label),
            encouragement=self._build_encouragement(language, overall_score, best_dimension.label, weakest_dimension.label),
            summaryParagraph=self._build_summary(language, overall_score, best_dimension.label, weakest_dimension.label),
            highlights=self._fallback_highlights(language, strengths_ranked),
            suggestions=self._fallback_suggestions(language, weakness_ranked),
            radarMetrics=self._radar_metrics_from_dimensions(merged_dimensions),
            dimensions=merged_dimensions,
            generatedAt=self._now_iso(),
        )

    def _fallback_dimensions(
        self,
        *,
        scenario_id: ScenarioType,
        language: LanguageOption,
        transcript_stats: dict,
        coach_signals: list[dict],
    ) -> list[ReportTopDimensionScore]:
        weights = scenario_weights(scenario_id)
        signal_groups = self._group_signals_by_top_dimension(coach_signals)
        dimensions: list[ReportTopDimensionScore] = []
        for dimension_id in TOP_DIMENSION_ORDER:
            signals = signal_groups.get(dimension_id, [])
            score = self._fallback_dimension_score(dimension_id, transcript_stats, signals)
            sub_dimensions = self._fallback_sub_dimensions(language, signals)
            strengths = self._fallback_dimension_strengths(language, dimension_id, score, signals)
            weaknesses = self._fallback_dimension_weaknesses(language, dimension_id, transcript_stats, signals)
            evidence_refs = self._fallback_evidence_refs(dimension_id, signals)
            dimensions.append(
                ReportTopDimensionScore(
                    id=dimension_id,
                    label=top_dimension_label(dimension_id, language),
                    score=score,
                    weight=weights[dimension_id],
                    strengths=strengths,
                    weaknesses=weaknesses,
                    subDimensions=sub_dimensions,
                    evidenceRefs=evidence_refs,
                )
            )
        return dimensions

    def _group_signals_by_top_dimension(self, coach_signals: list[dict]) -> dict[TopDimensionId, list[dict]]:
        grouped: dict[TopDimensionId, list[dict]] = defaultdict(list)
        for signal in coach_signals:
            sub_dimension_id = str(signal.get("subDimensionId") or "").strip()
            top_dimensions = ()
            from app.services.report_domain import COACH_TO_TOP_DIMENSIONS  # local import to avoid cycle

            top_dimensions = COACH_TO_TOP_DIMENSIONS.get(sub_dimension_id, ())
            for top_dimension_id in top_dimensions:
                grouped[top_dimension_id].append(signal)
        return grouped

    def _fallback_dimension_score(self, dimension_id: TopDimensionId, transcript_stats: dict, signals: list[dict]) -> int:
        score = 76
        for signal in signals:
            polarity = str(signal.get("signalPolarity") or "negative").lower()
            severity = str(signal.get("severity") or "medium").lower()
            confidence = self._coerce_confidence(signal.get("confidence"), 0.75) or 0.75
            confidence_scale = 0.75 + min(max(confidence, 0.0), 1.0) * 0.5
            penalty = round({"low": 4, "medium": 9, "high": 15}.get(severity, 8) * confidence_scale)
            bonus = round({"low": 2, "medium": 4, "high": 6}.get(severity, 3) * confidence_scale)
            if polarity == "positive":
                score += bonus
            elif polarity == "neutral":
                score -= 2
            else:
                score -= penalty

        filler_density = float(transcript_stats.get("fillerDensity", 0))
        repetition_ratio = float(transcript_stats.get("repetitionRatio", 0))
        long_pause_count = int(transcript_stats.get("longPauseCount", 0))
        restart_count = int(transcript_stats.get("restartCount", 0))
        total_chars = int(transcript_stats.get("totalChars", 0))
        negative_signal_count = sum(
            1 for signal in signals if str(signal.get("signalPolarity") or "negative").lower() != "positive"
        )
        if negative_signal_count >= 4:
            score -= min((negative_signal_count - 3) * 3, 12)
        if total_chars <= 20:
            score -= 18
        if dimension_id in {"content_quality", "expression_structure"}:
            score -= int(repetition_ratio * 30)
            if filler_density >= 0.08:
                score -= 8
            if filler_density >= 0.14:
                score -= 8
            score -= min(restart_count * 3, 12)
        if dimension_id in {"rhythm", "vocal_tone"}:
            score -= min(long_pause_count * 4, 18)
            score -= int(filler_density * 35)
            score -= min(restart_count * 2, 10)
        return max(25, min(96, score))

    def _fallback_sub_dimensions(self, language: LanguageOption, signals: list[dict]) -> list[ReportSubDimensionScore]:
        grouped: dict[str, list[dict]] = defaultdict(list)
        for signal in signals:
            sub_dimension_id = str(signal.get("subDimensionId") or "").strip()
            if not sub_dimension_id:
                continue
            grouped[sub_dimension_id].append(signal)
        result: list[ReportSubDimensionScore] = []
        for sub_dimension_id, items in grouped.items():
            score = 78
            for item in items:
                polarity = str(item.get("signalPolarity") or "negative").lower()
                severity = str(item.get("severity") or "medium").lower()
                confidence = self._coerce_confidence(item.get("confidence"), 0.75) or 0.75
                confidence_scale = 0.75 + min(max(confidence, 0.0), 1.0) * 0.5
                if polarity == "positive":
                    score += round({"low": 2, "medium": 4, "high": 6}.get(severity, 3) * confidence_scale)
                else:
                    score -= round({"low": 5, "medium": 10, "high": 16}.get(severity, 8) * confidence_scale)
            latest = items[-1]
            reason = str(latest.get("detail") or latest.get("evidenceText") or "").strip()
            result.append(
                ReportSubDimensionScore(
                    id=sub_dimension_id,
                    label=sub_dimension_label(sub_dimension_id, language),
                    score=max(25, min(96, score)),
                    reason=reason or self._text(language, "这一项需要继续观察。", "Keep watching this sub-dimension."),
                )
            )
        return sorted(result, key=lambda item: item.score)

    def _fallback_dimension_strengths(
        self,
        language: LanguageOption,
        dimension_id: TopDimensionId,
        score: int,
        signals: list[dict],
    ) -> list[str]:
        positives = [signal for signal in signals if str(signal.get("signalPolarity") or "").lower() == "positive"]
        strengths = [str(signal.get("headline") or "").strip() for signal in positives if str(signal.get("headline") or "").strip()]
        if strengths:
            return self._dedupe(strengths)[:3]
        if score >= 88:
            return [self._text(language, f"{top_dimension_label(dimension_id, language)}是本轮非常明确的优势。", f"{top_dimension_label(dimension_id, language)} is a clear strength in this session.")]
        if score >= 78:
            return [self._text(language, f"{top_dimension_label(dimension_id, language)}整体比较稳。", f"{top_dimension_label(dimension_id, language)} is mostly stable.")]
        return []

    def _fallback_dimension_weaknesses(
        self,
        language: LanguageOption,
        dimension_id: TopDimensionId,
        transcript_stats: dict,
        signals: list[dict],
    ) -> list[str]:
        negatives = [signal for signal in signals if str(signal.get("signalPolarity") or "negative").lower() != "positive"]
        weaknesses = [str(signal.get("headline") or "").strip() for signal in negatives if str(signal.get("headline") or "").strip()]
        weaknesses = self._dedupe(weaknesses)[:3]
        if weaknesses:
            return weaknesses
        if dimension_id in {"content_quality", "expression_structure"}:
            filler_density = float(transcript_stats.get("fillerDensity", 0))
            repetition_ratio = float(transcript_stats.get("repetitionRatio", 0))
            restart_count = int(transcript_stats.get("restartCount", 0))
            if repetition_ratio >= 0.2:
                return [self._text(language, "表达有重复绕圈，信息推进不够干脆。", "The message repeats or circles instead of moving forward clearly.")]
            if filler_density >= 0.08 or restart_count >= 2:
                return [self._text(language, "口头填充和重起偏多，影响内容密度。", "Fillers and restarts reduce content density.")]
        if dimension_id == "rhythm" and int(transcript_stats.get("longPauseCount", 0)) >= 2:
            return [self._text(language, "长停顿偏多，节奏有波动。", "Long pauses make the rhythm less stable.")]
        return []

    def _fallback_evidence_refs(self, dimension_id: TopDimensionId, signals: list[dict]) -> list[ReportEvidenceRef]:
        refs: list[ReportEvidenceRef] = []
        for signal in signals[-4:]:
            refs.append(
                ReportEvidenceRef(
                    timestampMs=int(signal.get("timestampMs", 0)),
                    quote=str(signal.get("evidenceText") or signal.get("detail") or "").strip() or None,
                    dimensionId=dimension_id,
                    subDimensionId=str(signal.get("subDimensionId") or "").strip() or None,
                )
            )
        return refs

    def _dimension_scores_from_payload(
        self,
        payload: object,
        *,
        language: LanguageOption,
        fallback: list[ReportTopDimensionScore],
    ) -> list[ReportTopDimensionScore]:
        if not isinstance(payload, list):
            return fallback
        fallback_map = {item.id: item for item in fallback}
        result: list[ReportTopDimensionScore] = []
        for dimension_id in TOP_DIMENSION_ORDER:
            raw_item = next(
                (
                    item
                    for item in payload
                    if isinstance(item, dict) and str(item.get("id") or "").strip() == dimension_id
                ),
                None,
            )
            fallback_item = fallback_map.get(dimension_id)
            if not isinstance(raw_item, dict) or fallback_item is None:
                if fallback_item is not None:
                    result.append(fallback_item)
                continue
            score = self._coerce_score(raw_item.get("score"), fallback_item.score)
            sub_dimensions = self._sub_dimensions_from_payload(raw_item.get("sub_dimensions"), language, fallback_item.subDimensions)
            evidence_refs = self._evidence_refs_from_payload(
                raw_item.get("evidence_refs"),
                dimension_id=dimension_id,
                fallback=fallback_item.evidenceRefs,
            )
            strengths, weaknesses = self._align_dimension_copy_with_score(
                language=language,
                label=top_dimension_label(dimension_id, language),
                score=score,
                strengths=self._coerce_list(raw_item.get("strengths"), fallback_item.strengths),
                weaknesses=self._coerce_list(raw_item.get("weaknesses"), fallback_item.weaknesses),
            )
            result.append(
                ReportTopDimensionScore(
                    id=dimension_id,
                    label=top_dimension_label(dimension_id, language),
                    score=score,
                    weight=fallback_item.weight,
                    strengths=strengths,
                    weaknesses=weaknesses,
                    subDimensions=sub_dimensions,
                    evidenceRefs=evidence_refs,
                )
            )
        return result or fallback

    def _sub_dimensions_from_payload(
        self,
        payload: object,
        language: LanguageOption,
        fallback: list[ReportSubDimensionScore],
    ) -> list[ReportSubDimensionScore]:
        if not isinstance(payload, list):
            return fallback
        items: list[ReportSubDimensionScore] = []
        for raw_item in payload[:8]:
            if not isinstance(raw_item, dict):
                continue
            sub_dimension_id = str(raw_item.get("id") or "").strip()
            if not sub_dimension_id:
                continue
            items.append(
                ReportSubDimensionScore(
                    id=sub_dimension_id,
                    label=sub_dimension_label(sub_dimension_id, language),
                    score=self._coerce_score(raw_item.get("score"), 78),
                    reason=self._coerce_str(raw_item.get("reason"), self._text(language, "这一项需要继续观察。", "Keep watching this part.")),
                )
            )
        return items or fallback

    def _evidence_refs_from_payload(
        self,
        payload: object,
        *,
        dimension_id: TopDimensionId,
        fallback: list[ReportEvidenceRef],
    ) -> list[ReportEvidenceRef]:
        if not isinstance(payload, list):
            return fallback
        refs: list[ReportEvidenceRef] = []
        for raw_item in payload[:5]:
            if not isinstance(raw_item, dict):
                continue
            refs.append(
                ReportEvidenceRef(
                    timestampMs=self._coerce_int(raw_item.get("timestamp_ms"), 0),
                    quote=self._coerce_nullable_str(raw_item.get("quote")),
                    dimensionId=dimension_id,
                    subDimensionId=self._coerce_nullable_str(raw_item.get("sub_dimension_id")),
                )
            )
        return refs or fallback

    def _suggestions_from_payload(
        self,
        payload: object,
        fallback: list[SuggestionItem],
        *,
        language: LanguageOption,
    ) -> list[SuggestionItem]:
        if not isinstance(payload, list):
            return self._sanitize_suggestions(language=language, suggestions=fallback)
        suggestions: list[SuggestionItem] = []
        for raw_item in payload[:4]:
            if not isinstance(raw_item, dict):
                continue
            title = self._coerce_str(raw_item.get("title"), "")
            detail = self._coerce_str(raw_item.get("detail"), "")
            if not title or not detail:
                continue
            suggestions.append(SuggestionItem(title=title, detail=detail))
        if suggestions:
            return self._sanitize_suggestions(language=language, suggestions=suggestions)
        return self._sanitize_suggestions(language=language, suggestions=fallback)

    def _fallback_suggestions(self, language: LanguageOption, dimensions: list[ReportTopDimensionScore]) -> list[SuggestionItem]:
        weakest = sorted(dimensions, key=lambda item: item.score)[:3]
        suggestions: list[SuggestionItem] = []
        for dimension in weakest:
            if dimension.weaknesses:
                detail = dimension.weaknesses[0]
            else:
                detail = self._text(language, "下一轮优先针对这一项做更明确的调整。", "Prioritize this dimension in the next round.")
            suggestions.append(
                SuggestionItem(
                    title=self._text(language, f"优先优化{dimension.label}", f"Improve {dimension.label} first"),
                    detail=detail,
                )
            )
        return self._sanitize_suggestions(language=language, suggestions=suggestions)

    def _fallback_highlights(self, language: LanguageOption, dimensions: list[ReportTopDimensionScore]) -> list[str]:
        highlights: list[str] = []
        for dimension in dimensions[:3]:
            if dimension.strengths:
                highlights.append(f"{dimension.label}：{dimension.strengths[0]}")
            elif dimension.score >= 78:
                highlights.append(
                    self._text(language, f"{dimension.label}：这一项相对稳定。", f"{dimension.label}: This area is relatively stable.")
                )
        if not highlights and dimensions:
            weakest = sorted(dimensions, key=lambda item: item.score)[0]
            highlights.append(
                self._text(
                    language,
                    f"暂时没有明确高光，先把{weakest.label}拉回及格线。",
                    f"There is no clear highlight yet; bring {weakest.label} back to passing level first.",
                )
            )
        return self._sanitize_highlights(
            language=language,
            payload=highlights[:3],
            dimensions=dimensions,
            fallback=[],
        )

    def _sanitize_highlights(
        self,
        *,
        language: LanguageOption,
        payload: list[str],
        dimensions: list[ReportTopDimensionScore],
        fallback: list[str],
    ) -> list[str]:
        cleaned: list[str] = []
        for item in payload:
            text = str(item).strip()
            if not text or self._looks_like_meta_observation(text):
                continue
            cleaned.append(text)
        deduped = self._dedupe(cleaned)[:3]
        if deduped:
            return deduped
        fallback_cleaned = [item for item in fallback if item and not self._looks_like_meta_observation(item)]
        if fallback_cleaned:
            return self._dedupe(fallback_cleaned)[:3]
        regenerated: list[str] = []
        for dimension in dimensions[:3]:
            if dimension.strengths:
                candidate = dimension.strengths[0]
            elif dimension.score >= 78:
                candidate = self._text(language, "这一项相对稳定。", "This area is relatively stable.")
            else:
                continue
            if self._looks_like_meta_observation(candidate):
                continue
            regenerated.append(f"{dimension.label}：{candidate}")
        if not regenerated and dimensions:
            weakest = sorted(dimensions, key=lambda item: item.score)[0]
            regenerated.append(
                self._text(
                    language,
                    f"暂时没有明确高光，先把{weakest.label}拉回及格线。",
                    f"There is no clear highlight yet; bring {weakest.label} back to passing level first.",
                )
            )
        return self._dedupe(regenerated)[:3]

    @staticmethod
    def _looks_like_meta_observation(text: str) -> bool:
        normalized = re.sub(r"\s+", "", text).lower()
        meta_keywords = (
            "置信度",
            "覆盖评估",
            "结构完整",
            "维度完整",
            "检测",
            "反馈精准",
            "信号检测",
            "系统",
            "模型",
            "评分",
            "报告",
            "window",
            "artifact",
            "pack",
            "prompt",
            "confidence",
            "coverage",
            "dimensioncoverage",
            "structurecomplete",
        )
        return any(keyword in normalized for keyword in meta_keywords)

    def _sanitize_suggestions(self, *, language: LanguageOption, suggestions: list[SuggestionItem]) -> list[SuggestionItem]:
        cleaned: list[SuggestionItem] = []
        for item in suggestions:
            title = self._sanitize_user_facing_text(language=language, text=item.title)
            detail = self._sanitize_user_facing_text(language=language, text=item.detail)
            if not title or not detail:
                continue
            cleaned.append(SuggestionItem(title=title, detail=detail))
        deduped: list[SuggestionItem] = []
        seen: set[tuple[str, str]] = set()
        for item in cleaned:
            key = (item.title, item.detail)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped[:3]

    def _sanitize_user_facing_text(self, *, language: LanguageOption, text: str) -> str:
        result = str(text).strip()
        if not result:
            return ""

        replacements = (
            (r"\brhythm\b", self._text(language, "节奏", "rhythm")),
            (r"\bvocal_tone\b", self._text(language, "语音语调", "vocal tone")),
            (r"\bcontent_quality\b", self._text(language, "内容质量", "content quality")),
            (r"\bexpression_structure\b", self._text(language, "表达结构", "expression structure")),
            (r"\bfacial_expression\b", self._text(language, "表情", "facial expression")),
            (r"\bbody\b", self._text(language, "肢体表现", "body language")),
        )
        for pattern, replacement in replacements:
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

        cleanup_patterns = (
            r"[，,、 ]*以(?:激活|获得|触发)?[^，。；;]*(?:维度反馈|深度反馈)",
            r"[，,、 ]*以便[^，。；;]*(?:维度|反馈)",
            r"[，,、 ]*这样可以让(?:系统|模型)[^，。；;]*",
            r"[，,、 ]*便于(?:系统|模型)[^，。；;]*",
            r"[，,、 ]*从而获得[^，。；;]*(?:反馈|评估)",
            r"[，,、 ]*帮助(?:系统|模型)[^，。；;]*",
            r"[，,、 ]*重点关注[^，。；;]*(?:维度|反馈)",
        )
        for pattern in cleanup_patterns:
            result = re.sub(pattern, "", result, flags=re.IGNORECASE)

        result = re.sub(r"(节奏|语音语调|内容质量|表达结构|表情|肢体表现)\s*维度", r"\1", result)
        result = re.sub(r"(语音语调|节奏|表情|肢体表现|内容质量|表达结构)反馈", r"\1表现", result)
        result = re.sub(r"[，,、 ]*(系统|模型)(检测|判断|评分|分析)[^，。；;]*", "", result, flags=re.IGNORECASE)
        result = re.sub(r"[，,、 ]*(置信度|覆盖率|覆盖评估|结构完整性?)[^，。；;]*", "", result, flags=re.IGNORECASE)
        result = re.sub(r"[，,、 ]{2,}", "，", result)
        result = re.sub(r"[，,、]\s*[，,、]", "，", result)
        result = re.sub(r"[，,、]\s*(。|；|;)", r"\1", result)
        result = re.sub(r"\s+", " ", result).strip(" ，,、;；")
        if result and result[-1] not in "。！？!?":
            result = f"{result}。"
        return result

    @staticmethod
    def _supports_thinking_toggle(model: str) -> bool:
        normalized = model.strip().lower()
        if not normalized:
            return False
        if normalized.startswith("qwen-max"):
            return False
        return any(
            marker in normalized
            for marker in (
                "qwen-flash",
                "qwen-plus",
                "qwen-turbo",
                "qwen3",
            )
        )

    @staticmethod
    def _score_rubric(language: LanguageOption) -> list[str]:
        return SCORE_RUBRIC_EN if language == "en" else SCORE_RUBRIC_ZH

    def _align_dimension_copy_with_score(
        self,
        *,
        language: LanguageOption,
        label: str,
        score: int,
        strengths: list[str],
        weaknesses: list[str],
    ) -> tuple[list[str], list[str]]:
        clean_strengths = self._dedupe([item for item in strengths if item.strip()])[:3]
        clean_weaknesses = self._dedupe([item for item in weaknesses if item.strip()])[:3]

        if score < 70:
            clean_strengths = [
                item for item in clean_strengths if not self._looks_like_unqualified_praise(item)
            ][:2]
        if score < 75 and not clean_weaknesses:
            clean_weaknesses = [self._default_dimension_weakness(language, label, score)]
        if score >= 85 and not clean_strengths:
            clean_strengths = [self._default_dimension_strength(language, label, score)]
        return clean_strengths, clean_weaknesses

    def _align_report_copy_with_score(
        self,
        *,
        language: LanguageOption,
        overall_score: int,
        headline: str,
        encouragement: str,
        summary_paragraph: str,
        best_dimension: ReportTopDimensionScore | None,
        weakest_dimension: ReportTopDimensionScore | None,
    ) -> tuple[str, str, str]:
        best_label = best_dimension.label if best_dimension is not None else self._text(language, "相对稳定项", "the strongest area")
        weakest_label = weakest_dimension.label if weakest_dimension is not None else self._text(language, "核心短板", "the weakest area")
        default_headline = self._build_headline(language, overall_score, best_label, weakest_label)
        default_encouragement = self._build_encouragement(language, overall_score, best_label, weakest_label)
        default_summary = self._build_summary(language, overall_score, best_label, weakest_label)
        combined = f"{headline}\n{encouragement}\n{summary_paragraph}"

        if overall_score < 70:
            return default_headline, default_encouragement, default_summary
        if overall_score < 80 and self._looks_like_high_praise(combined):
            return default_headline, default_encouragement, default_summary
        if overall_score >= 80 and self._looks_like_severe_criticism(combined):
            return default_headline, default_encouragement, default_summary
        if overall_score >= 85 and not self._looks_like_unqualified_praise(combined):
            return default_headline, default_encouragement, summary_paragraph or default_summary
        return headline, encouragement, summary_paragraph

    def _default_dimension_weakness(self, language: LanguageOption, label: str, score: int) -> str:
        if score < 60:
            return self._text(
                language,
                f"{label}没有达到可接受水平，已经影响听众理解或观感。",
                f"{label} is below an acceptable level and hurts audience understanding or perception.",
            )
        return self._text(
            language,
            f"{label}只是勉强过线，还需要一个更明确的修正动作。",
            f"{label} barely passes and still needs a more specific correction.",
        )

    def _default_dimension_strength(self, language: LanguageOption, label: str, score: int) -> str:
        if score >= 90:
            return self._text(
                language,
                f"{label}是本轮很突出的优势，可以放心保留。",
                f"{label} is a standout strength and should be kept.",
            )
        return self._text(
            language,
            f"{label}表现稳定，是本轮比较可靠的长板。",
            f"{label} is stable and reliable in this session.",
        )

    @staticmethod
    def _looks_like_unqualified_praise(text: str) -> bool:
        normalized = re.sub(r"\s+", "", text).lower()
        if not normalized:
            return False
        praise_keywords = (
            "很稳",
            "稳定",
            "不错",
            "很好",
            "优秀",
            "出色",
            "漂亮",
            "成熟",
            "清晰",
            "顺畅",
            "亮点",
            "优势",
            "可圈可点",
            "扎实",
            "到位",
            "能打",
            "good",
            "great",
            "strong",
            "stable",
            "excellent",
            "standout",
        )
        caveat_keywords = ("但是", "但", "不过", "只是", "还不", "不够", "问题", "短板", "barely", "but", "however")
        return any(keyword in normalized for keyword in praise_keywords) and not any(
            keyword in normalized for keyword in caveat_keywords
        )

    @staticmethod
    def _looks_like_high_praise(text: str) -> bool:
        normalized = re.sub(r"\s+", "", text).lower()
        high_praise_keywords = (
            "非常出色",
            "非常优秀",
            "很漂亮",
            "很棒",
            "炸裂",
            "封神",
            "拉满",
            "极好",
            "excellent",
            "outstanding",
            "fantastic",
            "brilliant",
        )
        return any(keyword in normalized for keyword in high_praise_keywords)

    @staticmethod
    def _looks_like_severe_criticism(text: str) -> bool:
        normalized = re.sub(r"\s+", "", text).lower()
        severe_keywords = (
            "很差",
            "严重失效",
            "完全失控",
            "毫无",
            "拖垮",
            "不及格",
            "不能接受",
            "severe",
            "unacceptable",
            "failed",
            "collapse",
            "broken",
        )
        return any(keyword in normalized for keyword in severe_keywords)

    def _radar_metrics_from_dimensions(self, dimensions: list[ReportTopDimensionScore]) -> list[RadarMetric]:
        return [
            RadarMetric(subject=dimension.label, score=dimension.score, fullMark=100)
            for dimension in dimensions
        ]

    def _weighted_score(self, scenario_id: ScenarioType, dimensions: list[ReportTopDimensionScore]) -> int:
        weight_map = scenario_weights(scenario_id)
        total_weight = sum(weight_map.values())
        weighted_sum = sum(dimension.score * weight_map[dimension.id] for dimension in dimensions)
        return round(weighted_sum / max(total_weight, 1))

    def _sanitize_report_headline(self, *, language: LanguageOption, headline: str, fallback: str) -> str:
        result = str(headline or "").strip() or fallback
        result = re.sub(r"\s+", " ", result).strip(" “”…\"'《》【】[]()（）")
        result = re.sub(r"^.{0,24}?(?:教练)?(?:赛后|训练|本轮训练)?报告\s*[:：]\s*", "", result)
        result = re.sub(r"^(?:headline|title)\s*[:：]\s*", "", result, flags=re.IGNORECASE)
        result = result.strip(" ：:，,。.!！?？;；-—")

        normalized = re.sub(r"\s+", "", result).lower()
        if language != "en" and (
            "表达启动阶段的关键调整" in normalized
            or "启动阶段的关键调整" in normalized
        ):
            return "开场先说重点"

        if "报告" in normalized or not result:
            result = fallback.strip(" ：:，,。.!！?？;；-—")
            normalized = re.sub(r"\s+", "", result).lower()

        blocked_headlines = (
            "问题明显",
            "别粉饰",
            "问题明显别粉饰",
            "勉强过线",
            "勉强过线先补短板",
            "严重失效",
            "clearproblems",
            "barelypassing",
            "severeissues",
        )
        if any(keyword in normalized for keyword in blocked_headlines):
            result = fallback.strip(" ：:，,。.!！?？;；-—")
            if result == headline.strip(" ：:，,。.!！?？;；-—"):
                result = self._text(language, "先把逻辑理顺", "Fix the structure first")

        if language == "en":
            result = re.sub(r"\bpost[- ]?(session|training)? report\b[:：]?\s*", "", result, flags=re.IGNORECASE)
            result = result.strip(" ：:，,。.!！?？;；-—")
            return result or "Lead with the point"

        if len(result) > 18:
            compact = re.split(r"[，,。.!！?？；;]", result, maxsplit=1)[0].strip()
            result = compact if compact else result
        if len(result) > 18:
            result = result[:18].rstrip(" ：:，,、")
        return result or "开场先说重点"

    def _build_headline(
        self,
        language: LanguageOption,
        overall_score: int,
        best_dimension_label: str,
        weakest_dimension_label: str,
    ) -> str:
        if overall_score >= 90:
            return self._text(language, f"{best_dimension_label}很能打", f"{best_dimension_label} is a real strength")
        if overall_score >= 80:
            return self._text(language, "这轮表达很稳", "This round is strong")
        if overall_score >= 70:
            return self._text(language, f"再把{weakest_dimension_label}补齐", f"Tighten {weakest_dimension_label}")
        if overall_score >= 60:
            return self._text(language, self._headline_action_for_dimension(weakest_dimension_label), f"Fix {weakest_dimension_label} first")
        return self._text(language, self._headline_action_for_dimension(weakest_dimension_label), f"Rebuild {weakest_dimension_label} first")

    @staticmethod
    def _headline_action_for_dimension(dimension_label: str) -> str:
        actions = {
            "肢体": "先把肢体收住",
            "表情": "先把表情打开",
            "语音语调": "先把声音说清",
            "节奏": "先把节奏稳住",
            "内容质量": "先把内容讲实",
            "表达结构": "先把逻辑理顺",
        }
        return actions.get(dimension_label, f"先补{dimension_label}短板")

    def _build_encouragement(
        self,
        language: LanguageOption,
        overall_score: int,
        best_dimension_label: str,
        weakest_dimension_label: str,
    ) -> str:
        if overall_score >= 90:
            return self._text(
                language,
                f"这轮{best_dimension_label}发挥很漂亮，不是礼貌性表扬，是确实能支撑整场表达的优势。",
                f"{best_dimension_label} was genuinely strong here, not just politely good.",
            )
        if overall_score >= 80:
            return self._text(
                language,
                f"整体完成度已经不错，{best_dimension_label}是清楚的长板；下一步把{weakest_dimension_label}再收紧，表现会更有压迫感。",
                f"The overall delivery is strong, especially {best_dimension_label}. Tighten {weakest_dimension_label} next.",
            )
        if overall_score >= 70:
            return self._text(
                language,
                f"这轮能让人听懂，但还没到“哇，真稳”的程度。{best_dimension_label}可以保留，{weakest_dimension_label}要优先补。",
                f"This is understandable, but not yet impressive. Keep {best_dimension_label} and improve {weakest_dimension_label}.",
            )
        if overall_score >= 60:
            return self._text(
                language,
                f"这轮不是完全失控，但只是勉强过线。{weakest_dimension_label}已经在拖整体效果，下一轮别再平均用力。",
                f"This did not collapse, but it barely passes. {weakest_dimension_label} is dragging the whole delivery down.",
            )
        return self._text(
            language,
            f"这轮主要问题比较直接：{weakest_dimension_label}没有站住。先把这个点修好，再谈风格和高级感。",
            f"The main issue is direct: {weakest_dimension_label} is not holding up. Fix that before chasing style.",
        )

    def _build_summary(
        self,
        language: LanguageOption,
        overall_score: int,
        best_dimension_label: str,
        weakest_dimension_label: str,
    ) -> str:
        if overall_score >= 80:
            return self._text(
                language,
                f"这轮的长板主要在{best_dimension_label}，已经能撑起基本观感；短板集中在{weakest_dimension_label}，属于精修项，不是推倒重来。",
                f"The strongest area is {best_dimension_label}; {weakest_dimension_label} is a refinement target, not a full rebuild.",
            )
        if overall_score >= 60:
            return self._text(
                language,
                f"这轮有可保留的部分，但{weakest_dimension_label}的问题太显眼，像一颗螺丝没拧紧，整台机器都跟着晃。下一轮先处理这一项。",
                f"There are usable parts, but {weakest_dimension_label} is too visible. Fix that first in the next round.",
            )
        return self._text(
            language,
            f"这轮不要粉饰成“还不错”。核心短板是{weakest_dimension_label}，它已经影响听众理解；先做基础修复，再谈亮点。",
            f"Do not dress this up as fine. {weakest_dimension_label} is hurting audience understanding and needs basic repair first.",
        )

    @staticmethod
    def _flatten_evidence_refs(dimensions: list[ReportTopDimensionScore]) -> list[ReportEvidenceRef]:
        refs: list[ReportEvidenceRef] = []
        for dimension in dimensions:
            refs.extend(dimension.evidenceRefs[:2])
        return refs[:6]

    @staticmethod
    def _merge_strings(groups: list[list[str]], limit: int) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()
        for group in groups:
            for item in group:
                normalized = item.strip()
                if not normalized or normalized.lower() in seen:
                    continue
                seen.add(normalized.lower())
                merged.append(normalized)
        return merged[:limit]

    def _merge_sub_dimensions(self, groups: list[list[ReportSubDimensionScore]], language: LanguageOption) -> list[ReportSubDimensionScore]:
        merged: dict[str, list[ReportSubDimensionScore]] = defaultdict(list)
        for group in groups:
            for item in group:
                merged[item.id].append(item)
        result: list[ReportSubDimensionScore] = []
        for sub_dimension_id, items in merged.items():
            result.append(
                ReportSubDimensionScore(
                    id=sub_dimension_id,
                    label=sub_dimension_label(sub_dimension_id, language),
                    score=round(sum(item.score for item in items) / max(len(items), 1)),
                    reason=items[-1].reason,
                )
            )
        return sorted(result, key=lambda item: item.score)[:6]

    @staticmethod
    def _merge_evidence_refs(groups: list[list[ReportEvidenceRef]], limit: int) -> list[ReportEvidenceRef]:
        merged: list[ReportEvidenceRef] = []
        seen: set[tuple[int, str | None]] = set()
        for group in groups:
            for item in group:
                key = (item.timestampMs, item.subDimensionId)
                if key in seen:
                    continue
                seen.add(key)
                merged.append(item)
        return merged[:limit]

    @staticmethod
    def _dedupe(items: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for item in items:
            normalized = item.strip()
            if not normalized or normalized.lower() in seen:
                continue
            seen.add(normalized.lower())
            result.append(normalized)
        return result

    @staticmethod
    def _coerce_str(value: object, fallback: str) -> str:
        text = str(value).strip() if value is not None else ""
        return text or fallback

    @staticmethod
    def _coerce_nullable_str(value: object) -> str | None:
        text = str(value).strip() if value is not None else ""
        return text or None

    @staticmethod
    def _coerce_list(value: object, fallback: list[str]) -> list[str]:
        if not isinstance(value, list):
            return fallback
        cleaned = [str(item).strip() for item in value if str(item).strip()]
        return cleaned or fallback

    @staticmethod
    def _coerce_int(value: object, fallback: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return fallback

    @staticmethod
    def _coerce_score(value: object, fallback: int) -> int:
        try:
            numeric = round(float(value))
        except (TypeError, ValueError):
            numeric = fallback
        return max(0, min(100, int(numeric)))

    @staticmethod
    def _coerce_confidence(value: object, fallback: float | None) -> float | None:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return fallback
        return max(0.0, min(1.0, numeric))

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _text(language: LanguageOption, zh: str, en: str) -> str:
        return en if language == "en" else zh
