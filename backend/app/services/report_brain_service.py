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
    "host": "主持场景",
    "guest-sharing": "主题分享场景",
    "standup": "脱口秀 / 即兴表达场景",
}

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
        self.window_model = window_model or os.getenv("ALIYUN_REPORT_WINDOW_MODEL", "qwen-plus-latest")
        self.final_model = final_model or os.getenv("ALIYUN_REPORT_BRAIN_MODEL", "qwen-plus-latest")
        self.fallback_model = fallback_model or os.getenv("ALIYUN_REPORT_BRAIN_FALLBACK_MODEL", "qwen-max-latest")
        self.window_timeout_seconds = max(10.0, float(os.getenv("ALIYUN_REPORT_WINDOW_TIMEOUT_SECONDS", "30")))
        self.final_timeout_seconds = max(15.0, float(os.getenv("ALIYUN_REPORT_BRAIN_TIMEOUT_SECONDS", "45")))
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
            "必须输出 JSON。"
        )
        user_prompt = json.dumps(
            {
                "language": language,
                "scenario": SCENARIO_LABELS[scenario_id],
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
            "你是 Speak Up 的赛后报告生成助手。"
            "你要基于历史窗口评估包和最后一个未覆盖尾窗的原始数据，生成一份完整、统一、去重后的整场报告。"
            "不要重复窗口建议，要做整合。"
            "你只能评价用户的演讲表现。"
            "不要描述系统检测过程、模型能力、覆盖率、置信度、维度完整性、报告生成流程。"
            "不要使用内部维度 id 或机制术语，例如 rhythm、vocal_tone、content_quality、expression_structure、body、facial_expression、维度反馈。"
            "如果要给建议，必须改写成用户能直接理解的自然表达。"
            f"当前报告要采用“{coach_profile.coach_name}”这位教练的人设口吻，但仍然必须保持专业、克制、面向用户。"
            f"{coach_profile.report_instruction_zh}"
            "必须输出 JSON。"
        )
        user_prompt = json.dumps(
            {
                "language": language,
                "scenario": SCENARIO_LABELS[scenario_id],
                "weights": scenario_weights(scenario_id),
                "window_packs": [pack.model_dump() for pack in window_packs],
                "tail_window": self._tail_payload(tail_bundle),
                "top_dimensions": list(TOP_DIMENSION_ORDER),
                "output_schema": {
                    "headline": "string",
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
        messages: list[dict[str, str]],
        temperature: float,
    ) -> str:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post(
                f"{self.base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
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
        headline = self._coerce_str(payload.get("headline"), fallback.headline)
        encouragement = self._coerce_str(payload.get("encouragement"), fallback.encouragement)
        summary_paragraph = self._coerce_str(payload.get("summary_paragraph"), fallback.summaryParagraph)
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
                        score=78,
                        weight=scenario_weights(scenario_id)[dimension_id],
                        strengths=[self._text(language, "表现基本稳定", "Performance stays mostly stable")],
                        weaknesses=[],
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
            headline=self._build_headline(language, overall_score, best_dimension.label),
            encouragement=self._build_encouragement(language, best_dimension.label),
            summaryParagraph=self._build_summary(language, best_dimension.label, weakest_dimension.label),
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
        score = 82
        for signal in signals:
            polarity = str(signal.get("signalPolarity") or "negative").lower()
            severity = str(signal.get("severity") or "medium").lower()
            penalty = {"low": 2, "medium": 5, "high": 8}.get(severity, 4)
            bonus = {"low": 1, "medium": 2, "high": 3}.get(severity, 2)
            if polarity == "positive":
                score += bonus
            elif polarity == "neutral":
                score -= 1
            else:
                score -= penalty

        filler_density = float(transcript_stats.get("fillerDensity", 0))
        repetition_ratio = float(transcript_stats.get("repetitionRatio", 0))
        long_pause_count = int(transcript_stats.get("longPauseCount", 0))
        if dimension_id in {"content_quality", "expression_structure"}:
            score -= int(repetition_ratio * 12)
            if filler_density >= 0.08:
                score -= 4
        if dimension_id in {"rhythm", "vocal_tone"}:
            score -= min(long_pause_count * 2, 8)
            score -= int(filler_density * 15)
        return max(58, min(96, score))

    def _fallback_sub_dimensions(self, language: LanguageOption, signals: list[dict]) -> list[ReportSubDimensionScore]:
        grouped: dict[str, list[dict]] = defaultdict(list)
        for signal in signals:
            sub_dimension_id = str(signal.get("subDimensionId") or "").strip()
            if not sub_dimension_id:
                continue
            grouped[sub_dimension_id].append(signal)
        result: list[ReportSubDimensionScore] = []
        for sub_dimension_id, items in grouped.items():
            score = 84
            for item in items:
                polarity = str(item.get("signalPolarity") or "negative").lower()
                severity = str(item.get("severity") or "medium").lower()
                if polarity == "positive":
                    score += {"low": 1, "medium": 2, "high": 3}.get(severity, 2)
                else:
                    score -= {"low": 3, "medium": 6, "high": 9}.get(severity, 5)
            latest = items[-1]
            reason = str(latest.get("detail") or latest.get("evidenceText") or "").strip()
            result.append(
                ReportSubDimensionScore(
                    id=sub_dimension_id,
                    label=sub_dimension_label(sub_dimension_id, language),
                    score=max(55, min(96, score)),
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
        if score >= 84:
            return [self._text(language, f"{top_dimension_label(dimension_id, language)}整体稳定。", f"{top_dimension_label(dimension_id, language)} stays stable overall.")]
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
            sub_dimensions = self._sub_dimensions_from_payload(raw_item.get("sub_dimensions"), language, fallback_item.subDimensions)
            evidence_refs = self._evidence_refs_from_payload(
                raw_item.get("evidence_refs"),
                dimension_id=dimension_id,
                fallback=fallback_item.evidenceRefs,
            )
            result.append(
                ReportTopDimensionScore(
                    id=dimension_id,
                    label=top_dimension_label(dimension_id, language),
                    score=self._coerce_int(raw_item.get("score"), fallback_item.score),
                    weight=fallback_item.weight,
                    strengths=self._coerce_list(raw_item.get("strengths"), fallback_item.strengths),
                    weaknesses=self._coerce_list(raw_item.get("weaknesses"), fallback_item.weaknesses),
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
                    score=self._coerce_int(raw_item.get("score"), 78),
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
            else:
                highlights.append(
                    self._text(language, f"{dimension.label}整体稳定。", f"{dimension.label} stays stable overall.")
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
            candidate = dimension.strengths[0] if dimension.strengths else self._text(
                language,
                f"{dimension.label}整体较稳定。",
                f"{dimension.label} stays relatively stable.",
            )
            if self._looks_like_meta_observation(candidate):
                continue
            regenerated.append(f"{dimension.label}：{candidate}")
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

    def _build_headline(self, language: LanguageOption, overall_score: int, best_dimension_label: str) -> str:
        if overall_score >= 86:
            return self._text(language, f"这轮 {best_dimension_label} 已经很稳", f"{best_dimension_label} is already a real strength")
        if overall_score >= 78:
            return self._text(language, "这轮整体表达已经比较成熟", "This round already feels more mature")
        return self._text(language, "这轮已经有清晰的提升方向", "This round reveals a clear improvement path")

    def _build_encouragement(self, language: LanguageOption, best_dimension_label: str) -> str:
        return self._text(
            language,
            f"整场最稳定的部分是{best_dimension_label}。如果把最弱的一两项再收紧，完整度会明显上来。",
            f"Your steadiest dimension is {best_dimension_label}. Tighten the weakest one or two areas and the whole performance will feel much stronger.",
        )

    def _build_summary(self, language: LanguageOption, best_dimension_label: str, weakest_dimension_label: str) -> str:
        return self._text(
            language,
            f"这轮表现的长板主要在{best_dimension_label}，短板更集中在{weakest_dimension_label}。后续训练可以优先围绕短板做更针对性的重复练习。",
            f"The strongest part of this session is {best_dimension_label}, while {weakest_dimension_label} needs the most work next. Future practice should focus there first.",
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
