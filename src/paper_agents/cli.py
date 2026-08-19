"""Small command-line utilities for learning and validating the system."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from paper_agents.agents.reader import PaperDocument, ReaderAgent, ReaderAgentError
from paper_agents.agents.screener import ScreenerAgent, ScreenerAgentError
from paper_agents.agents.synthesizer import SynthesizerAgent
from paper_agents.agents.verifier import VerifierAgent, VerifierAgentError
from paper_agents.harness import ResearchWorkflow
from paper_agents.providers.openai_compatible import (
    OpenAICompatibleProvider,
    ProviderError,
)
from paper_agents.schemas import CandidatePaper, ResearchCard, ResearchRun
from paper_agents.storage import ResearchStore
from paper_agents.tools import (
    CompositeRetriever,
    CrossrefClient,
    OpenAlexClient,
    RetrievalError,
    deduplicate_candidates,
)


def validate_card(path: Path) -> int:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        card = ResearchCard.model_validate(payload)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        print(f"❌ 研究卡片校验失败:\n{exc}")
        return 1

    print("✅ 研究卡片通过校验")
    print(f"论文: {card.paper.title}")
    print(f"证据数: {len(card.evidence)}")
    print(f"访问级别: {card.paper.document_access.value}")
    return 0


def read_paper(path: Path, output: Path) -> int:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        document = PaperDocument.model_validate(payload)
        provider = OpenAICompatibleProvider()
        card = ReaderAgent(provider).read(document)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(card.model_dump_json(indent=2), encoding="utf-8")
    except (
        OSError,
        json.JSONDecodeError,
        ValidationError,
        ProviderError,
        ReaderAgentError,
    ) as exc:
        print(f"❌ Reader Agent 运行失败:\n{exc}")
        return 1

    print("✅ Reader Agent 已生成研究卡片")
    print(f"论文: {card.paper.title}")
    print(f"模型: {card.model}")
    print(f"输出: {output}")
    return 0


def search_crossref(
    query: str,
    output: Path,
    *,
    rows: int,
    from_year: int | None,
    until_year: int | None,
) -> int:
    try:
        candidates = CrossrefClient().search(
            query, rows=rows, from_year=from_year, until_year=until_year
        )
        unique, removed = deduplicate_candidates(candidates)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(
                [item.model_dump(mode="json") for item in unique],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except (OSError, RetrievalError, ValueError) as exc:
        print(f"❌ Crossref 检索失败:\n{exc}")
        return 1

    print("✅ Crossref 检索完成")
    print(f"原始记录: {len(candidates)}")
    print(f"去除重复: {removed}")
    print(f"唯一候选: {len(unique)}")
    print(f"输出: {output}")
    return 0


def screen_candidates(path: Path, question: str, output: Path) -> int:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        candidates = [CandidatePaper.model_validate(item) for item in payload]
        batch = ScreenerAgent(OpenAICompatibleProvider()).screen(question, candidates)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(batch.model_dump_json(indent=2), encoding="utf-8")
    except (
        OSError,
        json.JSONDecodeError,
        ValidationError,
        ProviderError,
        ScreenerAgentError,
    ) as exc:
        print(f"❌ Screener Agent 运行失败:\n{exc}")
        return 1

    counts: dict[str, int] = {}
    for item in batch.results:
        counts[item.decision.value] = counts.get(item.decision.value, 0) + 1
    print("✅ Screener Agent 筛选完成")
    print(f"统计: {counts}")
    print(f"输出: {output}")
    return 0


def create_research_run(topic_id: str, question: str, database: Path) -> int:
    store = ResearchStore(database)
    run = ResearchRun(
        run_id="run-" + uuid4().hex[:12], topic_id=topic_id, question=question
    )
    store.create_run(run)
    print("✅ 调研任务已创建")
    print(f"run_id: {run.run_id}")
    print(f"status: {run.status.value}")
    print(f"database: {database}")
    return 0


def list_research_runs(database: Path) -> int:
    runs = ResearchStore(database).list_runs()
    if not runs:
        print("暂无调研任务")
        return 0
    for run in runs:
        print(
            f"{run.run_id} | {run.status.value:12} | "
            f"candidates={run.candidate_count} included={run.included_count} "
            f"verified={run.verified_count} | {run.question}"
        )
    return 0


def verify_paper(
    document_path: Path,
    card_path: Path,
    report_output: Path,
    card_output: Path,
) -> int:
    try:
        document = PaperDocument.model_validate_json(
            document_path.read_text(encoding="utf-8")
        )
        card = ResearchCard.model_validate_json(card_path.read_text(encoding="utf-8"))
        report, verified_card = VerifierAgent(OpenAICompatibleProvider()).verify(
            document, card
        )
        report_output.parent.mkdir(parents=True, exist_ok=True)
        card_output.parent.mkdir(parents=True, exist_ok=True)
        report_output.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        card_output.write_text(verified_card.model_dump_json(indent=2), encoding="utf-8")
    except (
        OSError,
        ValidationError,
        ValueError,
        ProviderError,
        VerifierAgentError,
    ) as exc:
        print(f"❌ Verifier Agent 运行失败:\n{exc}")
        return 1

    print("✅ Verifier Agent 核验完成")
    print(f"status: {report.status.value}")
    print(f"report: {report_output}")
    print(f"verified card: {card_output}")
    return 0


def run_research_workflow(
    *,
    topic_id: str,
    question: str,
    search_query: str,
    rows: int,
    from_year: int | None,
    until_year: int | None,
    database: Path,
) -> int:
    try:
        provider = OpenAICompatibleProvider()
        workflow = ResearchWorkflow(
            store=ResearchStore(database),
            retriever=CompositeRetriever([OpenAlexClient(), CrossrefClient()]),
            screener=ScreenerAgent(provider),
            reader=ReaderAgent(provider),
            verifier=VerifierAgent(provider),
            synthesizer=SynthesizerAgent(provider),
        )
        run = workflow.run(
            topic_id=topic_id,
            question=question,
            search_query=search_query,
            rows=rows,
            from_year=from_year,
            until_year=until_year,
        )
        workflow.close()
    except Exception as exc:
        print(f"❌ 调研工作流失败:\n{exc}")
        return 1

    print("✅ 调研工作流已完成")
    print(f"run_id: {run.run_id}")
    print(f"status: {run.status.value}")
    print(f"candidates: {run.candidate_count}")
    print(f"included: {run.included_count}")
    print(f"verified: {run.verified_count}")
    print(f"failed: {run.failed_count}")
    print(f"report: data/reports/{run.run_id}.md")
    return 0


def resume_research_workflow(run_id: str, database: Path) -> int:
    try:
        provider = OpenAICompatibleProvider()
        workflow = ResearchWorkflow(
            store=ResearchStore(database),
            retriever=CompositeRetriever([OpenAlexClient(), CrossrefClient()]),
            screener=ScreenerAgent(provider),
            reader=ReaderAgent(provider),
            verifier=VerifierAgent(provider),
            synthesizer=SynthesizerAgent(provider),
        )
        run = workflow.resume(run_id)
        workflow.close()
    except Exception as exc:
        print(f"❌ 恢复调研任务失败:\n{exc}")
        return 1

    print("✅ 调研任务已从中断点继续")
    print(f"run_id: {run.run_id}")
    print(f"status: {run.status.value}")
    print(f"verified: {run.verified_count}")
    print(f"failed: {run.failed_count}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="论文调研多 Agent 系统")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate-card", help="校验研究卡片 JSON")
    validate.add_argument("path", type=Path)
    read = subparsers.add_parser("read-paper", help="调用 Reader Agent 研读一篇论文")
    read.add_argument("path", type=Path, help="PaperDocument JSON 路径")
    read.add_argument(
        "--output",
        type=Path,
        default=Path("data/cards/research-card.json"),
        help="研究卡片输出路径",
    )
    search = subparsers.add_parser("search-crossref", help="从 Crossref 检索候选论文")
    search.add_argument("query", help="英文检索词")
    search.add_argument("--rows", type=int, default=10)
    search.add_argument("--from-year", type=int)
    search.add_argument("--until-year", type=int)
    search.add_argument(
        "--output",
        type=Path,
        default=Path("data/candidates/crossref.json"),
    )
    screen = subparsers.add_parser("screen-candidates", help="使用 Screener Agent 批量初筛")
    screen.add_argument("path", type=Path, help="CandidatePaper JSON 列表")
    screen.add_argument("question", help="研究问题")
    screen.add_argument(
        "--output",
        type=Path,
        default=Path("data/screening/results.json"),
    )
    create_run = subparsers.add_parser("create-run", help="创建可恢复的调研任务")
    create_run.add_argument("topic_id")
    create_run.add_argument("question")
    create_run.add_argument(
        "--database", type=Path, default=Path("data/research.db")
    )
    list_runs = subparsers.add_parser("list-runs", help="查看已保存的调研任务")
    list_runs.add_argument(
        "--database", type=Path, default=Path("data/research.db")
    )
    verify = subparsers.add_parser("verify-paper", help="独立核验 Reader 研究卡片")
    verify.add_argument("document", type=Path)
    verify.add_argument("card", type=Path)
    verify.add_argument(
        "--report-output",
        type=Path,
        default=Path("data/verifications/report.json"),
    )
    verify.add_argument(
        "--card-output",
        type=Path,
        default=Path("data/cards/verified-card.json"),
    )
    research = subparsers.add_parser("research", help="运行多源论文调研工作流")
    research.add_argument("question", help="最终需要回答的研究问题")
    research.add_argument("--query", required=True, help="OpenAlex/Crossref 英文检索词")
    research.add_argument("--topic-id", default="custom-topic")
    research.add_argument("--rows", type=int, default=10)
    research.add_argument("--from-year", type=int)
    research.add_argument("--until-year", type=int)
    research.add_argument(
        "--database", type=Path, default=Path("data/research.db")
    )
    resume = subparsers.add_parser("resume-run", help="从 SQLite 保存的中断点继续")
    resume.add_argument("run_id")
    resume.add_argument(
        "--database", type=Path, default=Path("data/research.db")
    )
    return parser


def main() -> int:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        # Installed project environments include python-dotenv. Keeping this
        # fallback lets the dependency-light validation command still run.
        pass

    args = build_parser().parse_args()
    if args.command == "validate-card":
        return validate_card(args.path)
    if args.command == "read-paper":
        return read_paper(args.path, args.output)
    if args.command == "search-crossref":
        return search_crossref(
            args.query,
            args.output,
            rows=args.rows,
            from_year=args.from_year,
            until_year=args.until_year,
        )
    if args.command == "screen-candidates":
        return screen_candidates(args.path, args.question, args.output)
    if args.command == "create-run":
        return create_research_run(args.topic_id, args.question, args.database)
    if args.command == "list-runs":
        return list_research_runs(args.database)
    if args.command == "verify-paper":
        return verify_paper(
            args.document, args.card, args.report_output, args.card_output
        )
    if args.command == "research":
        return run_research_workflow(
            topic_id=args.topic_id,
            question=args.question,
            search_query=args.query,
            rows=args.rows,
            from_year=args.from_year,
            until_year=args.until_year,
            database=args.database,
        )
    if args.command == "resume-run":
        return resume_research_workflow(args.run_id, args.database)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
