"""Safe PDF text extraction with page markers for evidence locators."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from datetime import datetime
import hashlib

from pypdf import PdfReader

from paper_agents.schemas import CandidatePaper, DocumentAccess, PaperMetadata


class PDFExtractionError(RuntimeError):
    pass


def extract_pdf_text(source: Path | bytes, *, max_pages: int = 200) -> str:
    try:
        reader = PdfReader(BytesIO(source) if isinstance(source, bytes) else source)
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception as exc:
                raise PDFExtractionError("PDF 已加密，无法提取全文") from exc
        chunks: list[str] = []
        for page_number, page in enumerate(reader.pages[:max_pages], 1):
            text = (page.extract_text() or "").strip()
            if text:
                chunks.append(f"[Page {page_number}]\n{text}")
    except PDFExtractionError:
        raise
    except Exception as exc:
        raise PDFExtractionError(f"PDF 解析失败: {exc}") from exc
    content = "\n\n".join(chunks)
    if len(content) < 20:
        raise PDFExtractionError("PDF 没有可提取文本，可能是扫描图片版")
    return content


def candidate_from_pdf(path: Path, *, query: str) -> CandidatePaper:
    content = extract_pdf_text(path)
    reader = PdfReader(path)
    metadata = reader.metadata or {}
    title = str(metadata.get("/Title") or path.stem).strip()
    author = str(metadata.get("/Author") or "用户上传").strip()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return CandidatePaper(
        paper=PaperMetadata(
            paper_id="upload-" + digest[:16],
            title=title,
            authors=[author],
            year=datetime.now().year,
            venue="用户上传 PDF",
            external_id="sha256:" + digest,
            document_access=DocumentAccess.FULL_TEXT,
        ),
        full_text=content,
        retrieval_source="user_upload",
        retrieval_query=query,
        retrieval_score=1_000_000,
    )


class UploadedPDFRetriever:
    def __init__(self, paths: list[Path]) -> None:
        self.paths = paths

    def search(self, query: str, *, rows: int, from_year: int | None,
               until_year: int | None) -> list[CandidatePaper]:
        return [candidate_from_pdf(path, query=query) for path in self.paths]
