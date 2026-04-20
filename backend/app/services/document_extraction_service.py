from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Literal


DocumentKind = Literal["pdf", "md"]


@dataclass(frozen=True)
class ExtractedDocument:
    kind: DocumentKind
    text: str


class DocumentExtractionError(RuntimeError):
    pass


class DocumentExtractionService:
    MAX_TEXT_CHARS = 30000

    def extract(self, *, filename: str, content_type: str | None, data: bytes) -> ExtractedDocument:
        suffix = Path(filename).suffix.lower()
        normalized_type = (content_type or "").lower()

        if suffix in {".md", ".markdown"} or normalized_type in {"text/markdown", "text/plain"}:
            return ExtractedDocument(
                kind="md",
                text=self._normalize_text(data.decode("utf-8", errors="ignore")),
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
            reader = PdfReader(BytesIO(data))
            page_texts: list[str] = []
            for page_index, page in enumerate(reader.pages, start=1):
                text = page.extract_text() or ""
                normalized = self._normalize_text(text)
                if normalized:
                    page_texts.append(f"## Page {page_index}\n{normalized}")
            return self._normalize_text("\n\n".join(page_texts))
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
        return "\n".join(normalized_lines).strip()[: self.MAX_TEXT_CHARS]


document_extraction_service = DocumentExtractionService()
