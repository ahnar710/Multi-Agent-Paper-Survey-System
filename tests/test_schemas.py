from __future__ import annotations

import json
import unittest
from pathlib import Path

from pydantic import ValidationError

from paper_agents.schemas import ResearchCard


EXAMPLE = Path(__file__).parents[1] / "examples" / "research_card.example.json"


def load_example() -> dict:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


class ResearchCardTests(unittest.TestCase):
    def test_example_card_is_valid(self) -> None:
        card = ResearchCard.model_validate(load_example())
        self.assertEqual(card.paper.paper_id, "example-001")
        self.assertEqual(len(card.evidence), 1)

    def test_paper_requires_stable_identifier(self) -> None:
        payload = load_example()
        payload["paper"]["doi"] = None
        payload["paper"]["external_id"] = None
        payload["paper"]["source_url"] = None

        with self.assertRaisesRegex(ValidationError, "至少需要一项"):
            ResearchCard.model_validate(payload)

    def test_full_text_evidence_requires_locator(self) -> None:
        payload = load_example()
        payload["evidence"][0]["locator"] = None

        with self.assertRaisesRegex(ValidationError, "每条证据"):
            ResearchCard.model_validate(payload)

    def test_full_text_evidence_rejects_placeholder_locator(self) -> None:
        payload = load_example()
        payload["evidence"][0]["locator"] = "未指明章节"

        with self.assertRaisesRegex(ValidationError, "每条证据"):
            ResearchCard.model_validate(payload)


if __name__ == "__main__":
    unittest.main()
