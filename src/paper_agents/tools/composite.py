"""Merge multiple academic retrievers into one workflow-compatible source."""

from __future__ import annotations

from typing import Protocol

from paper_agents.schemas import CandidatePaper
from paper_agents.tools.crossref import RetrievalError
from paper_agents.tools.deduplication import deduplicate_candidates


class RetrieverLike(Protocol):
    def search(self, query: str, *, rows: int, from_year: int | None,
               until_year: int | None) -> list[CandidatePaper]: ...


class CompositeRetriever:
    def __init__(self, retrievers: list[RetrieverLike]) -> None:
        if not retrievers:
            raise ValueError("至少需要一个论文检索源")
        self.retrievers = retrievers

    def search(self, query: str, *, rows: int, from_year: int | None,
               until_year: int | None) -> list[CandidatePaper]:
        collected: list[CandidatePaper] = []
        errors: list[str] = []
        for retriever in self.retrievers:
            try:
                collected.extend(retriever.search(
                    query, rows=rows, from_year=from_year, until_year=until_year
                ))
            except RetrievalError as exc:
                errors.append(str(exc))
        unique, _ = deduplicate_candidates(collected)
        unique.sort(key=lambda item: item.retrieval_score or 0, reverse=True)
        if not unique and errors:
            raise RetrievalError("；".join(errors))
        return unique[:rows]

    def hydrate(self, candidate: CandidatePaper) -> CandidatePaper:
        current = candidate
        for retriever in self.retrievers:
            hydrate = getattr(retriever, "hydrate", None)
            if callable(hydrate):
                current = hydrate(current)
                if current.full_text:
                    break
        return current
