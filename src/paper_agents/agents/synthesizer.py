"""Synthesizer agent and deterministic Markdown report renderer."""

from __future__ import annotations

import json
import re

from pydantic import ValidationError

from paper_agents.providers.base import ChatMessage, ModelProvider
from paper_agents.schemas import ResearchCard, SynthesisReport, VerificationStatus


SYSTEM_PROMPT = """你是论文调研系统的综合分析员。
你只能使用已通过 Verifier 的研究卡片，不得补充外部知识。

规则：
1. 明确区分 full_text 与 abstract_only 证据。
2. 只有一篇论文时，不得声称存在“领域共识”或“普遍趋势”。
3. 不得将研究原型直接写成已产品化技术。
4. 每个引用的 paper_id、title 和 DOI 必须来自输入卡片。
5. 证据不足时要明确写入 limitations 和 research_gaps。
6. 只返回 JSON 对象。
"""


class SynthesizerAgentError(RuntimeError):
    pass


def _json_object(text: str) -> dict:
    cleaned = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", cleaned, re.DOTALL)
    if fenced:
        cleaned = fenced.group(1)
    value = json.loads(cleaned)
    if not isinstance(value, dict):
        raise ValueError("输出必须是 JSON 对象")
    return value


class SynthesizerAgent:
    def __init__(self, provider: ModelProvider, *, max_attempts: int = 2) -> None:
        self.provider = provider
        self.max_attempts = max_attempts

    def synthesize(
        self, question: str, cards: list[ResearchCard]
    ) -> SynthesisReport:
        verified = [
            card
            for card in cards
            if card.verification_status == VerificationStatus.PASSED
        ]
        if not verified:
            raise ValueError("没有通过核验的研究卡片，不能生成综合报告")

        messages: list[ChatMessage] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"研究问题：{question}\n\n"
                    "通过核验的研究卡片：\n"
                    + json.dumps(
                        [card.model_dump(mode="json") for card in verified],
                        ensure_ascii=False,
                    )
                    + "\n\n输出 JSON Schema："
                    + json.dumps(SynthesisReport.model_json_schema(), ensure_ascii=False)
                ),
            },
        ]
        allowed = {
            card.paper.paper_id: (
                card.paper.title,
                card.paper.doi,
            )
            for card in verified
        }
        last_error: Exception | None = None

        for attempt in range(1, self.max_attempts + 1):
            response = self.provider.complete(messages)
            try:
                report = SynthesisReport.model_validate(_json_object(response.content))
                for citation in report.citations:
                    if citation.paper_id not in allowed:
                        raise ValueError(f"报告引用了未通过核验的论文: {citation.paper_id}")
                    title, doi = allowed[citation.paper_id]
                    if citation.title != title or citation.doi != doi:
                        raise ValueError(f"报告引用元数据不一致: {citation.paper_id}")
                return report
            except (json.JSONDecodeError, ValueError, ValidationError) as exc:
                last_error = exc
                if attempt < self.max_attempts:
                    messages.extend(
                        [
                            {"role": "assistant", "content": response.content},
                            {
                                "role": "user",
                                "content": f"综合报告未通过校验，请修正后只返回 JSON：{exc}",
                            },
                        ]
                    )
        raise SynthesizerAgentError(f"Synthesizer Agent 输出失败: {last_error}")


def render_markdown(report: SynthesisReport) -> str:
    """Render validated structured output; the model never writes file markup."""

    def section(title: str, items: list[str]) -> str:
        body = "\n".join(f"- {item}" for item in items) or "- 暂无足够证据"
        return f"## {title}\n\n{body}\n"

    citation_lines = []
    for index, citation in enumerate(report.citations, 1):
        doi = f" DOI: {citation.doi}." if citation.doi else ""
        citation_lines.append(
            f"{index}. {citation.title}. `{citation.paper_id}`.{doi}"
        )

    parts = [
        f"# {report.title}\n",
        f"**研究问题：** {report.research_question}\n",
        "## 执行摘要\n\n" + report.executive_summary + "\n",
        "## 证据范围\n\n" + report.evidence_scope + "\n",
        section("主要技术主题", report.main_themes),
        section("一致性发现", report.consensus_findings),
        section("冲突与不一致", report.conflicting_findings),
        section("研究空白", report.research_gaps),
        section("产品启示", report.product_implications),
        section("建议行动", report.recommended_actions),
        section("局限性", report.limitations),
        "## 引用论文\n\n" + "\n".join(citation_lines) + "\n",
    ]
    return "\n".join(parts)
