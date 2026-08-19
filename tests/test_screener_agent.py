from __future__ import annotations

import json
import unittest

from paper_agents.agents.screener import ScreenerAgent
from paper_agents.providers.base import ChatMessage, ModelResponse
from paper_agents.schemas import CandidatePaper, DocumentAccess, PaperMetadata


class FakeProvider:
    model_name = "fake-model"

    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[list[ChatMessage]] = []

    def complete(self, messages: list[ChatMessage]) -> ModelResponse:
        self.calls.append(messages)
        return ModelResponse(content=json.dumps(self.payload), model=self.model_name)


def candidate(paper_id: str, abstract: str | None) -> CandidatePaper:
    return CandidatePaper(
        paper=PaperMetadata(
            paper_id=paper_id,
            title="GNSS multipath study",
            authors=["A. Author"],
            year=2025,
            venue="Example Journal",
            doi=f"10.0000/{paper_id}",
            document_access=(
                DocumentAccess.ABSTRACT_ONLY if abstract else DocumentAccess.UNAVAILABLE
            ),
        ),
        abstract=abstract,
        retrieval_source="test",
        retrieval_query="GNSS",
    )


class ScreenerAgentTests(unittest.TestCase):
    def test_screener_covers_every_candidate(self) -> None:
        items = [candidate("p1", "Directly studies GNSS multipath."), candidate("p2", None)]
        provider = FakeProvider(
            {
                "results": [
                    {
                        "paper_id": "p1",
                        "decision": "include",
                        "relevance": 5,
                        "scientific_quality": 3,
                        "novelty": 3,
                        "reason": "Direct match.",
                        "needs_full_text": True,
                    },
                    {
                        "paper_id": "p2",
                        "decision": "review",
                        "relevance": 3,
                        "scientific_quality": 0,
                        "novelty": 0,
                        "reason": "No abstract.",
                        "needs_full_text": True,
                    },
                ]
            }
        )

        result = ScreenerAgent(provider).screen("GNSS multipath", items)

        self.assertEqual(len(result.results), 2)
        self.assertEqual(result.results[1].decision.value, "review")
