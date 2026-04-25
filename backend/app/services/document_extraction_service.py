import logging
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from time import monotonic
from typing import Literal


DocumentKind = Literal["pdf", "md"]
logger = logging.getLogger("speak_up.session")


@dataclass(frozen=True)
class ExtractedDocument:
    kind: DocumentKind
    text: str


class DocumentExtractionError(RuntimeError):
    pass


class DocumentExtractionService:
    TARGET_CONTEXT_CHARS = 2000
    MAX_PDF_PAGES = 6

    def extract(self, *, filename: str, content_type: str | None, data: bytes) -> ExtractedDocument:
        suffix = Path(filename).suffix.lower()
        normalized_type = (content_type or "").lower()

        if suffix in {".md", ".markdown"} or normalized_type in {"text/markdown", "text/plain"}:
            started_at = monotonic()
            raw_text = self._normalize_text(data.decode("utf-8", errors="ignore"))
            compressed = self._compress_text(raw_text)
            logger.info(
                "document.extract.fast_md.done bytes=%s raw_chars=%s compressed_chars=%s target_chars=%s elapsed_ms=%s",
                len(data),
                len(raw_text),
                len(compressed),
                self.TARGET_CONTEXT_CHARS,
                int((monotonic() - started_at) * 1000),
            )
            return ExtractedDocument(
                kind="md",
                text=compressed,
            )

        if suffix == ".pdf" or normalized_type == "application/pdf":
            return ExtractedDocument(kind="pdf", text=self._extract_pdf_text(data))

        raise DocumentExtractionError("当前只支持 PDF 和 Markdown 文档。")

    def _extract_pdf_text(self, data: bytes) -> str:
        try:
            from pypdf import PdfReader
        except ImportError as error:
            raise DocumentExtractionError("PDF 文本抽取依赖 pypdf 未安装，请先安装后端依赖。") from error

        try:
            started_at = monotonic()
            reader = PdfReader(BytesIO(data))
            page_texts: list[str] = []
            total_pages = len(reader.pages)
            pages_scanned = 0
            page_limited = total_pages > self.MAX_PDF_PAGES

            for page_index, page in enumerate(reader.pages[: self.MAX_PDF_PAGES], start=1):
                pages_scanned = page_index
                text = page.extract_text() or ""
                normalized = self._normalize_text(text)
                if normalized:
                    page_texts.append(normalized)

            raw_text = self._normalize_text("\n\n".join(page_texts))
            result = self._compress_text(raw_text)
            logger.info(
                "document.extract.fast_pdf.done bytes=%s pages_scanned=%s total_pages=%s raw_chars=%s compressed_chars=%s page_limited=%s max_pages=%s target_chars=%s elapsed_ms=%s",
                len(data),
                pages_scanned,
                total_pages,
                len(raw_text),
                len(result),
                page_limited,
                self.MAX_PDF_PAGES,
                self.TARGET_CONTEXT_CHARS,
                int((monotonic() - started_at) * 1000),
            )
            return result
        except Exception as error:
            raise DocumentExtractionError(f"PDF 文本抽取失败：{error}") from error

    def _normalize_text(self, text: str) -> str:
        lines = [line.strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
        normalized_lines: list[str] = []
        previous_blank = False
        for line in lines:
            if not line:
                if not previous_blank:
                    normalized_lines.append("")
                previous_blank = True
                continue
            normalized_lines.append(line)
            previous_blank = False
        return "\n".join(normalized_lines).strip()

    def _compress_text(self, text: str) -> str:
        normalized = self._normalize_text(text)
        if not normalized or len(normalized) <= self.TARGET_CONTEXT_CHARS:
            return normalized

        blocks = self._split_blocks(normalized)
        selected: list[str] = []
        selected_chars = 0

        for block in blocks:
            candidates = self._compress_block(block)
            for candidate in candidates:
                if not candidate:
                    continue
                candidate_len = len(candidate) + (2 if selected else 0)
                if selected_chars + candidate_len > self.TARGET_CONTEXT_CHARS:
                    continue
                selected.append(candidate)
                selected_chars += candidate_len

        if not selected:
            selected = self._fallback_sentences(normalized)

        return self._normalize_text("\n\n".join(selected))

    def _split_blocks(self, text: str) -> list[str]:
        return [block.strip() for block in text.split("\n\n") if block.strip()]

    def _compress_block(self, block: str) -> list[str]:
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        if not lines:
            return []

        first_line = lines[0]
        if first_line.startswith("#"):
            return [
                first_line,
                *self._first_list_items(lines[1:], limit=3),
                *self._first_sentences("\n".join(lines[1:]), limit=2),
            ]

        if all(self._is_list_like(line) for line in lines):
            return self._first_list_items(lines, limit=4)

        block_text = " ".join(lines)
        return self._first_sentences(block_text, limit=2)

    def _first_list_items(self, lines: list[str], *, limit: int) -> list[str]:
        items = [line for line in lines if self._is_list_like(line)]
        return items[:limit]

    def _first_sentences(self, text: str, *, limit: int) -> list[str]:
        sentences = self._split_sentences(text)
        return sentences[:limit]

    def _fallback_sentences(self, text: str) -> list[str]:
        selected: list[str] = []
        selected_chars = 0
        for sentence in self._split_sentences(text):
            sentence_len = len(sentence) + (2 if selected else 0)
            if selected_chars + sentence_len > self.TARGET_CONTEXT_CHARS:
                continue
            selected.append(sentence)
            selected_chars += sentence_len
            if selected_chars >= self.TARGET_CONTEXT_CHARS:
                break
        if not selected:
            sentences = self._split_sentences(text)
            return sentences[:1]
        return selected

    def _split_sentences(self, text: str) -> list[str]:
        separators = {"。", "！", "？", "；", ";", ".", "!", "?"}
        sentences: list[str] = []
        current: list[str] = []
        for char in text.replace("\n", " "):
            current.append(char)
            if char in separators:
                sentence = "".join(current).strip()
                if sentence:
                    sentences.append(sentence)
                current = []
        tail = "".join(current).strip()
        if tail:
            sentences.append(tail)
        return sentences

    @staticmethod
    def _is_list_like(line: str) -> bool:
        stripped = line.lstrip()
        if stripped.startswith(("- ", "* ", "+ ", "> ", "|")):
            return True
        if len(stripped) > 2 and stripped[0].isdigit() and stripped[1] in {".", "、", ")"}:
            return True
        return False


document_extraction_service = DocumentExtractionService()
