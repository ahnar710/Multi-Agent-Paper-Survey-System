"""Deterministic DOI and normalized-title deduplication."""

from __future__ import annotations

import re
import unicodedata

from paper_agents.schemas import CandidatePaper


def normalize_title(title: str) -> str:
    """Normalize punctuation, case, and spacing without semantic guessing."""

    normalized = unicodedata.normalize("NFKC", title).casefold()
    normalized = re.sub(r"[^\w]+", " ", normalized, flags=re.UNICODE)
    return " ".join(normalized.split())


def deduplicate_candidates(
    candidates: list[CandidatePaper],
) -> tuple[list[CandidatePaper], int]:
    """Keep the first record for each DOI or exact normalized title."""

    seen_dois: set[str] = set()
    seen_titles: set[str] = set()
    unique: list[CandidatePaper] = []
    duplicate_count = 0

    for candidate in candidates:
        doi = (candidate.paper.doi or "").strip().casefold()
        title = normalize_title(candidate.paper.title)
        if (doi and doi in seen_dois) or title in seen_titles:
            duplicate_count += 1
            continue
        if doi:
            seen_dois.add(doi)
        seen_titles.add(title)
        unique.append(candidate)

    return unique, duplicate_count
