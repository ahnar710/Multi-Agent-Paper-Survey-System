"""LangGraph orchestration for the durable literature-research workflow."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Protocol, TypedDict
from uuid import uuid4

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from paper_agents.agents.reader import PaperDocument, ReaderAgent
from paper_agents.agents.screener import ScreenerAgent
from paper_agents.agents.synthesizer import SynthesizerAgent, render_markdown
from paper_agents.agents.verifier import VerifierAgent
from paper_agents.harness.runtime import HarnessRuntime, RuntimeConfig
from paper_agents.schemas import (
    CandidatePaper,
    ResearchCard,
    ResearchRun,
    RunStatus,
    SynthesisReport,
)
from paper_agents.schemas import ScreeningDecision
from paper_agents.storage import ResearchStore
from paper_agents.tools import deduplicate_candidates


class Retriever(Protocol):
    def search(
        self,
        query: str,
        *,
        rows: int,
        from_year: int | None,
        until_year: int | None,
    ) -> list[CandidatePaper]: ...


class WorkflowState(TypedDict, total=False):
    run_id: str
    question: str
    search_query: str
    rows: int
    from_year: int | None
    until_year: int | None
    candidate_ids: list[str]
    included_ids: list[str]
    verified_count: int
    failed_count: int


class ResearchWorkflow:
    """Top-level LangGraph plus the durable per-paper HarnessRuntime."""

    def __init__(
        self,
        *,
        store: ResearchStore,
        retriever: Retriever,
        screener: ScreenerAgent,
        reader: ReaderAgent,
        verifier: VerifierAgent,
        synthesizer: SynthesizerAgent,
        report_directory: Path = Path("data/reports"),
        runtime_config: RuntimeConfig | None = None,
    ) -> None:
        self.store = store
        self.retriever = retriever
        self.screener = screener
        self.synthesizer = synthesizer
        self.report_directory = report_directory
        self.runtime = HarnessRuntime(
            store=store,
            reader=reader,
            verifier=verifier,
            config=runtime_config,
        )
        checkpoint_path = store.path.with_name(
            f"{store.path.stem}_langgraph_checkpoints.db"
        )
        self._checkpoint_connection = sqlite3.connect(
            checkpoint_path, check_same_thread=False
        )
        self.checkpointer = SqliteSaver(self._checkpoint_connection)
        self.checkpointer.setup()
        self.graph = self._build_graph()

    def close(self) -> None:
        connection = getattr(self, "_checkpoint_connection", None)
        if connection is not None:
            connection.close()
            self._checkpoint_connection = None

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def _build_graph(self):
        builder = StateGraph(WorkflowState)
        builder.add_node("search", self._search)
        builder.add_node("screen", self._screen)
        builder.add_node("read_and_verify", self._read_and_verify)
        builder.add_node("synthesize", self._synthesize)
        builder.add_edge(START, "search")
        builder.add_edge("search", "screen")
        builder.add_edge("screen", "read_and_verify")
        builder.add_edge("read_and_verify", "synthesize")
        builder.add_edge("synthesize", END)
        return builder.compile(checkpointer=self.checkpointer)

    def _search(self, state: WorkflowState) -> dict:
        run_id = state["run_id"]
        self.store.update_run(run_id, status=RunStatus.SEARCHING)
        raw = self.retriever.search(
            state["search_query"],
            rows=state["rows"],
            from_year=state.get("from_year"),
            until_year=state.get("until_year"),
        )
        candidates, _ = deduplicate_candidates(raw)
        for candidate in candidates:
            self.store.put_artifact(
                run_id, "candidate", candidate.paper.paper_id,
                candidate.model_dump(mode="json"),
            )
        self.store.update_run(
            run_id, status=RunStatus.SCREENING, candidate_count=len(candidates)
        )
        return {"candidate_ids": [item.paper.paper_id for item in candidates]}

    def _screen(self, state: WorkflowState) -> dict:
        run_id = state["run_id"]
        candidates = [
            CandidatePaper.model_validate(payload)
            for payload in self.store.list_artifacts(run_id, "candidate")
        ]
        batch = self.screener.screen(state["question"], candidates)
        for result in batch.results:
            self.store.put_artifact(
                run_id, "screening", result.paper_id, result.model_dump(mode="json")
            )
        included = [
            item.paper_id for item in batch.results
            if item.decision == ScreeningDecision.INCLUDE
        ]
        self.store.update_run(
            run_id, status=RunStatus.READING, included_count=len(included)
        )
        return {"included_ids": included}

    def _read_and_verify(self, state: WorkflowState) -> dict:
        run_id = state["run_id"]
        candidates = {
            item.paper.paper_id: item
            for item in (
                CandidatePaper.model_validate(payload)
                for payload in self.store.list_artifacts(run_id, "candidate")
            )
        }
        included_ids = state.get("included_ids", [])
        hydrate = getattr(self.retriever, "hydrate", None)
        if callable(hydrate):
            with ThreadPoolExecutor(
                max_workers=self.runtime.config.max_workers,
                thread_name_prefix="full-text",
            ) as pool:
                hydrated = list(pool.map(hydrate, (candidates[item] for item in included_ids)))
            for candidate in hydrated:
                candidates[candidate.paper.paper_id] = candidate
                self.store.put_artifact(
                    run_id, "candidate", candidate.paper.paper_id,
                    candidate.model_dump(mode="json"),
                )

        unavailable = 0
        for paper_id in included_ids:
            candidate = candidates[paper_id]
            content = candidate.full_text or candidate.abstract
            if not content:
                unavailable += 1
                self.store.put_artifact(
                    run_id, "failure", paper_id,
                    {"stage": "reading", "reason": "入选论文没有可用摘要或全文"},
                )
                continue
            self.runtime.enqueue(
                run_id, PaperDocument(paper=candidate.paper, content=content)
            )

        self.store.update_run(run_id, status=RunStatus.VERIFYING)
        summary = self.runtime.run_until_idle(run_id)
        failed = unavailable + summary.failed + (summary.completed - summary.accepted)
        self.store.update_run(
            run_id, verified_count=summary.accepted, failed_count=failed
        )
        return {"verified_count": summary.accepted, "failed_count": failed}

    def _synthesize(self, state: WorkflowState) -> dict:
        run_id = state["run_id"]
        self.store.update_run(run_id, status=RunStatus.SYNTHESIZING)
        cards = [
            ResearchCard.model_validate(payload)
            for payload in self.store.list_artifacts(run_id, "verified_card")
        ]
        report = (
            self.synthesizer.synthesize(state["question"], cards)
            if cards
            else SynthesisReport(
                title="论文调研结果（证据不足）",
                research_question=state["question"],
                executive_summary="本次任务没有论文通过证据核验，不能形成可靠结论。",
                evidence_scope="候选论文经过筛选、研读与核验，但合格证据为 0。",
                main_themes=[], consensus_findings=[], conflicting_findings=[],
                research_gaps=["需要补充可访问全文或调整检索与筛选条件。"],
                product_implications=[],
                recommended_actions=["检查失败记录并上传相关论文 PDF 后重新运行。"],
                limitations=["没有通过质量闸门的研究卡片。"], citations=[],
            )
        )
        markdown = render_markdown(report) + self._audit_appendix(run_id)
        self.store.put_artifact(
            run_id, "synthesis_report", "final", report.model_dump(mode="json")
        )
        self.store.put_artifact(
            run_id, "report_markdown", "final", {"content": markdown}
        )
        self.report_directory.mkdir(parents=True, exist_ok=True)
        (self.report_directory / f"{run_id}.md").write_text(
            markdown, encoding="utf-8"
        )
        self.store.update_run(run_id, status=RunStatus.COMPLETED)
        return {}

    def _audit_appendix(self, run_id: str) -> str:
        candidates = [
            CandidatePaper.model_validate(payload)
            for payload in self.store.list_artifacts(run_id, "candidate")
        ]
        full_text = sum(item.paper.document_access.value == "full_text" for item in candidates)
        abstract_only = sum(
            item.paper.document_access.value == "abstract_only" for item in candidates
        )
        unavailable = sum(
            item.paper.document_access.value == "unavailable" for item in candidates
        )
        source_counts: dict[str, int] = {}
        for item in candidates:
            source_counts[item.retrieval_source] = source_counts.get(item.retrieval_source, 0) + 1
        sources = ", ".join(f"{key}: {value}" for key, value in sorted(source_counts.items())) or "无"
        failures = len(self.store.list_artifacts(run_id, "failure"))
        gates = self.store.list_artifacts(run_id, "quality_gate")
        accepted = sum(bool(item.get("accepted")) for item in gates)
        counted_full_text = sum(bool(item.get("counts_toward_full_text_target")) for item in gates)
        return (
            "\n## 系统执行与证据审计\n\n"
            f"- 检索来源：{sources}\n"
            f"- 候选访问级别：全文 {full_text}；仅摘要 {abstract_only}；不可用 {unavailable}\n"
            f"- 通过质量闸门：{accepted}\n"
            f"- 计入全文研读产量：{counted_full_text}\n"
            f"- 终止失败记录：{failures}\n"
            "- 说明：仅摘要证据可以进入报告，但不会被计为全文研读成果。\n"
        )

    @staticmethod
    def _config(run_id: str) -> dict:
        return {"configurable": {"thread_id": run_id}}

    def run(
        self,
        *,
        topic_id: str,
        question: str,
        search_query: str,
        rows: int = 10,
        from_year: int | None = None,
        until_year: int | None = None,
    ) -> ResearchRun:
        run = ResearchRun(
            run_id="run-" + uuid4().hex[:12], topic_id=topic_id, question=question
        )
        self.store.create_run(run)
        initial: WorkflowState = {
            "run_id": run.run_id,
            "question": question,
            "search_query": search_query,
            "rows": rows,
            "from_year": from_year,
            "until_year": until_year,
        }
        try:
            self.graph.invoke(initial, config=self._config(run.run_id))
        except Exception as exc:
            current = self.store.get_run(run.run_id)
            if current is not None:
                self.store.update_run(
                    run.run_id, error=str(exc)
                )
            raise
        completed = self.store.get_run(run.run_id)
        assert completed is not None
        return completed

    def resume(self, run_id: str) -> ResearchRun:
        """Continue a LangGraph thread from its last durable checkpoint."""

        run = self.store.get_run(run_id)
        if run is None:
            raise KeyError(f"任务不存在: {run_id}")
        if run.status in (RunStatus.COMPLETED, RunStatus.FAILED):
            return run
        self.store.recover_expired_leases()
        self.graph.invoke(None, config=self._config(run_id))
        resumed = self.store.get_run(run_id)
        assert resumed is not None
        return resumed
