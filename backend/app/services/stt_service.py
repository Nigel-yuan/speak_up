from app.schemas import TranscriptChunk


class MockSttService:
    def acknowledge_audio_chunk(self, chunk_count: int) -> str:
        return f"mock audio chunk #{chunk_count} received"

    def build_partial_text(self, chunk: TranscriptChunk) -> str:
        text = chunk.text
        return text[: min(len(text), 18)]
