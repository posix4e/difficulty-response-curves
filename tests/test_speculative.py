import asyncio

import pytest

from drc.runner.speculative import (
    CandidateResult,
    HandoffContext,
    SpeculativeCouncil,
    TraceRiskPolicy,
    regex_verifier,
)


class FakeRunner:
    def __init__(self, model, text, *, chunks=(), delay=0.0):
        self.model = model
        self.text = text
        self.chunks = chunks
        self.delay = delay
        self.started = False
        self.cancelled = False

    async def run(self, _context, observer=None):
        self.started = True
        try:
            for text in self.chunks:
                if observer:
                    await observer("reasoning", text, 10.0)
                await asyncio.sleep(0)
            await asyncio.sleep(self.delay)
            return CandidateResult(model=self.model, text=self.text, finish_reason="stop")
        except asyncio.CancelledError:
            self.cancelled = True
            raise


def test_risk_policy_requires_persistent_signal():
    policy = TraceRiskPolicy(threshold=4.0, persistence=2, min_words=10, window_words=100)
    first = policy.observe("ordinary progress " * 6 + "wait actually that's wrong not sure")
    assert first.score >= 4.0 and not first.triggered
    second = policy.observe("wait, actually, that's wrong and I am not sure")
    assert second.triggered and second.consecutive == 2


def test_single_hedge_word_does_not_launch():
    policy = TraceRiskPolicy(threshold=4.0, persistence=2, min_words=1)
    assert not policy.observe("maybe this is correct").triggered
    assert not policy.observe("continuing with the proof").triggered


def test_candidate_model_names_must_be_unique():
    with pytest.raises(ValueError, match="unique"):
        SpeculativeCouncil(
            FakeRunner("same", "a"),
            [FakeRunner("same", "b")],
            policy=TraceRiskPolicy(),
            verifier=regex_verifier("a"),
        )


@pytest.mark.asyncio
async def test_trace_trigger_launches_challengers_and_cancels_losers():
    primary = FakeRunner(
        "glm",
        "unfinished",
        chunks=(
            "ordinary progress " * 6 + "wait actually that's wrong not sure",
            "wait actually that's wrong and I am not sure",
        ),
        delay=0.2,
    )
    grok = FakeRunner("grok", "VALID fast answer", delay=0.01)
    openai = FakeRunner("openai", "VALID slow answer", delay=0.2)
    pauses = []

    async def pause(_context, snapshot):
        pauses.append(snapshot.score)

    result = await SpeculativeCouncil(
        primary,
        [grok, openai],
        policy=TraceRiskPolicy(threshold=4.0, persistence=2, min_words=10),
        verifier=regex_verifier(r"\bVALID\b"),
        pause_side_effects=pause,
    ).run(HandoffContext(prompt="solve"))

    assert result.winner and result.winner.model == "grok"
    assert result.trigger and pauses == [result.trigger.score]
    assert set(result.cancel_requested) == {"glm", "openai"}
    assert primary.cancelled and openai.cancelled
    risk_events = [event for event in result.events if event["event"] == "risk_observed"]
    assert len(risk_events) == 2
    assert risk_events[-1]["markers"]["backtrack"] >= 1


@pytest.mark.asyncio
async def test_primary_can_finish_without_fanout():
    primary = FakeRunner("glm", "VALID answer", chunks=("steady progress",))
    challenger = FakeRunner("grok", "VALID challenger")
    result = await SpeculativeCouncil(
        primary,
        [challenger],
        policy=TraceRiskPolicy(min_words=50),
        verifier=regex_verifier("VALID"),
    ).run(HandoffContext(prompt="solve"))
    assert result.winner and result.winner.model == "glm"
    assert not challenger.started
    assert result.trigger is None


@pytest.mark.asyncio
async def test_council_is_exception_path_after_rejections():
    primary = FakeRunner("glm", "bad")
    challenger = FakeRunner("grok", "also bad")

    async def judge(_context, candidates):
        assert {item.model for item in candidates} == {"glm", "grok"}
        return CandidateResult(model="judge", text="VALID synthesis", finish_reason="stop")

    result = await SpeculativeCouncil(
        primary,
        [challenger],
        policy=TraceRiskPolicy(min_words=50),
        verifier=regex_verifier("VALID"),
        council_judge=judge,
    ).run(HandoffContext(prompt="solve"))
    assert result.council_used
    assert result.winner and result.winner.model == "judge"


def test_handoff_context_is_structured_and_reproducible():
    context = HandoffContext(
        prompt="repair the bug",
        files_read=("src/a.py",),
        workspace_revision="abc123",
        metadata={"task": "coding"},
    )
    rendered = context.render()
    assert rendered.startswith("repair the bug")
    assert '"workspace_revision": "abc123"' in rendered
    assert '"files_read": ["src/a.py"]' in rendered


def test_hedge_cli_requires_verifier_and_honours_worst_case_cap(capsys):
    from drc.cli import main

    assert main(["hedge", "--prompt", "solve this", "--dry-run"]) == 2
    assert "refusing first-answer-wins" in capsys.readouterr().out
    assert main([
        "hedge", "--prompt", "solve this", "--accept-first", "--dry-run", "--cap", "0.001"
    ]) == 2
    assert "exceeds --cap" in capsys.readouterr().out


def test_hedge_cli_default_plan_is_dry_runnable(capsys):
    from drc.cli import main

    assert main(["hedge", "--prompt", "solve this", "--accept-regex", "ANSWER", "--dry-run"]) == 0
    output = capsys.readouterr().out
    assert '"primary": "or/glm-5"' in output
    assert '"or/grok-4-fast"' in output
    assert '"or/gpt-5.5"' in output
