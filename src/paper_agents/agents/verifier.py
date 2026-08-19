"""Verifier agent: independently check a research card against its source text."""

from __future__ import annotations

import json
import re

from pydantic import ValidationError

from paper_agents.agents.reader import PaperDocument
from paper_agents.providers.base import ChatMessage, ModelProvider
from paper_agents.schemas import (
    DocumentAccess,
    ResearchCard,
    VerificationReport,
    VerificationStatus,
)


SYSTEM_PROMPT = """你是独立的论文证据核验员，不参与生成研究卡片。
请逐条对照原始输入，检查：
1. claim 是否被原文直接支持；
2. evidence 是否与原文一致；
3. locator 是否在原文中真实出现；
4. 结论强度是否超过原文，例如把“两条路线改善”夸大成“对所有城市均有效”。
信息不足时必须判定为不通过，不得用常识补齐。
只返回 JSON 对象。
"""


class VerifierAgentError(RuntimeError):
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


class VerifierAgent:
    def __init__(self, provider: ModelProvider, *, max_attempts: int = 2) -> None:
        self.provider = provider
        self.max_attempts = max_attempts

    def verify(
        self, document: PaperDocument, card: ResearchCard
    ) -> tuple[VerificationReport, ResearchCard]:
        if document.paper.paper_id != card.paper.paper_id:
            raise ValueError("原文和研究卡片的 paper_id 不一致")

        messages: list[ChatMessage] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"文档访问级别：{document.paper.document_access.value}\n\n"
                    f"原始文本：\n{document.content}\n\n"
                    f"待核验研究卡：\n{card.model_dump_json(indent=2)}\n\n"
                    "输出 JSON Schema："
                    + json.dumps(VerificationReport.model_json_schema(), ensure_ascii=False)
                ),
            },
        ]
        expected_indexes = set(range(len(card.evidence)))
        last_error: Exception | None = None

        for attempt in range(1, self.max_attempts + 1):
            response = self.provider.complete(messages)
            try:
                payload = _json_object(response.content)
                payload["paper_id"] = card.paper.paper_id
                report = VerificationReport.model_validate(payload)
                indexes = [item.evidence_index for item in report.items]
                if len(indexes) != len(set(indexes)) or set(indexes) != expected_indexes:
                    raise ValueError("核验结果必须逐条覆盖所有 evidence_index")

                full_text = document.paper.document_access == DocumentAccess.FULL_TEXT
                passed = all(
                    item.claim_supported
                    and item.strength_appropriate
                    and (item.locator_valid or not full_text)
                    for item in report.items
                )
                status = (
                    VerificationStatus.PASSED if passed else VerificationStatus.FAILED
                )
                report = report.model_copy(update={"status": status})
                verified_card = card.model_copy(update={"verification_status": status})
                return report, verified_card
            except (json.JSONDecodeError, ValueError, ValidationError) as exc:
                last_error = exc
                if attempt < self.max_attempts:
                    messages.extend(
                        [
                            {"role": "assistant", "content": response.content},
                            {
                                "role": "user",
                                "content": f"核验输出不合格，请修正后只返回 JSON：{exc}",
                            },
                        ]
                    )

        raise VerifierAgentError(f"Verifier Agent 输出失败: {last_error}")
