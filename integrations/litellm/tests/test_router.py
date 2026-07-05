import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from drc_router import FormGuideRouter, Rung


def make_mock(script):
    """script: dict model -> list of (content, tokens) returned in order."""
    counters = {}

    def completion(model, messages, **kw):
        i = counters.get(model, 0)
        counters[model] = i + 1
        content, tokens = script[model][min(i, len(script[model]) - 1)]
        return {
            "choices": [{"message": {"content": content}}],
            "usage": {"completion_tokens": tokens},
        }

    completion.counters = counters
    return completion


RUNGS = [
    Rung(model="cheap", frontier=4.6, sharpness=1.0, max_tokens=1000, price_out_per_m=0.2),
    Rung(model="strong", frontier=6.6, sharpness=1.3, max_tokens=2000, price_out_per_m=33.0),
]


def test_accepts_first_pass_no_escalation():
    mock = make_mock({"cheap": [("ANSWER: ok", 50)], "strong": [("ANSWER: ok", 50)]})
    r = FormGuideRouter(RUNGS, verifier=lambda t: "ok" in t, completion_fn=mock)
    resp = r.completion([{"role": "user", "content": "q"}])
    assert mock.counters == {"cheap": 1}
    assert r.trace[-1]["accepted"]


def test_mist_retry_same_rung_before_escalating():
    mock = make_mock({"cheap": [("bad", 900), ("bad", 900), ("ANSWER: ok", 60)],
                      "strong": [("ANSWER: ok", 50)]})
    r = FormGuideRouter(RUNGS, verifier=lambda t: "ok" in t, completion_fn=mock)
    r.completion([{"role": "user", "content": "q"}])
    assert mock.counters == {"cheap": 3}  # solved on retry 3, never escalated


def test_escalates_after_retries_spent():
    mock = make_mock({"cheap": [("bad", 900)] * 3, "strong": [("ANSWER: ok", 70)]})
    r = FormGuideRouter(RUNGS, verifier=lambda t: "ok" in t, completion_fn=mock)
    r.completion([{"role": "user", "content": "q"}])
    assert mock.counters == {"cheap": 3, "strong": 1}
    assert r.trace[-1]["rung"] == "strong" and r.trace[-1]["accepted"]


def test_difficulty_skips_incapable_rungs():
    mock = make_mock({"cheap": [("ANSWER: ok", 50)], "strong": [("ANSWER: ok", 50)]})
    r = FormGuideRouter(RUNGS, verifier=lambda t: "ok" in t, completion_fn=mock)
    r.completion([{"role": "user", "content": "q"}], difficulty=6.0)
    assert mock.counters == {"strong": 1}  # 6.0 > cheap frontier 4.6 + margin


def test_cheapest_capable_wins_even_with_lower_frontier_rungs():
    # real-world shape: the expensive model has the LOWER frontier
    rungs = [
        Rung(model="pricey-weak", frontier=3.3, sharpness=2, max_tokens=1000, price_out_per_m=4.84),
        Rung(model="cheap-strong", frontier=4.6, sharpness=1, max_tokens=1000, price_out_per_m=0.22),
    ]
    mock = make_mock({"cheap-strong": [("ANSWER: ok", 10)], "pricey-weak": [("ANSWER: ok", 10)]})
    r = FormGuideRouter(rungs, verifier=lambda t: "ok" in t, completion_fn=mock)
    r.completion([{"role": "user", "content": "q"}], difficulty=3.0)
    assert mock.counters == {"cheap-strong": 1}  # cheapest capable, not lowest-frontier


def test_no_verifier_single_attempt():
    mock = make_mock({"cheap": [("whatever", 10)]})
    r = FormGuideRouter(RUNGS, verifier=None, completion_fn=mock)
    r.completion([{"role": "user", "content": "q"}])
    assert mock.counters == {"cheap": 1}


def test_both_token_spellings_sent():
    seen = {}

    def completion(model, messages, **kw):
        seen.update(kw)
        return {"choices": [{"message": {"content": "ANSWER: ok"}}],
                "usage": {"completion_tokens": 5}}

    r = FormGuideRouter(RUNGS, verifier=lambda t: True, completion_fn=completion)
    r.completion([{"role": "user", "content": "q"}])
    assert seen["max_tokens"] == 1000 and seen["max_completion_tokens"] == 1000
