from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from paper_agents.harness import InvalidStateTransition, QualityGate, ensure_transition
from paper_agents.schemas import (
    EvidenceVerification,
    ResearchCard,
    ResearchRun,
    RunStatus,
    VerificationReport,
    VerificationStatus,
    WorkItemStatus,
)
from paper_agents.storage import ResearchStore


ROOT = Path(__file__).parents[1]


class StateMachineTests(unittest.TestCase):
    def test_allows_declared_transition(self) -> None:
        ensure_transition(RunStatus.CREATED, RunStatus.SEARCHING)

    def test_rejects_skipping_stages(self) -> None:
        with self.assertRaises(InvalidStateTransition):
            ensure_transition(RunStatus.CREATED, RunStatus.COMPLETED)


class QualityGateTests(unittest.TestCase):
    def test_abstract_card_is_accepted_but_not_counted_as_full_text(self) -> None:
        payload = json.loads(
            (ROOT / "examples" / "research_card.example.json").read_text()
        )
        payload["paper"]["document_access"] = "abstract_only"
        payload["evidence"][0]["locator"] = None
        payload["verification_status"] = "passed"
        card = ResearchCard.model_validate(payload)
        report = VerificationReport(
            paper_id=card.paper.paper_id,
            items=[
                EvidenceVerification(
                    evidence_index=0,
                    claim_supported=True,
                    locator_valid=False,
                    strength_appropriate=True,
                    reason="Supported by abstract.",
                )
            ],
            status=VerificationStatus.PASSED,
            summary="Passed at abstract level.",
        )

        result = QualityGate().evaluate(card, report)

        self.assertTrue(result.accepted)
        self.assertFalse(result.counts_toward_full_text_target)
        self.assertIn("不计入全文", result.reasons[0])


class PersistentQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = ResearchStore(Path(self.temp.name) / "runtime.db")
        self.run = ResearchRun(
            run_id="run-queue-test",
            topic_id="gnss",
            question="Test durable queue",
        )
        self.store.create_run(self.run)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_enqueue_is_idempotent_and_claim_is_exclusive(self) -> None:
        first = self.store.enqueue_work(
            self.run.run_id,
            stage="read",
            entity_id="paper-1",
            payload={"paper_id": "paper-1"},
        )
        second = self.store.enqueue_work(
            self.run.run_id,
            stage="read",
            entity_id="paper-1",
            payload={"paper_id": "paper-1"},
        )
        self.assertEqual(first.work_id, second.work_id)

        claimed = self.store.claim_work(stage="read", worker_id="worker-1")
        self.assertIsNotNone(claimed)
        assert claimed is not None
        self.assertEqual(claimed.status, WorkItemStatus.RUNNING)
        self.assertEqual(claimed.attempt, 1)
        self.assertIsNone(
            self.store.claim_work(stage="read", worker_id="worker-2")
        )

    def test_failure_retries_then_becomes_terminal(self) -> None:
        work = self.store.enqueue_work(
            self.run.run_id,
            stage="verify",
            entity_id="paper-1",
            payload={},
            max_attempts=2,
        )
        claimed = self.store.claim_work(stage="verify", worker_id="worker")
        assert claimed is not None
        retried = self.store.fail_work(claimed.work_id, "temporary")
        self.assertEqual(retried.status, WorkItemStatus.PENDING)

        claimed_again = self.store.claim_work(stage="verify", worker_id="worker")
        assert claimed_again is not None
        terminal = self.store.fail_work(claimed_again.work_id, "permanent")
        self.assertEqual(terminal.status, WorkItemStatus.FAILED)
        self.assertEqual(work.work_id, terminal.work_id)

    def test_expired_worker_lease_is_recovered(self) -> None:
        self.store.enqueue_work(
            self.run.run_id, stage="read", entity_id="paper-2", payload={}
        )
        claimed = self.store.claim_work(
            stage="read", worker_id="crashed-worker", lease_seconds=60
        )
        assert claimed is not None
        expired = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        with self.store._connect() as connection:
            connection.execute(
                "UPDATE work_items SET lease_until=? WHERE work_id=?",
                (expired, claimed.work_id),
            )

        self.assertEqual(self.store.recover_expired_leases(), 1)
        recovered = self.store.claim_work(stage="read", worker_id="new-worker")
        self.assertIsNotNone(recovered)
        assert recovered is not None
        self.assertEqual(recovered.attempt, 2)
