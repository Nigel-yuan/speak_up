from dataclasses import dataclass

from app.schemas import TrainingMode, TranscriptChunk


@dataclass(frozen=True)
class ContentSource:
    source_type: str
    title: str
    raw_text: str


@dataclass(frozen=True)
class ReferenceBundle:
    training_mode: TrainingMode
    document_sources: list[ContentSource]
    spoken_transcript_sources: list[ContentSource]
    manual_text_sources: list[ContentSource]

    @property
    def combined_text(self) -> str:
        sections: list[str] = []
        for source in [
            *self.document_sources,
            *self.spoken_transcript_sources,
            *self.manual_text_sources,
        ]:
            sections.append(f"[{source.source_type}] {source.title}\n{source.raw_text}")
        return "\n\n".join(section for section in sections if section.strip())


class ContentSourceService:
    def build_bundle(
        self,
        *,
        training_mode: TrainingMode,
        document_name: str | None,
        document_text: str | None,
        manual_text: str | None,
        transcript_chunks: list[TranscriptChunk],
    ) -> ReferenceBundle:
        document_sources: list[ContentSource] = []
        spoken_transcript_sources: list[ContentSource] = []
        manual_text_sources: list[ContentSource] = []

        normalized_document = self._normalize(document_text)
        if normalized_document:
            document_sources.append(
                ContentSource(
                    source_type="document",
                    title=document_name or "Current document",
                    raw_text=normalized_document,
                )
            )

        transcript_text = self._build_transcript_text(transcript_chunks)
        if transcript_text:
            spoken_transcript_sources.append(
                ContentSource(
                    source_type="spoken_transcript",
                    title="Spoken transcript",
                    raw_text=transcript_text,
                )
            )

        normalized_manual = self._normalize(manual_text)
        if normalized_manual:
            manual_text_sources.append(
                ContentSource(
                    source_type="manual_text",
                    title="Manual context",
                    raw_text=normalized_manual,
                )
            )

        return ReferenceBundle(
            training_mode=training_mode,
            document_sources=document_sources,
            spoken_transcript_sources=spoken_transcript_sources,
            manual_text_sources=manual_text_sources,
        )

    @staticmethod
    def _build_transcript_text(chunks: list[TranscriptChunk]) -> str:
        user_lines = [chunk.text.strip() for chunk in chunks if chunk.speaker == "user" and chunk.text.strip()]
        if not user_lines:
            return ""

        joined = "\n".join(f"- {line}" for line in user_lines[-18:])
        return joined[:6000]

    @staticmethod
    def _normalize(text: str | None) -> str:
        if not text:
            return ""
        normalized = text.strip()
        if not normalized:
            return ""
        return normalized[:10000]
