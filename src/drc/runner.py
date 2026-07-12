from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Protocol

from .config import StudyConfig
from .provider import OpenRouter
from .sat import parse_assignment, planned_instances, verify
from .store import Store
from .types import CallPlan, ProviderResponse, StudyStatus


class Provider(Protocol):
    async def complete(self, prompt: str) -> ProviderResponse: ...
    async def close(self) -> None: ...


def provider_matches(observed: str, required: str) -> bool:
    clean = lambda value: value.strip().lower().split("/")[-1]
    return bool(observed) and clean(observed) == clean(required)


class BudgetGate:
    def __init__(self, cap: int, spent: int = 0):
        self.cap = cap
        self.spent = spent
        self.reserved = 0
        self._lock = asyncio.Lock()

    async def reserve(self, amount: int) -> bool:
        async with self._lock:
            if self.spent + self.reserved + amount > self.cap:
                return False
            self.reserved += amount
            return True

    async def settle(self, reserved: int, actual: int) -> None:
        async with self._lock:
            self.reserved -= reserved
            self.spent += actual


def should_stop(status: StudyStatus, config: StudyConfig) -> str | None:
    if status.correct >= config.stop.correct and status.silent_wrong >= config.stop.silent_wrong:
        return "label target reached"
    if status.calls >= config.stop.max_calls:
        return "call cap reached"
    if status.spend_microdollars >= config.stop.max_spend_microdollars:
        return "spend cap reached"
    return None


def build_plan(config: StudyConfig) -> list[CallPlan]:
    instances = planned_instances(
        config.task.seed,
        config.task.difficulties,
        config.task.instances_per_level,
        config.task.variables,
    )
    return [
        CallPlan(instance, sample)
        for instance in instances
        for sample in range(config.task.samples_per_instance)
    ]


def plan_summary(config: StudyConfig) -> dict[str, object]:
    calls = (
        len(config.task.difficulties)
        * config.task.instances_per_level
        * config.task.samples_per_instance
    )
    reserve = config.model.estimated_microdollars(8_000, config.model.max_tokens)
    return {
        "study": config.name,
        "model": config.model.record_id,
        "provider": config.model.provider,
        "levels": list(config.task.difficulties),
        "planned_calls": calls,
        "concurrency": config.concurrency,
        "per_call_worst_case_usd": round(reserve / 1_000_000, 6),
        "hard_cap_usd": config.stop.max_spend_usd,
        "stop_labels": {
            "correct": config.stop.correct,
            "silent_wrong": config.stop.silent_wrong,
        },
    }


def _request_record(config: StudyConfig) -> str:
    return json.dumps(
        {
            "model": config.model.api_model,
            "provider_only": [config.model.provider],
            "max_completion_tokens": config.model.max_tokens,
            "temperature": config.model.temperature,
            "reasoning_effort": config.model.reasoning_effort,
            "prompt_version": config.prompt_version,
        },
        sort_keys=True,
    )


async def _run_call(
    plan: CallPlan,
    config: StudyConfig,
    store: Store,
    provider: Provider,
    gate: BudgetGate,
    reserve: int,
) -> bool:
    started = datetime.now(timezone.utc).isoformat()
    response = await provider.complete(plan.instance.prompt)
    actual_cost = response.usage.cost_microdollars or config.model.estimated_microdollars(
        response.usage.prompt_tokens, response.usage.completion_tokens
    )
    await gate.settle(reserve, actual_cost)

    assignment = parse_assignment(response.text, len(plan.instance.witness))
    mismatch = not response.error and not provider_matches(response.provider, config.model.provider)
    if response.error:
        outcome = "error_api"
    elif mismatch:
        outcome = "provider_mismatch"
    elif response.finish_reason not in {"stop", "completed"}:
        outcome = "fail_truncated"
    elif assignment is None:
        outcome = "fail_parse"
    elif verify(plan.instance.clauses, assignment):
        outcome = "pass"
    else:
        outcome = "fail_wrong"

    store.record_call(
        {
            "instance_id": plan.instance.instance_id,
            "model_id": config.model.record_id,
            "sample_idx": plan.sample_index,
            "stage": config.name,
            "api_path": "openai",
            "prompt_version": config.prompt_version,
            "prompt_sha256": hashlib.sha256(plan.instance.prompt.encode()).hexdigest(),
            "request_json": _request_record(config),
            "response_text": response.text if not response.error else response.error,
            "reasoning_text": response.reasoning_text,
            "finish_reason": response.finish_reason,
            "parsed_answer": json.dumps(assignment) if assignment is not None else None,
            "outcome": outcome,
            "pass": int(outcome == "pass"),
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "reasoning_tokens": response.usage.reasoning_tokens,
            "cost_microdollars": actual_cost,
            "cost_source": "provider" if response.usage.cost_microdollars else "price_table",
            "provider_endpoint": response.provider,
            "provider_pinned": 1,
            "provider_mismatch": int(mismatch),
            "http_status": response.http_status,
            "latency_ms": response.latency_ms,
            "observed_chars": len(response.text),
            "ts_start": started,
            "ts_end": datetime.now(timezone.utc).isoformat(),
        }
    )
    return mismatch


async def run(config: StudyConfig, provider: Provider | None = None) -> dict[str, object]:
    own_provider = provider is None
    provider = provider or OpenRouter(config.model)
    try:
        with Store(config.database) as store:
            plans = build_plan(config)
            level_indices = {value: index for index, value in enumerate(config.task.difficulties)}
            for plan in plans:
                store.add_instance(
                    plan.instance, config.name, level_indices[plan.instance.difficulty]
                )
            completed = store.completed_keys(config.name, config.model.record_id)
            remaining = [plan for plan in plans if plan.key not in completed]
            status = store.status(config.name, config.model.record_id)
            gate = BudgetGate(config.stop.max_spend_microdollars, status.spend_microdollars)
            reserve = config.model.estimated_microdollars(8_000, config.model.max_tokens)
            stop_reason = should_stop(status, config)

            while remaining and stop_reason is None:
                available = min(
                    config.concurrency,
                    config.stop.max_calls - status.calls,
                    len(remaining),
                )
                batch: list[CallPlan] = []
                for _ in range(available):
                    if not await gate.reserve(reserve):
                        stop_reason = "spend reserve would exceed cap"
                        break
                    batch.append(remaining.pop(0))
                if not batch:
                    break
                mismatches = await asyncio.gather(
                    *(
                        _run_call(plan, config, store, provider, gate, reserve)
                        for plan in batch
                    )
                )
                status = store.status(config.name, config.model.record_id)
                if any(mismatches):
                    stop_reason = "provider pin mismatch"
                    break
                stop_reason = should_stop(status, config)

            return {
                "status": status.as_dict(),
                "stop_reason": stop_reason or "plan exhausted",
                "remaining_calls": len(remaining),
            }
    finally:
        if own_provider:
            await provider.close()
