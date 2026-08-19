"""Screener agent: make conservative batch decisions on retrieved metadata."""

from __future__ import annotations

import json
import re

from pydantic import ValidationError

from paper_agents.providers.base import ChatMessage, ModelProvider
from paper_agents.schemas import CandidatePaper, ScreeningBatch


SYSTEM_PROMPT = """你是论文调研系统的初筛专员。
请根据用户的研究问题，使用候选论文的标题、年份、来源和摘要进行保守筛选。

规则：
1. include：现有元数据或摘要足以确认与问题直接相关。
2. exclude：足以确认与问题无关、领域不符或年份不符。
3. review：标题可能相关，但没有摘要或信息不足，需要获取全文后人工/机器复核。
4. 没有摘要时，不得根据标题猜测实验质量和研究结论。
5. 必须为每个输入 paper_id 返回且只返回一条结果。
6. 只返回 JSON 对象。
"""


class ScreenerAgentError(RuntimeError):
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


class ScreenerAgent:
    def __init__(self, provider: ModelProvider, *, max_attempts: int = 2) -> None:
        self.provider = provider
        self.max_attempts = max_attempts

    def screen(
        self, question: str, candidates: list[CandidatePaper]
    ) -> ScreeningBatch:
        if not candidates:
            return ScreeningBatch(results=[])

        compact = [
            {
                "paper_id": item.paper.paper_id,
                "title": item.paper.title,
                "year": item.paper.year,
                "venue": item.paper.venue,
                "document_access": item.paper.document_access,
                "abstract": item.abstract,
            }
            for item in candidates
        ]
        messages: list[ChatMessage] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"研究问题：{question}\n\n"
                    f"候选论文：{json.dumps(compact, ensure_ascii=False)}\n\n"
                    "输出 JSON Schema："
                    + json.dumps(ScreeningBatch.model_json_schema(), ensure_ascii=False)
                ),
            },
        ]
        expected_ids = {item.paper.paper_id for item in candidates}
        last_error: Exception | None = None

        for attempt in range(1, self.max_attempts + 1):
            response = self.provider.complete(messages)
            try:
                batch = ScreeningBatch.model_validate(_json_object(response.content))
                actual_ids = [item.paper_id for item in batch.results]
                if len(actual_ids) != len(set(actual_ids)):
                    raise ValueError("筛选结果包含重复 paper_id")
                if set(actual_ids) != expected_ids:
                    raise ValueError("筛选结果必须完整覆盖所有输入 paper_id")
                return batch
            except (json.JSONDecodeError, ValueError, ValidationError) as exc:
                last_error = exc
                if attempt < self.max_attempts:
                    messages.extend(
                        [
                            {"role": "assistant", "content": response.content},
                            {
                                "role": "user",
                                "content": f"输出未通过校验，请修正后只返回 JSON：{exc}",
                            },
                        ]
                    )

        raise ScreenerAgentError(f"Screener Agent 输出失败: {last_error}")
