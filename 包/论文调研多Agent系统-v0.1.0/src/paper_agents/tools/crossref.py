"""Crossref REST API retrieval tool."""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from paper_agents.schemas import CandidatePaper, DocumentAccess, PaperMetadata


class RetrievalError(RuntimeError):
    """Raised when an academic metadata source cannot be queried."""


def _first_text(value: Any, default: str = "") -> str:
    if isinstance(value, list) and value:
        return str(value[0]).strip()
    if isinstance(value, str):
        return value.strip()
    return default


def _published_year(item: dict[str, Any]) -> int | None:
    for field in ("published", "published-online", "published-print", "issued"):
        parts = item.get(field, {}).get("date-parts", [])
        if parts and parts[0]:
            try:
                return int(parts[0][0])
            except (TypeError, ValueError, IndexError):
                continue
    return None


def _authors(item: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for author in item.get("author", []):
        if not isinstance(author, dict):
            continue
        name = " ".join(
            part for part in (author.get("given", ""), author.get("family", "")) if part
        ).strip()
        if name:
            result.append(name)
    return result or ["作者未报告"]


def _clean_abstract(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    without_tags = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(without_tags)).strip() or None


def _paper_id(doi: str | None, title: str) -> str:
    identity = (doi or title).casefold().encode("utf-8")
    return "crossref-" + hashlib.sha1(identity).hexdigest()[:16]


def parse_crossref_item(item: dict[str, Any], *, query: str) -> CandidatePaper | None:
    """Convert one loose Crossref record into our strict internal contract."""

    title = _first_text(item.get("title"))
    year = _published_year(item)
    if not title or year is None:
        return None

    doi = str(item.get("DOI", "")).strip().lower() or None
    source_url = str(item.get("URL", "")).strip() or (
        f"https://doi.org/{doi}" if doi else None
    )
    if not source_url:
        return None

    abstract = _clean_abstract(item.get("abstract"))
    metadata = PaperMetadata(
        paper_id=_paper_id(doi, title),
        title=title,
        authors=_authors(item),
        year=year,
        venue=_first_text(item.get("container-title"), "来源未报告"),
        doi=doi,
        external_id=None,
        source_url=source_url,
        document_access=(
            DocumentAccess.ABSTRACT_ONLY if abstract else DocumentAccess.UNAVAILABLE
        ),
    )
    score = item.get("score")
    return CandidatePaper(
        paper=metadata,
        abstract=abstract,
        retrieval_source="crossref",
        retrieval_query=query,
        retrieval_score=float(score) if isinstance(score, (int, float)) else None,
    )


class CrossrefClient:
    def __init__(
        self,
        *,
        base_url: str = "https://api.crossref.org/v1",
        mailto: str | None = None,
        timeout: int = 30,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.mailto = mailto or os.getenv("CROSSREF_MAILTO", "")
        self.timeout = timeout

    def search(
        self,
        query: str,
        *,
        rows: int = 20,
        from_year: int | None = None,
        until_year: int | None = None,
    ) -> list[CandidatePaper]:
        if not query.strip():
            raise ValueError("检索词不能为空")
        if not 1 <= rows <= 100:
            raise ValueError("MVP 单次检索 rows 必须在 1 到 100 之间")

        params: dict[str, str | int] = {
            "query.bibliographic": query,
            "rows": rows,
        }
        filters: list[str] = []
        if from_year is not None:
            filters.append(f"from-pub-date:{from_year}-01-01")
        if until_year is not None:
            filters.append(f"until-pub-date:{until_year}-12-31")
        if filters:
            params["filter"] = ",".join(filters)
        if self.mailto:
            params["mailto"] = self.mailto

        url = f"{self.base_url}/works?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "paper-research-agents/0.1 (mailto:" + (self.mailto or "unset") + ")",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RetrievalError(f"Crossref HTTP {exc.code}: {detail[:500]}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RetrievalError(f"无法连接 Crossref: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise RetrievalError("Crossref 未返回有效 JSON") from exc

        try:
            items = payload["message"]["items"]
        except (KeyError, TypeError) as exc:
            raise RetrievalError(f"Crossref 返回结构异常: {payload}") from exc

        candidates: list[CandidatePaper] = []
        for item in items:
            if isinstance(item, dict):
                candidate = parse_crossref_item(item, query=query)
                if candidate is not None:
                    candidates.append(candidate)
        return candidates
