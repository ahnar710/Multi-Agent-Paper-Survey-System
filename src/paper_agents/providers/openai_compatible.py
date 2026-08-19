"""Adapter for OpenAI-compatible Chat Completions APIs."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

from paper_agents.providers.base import ChatMessage, ModelResponse


class ProviderError(RuntimeError):
    """Raised when a model endpoint cannot return a usable response."""


class OpenAICompatibleProvider:
    """Call OpenAI, DeepSeek, GLM, or another compatible endpoint.

    The rest of the application depends only on ModelProvider. Changing model
    vendors therefore does not change any agent or workflow code.
    """

    def __init__(
        self,
        *,
        api_base: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        timeout: int = 120,
        request_attempts: int = 3,
    ) -> None:
        self.api_base = (
            api_base or os.getenv("LLM_API_BASE", "https://api.openai.com/v1")
        ).rstrip("/")
        self.api_key = api_key or os.getenv("LLM_API_KEY", "")
        self.model = model or os.getenv("LLM_MODEL", "")
        self.max_tokens = max_tokens or int(os.getenv("LLM_MAX_TOKENS", "12000"))
        self.timeout = timeout
        self.request_attempts = request_attempts

        if not self.api_key:
            raise ProviderError("未配置 LLM_API_KEY")
        if not self.model:
            raise ProviderError("未配置 LLM_MODEL")

    @property
    def model_name(self) -> str:
        return self.model

    def complete(self, messages: list[ChatMessage]) -> ModelResponse:
        payload = json.dumps(
            {
                "model": self.model,
                "messages": messages,
                "temperature": 0.1,
                "max_tokens": self.max_tokens,
                "response_format": {"type": "json_object"},
            },
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.api_base}/chat/completions",
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        data: dict[str, Any] | None = None
        last_error: Exception | None = None
        for attempt in range(1, self.request_attempts + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    data = json.loads(response.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                last_error = ProviderError(
                    f"模型接口返回 HTTP {exc.code}: {detail[:800]}"
                )
                if exc.code not in (429, 500, 502, 503, 504):
                    raise last_error from exc
                retry_after = exc.headers.get("Retry-After")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else 2 ** (attempt - 1)
            except (urllib.error.URLError, TimeoutError) as exc:
                last_error = ProviderError(f"无法连接模型接口: {exc}")
                delay = 2 ** (attempt - 1)
            except json.JSONDecodeError as exc:
                raise ProviderError("模型接口未返回有效 JSON") from exc
            if attempt < self.request_attempts:
                time.sleep(delay)
        if data is None:
            raise last_error or ProviderError("模型接口请求失败")

        try:
            content = str(data["choices"][0]["message"]["content"])
            usage = data.get("usage", {})
            return ModelResponse(
                content=content,
                model=str(data.get("model", self.model)),
                input_tokens=usage.get("prompt_tokens"),
                output_tokens=usage.get("completion_tokens"),
            )
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f"模型接口返回结构异常: {data}") from exc
