from __future__ import annotations

import json
import unittest
from pathlib import Path

from paper_agents.agents.reader import PaperDocument
from paper_agents.agents.verifier import VerifierAgent
from paper_agents.providers.base import ChatMessage, ModelResponse
from paper_agents.schemas import ResearchCard, VerificationStatus


ROOT = Path(__file__).parents[1]


class FakeProvider:
    model_name = "fake-verifier"

    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def complete(self, messages: list[ChatMessage]) -> ModelResponse:
        return ModelResponse(content=json.dumps(self.payload), model=self.model_name)


def load(name: str) -> dict:
    return json.loads((ROOT / "examples" / name).read_text(encoding="utf-8"))


class VerifierAgentTests(unittest.TestCase):
    def test_code_computes_passed_status(self) -> None:
        document = PaperDocument.model_validate(load("paper_document.example.json"))
        card = ResearchCard.model_validate(load("research_card.example.json"))
        provider = FakeProvider(
            {
                "paper_id": "ignored",
                "items": [
                    {
                        "evidence_index": 0,
                        "claim_supported": True,
                        "locator_valid": True,
                        "strength_appropriate": True,
                        "reason": "Directly supported by Table 3.",
                    }
                ],
                "status": "failed",
                "summary": "All evidence is supported.",
            }
        )

        report, verified = VerifierAgent(provider).verify(document, card)

        self.assertEqual(report.status, VerificationStatus.PASSED)
        self.assertEqual(verified.verification_status, VerificationStatus.PASSED)

    def test_code_rejects_unsupported_claim(self) -> None:
        document = PaperDocument.model_validate(load("paper_document.example.json"))
        card = ResearchCard.model_validate(load("research_card.example.json"))
        provider = FakeProvider(
            {
                "paper_id": card.paper.paper_id,
                "items": [
                    {
                        "evidence_index": 0,
                        "claim_supported": False,
                        "locator_valid": True,
                        "strength_appropriate": False,
                        "reason": "The claim is stronger than the source.",
                    }
                ],
                "status": "passed",
                "summary": "Unsupported claim.",
            }
        )

        report, _ = VerifierAgent(provider).verify(document, card)

        self.assertEqual(report.status, VerificationStatus.FAILED)
