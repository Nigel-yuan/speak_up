from app.schemas import DocumentKind, DocumentPreview


class DocumentPreviewService:
    async def build_preview(
        self,
        *,
        kind: DocumentKind,
        filename: str,
        content_type: str | None,
        data: bytes,
    ) -> DocumentPreview:
        del filename, content_type, data

        if kind == "pdf":
            return DocumentPreview(kind="pdf", status="ready", message=None)

        return DocumentPreview(kind="none", status="ready", message=None)


document_preview_service = DocumentPreviewService()
