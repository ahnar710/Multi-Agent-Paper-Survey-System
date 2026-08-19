from __future__ import annotations

import unittest

from paper_agents.schemas import CandidatePaper
from paper_agents.tools.crossref import parse_crossref_item
from paper_agents.tools.openalex import parse_openalex_item
from paper_agents.tools.deduplication import deduplicate_candidates, normalize_title


SAMPLE_ITEM = {
    "DOI": "10.1234/GNSS.001",
    "URL": "https://doi.org/10.1234/GNSS.001",
    "title": ["GNSS Multipath Mitigation in Urban Canyons"],
    "author": [
        {"given": "Ada", "family": "Liu"},
        {"given": "Bo", "family": "Zhang"},
    ],
    "published": {"date-parts": [[2025, 6, 1]]},
    "container-title": ["Journal of Navigation Examples"],
    "abstract": "<jats:p>A robust method for urban GNSS.</jats:p>",
    "score": 12.5,
}


class RetrievalToolTests(unittest.TestCase):
    def test_parse_openalex_item_reconstructs_abstract_and_oa_url(self) -> None:
        candidate = parse_openalex_item(
            {
                "id": "https://openalex.org/W123",
                "title": "GNSS Integrity Monitoring",
                "publication_year": 2024,
                "authorships": [
                    {"author": {"display_name": "A. Researcher"}}
                ],
                "ids": {"doi": "https://doi.org/10.1000/example"},
                "abstract_inverted_index": {
                    "GNSS": [0], "integrity": [1], "monitoring": [2]
                },
                "primary_location": {
                    "landing_page_url": "https://example.org/article",
                    "pdf_url": "https://example.org/article.pdf",
                    "source": {"display_name": "Example Journal"},
                },
                "relevance_score": 9.5,
            },
            query="GNSS integrity",
        )
        self.assertIsNotNone(candidate)
        assert candidate is not None
        self.assertEqual(candidate.abstract, "GNSS integrity monitoring")
        self.assertEqual(candidate.retrieval_source, "openalex")
        self.assertEqual(str(candidate.full_text_source_url), "https://example.org/article.pdf")
    def test_parse_crossref_item(self) -> None:
        candidate = parse_crossref_item(SAMPLE_ITEM, query="GNSS multipath")
        self.assertIsNotNone(candidate)
        assert candidate is not None
        self.assertEqual(candidate.paper.doi, "10.1234/gnss.001")
        self.assertEqual(candidate.paper.year, 2025)
        self.assertEqual(candidate.paper.authors, ["Ada Liu", "Bo Zhang"])
        self.assertEqual(candidate.abstract, "A robust method for urban GNSS.")
        self.assertEqual(candidate.paper.document_access.value, "abstract_only")

    def test_title_normalization(self) -> None:
        self.assertEqual(
            normalize_title("GNSS: Multipath—Mitigation!"),
            normalize_title("gnss multipath mitigation"),
        )

    def test_deduplicate_by_doi_and_title(self) -> None:
        first = parse_crossref_item(SAMPLE_ITEM, query="GNSS")
        assert first is not None
        duplicate_payload = dict(SAMPLE_ITEM)
        duplicate_payload["DOI"] = "10.9999/different"
        duplicate_payload["title"] = ["GNSS multipath mitigation in urban canyons!"]
        duplicate = parse_crossref_item(duplicate_payload, query="GNSS")
        assert duplicate is not None

        unique, removed = deduplicate_candidates([first, duplicate])

        self.assertEqual(len(unique), 1)
        self.assertEqual(removed, 1)
