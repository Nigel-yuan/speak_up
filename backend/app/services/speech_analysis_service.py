import re
from collections import deque
from dataclasses import dataclass, field

from app.schemas import LanguageOption, TranscriptChunk


FILLER_TOKENS = {
    "zh": ("嗯", "啊", "额", "呃", "然后", "就是", "那个", "其实", "哦", "诶", "欸", "哎", "唉"),
    "en": ("um", "uh", "well", "so", "like"),
}
WINDOW_SIZE = 6


@dataclass(frozen=True)
class DimensionDraft:
    status: str
    headline: str
    detail: str


@dataclass(frozen=True)
class SpeechPanelUpdate:
    voice: DimensionDraft
    content: DimensionDraft


@dataclass
class SpeechSessionState:
    chunks: deque[TranscriptChunk] = field(default_factory=lambda: deque(maxlen=WINDOW_SIZE))


class SpeechAnalysisService:
    def __init__(self) -> None:
        self.sessions: dict[str, SpeechSessionState] = {}

    def close_session(self, session_id: str) -> None:
        self.sessions.pop(session_id, None)

    def ingest_chunk(
        self,
        session_id: str,
        language: LanguageOption,
        chunk: TranscriptChunk,
    ) -> SpeechPanelUpdate:
        state = self.sessions.setdefault(session_id, SpeechSessionState())
        state.chunks.append(chunk)
        return self._build_update(language, list(state.chunks))

    def replace_last_chunk(
        self,
        session_id: str,
        language: LanguageOption,
        chunk: TranscriptChunk,
    ) -> SpeechPanelUpdate:
        state = self.sessions.setdefault(session_id, SpeechSessionState())
        if state.chunks:
            state.chunks.pop()
        state.chunks.append(chunk)
        return self._build_update(language, list(state.chunks))

    def preview_partial(
        self,
        session_id: str,
        language: LanguageOption,
        text: str,
        *,
        timestamp_ms: int,
    ) -> SpeechPanelUpdate | None:
        clean_text = text.strip()
        if not clean_text:
            return None

        state = self.sessions.setdefault(session_id, SpeechSessionState())
        start_ms = max(0, timestamp_ms - 2500)
        partial_chunk = TranscriptChunk(
            id="speech-preview-partial",
            speaker="user",
            text=clean_text,
            timestampLabel="",
            startMs=start_ms,
            endMs=max(timestamp_ms, start_ms + 1),
        )
        return self._build_update(language, [*state.chunks, partial_chunk])

    def _build_update(self, language: LanguageOption, chunks: list[TranscriptChunk]) -> SpeechPanelUpdate:
        units_per_chunk = [self._count_units(language, chunk.text) for chunk in chunks]
        total_units = sum(units_per_chunk)
        filler_count = sum(self._count_fillers(language, chunk.text) for chunk in chunks)
        filler_density = filler_count / max(total_units, 1)
        repetition_score = self._build_repetition_score(language, chunks)
        latest_chunk = chunks[-1]
        latest_units = units_per_chunk[-1] if units_per_chunk else 0
        latest_duration_ms = max(latest_chunk.endMs - latest_chunk.startMs, 1)
        pace = self._build_pace_band(language, latest_units, latest_duration_ms)
        average_units = total_units / max(len(chunks), 1)
        restart_count = sum(1 for chunk in chunks if self._starts_with_filler(language, chunk.text))

        voice = self._build_voice_dimension(
            language,
            total_units=total_units,
            filler_density=filler_density,
            pace=pace,
            restart_count=restart_count,
        )
        content = self._build_content_dimension(
            language,
            total_units=total_units,
            filler_density=filler_density,
            repetition_score=repetition_score,
            average_units=average_units,
        )

        return SpeechPanelUpdate(voice=voice, content=content)

    def _build_voice_dimension(
        self,
        language: LanguageOption,
        *,
        total_units: int,
        filler_density: float,
        pace: str,
        restart_count: int,
    ) -> DimensionDraft:
        if total_units < (12 if language == "zh" else 8):
            return DimensionDraft(
                status="analyzing",
                headline=self._text(language, "正在更新语音节奏反馈", "Updating vocal pacing"),
                detail=self._text(language, "保持当前节奏", "Keep your current rhythm"),
            )

        if filler_density >= 0.24 or restart_count >= 3:
            return DimensionDraft(
                status="adjust_now",
                headline=self._text(language, "节奏有点卡", "The pacing is catching"),
                detail=self._text(
                    language,
                    "这一段口头禅和找词感偏多，先把句子收短一点，节奏会更干净。",
                    "This stretch has too many fillers and restarts. Shorten the next sentence so the pacing feels cleaner.",
                ),
            )

        if pace == "fast" and total_units >= (18 if language == "zh" else 12):
            return DimensionDraft(
                status="adjust_now",
                headline=self._text(language, "语速有点快", "The pace is a bit fast"),
                detail=self._text(
                    language,
                    "听众可能来不及消化重点，下一句稍微放慢一点。",
                    "Listeners may not have time to absorb the key point. Slow the next sentence down a touch.",
                ),
            )

        if pace == "slow":
            return DimensionDraft(
                status="stable",
                headline=self._text(language, "语速偏慢但还稳", "The pace is a bit slow but steady"),
                detail=self._text(
                    language,
                    "现在听感不乱，但核心句可以再利落一点。",
                    "The delivery is steady, but the key line could land more crisply.",
                ),
            )

        if filler_density <= 0.04 and restart_count == 0:
            return DimensionDraft(
                status="doing_well",
                headline=self._text(language, "节奏整体顺", "The pacing feels smooth"),
                detail=self._text(
                    language,
                    "这一段的语速和衔接都比较自然，可以继续保持。",
                    "The pace and transitions feel natural here. Keep that flow.",
                ),
            )

        return DimensionDraft(
            status="stable",
            headline=self._text(language, "语音节奏基本稳定", "The vocal pacing is mostly stable"),
            detail=self._text(
                language,
                "整体没有明显失控，继续把重点句的停顿和重音拉开就够了。",
                "Nothing is breaking down here. Keep widening the pauses and emphasis on key lines.",
            ),
        )

    def _build_content_dimension(
        self,
        language: LanguageOption,
        *,
        total_units: int,
        filler_density: float,
        repetition_score: float,
        average_units: float,
    ) -> DimensionDraft:
        if total_units < (18 if language == "zh" else 12):
            return DimensionDraft(
                status="analyzing",
                headline=self._text(language, "正在更新内容表达反馈", "Updating content clarity"),
                detail=self._text(language, "继续往下讲，稍后更新这一项反馈", "Keep going and this card will update shortly"),
            )

        if filler_density >= 0.2:
            return DimensionDraft(
                status="adjust_now",
                headline=self._text(language, "口头禅有点多", "There are too many fillers"),
                detail=self._text(
                    language,
                    "“嗯”“然后”这类口头禅偏多，会削弱干净度和专业感。",
                    "There are too many fillers right now, which weakens clarity and authority.",
                ),
            )

        if repetition_score >= 0.6:
            return DimensionDraft(
                status="adjust_now",
                headline=self._text(language, "这一段有点绕", "This point is looping"),
                detail=self._text(
                    language,
                    "你在重复同一个意思，但推进不够。下一句直接把结论说出来。",
                    "You are circling the same idea without enough forward motion. Land the conclusion more directly in the next line.",
                ),
            )

        if average_units >= (34 if language == "zh" else 22):
            return DimensionDraft(
                status="stable",
                headline=self._text(language, "句子稍微有点长", "The sentences are a bit long"),
                detail=self._text(
                    language,
                    "信息是清楚的，但可以把句子再收短一点，让推进更利落。",
                    "The meaning is clear, but shorter sentences would make the point move faster.",
                ),
            )

        if filler_density <= 0.04 and repetition_score <= 0.12:
            return DimensionDraft(
                status="doing_well",
                headline=self._text(language, "内容主线比较清楚", "The message is easy to follow"),
                detail=self._text(
                    language,
                    "这一段没有明显绕圈，听众比较容易跟住你的表达。",
                    "This section stays on track and is easy for listeners to follow.",
                ),
            )

        return DimensionDraft(
            status="stable",
            headline=self._text(language, "表达基本清楚", "The message is mostly clear"),
            detail=self._text(
                language,
                "主线没有明显跑偏，再把句子收紧一点会更好。",
                "The thread is still clear. Tightening the next sentence will make it stronger.",
            ),
        )

    @staticmethod
    def _build_pace_band(language: LanguageOption, unit_count: int, duration_ms: int) -> str:
        units_per_second = unit_count / max(duration_ms / 1000, 0.001)
        if language == "zh":
            if units_per_second >= 6.0:
                return "fast"
            if units_per_second <= 1.7:
                return "slow"
            return "normal"

        if units_per_second >= 3.8:
            return "fast"
        if units_per_second <= 1.0:
            return "slow"
        return "normal"

    def _build_repetition_score(self, language: LanguageOption, chunks: list[TranscriptChunk]) -> float:
        if len(chunks) <= 1:
            return 0.0

        repeated = 0
        comparisons = 0
        normalized_chunks = [self._normalize(language, chunk.text) for chunk in chunks if self._normalize(language, chunk.text)]

        for index in range(1, len(normalized_chunks)):
            current = normalized_chunks[index]
            previous = normalized_chunks[index - 1]
            comparisons += 1
            if current == previous or current in previous or previous in current:
                repeated += 1

        if comparisons == 0:
            return 0.0
        return repeated / comparisons

    def _starts_with_filler(self, language: LanguageOption, text: str) -> bool:
        normalized = self._normalize(language, text)
        if not normalized:
            return False

        if language == "zh":
            return any(normalized.startswith(token) for token in FILLER_TOKENS["zh"])

        words = normalized.split()
        return bool(words and words[0] in FILLER_TOKENS["en"])

    def _count_fillers(self, language: LanguageOption, text: str) -> int:
        if language == "zh":
            return sum(text.count(token) for token in FILLER_TOKENS["zh"])

        words = re.findall(r"[a-zA-Z']+", text.lower())
        return sum(1 for word in words if word in FILLER_TOKENS["en"])

    def _count_units(self, language: LanguageOption, text: str) -> int:
        if language == "zh":
            return len(re.sub(r"[\s,.!?，。！？、…:：;；\"'“”‘’（）()\-\u3000]+", "", text))

        return len(re.findall(r"[a-zA-Z']+", text.lower()))

    def _normalize(self, language: LanguageOption, text: str) -> str:
        if language == "zh":
            return re.sub(r"[\s,.!?，。！？、…:：;；\"'“”‘’（）()\-\u3000]+", "", text)

        return " ".join(re.findall(r"[a-zA-Z']+", text.lower()))

    @staticmethod
    def _text(language: LanguageOption, zh: str, en: str) -> str:
        return en if language == "en" else zh
