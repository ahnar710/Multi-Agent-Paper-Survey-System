"""Reader agent: turn one paper into a validated research card."""

from __future__ import annotations

import json
import re

from pydantic import Field, ValidationError

from paper_agents.providers.base import ChatMessage, ModelProvider
from paper_agents.schemas import PaperMetadata, ResearchCard, StrictModel


READER_AGENT_ID = "reader-v0.1"
PROMPT_VERSION = "reader-prompt-v0.1"

SYSTEM_PROMPT = """你是一名谨慎的论文研读专员。
你的任务是根据用户提供的论文内容生成结构化研究卡片。

强制规则：
1. 只使用输入文本中能找到的信息，不得补写不存在的实验、数值或引用。
2. 摘要级输入不得声称已阅读全文。
3. 全文证据必须使用输入中真实出现的页码、章节或图表定位。
4. 信息不足时明确写“输入未报告”，不得猜测。
5. 返回且只返回一个 JSON 对象，不要使用 Markdown 代码块。
"""


class PaperDocument(StrictModel):
    """Metadata plus the abstract or extracted full text supplied to a reader."""

    paper: PaperMetadata
    content: str = Field(min_length=20)


class ReaderAgentError(RuntimeError):
    """Raised after the reader cannot produce a valid card."""


def _extract_json(text: str) -> dict:
    cleaned = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", cleaned, re.DOTALL)
    if fenced:
        cleaned = fenced.group(1)
    value = json.loads(cleaned)
    if not isinstance(value, dict):
        raise ValueError("模型输出必须是 JSON 对象")
    return value


class ReaderAgent:
    def __init__(self, provider: ModelProvider, *, max_attempts: int = 2) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts 必须大于等于 1")
        self.provider = provider
        self.max_attempts = max_attempts

    def read(self, document: PaperDocument) -> ResearchCard:
        schema = ResearchCard.model_json_schema()
        user_prompt = (
            "请研读以下论文。\n\n"
            f"固定元数据：\n{document.paper.model_dump_json(indent=2)}\n\n"
            f"论文内容：\n{document.content}\n\n"
            "输出必须符合以下 JSON Schema：\n"
            f"{json.dumps(schema, ensure_ascii=False)}"
        )
        messages: list[ChatMessage] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        last_error: Exception | None = None

        for attempt in range(1, self.max_attempts + 1):
            response = self.provider.complete(messages)
            try:
                payload = _extract_json(response.content)

                # Identity and audit fields come from code, not model claims.
                payload["paper"] = document.paper.model_dump(mode="json")
                payload["reader_agent_id"] = READER_AGENT_ID
                payload["model"] = response.model or self.provider.model_name
                payload["prompt_version"] = PROMPT_VERSION
                payload["verification_status"] = "pending"
                payload["failure_reason"] = None
                return ResearchCard.model_validate(payload)
            except (json.JSONDecodeError, ValueError, ValidationError) as exc:
                last_error = exc
                if attempt < self.max_attempts:
                    messages.extend(
                        [
                            {"role": "assistant", "content": response.content},
                            {
                                "role": "user",
                                "content": (
                                    "上一次输出未通过校验。请修正后只返回 JSON。\n"
                                    f"校验错误：{exc}"
                                ),
                            },
                        ]
                    )

        raise ReaderAgentError(
            f"Reader Agent 连续 {self.max_attempts} 次未生成合格研究卡片: {last_error}"
        )
