"""OpenAlex metadata and lawful open-access full-text retrieval."""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from paper_agents.schemas import CandidatePaper, DocumentAccess, PaperMetadata
from paper_agents.tools.crossref import RetrievalError
from paper_agents.tools.pdf_text import PDFExtractionError, extract_pdf_text


def _abstract(index: Any) -> str | None:
    if not isinstance(index, dict):
        return None
    positions: list[tuple[int, str]] = []
    for word, indexes in index.items():
        if isinstance(indexes, list):
            positions.extend((int(position), str(word)) for position in indexes)
    return " ".join(word for _, word in sorted(positions)) or None


def _location(item: dict[str, Any]) -> tuple[str | None, str | None]:
    for key in ("best_oa_location", "primary_location"):
        location = item.get(key)
        if isinstance(location, dict):
            pdf = location.get("pdf_url")
            landing = location.get("landing_page_url")
            if pdf or landing:
                return str(pdf) if pdf else None, str(landing) if landing else None
    return None, None


def parse_openalex_item(item: dict[str, Any], *, query: str) -> CandidatePaper | None:
    title = str(item.get("title") or "").strip()
    year = item.get("publication_year")
    openalex_id = str(item.get("id") or "").rsplit("/", 1)[-1]
    if not title or not isinstance(year, int) or not openalex_id:
        return None
    authors = [
        str(entry.get("author", {}).get("display_name"))
        for entry in item.get("authorships", [])
        if isinstance(entry, dict) and entry.get("author", {}).get("display_name")
    ] or ["作者未报告"]
    ids = item.get("ids") if isinstance(item.get("ids"), dict) else {}
    doi_url = str(ids.get("doi") or "")
    doi = doi_url.removeprefix("https://doi.org/") or None
    primary_location = item.get("primary_location") or {}
    source = primary_location.get("source") or {}
    venue = str(source.get("display_name") or "来源未报告")
    pdf_url, landing_url = _location(item)
    abstract = _abstract(item.get("abstract_inverted_index"))
    paper_id = "openalex-" + hashlib.sha1(openalex_id.encode()).hexdigest()[:16]
    return CandidatePaper(
        paper=PaperMetadata(
            paper_id=paper_id,
            title=title,
            authors=authors,
            year=year,
            venue=venue,
            doi=doi,
            external_id=openalex_id,
            source_url=landing_url or doi_url or str(item.get("id")),
            document_access=(
                DocumentAccess.ABSTRACT_ONLY if abstract else DocumentAccess.UNAVAILABLE
            ),
        ),
        abstract=abstract,
        full_text_source_url=pdf_url,
        retrieval_source="openalex",
        retrieval_query=query,
        retrieval_score=float(item.get("relevance_score") or 0),
    )


class OpenAlexClient:
    def __init__(
        self,
        *,
        email: str = "",
        fetch_full_text: bool = True,
        timeout: int = 30,
        max_pdf_bytes: int = 25_000_000,
    ) -> None:
        self.email = email
        self.fetch_full_text = fetch_full_text
        self.timeout = timeout
        self.max_pdf_bytes = max_pdf_bytes

    def _download_pdf(self, url: str) -> bytes:
        request = urllib.request.Request(url, headers={"User-Agent": "paper-agents/0.2"})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            content_type = response.headers.get("Content-Type", "").lower()
            length = int(response.headers.get("Content-Length", "0") or 0)
            if length > self.max_pdf_bytes:
                raise PDFExtractionError("开放全文 PDF 超过大小限制")
            data = response.read(self.max_pdf_bytes + 1)
            if len(data) > self.max_pdf_bytes:
                raise PDFExtractionError("开放全文 PDF 超过大小限制")
            if "pdf" not in content_type and not data.startswith(b"%PDF"):
                raise PDFExtractionError("开放地址返回的不是 PDF")
            return data

    def search(
        self,
        query: str,
        *,
        rows: int = 20,
        from_year: int | None = None,
        until_year: int | None = None,
    ) -> list[CandidatePaper]:
        filters: list[str] = []
        if from_year:
            filters.append(f"from_publication_date:{from_year}-01-01")
        if until_year:
            filters.append(f"to_publication_date:{until_year}-12-31")
        params: dict[str, str | int] = {"search": query, "per-page": min(rows, 100)}
        if filters:
            params["filter"] = ",".join(filters)
        if self.email:
            params["mailto"] = self.email
        url = "https://api.openalex.org/works?" + urllib.parse.urlencode(params)
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RetrievalError(f"OpenAlex 检索失败: {exc}") from exc

        candidates: list[CandidatePaper] = []
        for raw in payload.get("results", []):
            if not isinstance(raw, dict):
                continue
            candidate = parse_openalex_item(raw, query=query)
            if candidate is None:
                continue
            candidates.append(candidate)
        return candidates

    def hydrate(self, candidate: CandidatePaper) -> CandidatePaper:
        pdf_url = candidate.full_text_source_url
        if not self.fetch_full_text or not pdf_url or candidate.full_text:
            return candidate
        try:
            text = extract_pdf_text(self._download_pdf(str(pdf_url)))
        except (PDFExtractionError, urllib.error.URLError, TimeoutError):
            return candidate
        return candidate.model_copy(
            update={
                "full_text": text,
                "paper": candidate.paper.model_copy(
                    update={"document_access": DocumentAccess.FULL_TEXT}
                ),
            }
        )
