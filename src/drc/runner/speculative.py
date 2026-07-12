"""Trace-triggered speculative execution with an optional council fallback.

This is deliberately separate from the benchmark scheduler.  The scheduler
measures one model call at a time; this module controls several cancellable
candidate calls for one task.  Only the elected candidate may cross the
side-effect boundary supplied by the caller.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
import json
import re
import time
from typing import Awaitable, Callable, Protocol

from ..config import ModelCfg
from ..stats.tracefeat import BACKTRACK, GIVEUP, HEDGE, shingle_rep
from .client import TRClient


@dataclass(frozen=True)
class HandoffContext:
    """Serializable task state copied to challengers after a hedge trigger."""

    prompt: str
    messages: tuple[dict, ...] = ()
    tool_results: tuple[dict, ...] = ()
    files_read: tuple[str, ...] = ()
    workspace_revision: str = ""
    metadata: dict = field(default_factory=dict)

    def render(self) -> str:
        payload = {
            "messages": self.messages,
            "tool_results": self.tool_results,
            "files_read": self.files_read,
            "workspace_revision": self.workspace_revision,
            "metadata": self.metadata,
        }
        if not any(payload.values()):
            return self.prompt
        return (
            self.prompt
            + "\n\n<HANDOFF_CONTEXT>\n"
            + json.dumps(payload, sort_keys=True, default=str)
            + "\n</HANDOFF_CONTEXT>"
        )


@dataclass(frozen=True)
class RiskSnapshot:
    score: float
    words_seen: int
    consecutive: int
    triggered: bool
    markers: dict[str, float]


class TraceRiskPolicy:
    """Small auditable live-risk accumulator with persistence hysteresis.

    A lone hedge word never launches work.  The score is computed over a
    rolling reasoning window and must remain above threshold for more than
    one observation.  Thresholds are policy parameters, not validated model
    facts; they must be calibrated before production use.
    """

    def __init__(
        self,
        *,
        threshold: float = 4.0,
        persistence: int = 2,
        min_words: int = 80,
        window_words: int = 320,
    ):
        if threshold <= 0 or persistence < 1 or min_words < 0 or window_words < 24:
            raise ValueError("invalid trace-risk policy")
        self.threshold = float(threshold)
        self.persistence = int(persistence)
        self.min_words = int(min_words)
        self.window_words = int(window_words)
        self._words: list[str] = []
        self._consecutive = 0
        self._triggered = False

    def observe(self, text: str, channel: str = "reasoning") -> RiskSnapshot:
        if channel == "reasoning" and text:
            self._words.extend(text.split())
        window = " ".join(self._words[-self.window_words :])
        markers = {
            "backtrack": float(len(BACKTRACK.findall(window))),
            "hedge": float(len(HEDGE.findall(window))),
            "give_up": float(len(GIVEUP.findall(window))),
            "repetition": round(shingle_rep(window, k=4), 6),
        }
        score = (
            1.2 * min(markers["backtrack"], 4.0)
            + 0.8 * min(markers["hedge"], 4.0)
            + 2.5 * min(markers["give_up"], 2.0)
            + 2.0 * min(markers["repetition"] / 0.25, 1.0)
        )
        eligible = len(self._words) >= self.min_words and score >= self.threshold
        self._consecutive = self._consecutive + 1 if eligible else 0
        if self._consecutive >= self.persistence:
            self._triggered = True
        return RiskSnapshot(
            score=round(score, 6),
            words_seen=len(self._words),
            consecutive=self._consecutive,
            triggered=self._triggered,
            markers=markers,
        )


@dataclass
class CandidateResult:
    model: str
    text: str | None = None
    elapsed_ms: float = 0.0
    finish_reason: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cost_microdollars: int = 0
    provider_endpoint: str | None = None
    error: str | None = None


StreamObserver = Callable[[str, str, float], Awaitable[None]]


class CandidateRunner(Protocol):
    model: str

    async def run(
        self, context: HandoffContext, observer: StreamObserver | None = None
    ) -> CandidateResult: ...


class ModelCandidate:
    """CandidateRunner adapter for the repository's OpenAI-compatible client."""

    def __init__(self, client: TRClient, cfg: ModelCfg, temperature: float | None = None):
        self.client = client
        self.cfg = cfg
        self.temperature = temperature
        self.model = cfg.model_id

    async def run(
        self, context: HandoffContext, observer: StreamObserver | None = None
    ) -> CandidateResult:
        async def bridge(event: dict) -> None:
            if observer is not None:
                await observer(event["channel"], event["text"], float(event["elapsed_ms"]))

        result = await self.client.call(
            self.cfg,
            context.render(),
            temperature=self.temperature,
            stream_telemetry=True,
            stream_observer=bridge if observer is not None else None,
        )
        return CandidateResult(
            model=self.model,
            text=result.text,
            elapsed_ms=result.latency_ms,
            finish_reason=result.finish_reason,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            cost_microdollars=result.cost_microdollars,
            provider_endpoint=result.provider_endpoint,
            error=result.error,
        )


Verifier = Callable[[CandidateResult], Awaitable[bool]]
PauseHook = Callable[[HandoffContext, RiskSnapshot | None], Awaitable[None]]
CouncilJudge = Callable[[HandoffContext, list[CandidateResult]], Awaitable[CandidateResult | None]]


@dataclass
class SpeculativeResult:
    winner: CandidateResult | None
    trigger: RiskSnapshot | None
    completed: list[CandidateResult]
    cancel_requested: list[str]
    council_used: bool
    events: list[dict]

    @property
    def reported_cost_microdollars(self) -> int:
        total = sum(item.cost_microdollars for item in self.completed)
        if self.council_used and self.winner is not None:
            total += self.winner.cost_microdollars
        return total

    def as_dict(self) -> dict:
        return {
            "winner": asdict(self.winner) if self.winner else None,
            "trigger": asdict(self.trigger) if self.trigger else None,
            "completed": [asdict(item) for item in self.completed],
            "cancel_requested": self.cancel_requested,
            "unresolved_usage": list(self.cancel_requested),
            "reported_cost_microdollars": self.reported_cost_microdollars,
            "council_used": self.council_used,
            "events": self.events,
        }


class SpeculativeCouncil:
    """Run one primary, conditionally hedge, verify, then cancel losers."""

    def __init__(
        self,
        primary: CandidateRunner,
        challengers: list[CandidateRunner],
        *,
        policy: TraceRiskPolicy,
        verifier: Verifier,
        pause_side_effects: PauseHook | None = None,
        council_judge: CouncilJudge | None = None,
        fixed_delay_ms: float | None = None,
        trace_trigger_enabled: bool = True,
    ):
        if not challengers:
            raise ValueError("at least one challenger is required")
        names = [primary.model, *(runner.model for runner in challengers)]
        if len(names) != len(set(names)):
            raise ValueError("primary and challenger model names must be unique")
        self.primary = primary
        self.challengers = challengers
        self.policy = policy
        self.verifier = verifier
        self.pause_side_effects = pause_side_effects
        self.council_judge = council_judge
        if fixed_delay_ms is not None and fixed_delay_ms < 0:
            raise ValueError("fixed delay must be non-negative")
        self.fixed_delay_ms = fixed_delay_ms
        self.trace_trigger_enabled = trace_trigger_enabled

    async def run(self, context: HandoffContext) -> SpeculativeResult:
        started = time.perf_counter()
        completion_queue: asyncio.Queue[CandidateResult] = asyncio.Queue()
        tasks: dict[str, asyncio.Task] = {}
        completed: list[CandidateResult] = []
        processed_models: set[str] = set()
        events: list[dict] = []
        trigger: RiskSnapshot | None = None
        challengers_started = False
        side_effects_paused = False
        delay_task: asyncio.Task | None = None

        def stamp(event: str, **fields) -> None:
            events.append({
                "event": event,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                **fields,
            })

        async def execute(runner: CandidateRunner, observer: StreamObserver | None) -> None:
            t0 = time.perf_counter()
            try:
                result = await runner.run(context, observer)
            except asyncio.CancelledError:
                stamp("cancelled", model=runner.model)
                raise
            except Exception as exc:  # candidates fail independently
                result = CandidateResult(
                    model=runner.model,
                    error=f"{type(exc).__name__}: {exc}",
                )
            if not result.elapsed_ms:
                result.elapsed_ms = (time.perf_counter() - t0) * 1000
            await completion_queue.put(result)

        def start(runner: CandidateRunner, observer: StreamObserver | None = None) -> None:
            if runner.model in tasks:
                return
            stamp("candidate_started", model=runner.model)
            tasks[runner.model] = asyncio.create_task(execute(runner, observer))

        async def start_challengers(
            reason: str, snapshot: RiskSnapshot | None = None
        ) -> None:
            nonlocal challengers_started, side_effects_paused
            if challengers_started:
                return
            challengers_started = True
            if not side_effects_paused:
                if self.pause_side_effects:
                    await self.pause_side_effects(context, snapshot)
                side_effects_paused = True
                stamp("side_effects_paused", reason=reason)
            stamp("challengers_started", reason=reason)
            for runner in self.challengers:
                start(runner)

        async def observe(channel: str, text: str, elapsed_ms: float) -> None:
            nonlocal trigger
            snapshot = self.policy.observe(text, channel)
            if channel == "reasoning":
                stamp(
                    "risk_observed",
                    score=snapshot.score,
                    words_seen=snapshot.words_seen,
                    consecutive=snapshot.consecutive,
                    markers=snapshot.markers,
                    source_elapsed_ms=round(elapsed_ms, 3),
                )
            if snapshot.triggered and trigger is None:
                trigger = snapshot
                stamp(
                    "risk_triggered",
                    score=snapshot.score,
                    words_seen=snapshot.words_seen,
                    source_elapsed_ms=round(elapsed_ms, 3),
                )
                if self.trace_trigger_enabled:
                    await start_challengers("trace_risk", snapshot)

        start(self.primary, observe)
        if self.fixed_delay_ms is not None:
            async def delayed_launch() -> None:
                await asyncio.sleep(self.fixed_delay_ms / 1000.0)
                await start_challengers("fixed_delay")

            delay_task = asyncio.create_task(delayed_launch())
        winner: CandidateResult | None = None
        council_used = False
        while tasks:
            result = await completion_queue.get()
            completed.append(result)
            processed_models.add(result.model)
            stamp("candidate_completed", model=result.model, error=bool(result.error))
            if not result.error and await self.verifier(result):
                winner = result
                stamp("candidate_accepted", model=result.model)
                break
            stamp("candidate_rejected", model=result.model)
            if result.model == self.primary.model and not challengers_started:
                await start_challengers("primary_rejected")
            if len(processed_models) == len(tasks):
                break

        cancel_requested: list[str] = []
        if delay_task is not None and not delay_task.done():
            delay_task.cancel()
        if winner is not None:
            for model, task in tasks.items():
                if not task.done():
                    cancel_requested.append(model)
                    stamp("cancel_requested", model=model)
                    task.cancel()
            await asyncio.gather(*tasks.values(), return_exceptions=True)
            while not completion_queue.empty():
                extra = completion_queue.get_nowait()
                if extra.model not in processed_models:
                    completed.append(extra)
                    processed_models.add(extra.model)
                    stamp("candidate_completed_after_winner", model=extra.model, error=bool(extra.error))
        else:
            await asyncio.gather(*tasks.values(), return_exceptions=True)
            if self.council_judge and completed:
                council_used = True
                stamp("council_started", candidates=len(completed))
                winner = await self.council_judge(context, completed)
                if winner is not None and not await self.verifier(winner):
                    winner = None
                stamp("council_completed", accepted=winner is not None)
        if delay_task is not None:
            await asyncio.gather(delay_task, return_exceptions=True)

        return SpeculativeResult(
            winner=winner,
            trigger=trigger,
            completed=completed,
            cancel_requested=cancel_requested,
            council_used=council_used,
            events=events,
        )


def regex_verifier(pattern: str) -> Verifier:
    compiled = re.compile(pattern, re.S)

    async def verify(result: CandidateResult) -> bool:
        return bool(result.text and compiled.search(result.text))

    return verify


async def accept_first_complete(result: CandidateResult) -> bool:
    """Explicitly unsafe opt-in for latency experiments without a verifier."""
    return bool(result.text and not result.error and result.finish_reason not in {"length", "max_tokens"})
