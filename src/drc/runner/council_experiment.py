"""Four-arm comparison for model councils and speculative hedging."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
from pathlib import Path
import random
import time
from typing import Callable, Sequence

from .speculative import (
    CandidateResult,
    CandidateRunner,
    CouncilJudge,
    HandoffContext,
    PauseHook,
    SpeculativeCouncil,
    TraceRiskPolicy,
    Verifier,
)


SCHEMA_VERSION = "speculative-council-experiment-v1"


class Arm(str, Enum):
    PRIMARY_ONLY = "primary_only"
    ALWAYS_COUNCIL = "always_on_council"
    FIXED_DELAY = "fixed_delay_hedge"
    TRACE_TRIGGERED = "trace_triggered_hedge"


@dataclass
class ArmResult:
    arm: str
    winner: CandidateResult | None
    verified: bool
    wall_ms: float
    reported_cost_microdollars: int
    unresolved_usage: list[str]
    completed: list[CandidateResult]
    events: list[dict]

    def as_dict(self) -> dict:
        return {
            "arm": self.arm,
            "winner": asdict(self.winner) if self.winner else None,
            "verified": self.verified,
            "wall_ms": round(self.wall_ms, 3),
            "reported_cost_microdollars": self.reported_cost_microdollars,
            "unresolved_usage": self.unresolved_usage,
            "completed": [asdict(item) for item in self.completed],
            "events": self.events,
        }


@dataclass
class ExperimentResult:
    task_id: str
    seed: int
    arm_order: list[str]
    fixed_delay_ms: float
    context_sha256: str
    arms: list[ArmResult]
    plan: dict

    def as_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "task_id": self.task_id,
            "seed": self.seed,
            "arm_order": self.arm_order,
            "fixed_delay_ms": self.fixed_delay_ms,
            "context_sha256": self.context_sha256,
            "plan": self.plan,
            "arms": [arm.as_dict() for arm in self.arms],
        }


RunnerFactory = Callable[[str], CandidateRunner]
PolicyFactory = Callable[[], TraceRiskPolicy]


class FourArmExperiment:
    """Run matched task context through the four registered control arms.

    Arms run sequentially in deterministic randomized order so one provider
    burst does not always favour the same policy. Candidate calls within an
    arm retain their intended concurrency.
    """

    def __init__(
        self,
        *,
        runner_factory: RunnerFactory,
        primary_model: str,
        challenger_models: Sequence[str],
        judge: CouncilJudge,
        verifier: Verifier,
        policy_factory: PolicyFactory,
        fixed_delay_ms: float,
        pause_side_effects: PauseHook | None = None,
    ):
        if fixed_delay_ms < 0:
            raise ValueError("fixed delay must be non-negative")
        names = [primary_model, *challenger_models]
        if len(names) != len(set(names)):
            raise ValueError("candidate model names must be unique")
        self.runner_factory = runner_factory
        self.primary_model = primary_model
        self.challenger_models = list(challenger_models)
        self.judge = judge
        self.verifier = verifier
        self.policy_factory = policy_factory
        self.fixed_delay_ms = float(fixed_delay_ms)
        self.pause_side_effects = pause_side_effects

    def _candidates(self) -> tuple[CandidateRunner, list[CandidateRunner]]:
        return (
            self.runner_factory(self.primary_model),
            [self.runner_factory(model) for model in self.challenger_models],
        )

    async def _primary_only(self, context: HandoffContext) -> ArmResult:
        runner = self.runner_factory(self.primary_model)
        started = time.perf_counter()
        result = await runner.run(context)
        verified = bool(not result.error and await self.verifier(result))
        wall_ms = (time.perf_counter() - started) * 1000
        return ArmResult(
            arm=Arm.PRIMARY_ONLY.value,
            winner=result if verified else None,
            verified=verified,
            wall_ms=wall_ms,
            reported_cost_microdollars=result.cost_microdollars,
            unresolved_usage=[],
            completed=[result],
            events=[{
                "event": "primary_completed",
                "elapsed_ms": round(wall_ms, 3),
                "verified": verified,
            }],
        )

    async def _always_council(self, context: HandoffContext) -> ArmResult:
        runners = [self.runner_factory(self.primary_model)] + [
            self.runner_factory(model) for model in self.challenger_models
        ]
        started = time.perf_counter()

        async def one(runner: CandidateRunner) -> CandidateResult:
            try:
                return await runner.run(context)
            except Exception as exc:
                return CandidateResult(
                    model=runner.model, error=f"{type(exc).__name__}: {exc}"
                )

        completed = await asyncio.gather(*(one(runner) for runner in runners))
        judge_result = await self.judge(context, list(completed))
        verified = bool(
            judge_result is not None
            and not judge_result.error
            and await self.verifier(judge_result)
        )
        wall_ms = (time.perf_counter() - started) * 1000
        reported = sum(item.cost_microdollars for item in completed)
        if judge_result is not None:
            reported += judge_result.cost_microdollars
        return ArmResult(
            arm=Arm.ALWAYS_COUNCIL.value,
            winner=judge_result if verified else None,
            verified=verified,
            wall_ms=wall_ms,
            reported_cost_microdollars=reported,
            unresolved_usage=[],
            completed=list(completed),
            events=[
                {"event": "council_candidates_completed", "count": len(completed)},
                {"event": "council_judge_completed", "verified": verified},
            ],
        )

    async def _hedge(
        self, context: HandoffContext, arm: Arm
    ) -> ArmResult:
        primary, challengers = self._candidates()
        trace_enabled = arm is Arm.TRACE_TRIGGERED
        started = time.perf_counter()
        result = await SpeculativeCouncil(
            primary,
            challengers,
            policy=self.policy_factory(),
            verifier=self.verifier,
            pause_side_effects=self.pause_side_effects,
            council_judge=self.judge,
            fixed_delay_ms=self.fixed_delay_ms if arm is Arm.FIXED_DELAY else None,
            trace_trigger_enabled=trace_enabled,
        ).run(context)
        wall_ms = (time.perf_counter() - started) * 1000
        return ArmResult(
            arm=arm.value,
            winner=result.winner,
            verified=result.winner is not None,
            wall_ms=wall_ms,
            reported_cost_microdollars=result.reported_cost_microdollars,
            unresolved_usage=list(result.cancel_requested),
            completed=result.completed,
            events=result.events,
        )

    async def run(
        self,
        context: HandoffContext,
        *,
        task_id: str,
        seed: int = 20260712,
        arms: Sequence[Arm] = tuple(Arm),
        plan: dict | None = None,
    ) -> ExperimentResult:
        order = list(arms)
        random.Random(seed).shuffle(order)
        results: list[ArmResult] = []
        for arm in order:
            if arm is Arm.PRIMARY_ONLY:
                results.append(await self._primary_only(context))
            elif arm is Arm.ALWAYS_COUNCIL:
                results.append(await self._always_council(context))
            else:
                results.append(await self._hedge(context, arm))
        context_hash = hashlib.sha256(context.render().encode()).hexdigest()
        result = ExperimentResult(
            task_id=task_id,
            seed=seed,
            arm_order=[arm.value for arm in order],
            fixed_delay_ms=self.fixed_delay_ms,
            context_sha256=context_hash,
            arms=results,
            plan=plan or {},
        )
        validate_experiment_result(result.as_dict())
        return result


def validate_experiment_result(payload: dict) -> None:
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unknown experiment schema")
    order = payload.get("arm_order") or []
    arms = payload.get("arms") or []
    if len(order) != len(set(order)) or {item.get("arm") for item in arms} != set(order):
        raise ValueError("arm order and arm results do not match")
    for item in arms:
        if item.get("verified") and not item.get("winner"):
            raise ValueError("verified arm is missing a winner")
        if item.get("unresolved_usage") is None:
            raise ValueError("usage resolution must be explicit")


def write_experiment_result(path: Path, result: ExperimentResult) -> None:
    payload = result.as_dict()
    validate_experiment_result(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n")
    temporary.replace(path)
