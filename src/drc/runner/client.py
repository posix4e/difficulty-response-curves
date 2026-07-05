"""TrustedRouter client. Two API surfaces on one gateway:

- OpenAI-compatible chat completions (most models):
    POST {base}/v1/chat/completions, Bearer auth.
    usage.cost_microdollars is authoritative spend.
- Native Anthropic Messages (Claude with extended thinking):
    POST {base}/v1/messages, x-api-key auth.
    No microdollars; cost computed from the price table (+10% margin).

Transient failures (429/5xx/transport) are retried with jittered
exponential backoff; anything that survives retries comes back as an
error result, which the store records as outcome=error_api (excluded
from fits, retried on the next run).
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from dataclasses import dataclass, field

import httpx

from ..config import ModelCfg

BASE = "https://api.trustedrouter.com"
RETRIABLE = {429, 500, 502, 503, 504, 520, 522, 524}
MAX_RETRIES = 8


@dataclass
class CallResult:
    text: str | None = None
    finish_reason: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    reasoning_tokens: int | None = None
    cost_microdollars: int = 0
    cost_source: str = "api"
    provider_endpoint: str | None = None
    http_status: int | None = None
    attempts: int = 1
    latency_ms: float = 0.0
    error: str | None = None


class TRClient:
    def __init__(self, api_key: str, base: str = BASE, transport: httpx.AsyncBaseTransport | None = None):
        self.api_key = api_key
        self.base = base.rstrip("/")
        import os
        read_s = float(os.environ.get("DRC_READ_TIMEOUT", 600))
        timeout = httpx.Timeout(connect=30.0, read=read_s, write=60.0, pool=60.0)
        limits = httpx.Limits(max_connections=128, max_keepalive_connections=64)
        self.http = httpx.AsyncClient(timeout=timeout, limits=limits, transport=transport)

    async def aclose(self) -> None:
        await self.http.aclose()

    async def call(self, cfg: ModelCfg, prompt: str, temperature: float | None = None) -> CallResult:
        if cfg.api_path == "anthropic":
            return await self._anthropic(cfg, prompt, temperature)
        return await self._openai(cfg, prompt, temperature)

    def _gateway(self, cfg: ModelCfg) -> tuple[str, str]:
        """(base_url, bearer_key) for this model's gateway."""
        if not cfg.base_url:
            return self.base, self.api_key
        import pathlib, re, os
        raw = os.environ.get(cfg.key_env, "")
        if not raw:
            p = pathlib.Path.home() / "src" / f".env-{cfg.key_env}"
            raw = p.read_text().strip() if p.is_file() else ""
        m = re.search(r"sk-[A-Za-z0-9_-]+", raw)
        return cfg.base_url.rstrip("/"), (m.group(0) if m else raw)

    # -- OpenAI-compatible path -------------------------------------------------

    async def _openai(self, cfg: ModelCfg, prompt: str, temperature: float | None) -> CallResult:
        body: dict = {
            "model": cfg.api_model or cfg.model_id,
            "messages": [{"role": "user", "content": prompt}],
            # TrustedRouter's translation to some upstreams (Anthropic, and
            # likely baseten) silently drops max_completion_tokens and
            # defaults to 4096 -- diagnosed 2026-07-05. Send both spellings.
            "max_completion_tokens": cfg.max_completion_tokens,
            "max_tokens": cfg.max_completion_tokens,
        }
        if temperature is not None:
            body["temperature"] = temperature
        if cfg.provider_only:
            body["provider"] = {"only": list(cfg.provider_only), "allow_fallbacks": False}
        base, key = self._gateway(cfg)
        headers = {"Authorization": f"Bearer {key}", "content-type": "application/json"}

        result, data = await self._post_with_retries("/v1/chat/completions", body, headers, base=base)
        if data is None:
            return result
        try:
            choice = data["choices"][0]
            msg = choice.get("message") or {}
            usage = data.get("usage") or {}
            details = usage.get("completion_tokens_details") or {}
            provider_usage = usage.get("provider_usage") or {}
            routing = (data.get("trustedrouter") or {}).get("routing") or {}
            # OpenRouter (and some TR upstreams) deliver the trace in a
            # separate reasoning field; losing it starves the trace judge.
            # Re-wrap in <think> tags to match the inline-delivery format.
            reasoning = msg.get("reasoning") or msg.get("reasoning_content") or ""
            content = msg.get("content") or ""
            result.text = f"<think>{reasoning}</think>\n{content}" if reasoning else (content or None)
            result.finish_reason = choice.get("finish_reason")
            result.prompt_tokens = usage.get("prompt_tokens")
            result.completion_tokens = usage.get("completion_tokens")
            result.reasoning_tokens = details.get("reasoning_tokens") or provider_usage.get("reasoning_tokens")
            micro = usage.get("cost_microdollars")
            if micro is None:
                micro = cfg.pricetable_microdollars(
                    usage.get("prompt_tokens") or 0, usage.get("completion_tokens") or 0
                )
                result.cost_source = "openrouter" if cfg.base_url else "pricetable"
            result.cost_microdollars = int(micro)
            result.provider_endpoint = routing.get("selected_endpoint") or (
                f"openrouter/{data.get('provider', '')}" if cfg.base_url else None
            )
        except (KeyError, IndexError, TypeError) as e:
            result.error = f"malformed response: {e}"
        return result

    # -- Anthropic Messages path -------------------------------------------------

    async def _anthropic(self, cfg: ModelCfg, prompt: str, temperature: float | None) -> CallResult:
        body: dict = {
            "model": cfg.model_id,
            "max_tokens": cfg.max_completion_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if cfg.thinking_budget:
            body["thinking"] = {"type": "enabled", "budget_tokens": cfg.thinking_budget}
        if temperature is not None:
            body["temperature"] = temperature
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        result, data = await self._post_with_retries("/v1/messages", body, headers)
        if data is None:
            return result
        try:
            texts = [blk.get("text", "") for blk in data.get("content", []) if blk.get("type") == "text"]
            thinking_chars = sum(
                len(blk.get("thinking", "")) for blk in data.get("content", []) if blk.get("type") == "thinking"
            )
            usage = data.get("usage") or {}
            result.text = "\n".join(t for t in texts if t) or None
            stop = data.get("stop_reason")
            result.finish_reason = "length" if stop == "max_tokens" else stop
            result.prompt_tokens = usage.get("input_tokens")
            result.completion_tokens = usage.get("output_tokens")
            # thinking tokens are inside output_tokens; approximate the split for reporting
            result.reasoning_tokens = int(thinking_chars / 3.6) if thinking_chars else None
            result.cost_microdollars = cfg.pricetable_microdollars(
                usage.get("input_tokens") or 0, usage.get("output_tokens") or 0
            )
            result.cost_source = "pricetable"
            result.provider_endpoint = "anthropic-messages"
        except (KeyError, IndexError, TypeError) as e:
            result.error = f"malformed response: {e}"
        return result

    # -- shared transport --------------------------------------------------------

    async def _post_with_retries(
        self, path: str, body: dict, headers: dict, base: str | None = None
    ) -> tuple[CallResult, dict | None]:
        result = CallResult()
        t0 = time.perf_counter()
        payload = json.dumps(body).encode()
        last_err = "unknown"
        for attempt in range(1, MAX_RETRIES + 1):
            result.attempts = attempt
            try:
                resp = await self.http.post((base or self.base) + path, content=payload, headers=headers)
                result.http_status = resp.status_code
                if resp.status_code in RETRIABLE:
                    last_err = f"HTTP {resp.status_code}: {resp.text[:200]}"
                elif resp.status_code >= 400:
                    result.error = f"HTTP {resp.status_code}: {resp.text[:300]}"
                    result.latency_ms = (time.perf_counter() - t0) * 1000
                    return result, None
                else:
                    result.latency_ms = (time.perf_counter() - t0) * 1000
                    return result, resp.json()
            except (httpx.TransportError, json.JSONDecodeError) as e:
                last_err = f"{type(e).__name__}: {e}"
            if attempt < MAX_RETRIES:
                # the gateway sheds load with 502 'authorization/settlement
                # failed' bursts: back off like a rate limit, not a blip
                await asyncio.sleep(min(150, 5 * 2**attempt) * (0.5 + random.random()))
        result.error = f"retries exhausted: {last_err}"
        result.latency_ms = (time.perf_counter() - t0) * 1000
        return result, None
