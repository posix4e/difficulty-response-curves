"""Async job execution with per-model AIMD concurrency and budget admission.

Every completed call is written to the store immediately, so a killed
run resumes exactly where it stopped. The job queue is shuffled with a
fixed seed so time-of-day provider drift stays orthogonal to difficulty.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone

from ..config import ModelCfg
from ..tasks import families
from ..tasks.base import TASK_VERSION, Instance
from . import parse
from .budget import BudgetExceeded, BudgetGuard
from .client import CallResult, TRClient
from .store import Store

import os

PER_MODEL_START = int(os.environ.get("DRC_CONC_START", 10))
PER_MODEL_CAP = int(os.environ.get("DRC_CONC_CAP", 24))
GLOBAL_CAP = int(os.environ.get("DRC_CONC_GLOBAL", 48))
PROMPT_VERSION = 1


@dataclass
class Job:
    inst: Instance
    model_id: str
    sample_idx: int
    stage: str
    temperature: float | None = None
    stop_correct: int = 0
    stop_silent_wrong: int = 0
    required_provider_endpoint: str = ""
    stream_telemetry: bool = False


@dataclass
class _ModelState:
    limit: int = PER_MODEL_START
    active: int = 0
    streak: int = 0
    stopped: str = ""  # non-empty = stop reason
    correct: int = 0
    silent_wrong: int = 0


async def run_jobs(
    jobs: list[Job],
    models: dict[str, ModelCfg],
    client: TRClient,
    store: Store,
    budget: BudgetGuard,
    log=print,
    shuffle_seed: int = 12345,
) -> dict:
    rng = random.Random(shuffle_seed)
    jobs = list(jobs)
    rng.shuffle(jobs)

    queues: dict[str, deque[Job]] = {}
    for job in jobs:
        queues.setdefault(job.model_id, deque()).append(job)
    states = {m: _ModelState() for m in queues}
    for model_id, q in queues.items():
        if q:
            counts = store.outcome_counts(q[0].stage, model_id)
            states[model_id].correct = counts["correct"]
            states[model_id].silent_wrong = counts["silent_wrong"]
    active_tasks: dict[asyncio.Task, tuple[Job, str]] = {}
    done_count = 0
    total = len(jobs)
    last_report = 0

    def fallback_est(model_id: str) -> int:
        cfg = models[model_id]
        return cfg.pricetable_microdollars(1200, 4000)

    def dispatch() -> None:
        for model_id, q in queues.items():
            st = states[model_id]
            while q and not st.stopped and st.active < st.limit and len(active_tasks) < GLOBAL_CAP:
                job = q.popleft()
                est = budget.p95_estimate(model_id, fallback_est(model_id))
                try:
                    token = budget.admit(job.stage, model_id, est)
                except BudgetExceeded as e:
                    st.stopped = str(e)
                    log(f"[budget] {model_id} stopped: {e}")
                    q.clear()
                    break
                st.active += 1
                task = asyncio.create_task(_run_one(client, models[job.model_id], job))
                active_tasks[task] = (job, token)

    dispatch()
    while active_tasks:
        done, _ = await asyncio.wait(active_tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            job, token = active_tasks.pop(task)
            budget.release(token)
            st = states[job.model_id]
            st.active -= 1
            try:
                result: CallResult = task.result()
            except Exception as e:  # defensive: record as error_api
                result = CallResult(error=f"scheduler exception: {type(e).__name__}: {e}")
            outcome = _record(store, models[job.model_id], job, result)
            budget.note_cost(job.model_id, result.cost_microdollars)
            if outcome == "pass":
                st.correct += 1
            elif outcome == "fail_wrong":
                st.silent_wrong += 1
            if (
                job.required_provider_endpoint
                and not result.error
                and result.provider_endpoint != job.required_provider_endpoint
            ):
                st.stopped = (
                    f"protocol deviation: expected {job.required_provider_endpoint}, "
                    f"received {result.provider_endpoint or 'no endpoint'}"
                )
                queues[job.model_id].clear()
                log(f"[protocol] {job.model_id} stopped: {st.stopped}")
            elif (
                job.stop_correct
                and job.stop_silent_wrong
                and st.correct >= job.stop_correct
                and st.silent_wrong >= job.stop_silent_wrong
            ):
                st.stopped = (
                    f"label target reached: {st.correct} correct, "
                    f"{st.silent_wrong} silently wrong"
                )
                queues[job.model_id].clear()
                log(f"[protocol] {job.model_id} stopped: {st.stopped}")
            if result.error or result.attempts > 1:
                st.limit = max(2, st.limit // 2)
                st.streak = 0
            else:
                st.streak += 1
                if st.streak % 10 == 0:
                    st.limit = min(PER_MODEL_CAP, st.limit + 1)
            done_count += 1
            if done_count - last_report >= 25 or done_count == total:
                last_report = done_count
                s = budget.summary()
                log(
                    f"[{datetime.now().strftime('%H:%M:%S')}] {done_count}/{total} done, "
                    f"${s['spent_usd']:.2f} spent (${s['inflight_reserved_usd']:.2f} reserved)"
                )
        dispatch()

    stopped = {m: st.stopped for m, st in states.items() if st.stopped}
    return {"done": done_count, "total": total, "stopped": stopped, "spent": budget.summary()}


async def _run_one(client: TRClient, cfg: ModelCfg, job: Job) -> CallResult:
    prompt = families.render_prompt(job.inst)
    return await client.call(
        cfg, prompt, temperature=job.temperature, stream_telemetry=job.stream_telemetry
    )


def _record(store: Store, cfg: ModelCfg, job: Job, result: CallResult) -> str:
    prompt = families.render_prompt(job.inst)
    if result.error:
        outcome = "error_api"
        parsed = None
    else:
        outcome = parse.classify(job.inst, result.text, result.finish_reason)
        parsed = parse.extract_parsed(job.inst, result.text or "")
    pinned = 1 if cfg.provider_only else 0
    mismatch = 0
    if pinned and result.provider_endpoint:
        if "@" in result.provider_endpoint:
            provider = result.provider_endpoint.split("@", 1)[1].split("/", 1)[0]
        elif "/" in result.provider_endpoint:
            provider = result.provider_endpoint.rsplit("/", 1)[-1]
        else:
            provider = result.provider_endpoint
        mismatch = 0 if provider.casefold() in {p.casefold() for p in cfg.provider_only} else 1
    now = datetime.now(timezone.utc)
    call_id = store.record_call(
        {
            "instance_id": job.inst.instance_id,
            "model_id": job.model_id,
            "sample_idx": job.sample_idx,
            "stage": job.stage,
            "api_path": cfg.api_path,
            "prompt_version": PROMPT_VERSION,
            "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "request_json": json.dumps(
                {
                    "max_completion_tokens": cfg.max_completion_tokens,
                    "temperature": job.temperature,
                    "provider_only": list(cfg.provider_only),
                    "thinking_budget": cfg.thinking_budget or None,
                    "stream_telemetry": job.stream_telemetry,
                }
            ),
            "response_text": result.text if not result.error else result.error,
            "finish_reason": result.finish_reason,
            "parsed_answer": parsed,
            "outcome": outcome,
            "pass": 1 if outcome == "pass" else 0,
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
            "reasoning_tokens": result.reasoning_tokens,
            "cost_microdollars": result.cost_microdollars,
            "cost_source": result.cost_source,
            "provider_endpoint": result.provider_endpoint,
            "provider_pinned": pinned,
            "provider_mismatch": mismatch,
            "http_status": result.http_status,
            "attempt": result.attempts,
            "latency_ms": result.latency_ms,
            "ttft_ms": result.ttft_ms,
            "first_reasoning_ms": result.first_reasoning_ms,
            "first_answer_ms": result.first_answer_ms,
            "stream_duration_ms": result.stream_duration_ms,
            "observed_chars": result.observed_chars,
            "ts_start": (now).isoformat(timespec="seconds"),
            "ts_end": now.isoformat(timespec="seconds"),
        }
    )
    store.record_stream_events(call_id, result.stream_events)
    return outcome
