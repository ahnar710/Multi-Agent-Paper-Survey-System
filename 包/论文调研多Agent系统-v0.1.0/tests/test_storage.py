from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from paper_agents.schemas import ResearchRun, RunStatus
from paper_agents.storage import ResearchStore


class ResearchStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = ResearchStore(Path(self.temp_dir.name) / "research.db")
        self.run = ResearchRun(
            run_id="run-test-001",
            topic_id="gnss-multipath",
            question="How can GNSS multipath be mitigated?",
        )
        self.store.create_run(self.run)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_run_survives_new_store_instance(self) -> None:
        reopened = ResearchStore(self.store.path)
        loaded = reopened.get_run(self.run.run_id)
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded.question, self.run.question)

    def test_update_progress(self) -> None:
        self.store.update_run(self.run.run_id, status=RunStatus.SEARCHING)
        updated = self.store.update_run(
            self.run.run_id,
            status=RunStatus.SCREENING,
            candidate_count=9,
            included_count=3,
        )
        self.assertEqual(updated.status, RunStatus.SCREENING)
        self.assertEqual(updated.candidate_count, 9)
        self.assertEqual(updated.included_count, 3)

    def test_artifact_upsert(self) -> None:
        self.store.put_artifact(
            self.run.run_id, "candidate", "paper-1", {"title": "First"}
        )
        self.store.put_artifact(
            self.run.run_id, "candidate", "paper-1", {"title": "Updated"}
        )
        artifact = self.store.get_artifact(self.run.run_id, "candidate", "paper-1")
        self.assertEqual(artifact, {"title": "Updated"})
