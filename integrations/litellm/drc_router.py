"""Form-guide routing for LiteLLM: pick models by measured frontier, retry
inside the mist, escalate only past a rung's frontier, give budget-elastic
models their tokens.

Every rule here traces to a measured finding (see the paper / site):

- rungs are ordered by *frontier on the task family*, not price — in our
  replay, "premium" models solved half as much as a cheap open model at
  17x the cost per solve;
- failures near a rung's frontier are coin-flips, so the first response
  to failure is retry-same-rung (retry x3 beat every cascade we replayed);
- escalation happens when the verifier keeps failing or the request's
  difficulty estimate sits past the rung's frontier;
- each rung carries its own max_tokens: budget-elastic models (e.g.
  MiniMax) lose whole difficulty bands when capped tight;
- calibrations expire (same-day endpoint drift is in our data): recalibrate
  with `drc adaptive` (see recalibrate.py) on a schedule.

Usage (LiteLLM):

    import litellm
    from drc_router import FormGuideRouter

    router = FormGuideRouter.from_config("formguide.json",
                                         verifier=my_check_fn)  # optional
    resp = router.completion(messages=[...], difficulty=4.2)    # difficulty optional

`verifier(text) -> bool` is your domain's answer checker. Without one, the
router still ranks rungs by frontier and applies budget policy, but cannot
retry-on-failure (there is nothing trustworthy to retry on: per-call token
signals do NOT grade a single answer -- we measured that too, AUC ~0.5).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


@dataclass
class Rung:
    model: str  # litellm model string, e.g. "openrouter/openai/gpt-oss-20b"
    frontier: float  # calibrated x50 on your task family's difficulty scale
    sharpness: float
    max_tokens: int  # budget this rung needs (elastic models need more)
    price_out_per_m: float
    retries: int = 3  # mist-aware: retry same rung before escalating
    calibrated_at: str = ""  # ISO date; stale calibrations should be re-probed
    notes: str = ""


class FormGuideRouter:
    def __init__(
        self,
        rungs: list[Rung],
        verifier: Callable[[str], bool] | None = None,
        completion_fn: Callable[..., Any] | None = None,
        mist_margin: float = 0.5,
    ):
        """rungs are sorted by frontier ascending; routing picks the first
        rung whose frontier covers the request's difficulty (when given),
        else starts at the cheapest rung. mist_margin widens the band where
        retries are considered worthwhile."""
        self.rungs = sorted(rungs, key=lambda r: r.frontier)
        self.verifier = verifier
        self.mist_margin = mist_margin
        if completion_fn is None:
            import litellm  # deferred so tests can inject a mock

            completion_fn = litellm.completion
        self._completion = completion_fn
        self.trace: list[dict] = []  # decision log of the last call

    @classmethod
    def from_config(cls, path: str | Path, **kw) -> "FormGuideRouter":
        cfg = json.loads(Path(path).read_text())
        rungs = [Rung(**r) for r in cfg["rungs"]]
        return cls(rungs, **kw)

    # -- core policy ---------------------------------------------------------

    def _ladder(self, difficulty: float | None) -> list[Rung]:
        """Cost and frontier need not be correlated (in our measurements the
        cheap open models out-frontiered the premium ones), so: start at the
        CHEAPEST rung whose frontier covers the difficulty, then escalate
        only to rungs with strictly higher frontiers, cheapest first at each
        frontier level."""
        capable = [r for r in self.rungs if difficulty is None
                   or r.frontier + self.mist_margin >= difficulty]
        if not capable:
            capable = [max(self.rungs, key=lambda r: r.frontier)]
        start = min(capable, key=lambda r: r.price_out_per_m)
        ladder = [start] + sorted(
            (r for r in self.rungs if r.frontier > start.frontier),
            key=lambda r: (r.frontier, r.price_out_per_m),
        )
        return ladder

    def completion(self, messages: list[dict], difficulty: float | None = None, **kw) -> Any:
        """Try rungs from the cheapest capable one upward. Within a rung,
        retry on verifier failure (the mist). Escalate when retries are
        spent. Returns the first accepted response (or the last attempt)."""
        self.trace = []
        last = None
        for rung in self._ladder(difficulty):
            attempts = rung.retries if self.verifier else 1
            for attempt in range(1, attempts + 1):
                t0 = time.time()
                resp = self._completion(
                    model=rung.model,
                    messages=messages,
                    max_tokens=rung.max_tokens,
                    max_completion_tokens=rung.max_tokens,  # both spellings: gateways drop one
                    **kw,
                )
                last = resp
                text = _content(resp)
                ok = self.verifier(text) if self.verifier else True
                self.trace.append(
                    {
                        "rung": rung.model,
                        "attempt": attempt,
                        "accepted": bool(ok),
                        "tokens": _tokens(resp),
                        "seconds": round(time.time() - t0, 1),
                    }
                )
                if ok:
                    return resp
            # retries spent on this rung: escalate
        return last

    # -- introspection ---------------------------------------------------------

    def explain(self) -> str:
        return json.dumps(self.trace, indent=2)


def _content(resp: Any) -> str:
    try:
        return resp["choices"][0]["message"]["content"] or ""
    except Exception:
        try:
            return resp.choices[0].message.content or ""
        except Exception:
            return ""


def _tokens(resp: Any) -> int | None:
    try:
        return resp["usage"]["completion_tokens"]
    except Exception:
        try:
            return resp.usage.completion_tokens
        except Exception:
            return None
