"""Deterministic external tools used by agents and workflows."""

from paper_agents.tools.crossref import CrossrefClient, RetrievalError
from paper_agents.tools.deduplication import deduplicate_candidates, normalize_title
from paper_agents.tools.composite import CompositeRetriever
from paper_agents.tools.openalex import OpenAlexClient
from paper_agents.tools.pdf_text import (
    PDFExtractionError,
    UploadedPDFRetriever,
    candidate_from_pdf,
    extract_pdf_text,
)

__all__ = [
    "CrossrefClient",
    "CompositeRetriever",
    "OpenAlexClient",
    "PDFExtractionError",
    "UploadedPDFRetriever",
    "candidate_from_pdf",
    "RetrievalError",
    "deduplicate_candidates",
    "extract_pdf_text",
    "normalize_title",
]
