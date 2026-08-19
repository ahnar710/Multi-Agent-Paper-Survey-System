"""Durable concurrent runtime for per-paper Reader/Verifier work."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from uuid import uuid4

from paper_agents.agents.reader import PaperDocument, ReaderAgent
from paper_agents.agents.verifier import VerifierAgent
from paper_agents.harness.quality import QualityGate
from paper_agents.schemas import QualityGateResult, ResearchCard, WorkItemStatus
from paper_agents.storage import ResearchStore


READ_VERIFY_STAGE = "read_verify"


@dataclass(frozen=True)
class RuntimeConfig:
    max_workers: int = 4
    lease_seconds: int = 600
    max_attempts: int = 2
    retry_delay_seconds: int = 0

    def __post_init__(self) -> None:
        if self.max_workers < 1:
            raise ValueError("max_workers 必须大于 0")
        if self.lease_seconds < 1:
            raise ValueError("lease_seconds 必须大于 0")
        if self.max_attempts < 1:
            raise ValueError("max_attempts 必须大于 0")


@dataclass(frozen=True)
class RuntimeSummary:
    completed: int
    failed: int
    accepted: int
    full_text_accepted: int


class HarnessRuntime:
    """Process durable work items with bounded concurrency and retries."""

    def __init__(
        self,
        *,
        store: ResearchStore,
        reader: ReaderAgent,
        verifier: VerifierAgent,
        quality_gate: QualityGate | None = None,
        config: RuntimeConfig | None = None,
    ) -> None:
        self.store = store
        self.reader = reader
        self.verifier = verifier
        self.quality_gate = quality_gate or QualityGate()
        self.config = config or RuntimeConfig()

    def enqueue(self, run_id: str, document: PaperDocument) -> None:
        self.store.put_artifact(
            run_id,
            "document",
            document.paper.paper_id,
            document.model_dump(mode="json"),
        )
        self.store.enqueue_work(
            run_id,
            stage=READ_VERIFY_STAGE,
            entity_id=document.paper.paper_id,
            payload={"paper_id": document.paper.paper_id},
            max_attempts=self.config.max_attempts,
        )

    def _process(self, run_id: str, worker_id: str) -> None:
        while True:
            work = self.store.claim_work(
                stage=READ_VERIFY_STAGE,
                worker_id=worker_id,
                lease_seconds=self.config.lease_seconds,
                run_id=run_id,
            )
            if work is None:
                return
            try:
                document_payload = self.store.get_artifact(
                    run_id, "document", work.entity_id
                )
                if document_payload is None:
                    raise RuntimeError("队列对应的文档不存在")
                document = PaperDocument.model_validate(document_payload)

                card_payload = self.store.get_artifact(
                    run_id, "research_card", work.entity_id
                )
                card = (
                    ResearchCard.model_validate(card_payload)
                    if card_payload is not None
                    else self.reader.read(document)
                )
                self.store.put_artifact(
                    run_id,
                    "research_card",
                    work.entity_id,
                    card.model_dump(mode="json"),
                )

                report, verified_card = self.verifier.verify(document, card)
                gate = self.quality_gate.evaluate(verified_card, report)
                self.store.put_artifact(
                    run_id,
                    "verification",
                    work.entity_id,
                    report.model_dump(mode="json"),
                )
                self.store.put_artifact(
                    run_id,
                    "quality_gate",
                    work.entity_id,
                    gate.model_dump(mode="json"),
                )
                if gate.accepted:
                    self.store.put_artifact(
                        run_id,
                        "verified_card",
                        work.entity_id,
                        verified_card.model_dump(mode="json"),
                    )
                self.store.complete_work(work.work_id)
            except Exception as exc:
                updated = self.store.fail_work(
                    work.work_id,
                    str(exc),
                    retry_delay_seconds=self.config.retry_delay_seconds,
                )
                if updated.status == WorkItemStatus.FAILED:
                    self.store.put_artifact(
                        run_id,
                        "failure",
                        work.entity_id,
                        {
                            "stage": READ_VERIFY_STAGE,
                            "reason": str(exc),
                            "attempts": updated.attempt,
                        },
                    )

    def run_until_idle(self, run_id: str) -> RuntimeSummary:
        self.store.recover_expired_leases()
        with ThreadPoolExecutor(
            max_workers=self.config.max_workers,
            thread_name_prefix="paper-runtime",
        ) as pool:
            futures = [
                pool.submit(self._process, run_id, f"worker-{uuid4().hex[:8]}")
                for _ in range(self.config.max_workers)
            ]
            for future in futures:
                future.result()

        work = self.store.list_work(run_id, READ_VERIFY_STAGE)
        gates = [
            QualityGateResult.model_validate(payload)
            for payload in self.store.list_artifacts(run_id, "quality_gate")
        ]
        return RuntimeSummary(
            completed=sum(item.status == WorkItemStatus.COMPLETED for item in work),
            failed=sum(item.status == WorkItemStatus.FAILED for item in work),
            accepted=sum(gate.accepted for gate in gates),
            full_text_accepted=sum(gate.counts_toward_full_text_target for gate in gates),
        )
