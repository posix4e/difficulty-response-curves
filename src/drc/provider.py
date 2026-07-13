from __future__ import annotations

import json
import time
from typing import Any

import httpx

from .config import ModelConfig
from .types import ProviderResponse, StreamEvent, Usage


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(
            str(part.get("text", "")) if isinstance(part, dict) else str(part)
            for part in value
        )
    return "" if value is None else str(value)


def _usage(payload: dict[str, Any]) -> Usage:
    usage = payload.get("usage") or {}
    cost = usage.get("cost")
    return Usage(
        prompt_tokens=int(usage.get("prompt_tokens") or 0),
        completion_tokens=int(usage.get("completion_tokens") or 0),
        reasoning_tokens=int(
            (usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0
        ),
        cost_microdollars=(
            int(round(float(cost) * 1_000_000)) if cost is not None else 0
        ),
    )


def _stream_error(payload: dict[str, Any]) -> str | None:
    error = payload.get("error")
    if not error:
        return None
    if isinstance(error, dict):
        code = error.get("code") or "unknown"
        message = error.get("message") or error
        return f"stream error {code}: {message}"
    return f"stream error: {error}"


class SSEDecoder:
    """Decode SSE data fields while ignoring comments and other SSE fields."""

    def __init__(self) -> None:
        self._data: list[str] = []

    def feed(self, line: str) -> tuple[str, ...]:
        if line == "":
            return self._flush()
        if line.startswith(":"):
            return ()
        if line == "data":
            self._data.append("")
        elif line.startswith("data:"):
            value = line[5:]
            self._data.append(value[1:] if value.startswith(" ") else value)
        return ()

    def finish(self) -> tuple[str, ...]:
        return self._flush()

    def _flush(self) -> tuple[str, ...]:
        if not self._data:
            return ()
        value = "\n".join(self._data)
        self._data.clear()
        return (value,)


class OpenRouter:
    """Pinned OpenRouter adapter with optional chunk-preserving streaming."""

    def __init__(
        self,
        model: ModelConfig,
        client: httpx.AsyncClient | None = None,
        stream_telemetry: bool = False,
    ):
        self.model = model
        self.stream_telemetry = stream_telemetry
        self._owned = client is None
        self.client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(connect=30.0, read=None, write=30.0, pool=30.0)
        )

    async def close(self) -> None:
        if self._owned:
            await self.client.aclose()

    def _body(self, prompt: str, stream: bool) -> dict[str, Any]:
        body: dict[str, Any] = {
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
        if stream:
            body["stream"] = True
            body["stream_options"] = {"include_usage": True}
        return body

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.model.key()}"}

    async def complete(self, prompt: str) -> ProviderResponse:
        if self.stream_telemetry:
            return await self._complete_streaming(prompt)
        return await self._complete_buffered(prompt)

    async def _complete_buffered(self, prompt: str) -> ProviderResponse:
        start = time.monotonic()
        response: httpx.Response | None = None
        try:
            response = await self.client.post(
                f"{self.model.base_url}/chat/completions",
                headers=self._headers(),
                json=self._body(prompt, stream=False),
            )
            response.raise_for_status()
            payload = response.json()
            choice = payload["choices"][0]
            message = choice.get("message") or {}
            return ProviderResponse(
                text=_text(message.get("content")),
                finish_reason=str(choice.get("finish_reason") or ""),
                provider=str(
                    payload.get("provider") or response.headers.get("x-provider") or ""
                ),
                usage=_usage(payload),
                latency_ms=(time.monotonic() - start) * 1000,
                reasoning_text=_text(
                    message.get("reasoning") or message.get("reasoning_content")
                ),
                http_status=response.status_code,
                generation_id=response.headers.get("x-generation-id", ""),
            )
        except Exception as error:  # transport and malformed payload are loud failures
            status = response.status_code if response is not None else 0
            raw = response.text if response is not None else ""
            return ProviderResponse(
                text="",
                finish_reason="error",
                provider=(response.headers.get("x-provider", "") if response else ""),
                usage=Usage(),
                latency_ms=(time.monotonic() - start) * 1000,
                http_status=status,
                error=f"{type(error).__name__}: {error}",
                raw_response_text=raw,
                generation_id=(
                    response.headers.get("x-generation-id", "") if response else ""
                ),
            )

    async def _complete_streaming(self, prompt: str) -> ProviderResponse:
        start = time.monotonic()
        answer: list[str] = []
        reasoning: list[str] = []
        events: list[StreamEvent] = []
        rejected_events: list[str] = []
        decoder = SSEDecoder()
        usage = Usage()
        provider = ""
        generation_id = ""
        finish_reason = ""
        error_text: str | None = None
        status = 0
        first_reasoning_ms: float | None = None
        first_answer_ms: float | None = None

        def process(data: str) -> None:
            nonlocal usage, provider, finish_reason, error_text
            nonlocal first_reasoning_ms, first_answer_ms
            if data == "[DONE]":
                return
            elapsed = (time.monotonic() - start) * 1000
            try:
                payload = json.loads(data)
            except json.JSONDecodeError as error:
                rejected_events.append(data)
                error_text = f"malformed SSE event: {error}"
                return
            provider = str(payload.get("provider") or provider)
            if payload.get("usage"):
                usage = _usage(payload)
            event_error = _stream_error(payload)
            if event_error:
                error_text = event_error
            choices = payload.get("choices") or []
            if not choices:
                return
            choice = choices[0]
            delta = choice.get("delta") or {}
            reasoning_chunk = _text(
                delta.get("reasoning") or delta.get("reasoning_content")
            )
            answer_chunk = _text(delta.get("content"))
            if reasoning_chunk:
                reasoning.append(reasoning_chunk)
                first_reasoning_ms = first_reasoning_ms or elapsed
                events.append(
                    StreamEvent(len(events), elapsed, "reasoning", len(reasoning_chunk))
                )
            if answer_chunk:
                answer.append(answer_chunk)
                first_answer_ms = first_answer_ms or elapsed
                events.append(StreamEvent(len(events), elapsed, "answer", len(answer_chunk)))
            if choice.get("finish_reason"):
                finish_reason = str(choice["finish_reason"])

        response: httpx.Response | None = None
        try:
            async with self.client.stream(
                "POST",
                f"{self.model.base_url}/chat/completions",
                headers=self._headers(),
                json=self._body(prompt, stream=True),
            ) as response:
                status = response.status_code
                provider = response.headers.get("x-provider", "")
                generation_id = response.headers.get("x-generation-id", "")
                if response.is_error:
                    raw = (await response.aread()).decode(errors="replace")
                    rejected_events.append(raw)
                    response.raise_for_status()
                async for line in response.aiter_lines():
                    for data in decoder.feed(line):
                        process(data)
                for data in decoder.finish():
                    process(data)
        except Exception as error:
            error_text = f"{type(error).__name__}: {error}"
            if isinstance(error, httpx.HTTPStatusError):
                status = error.response.status_code

        if not error_text and finish_reason not in {"stop", "completed"}:
            error_text = f"stream ended with finish_reason={finish_reason or 'missing'}"
        duration = (time.monotonic() - start) * 1000
        observed_first_tokens = [
            value
            for value in (first_reasoning_ms, first_answer_ms)
            if value is not None
        ]
        first_token = min(observed_first_tokens) if observed_first_tokens else None
        return ProviderResponse(
            text="".join(answer),
            finish_reason="error" if error_text else finish_reason,
            provider=provider,
            usage=usage,
            latency_ms=duration,
            reasoning_text="".join(reasoning),
            http_status=status,
            error=error_text,
            raw_response_text="\n\n".join(rejected_events),
            generation_id=generation_id,
            stream_events=tuple(events),
            ttft_ms=first_token,
            first_reasoning_ms=first_reasoning_ms,
            first_answer_ms=first_answer_ms,
            stream_duration_ms=duration,
        )
