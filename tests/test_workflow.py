from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from paper_agents.harness import ResearchWorkflow
from paper_agents.schemas import (
    CandidatePaper,
    Confidence,
    DocumentAccess,
    Evidence,
    EvidenceVerification,
    PaperMetadata,
    ResearchCard,
    RunStatus,
    ScreeningBatch,
    ScreeningDecision,
    ScreeningResult,
    VerificationReport,
    VerificationStatus,
    SynthesisReport,
    ReportCitation,
)
from paper_agents.storage import ResearchStore


def make_candidate() -> CandidatePaper:
    return CandidatePaper(
        paper=PaperMetadata(
            paper_id="paper-1",
            title="GNSS Multipath Mitigation",
            authors=["A. Author"],
            year=2025,
            venue="Example Journal",
            doi="10.0000/paper-1",
            document_access=DocumentAccess.ABSTRACT_ONLY,
        ),
        abstract="This study evaluates a GNSS multipath mitigation method in an urban route.",
        retrieval_source="fake",
        retrieval_query="GNSS multipath",
    )


class FakeRetriever:
    def search(self, query, *, rows, from_year, until_year):
        return [make_candidate(), make_candidate()]


class FakeScreener:
    def screen(self, question, candidates):
        return ScreeningBatch(
            results=[
                ScreeningResult(
                    paper_id="paper-1",
                    decision=ScreeningDecision.INCLUDE,
                    relevance=5,
                    scientific_quality=3,
                    novelty=3,
                    reason="Directly relevant.",
                    needs_full_text=True,
                )
            ]
        )


class FakeReader:
    def read(self, document):
        return ResearchCard(
            paper=document.paper,
            gnss_domain=["multipath"],
            product_relevance=4,
            scientific_quality=3,
            novelty=3,
            screening_decision=ScreeningDecision.INCLUDE,
            screening_reason="Direct match.",
            problem="Urban GNSS multipath.",
            method="Mitigation method.",
            data_and_experiment="One urban route.",
            key_findings=["Reported improvement."],
            limitations=["Abstract only."],
            applicable_conditions=["Urban route."],
            comparison_baselines=["Baseline."],
            technology_readiness="Research prototype.",
            product_implications=[],
            opportunities=[],
            risks=[],
            recommended_actions=[],
            evidence=[
                Evidence(
                    claim="Reported improvement.",
                    evidence="The abstract reports improvement.",
                    locator=None,
                    confidence=Confidence.MEDIUM,
                )
            ],
            reader_agent_id="fake-reader",
            model="fake-model",
            prompt_version="test",
            quality_score=3,
        )


class FakeVerifier:
    def verify(self, document, card):
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
            summary="Abstract-level verification passed.",
        )
        return report, card.model_copy(
            update={"verification_status": VerificationStatus.PASSED}
        )


class FakeSynthesizer:
    def synthesize(self, question, cards):
        card = cards[0]
        return SynthesisReport(
            title="GNSS Multipath Research Report",
            research_question=question,
            executive_summary="One abstract-level paper was verified.",
            evidence_scope="One abstract-only research card.",
            main_themes=["Multipath mitigation"],
            consensus_findings=[],
            conflicting_findings=[],
            research_gaps=["Full text is required."],
            product_implications=["Prototype evaluation is needed."],
            recommended_actions=["Obtain the full paper."],
            limitations=["Single abstract-level source."],
            citations=[
                ReportCitation(
                    paper_id=card.paper.paper_id,
                    title=card.paper.title,
                    doi=card.paper.doi,
                )
            ],
        )


class FailOnceSynthesizer(FakeSynthesizer):
    def __init__(self):
        self.calls = 0

    def synthesize(self, question, cards):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("temporary synthesis failure")
        return super().synthesize(question, cards)


class WorkflowTests(unittest.TestCase):
    def test_one_click_workflow_persists_every_stage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "research.db")
            workflow = ResearchWorkflow(
                store=store,
                retriever=FakeRetriever(),
                screener=FakeScreener(),
                reader=FakeReader(),
                verifier=FakeVerifier(),
                synthesizer=FakeSynthesizer(),
                report_directory=Path(directory) / "reports",
            )

            run = workflow.run(
                topic_id="gnss",
                question="How is multipath mitigated?",
                search_query="GNSS multipath",
                rows=10,
                from_year=2021,
                until_year=2026,
            )

            self.assertEqual(run.status, RunStatus.COMPLETED)
            self.assertEqual(run.candidate_count, 1)
            self.assertEqual(run.included_count, 1)
            self.assertEqual(run.verified_count, 1)
            self.assertEqual(len(store.list_artifacts(run.run_id, "candidate")), 1)
            self.assertEqual(len(store.list_artifacts(run.run_id, "verified_card")), 1)
            self.assertEqual(len(store.list_artifacts(run.run_id, "synthesis_report")), 1)

            resumed = workflow.resume(run.run_id)
            self.assertEqual(resumed.verified_count, 1)
            self.assertEqual(len(store.list_artifacts(run.run_id, "verification")), 1)
            workflow.close()

    def test_langgraph_resumes_failed_node_from_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "research.db")
            workflow = ResearchWorkflow(
                store=store,
                retriever=FakeRetriever(),
                screener=FakeScreener(),
                reader=FakeReader(),
                verifier=FakeVerifier(),
                synthesizer=FailOnceSynthesizer(),
                report_directory=Path(directory) / "reports",
            )
            with self.assertRaisesRegex(RuntimeError, "temporary synthesis failure"):
                workflow.run(
                    topic_id="gnss",
                    question="How is multipath mitigated?",
                    search_query="GNSS multipath",
                )
            interrupted = store.list_runs()[0]
            self.assertEqual(interrupted.status, RunStatus.SYNTHESIZING)
            workflow.close()

            restarted_workflow = ResearchWorkflow(
                store=ResearchStore(Path(directory) / "research.db"),
                retriever=FakeRetriever(),
                screener=FakeScreener(),
                reader=FakeReader(),
                verifier=FakeVerifier(),
                synthesizer=FakeSynthesizer(),
                report_directory=Path(directory) / "reports",
            )
            resumed = restarted_workflow.resume(interrupted.run_id)
            self.assertEqual(resumed.status, RunStatus.COMPLETED)
            self.assertEqual(resumed.candidate_count, 1)
            self.assertEqual(resumed.verified_count, 1)
            restarted_workflow.close()
