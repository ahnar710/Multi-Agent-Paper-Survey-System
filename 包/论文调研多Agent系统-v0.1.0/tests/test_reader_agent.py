from __future__ import annotations

import json
import unittest
from pathlib import Path

from paper_agents.agents.reader import PaperDocument, ReaderAgent
from paper_agents.providers.base import ChatMessage, ModelResponse


ROOT = Path(__file__).parents[1]


class FakeProvider:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls: list[list[ChatMessage]] = []

    @property
    def model_name(self) -> str:
        return "fake-model"

    def complete(self, messages: list[ChatMessage]) -> ModelResponse:
        self.calls.append(messages.copy())
        return ModelResponse(
            content=self.responses[len(self.calls) - 1], model=self.model_name
        )


def load_json(name: str) -> dict:
    return json.loads((ROOT / "examples" / name).read_text(encoding="utf-8"))


class ReaderAgentTests(unittest.TestCase):
    def test_reader_returns_validated_card(self) -> None:
        document = PaperDocument.model_validate(load_json("paper_document.example.json"))
        response = load_json("research_card.example.json")
        response["paper"]["title"] = "Model tried to change the title"
        provider = FakeProvider([json.dumps(response, ensure_ascii=False)])

        card = ReaderAgent(provider).read(document)

        self.assertEqual(card.paper.title, document.paper.title)
        self.assertEqual(card.reader_agent_id, "reader-v0.1")
        self.assertEqual(card.model, "fake-model")
        self.assertEqual(len(provider.calls), 1)

    def test_reader_retries_invalid_json(self) -> None:
        document = PaperDocument.model_validate(load_json("paper_document.example.json"))
        valid_response = json.dumps(
            load_json("research_card.example.json"), ensure_ascii=False
        )
        provider = FakeProvider(["not json", valid_response])

        card = ReaderAgent(provider, max_attempts=2).read(document)

        self.assertEqual(card.paper.paper_id, "example-001")
        self.assertEqual(len(provider.calls), 2)
        self.assertIn("校验错误", provider.calls[1][-1]["content"])
