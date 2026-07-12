import os
import re

import pytest

from drc.config import load_config
from drc.runner import BudgetGate, provider_matches, run, should_stop
from drc.sat import solve
from drc.store import Store
from drc.types import ProviderResponse, StudyStatus, Usage


class FakeProvider:
    def __init__(self, provider: str = "Parasail"):
        self.provider = provider
        self.calls = 0

    async def complete(self, prompt: str) -> ProviderResponse:
        self.calls += 1
        clauses = []
        for line in prompt.splitlines():
            if re.fullmatch(r"-?\d+ -?\d+ -?\d+", line):
                clauses.append(tuple(map(int, line.split())))
        variables = max(abs(value) for clause in clauses for value in clause)
        assignment = solve(clauses, variables)
        assert assignment is not None
        bits = " ".join("1" if value else "0" for value in assignment)
        return ProviderResponse(
            text=f"FINAL: {bits}",
            finish_reason="stop",
            provider=self.provider,
            usage=Usage(prompt_tokens=20, completion_tokens=10, cost_microdollars=100),
            latency_ms=10,
        )

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_budget_gate_accounts_for_reservations():
    gate = BudgetGate(cap=100, spent=20)
    assert await gate.reserve(60)
    assert not await gate.reserve(30)
    await gate.settle(60, 40)
    assert gate.spent == 60
    assert await gate.reserve(40)


@pytest.mark.asyncio
async def test_budget_gate_can_be_explicitly_unlimited():
    gate = BudgetGate(cap=None, spent=10_000_000)
    assert await gate.reserve(10**12)


def test_provider_pin_matching_is_explicit():
    assert provider_matches("openrouter/Parasail", "Parasail")
    assert not provider_matches("Other", "Parasail")
    assert not provider_matches("", "Parasail")


def test_stopping_rules_are_hard(study_config):
    assert should_stop(StudyStatus(2, 0, 0, 2, 0), study_config) == "call cap reached"
    assert should_stop(StudyStatus(0, 0, 0, 0, 1_000_000), study_config) == "spend cap reached"


def test_explicit_unlimited_spend_does_not_stop_on_cost():
    config = load_config("configs/glm-5.2-frontier-256k-siliconflow.toml")
    assert should_stop(StudyStatus(1, 0, 0, 1, 10**12), config) is None


@pytest.mark.asyncio
async def test_runner_records_and_resumes(monkeypatch, study_config):
    monkeypatch.setenv("TEST_OPENROUTER_KEY", "test")
    provider = FakeProvider()
    first = await run(study_config, provider)
    assert first["status"]["calls"] == 2
    assert first["status"]["correct"] == 2
    assert provider.calls == 2
    second = await run(study_config, provider)
    assert second["status"]["calls"] == 2
    assert provider.calls == 2


@pytest.mark.asyncio
async def test_provider_mismatch_stops_admission(monkeypatch, study_config):
    monkeypatch.setenv("TEST_OPENROUTER_KEY", "test")
    provider = FakeProvider("Other")
    result = await run(study_config, provider)
    assert result["stop_reason"] == "provider pin mismatch"
    with Store(study_config.database) as store:
        assert store.status(study_config.name, study_config.model.record_id).loud == 2
