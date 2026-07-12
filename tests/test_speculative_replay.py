import json

import pytest

from drc.runner.council_experiment import (
    Arm,
    FourArmExperiment,
    validate_experiment_result,
    write_experiment_result,
)
from drc.runner.speculative import (
    CandidateResult,
    HandoffContext,
    TraceRiskPolicy,
    regex_verifier,
)
from drc.stats.speculative_replay import (
    matched_fixed_delay,
    replay_reasoning,
    summarize_replay,
    visible_reasoning,
)


def policy_factory():
    return TraceRiskPolicy(threshold=4.0, persistence=2, min_words=10)


def test_visible_reasoning_requires_explicit_trace_channel():
    assert visible_reasoning("ANSWER: 1") is None
    assert visible_reasoning("<think>wait and retry</think>ANSWER: 1") == "wait and retry"


def test_word_chunk_proxy_replay_records_trigger_position():
    reasoning = (
        "ordinary progress " * 8
        + " wait actually that's wrong not sure "
        + " wait actually that's wrong not sure"
    )
    result = replay_reasoning(reasoning, policy_factory, chunk_words=12)
    assert result["triggered"]
    assert 0 < result["trigger_fraction"] <= 1
    assert result["trigger"]["markers"]["backtrack"] >= 1


def test_replay_summary_is_censored_without_real_timestamps():
    rows = []
    for index in range(20):
        rows.append({
            "outcome_class": "correct_completed" if index < 10 else "silently_wrong_completed",
            "triggered": index >= 5,
            "trigger_fraction": 0.5 if index >= 5 else None,
            "latency_ms": 100_000 + index,
        })
    report = summarize_replay(rows)
    assert report["status"] == "Censored"
    assert report["gate_pass"] is False
    assert report["trace_trigger"]["silent_wrong_recall"] == 1.0
    assert report["matched_fixed_delay"]["available"]


def test_fixed_delay_matches_requested_launch_rate_approximately():
    rows = [
        {"latency_ms": value, "outcome_class": "correct_completed" if value < 8 else "loud_failure"}
        for value in range(1, 11)
    ]
    result = matched_fixed_delay(rows, 0.3)
    assert result["available"]
    assert result["launch_rate"] == 0.3


class ExperimentRunner:
    def __init__(self, model):
        self.model = model

    async def run(self, _context, observer=None):
        if observer and self.model == "glm":
            await observer("reasoning", "ordinary " * 12 + "wait actually that's wrong not sure", 5.0)
            await observer("reasoning", "wait actually that's wrong not sure", 10.0)
        text = "bad primary" if self.model == "glm" else "VALID candidate"
        return CandidateResult(
            model=self.model,
            text=text,
            finish_reason="stop",
            cost_microdollars=10,
        )


@pytest.mark.asyncio
async def test_four_arm_experiment_runs_registered_comparison(tmp_path):
    pauses = []

    async def pause(_context, snapshot):
        pauses.append(snapshot.score if snapshot else None)

    async def judge(_context, candidates):
        assert candidates
        return CandidateResult(
            model="judge", text="VALID synthesis", finish_reason="stop", cost_microdollars=5
        )

    experiment = FourArmExperiment(
        runner_factory=ExperimentRunner,
        primary_model="glm",
        challenger_models=["grok", "openai"],
        judge=judge,
        verifier=regex_verifier("VALID"),
        policy_factory=policy_factory,
        fixed_delay_ms=0,
        pause_side_effects=pause,
    )
    result = await experiment.run(
        HandoffContext(prompt="solve"), task_id="task-1", seed=7
    )
    payload = result.as_dict()
    assert set(payload["arm_order"]) == {arm.value for arm in Arm}
    assert {item["arm"] for item in payload["arms"]} == set(payload["arm_order"])
    by_arm = {item["arm"]: item for item in payload["arms"]}
    assert not by_arm[Arm.PRIMARY_ONLY.value]["verified"]
    assert by_arm[Arm.ALWAYS_COUNCIL.value]["winner"]["model"] == "judge"
    assert by_arm[Arm.FIXED_DELAY.value]["verified"]
    assert by_arm[Arm.TRACE_TRIGGERED.value]["verified"]
    assert len(pauses) == 2

    output = tmp_path / "experiment.json"
    write_experiment_result(output, result)
    saved = json.loads(output.read_text())
    validate_experiment_result(saved)
    assert saved["schema_version"] == "speculative-council-experiment-v1"


def test_experiment_schema_rejects_missing_arm():
    with pytest.raises(ValueError, match="do not match"):
        validate_experiment_result({
            "schema_version": "speculative-council-experiment-v1",
            "arm_order": ["primary_only"],
            "arms": [],
        })


def test_council_experiment_cli_dry_run_and_cap(capsys):
    from drc.cli import main

    base = [
        "council-experiment", "--prompt", "solve", "--task-id", "t1",
        "--accept-regex", "ANSWER", "--dry-run",
    ]
    assert main(base) == 0
    output = capsys.readouterr().out
    assert '"always_on_council"' in output
    assert '"authorized_worst_case_usd"' in output
    assert main([*base, "--cap", "0.01"]) == 2
    assert "exceeds --cap" in capsys.readouterr().out
