from __future__ import annotations

import re
from dataclasses import dataclass
from statistics import mean

from app.schemas import LanguageOption, ReportArtifactEntry, TranscriptChunk
from app.services.report_domain import COACH_TO_TOP_DIMENSIONS


FILLER_TOKENS = {
    "zh": {"嗯", "啊", "额", "呃", "然后", "就是", "那个", "其实", "哦", "诶", "欸", "哎", "唉"},
    "en": {"um", "uh", "well", "so", "like", "hmm", "hm"},
}


@dataclass(frozen=True)
class ReportSignalBundle:
    transcript_chunks: list[TranscriptChunk]
    transcript_text: str
    transcript_stats: dict
    qa_questions: list[dict]
    coach_signals: list[dict]
    top_dimension_map: dict
    latest_timestamp_ms: int


class ReportSignalService:
    def build_bundle(
        self,
        *,
        language: LanguageOption,
        artifacts: list[ReportArtifactEntry],
        after_ms: int = 0,
        end_ms: int | None = None,
    ) -> ReportSignalBundle:
        transcript_chunks = self._reconstruct_transcript_chunks(artifacts)
        filtered_chunks = [
            chunk
            for chunk in transcript_chunks
            if chunk.endMs > after_ms and (end_ms is None or chunk.startMs <= end_ms)
        ]
        qa_questions = self._collect_qa_questions(artifacts, after_ms=after_ms, end_ms=end_ms)
        coach_signals = self._collect_coach_signals(artifacts, after_ms=after_ms, end_ms=end_ms)
        latest_timestamp_ms = max(
            [
                0,
                *[chunk.endMs for chunk in filtered_chunks],
                *[int(question.get("timestampMs", 0)) for question in qa_questions],
                *[int(signal.get("timestampMs", 0)) for signal in coach_signals],
            ]
        )
        transcript_text = "\n".join(chunk.text for chunk in filtered_chunks if chunk.text.strip()).strip()
        transcript_stats = self._build_transcript_stats(language, filtered_chunks)
        return ReportSignalBundle(
            transcript_chunks=filtered_chunks,
            transcript_text=transcript_text,
            transcript_stats=transcript_stats,
            qa_questions=qa_questions,
            coach_signals=coach_signals,
            top_dimension_map=self._build_top_dimension_map(coach_signals),
            latest_timestamp_ms=latest_timestamp_ms,
        )

    def _reconstruct_transcript_chunks(self, artifacts: list[ReportArtifactEntry]) -> list[TranscriptChunk]:
        chunks: list[TranscriptChunk] = []
        for artifact in sorted(artifacts, key=lambda item: item.timestampMs):
            if artifact.type not in {"transcript_final", "transcript_merged"}:
                continue
            raw_chunk = artifact.payload.get("chunk")
            if not isinstance(raw_chunk, dict):
                continue
            chunk = TranscriptChunk.model_validate(raw_chunk)
            replace_previous = bool(artifact.payload.get("replacePrevious", False))
            if replace_previous and chunks:
                chunks[-1] = chunk
                continue
            if chunks and chunks[-1].id == chunk.id:
                chunks[-1] = chunk
                continue
            chunks.append(chunk)
        return chunks

    def _collect_coach_signals(
        self,
        artifacts: list[ReportArtifactEntry],
        *,
        after_ms: int,
        end_ms: int | None,
    ) -> list[dict]:
        signals: list[dict] = []
        for artifact in sorted(artifacts, key=lambda item: item.timestampMs):
            if artifact.type != "coach_signal":
                continue
            timestamp_ms = artifact.timestampMs
            if timestamp_ms <= after_ms:
                continue
            if end_ms is not None and timestamp_ms > end_ms:
                continue
            payload = dict(artifact.payload)
            payload["timestampMs"] = timestamp_ms
            signals.append(payload)
        return signals

    def _collect_qa_questions(
        self,
        artifacts: list[ReportArtifactEntry],
        *,
        after_ms: int,
        end_ms: int | None,
    ) -> list[dict]:
        questions: list[dict] = []
        for artifact in sorted(artifacts, key=lambda item: item.timestampMs):
            if artifact.type != "qa_question":
                continue
            timestamp_ms = artifact.timestampMs
            if timestamp_ms <= after_ms:
                continue
            if end_ms is not None and timestamp_ms > end_ms:
                continue
            payload = dict(artifact.payload)
            payload["timestampMs"] = timestamp_ms
            questions.append(payload)
        return questions

    def _build_transcript_stats(self, language: LanguageOption, chunks: list[TranscriptChunk]) -> dict:
        total_chars = sum(len(re.sub(r"\s+", "", chunk.text)) for chunk in chunks)
        total_words = sum(len(self._split_tokens(chunk.text)) for chunk in chunks)
        filler_count = sum(self._count_fillers(language, chunk.text) for chunk in chunks)
        restart_count = sum(1 for chunk in chunks if self._starts_with_filler(language, chunk.text))
        avg_chunk_chars = round(total_chars / max(len(chunks), 1), 2)
        gap_ms_values: list[int] = []
        for index in range(1, len(chunks)):
            gap_ms = max(chunks[index].startMs - chunks[index - 1].endMs, 0)
            gap_ms_values.append(gap_ms)
        mean_gap_ms = round(mean(gap_ms_values), 2) if gap_ms_values else 0.0
        long_pause_count = sum(1 for gap in gap_ms_values if gap >= 1800)
        repetition_ratio = self._build_repetition_ratio(chunks)
        return {
            "totalChars": total_chars,
            "totalWords": total_words,
            "totalChunks": len(chunks),
            "fillerCount": filler_count,
            "fillerDensity": round(filler_count / max(total_words, 1), 4),
            "restartCount": restart_count,
            "avgChunkChars": avg_chunk_chars,
            "meanGapMs": mean_gap_ms,
            "longPauseCount": long_pause_count,
            "repetitionRatio": repetition_ratio,
        }

    def _build_top_dimension_map(self, coach_signals: list[dict]) -> dict:
        result: dict[str, list[dict]] = {}
        for signal in coach_signals:
            sub_dimension_id = str(signal.get("subDimensionId") or "").strip()
            mapped_top_dimensions = COACH_TO_TOP_DIMENSIONS.get(sub_dimension_id, ())
            for top_dimension_id in mapped_top_dimensions:
                result.setdefault(top_dimension_id, []).append(signal)
        return result

    @staticmethod
    def _split_tokens(text: str) -> list[str]:
        stripped = text.strip()
        if not stripped:
            return []
        if re.search(r"[\u4e00-\u9fff]", stripped):
            return [char for char in stripped if not char.isspace()]
        return [token for token in re.split(r"\s+", stripped) if token]

    def _count_fillers(self, language: LanguageOption, text: str) -> int:
        tokens = self._split_tokens(text)
        fillers = FILLER_TOKENS["en" if language == "en" else "zh"]
        return sum(1 for token in tokens if token.lower() in fillers)

    def _starts_with_filler(self, language: LanguageOption, text: str) -> bool:
        tokens = self._split_tokens(text)
        if not tokens:
            return False
        fillers = FILLER_TOKENS["en" if language == "en" else "zh"]
        return tokens[0].lower() in fillers

    @staticmethod
    def _build_repetition_ratio(chunks: list[TranscriptChunk]) -> float:
        normalized = [re.sub(r"\s+", "", chunk.text).lower() for chunk in chunks if chunk.text.strip()]
        if len(normalized) <= 1:
            return 0.0
        repeated = 0
        comparisons = 0
        for index in range(1, len(normalized)):
            current = normalized[index]
            previous = normalized[index - 1]
            comparisons += 1
            if current == previous or current in previous or previous in current:
                repeated += 1
        return round(repeated / max(comparisons, 1), 4)
