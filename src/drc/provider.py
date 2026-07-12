from __future__ import annotations

import time
from typing import Any

import httpx

from .config import ModelConfig
from .types import ProviderResponse, Usage


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(
            str(part.get("text", "")) if isinstance(part, dict) else str(part)
            for part in value
        )
    return "" if value is None else str(value)


class OpenRouter:
    """The only provider adapter required by the frozen MiniMax study."""

    def __init__(self, model: ModelConfig, client: httpx.AsyncClient | None = None):
        self.model = model
        self._owned = client is None
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(1800.0))

    async def close(self) -> None:
        if self._owned:
            await self.client.aclose()

    async def complete(self, prompt: str) -> ProviderResponse:
        body = {
            "model": self.model.api_model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": self.model.max_tokens,
            "temperature": self.model.temperature,
            "reasoning": {
                "effort": self.model.reasoning_effort,
                "exclude": False,
            },
            "provider": {"only": [self.model.provider], "allow_fallbacks": False},
        }
        start = time.monotonic()
        try:
            response = await self.client.post(
                f"{self.model.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.model.key()}"},
                json=body,
            )
            response.raise_for_status()
            payload = response.json()
            choice = payload["choices"][0]
            message = choice.get("message") or {}
            usage = payload.get("usage") or {}
            cost = usage.get("cost")
            return ProviderResponse(
                text=_text(message.get("content")),
                finish_reason=str(choice.get("finish_reason") or ""),
                provider=str(payload.get("provider") or response.headers.get("x-provider") or ""),
                usage=Usage(
                    prompt_tokens=int(usage.get("prompt_tokens") or 0),
                    completion_tokens=int(usage.get("completion_tokens") or 0),
                    reasoning_tokens=int(
                        (usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0
                    ),
                    cost_microdollars=int(round(float(cost) * 1_000_000)) if cost is not None else 0,
                ),
                latency_ms=(time.monotonic() - start) * 1000,
                reasoning_text=_text(
                    message.get("reasoning") or message.get("reasoning_content")
                ),
                http_status=response.status_code,
            )
        except Exception as error:  # transport and malformed payload are loud failures
            status = error.response.status_code if isinstance(error, httpx.HTTPStatusError) else 0
            return ProviderResponse(
                text="",
                finish_reason="error",
                provider="",
                usage=Usage(),
                latency_ms=(time.monotonic() - start) * 1000,
                http_status=status,
                error=f"{type(error).__name__}: {error}",
            )
