"""Phase C: the router meets reality. Fresh never-seen SAT instances run
live through three policies via OpenRouter:

  A. always gpt-oss-20b (the replay's cheap champion)
  B. always o4-mini (the premium baseline)
  C. FormGuideRouter (cheapest-capable + mist retries + frontier escalation)

Reports realized solve rate and cost per solved, appended to
analysis/routing.json under "live_eval". Instances within a policy run
concurrently (the calls are minutes long each; sequential was a 10-hour
design), and results checkpoint to routing.json after every policy so a
dead process loses one policy at most.
"""

from __future__ import annotations

import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

from drc.tasks import sat  # noqa: E402
from drc_router import FormGuideRouter, Rung  # noqa: E402

PRICE = {  # $/1M (in, out) on OpenRouter, from its catalogue
    "openai/gpt-oss-20b": (0.04, 0.16),
    "openai/o4-mini": (1.1, 4.4),
    "anthropic/claude-fable-5": (9.9, 49.5),
}
KEY = re.search(r"sk-or-[A-Za-z0-9_-]+", (Path.home() / "src" / ".env-or").read_text()).group(0)
SPEND = {"usd": 0.0}
_SPEND_LOCK = threading.Lock()
CAP_USD = 18.0
WORKERS = 6


class CapReached(RuntimeError):
    pass


def or_completion(model: str, messages: list[dict], max_tokens: int = 32768, **kw) -> dict:
    with _SPEND_LOCK:
        if SPEND["usd"] >= CAP_USD:
            raise CapReached(f"live-eval cap ${CAP_USD} reached")
    slug = model.replace("openrouter/", "")
    body = {"model": slug, "messages": messages, "max_tokens": max_tokens}
    for attempt in range(4):
        try:
            r = httpx.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {KEY}"},
                json=body, timeout=600,
            )
            d = r.json()
            if "choices" in d:
                u = d.get("usage", {})
                pin, pout = PRICE.get(slug, (1.0, 5.0))
                cost = (u.get("prompt_tokens", 0) * pin + u.get("completion_tokens", 0) * pout) / 1e6
                with _SPEND_LOCK:
                    SPEND["usd"] += cost
                return d
        except Exception:
            pass
        time.sleep(5 * (attempt + 1))
    return {"choices": [{"message": {"content": ""}}], "usage": {"completion_tokens": 0}}


def checkpoint(results: dict, design: str, complete: bool) -> None:
    rj = ROOT / "analysis" / "routing.json"
    data = json.loads(rj.read_text())
    data["live_eval"] = {
        "design": design,
        "results": results,
        "total_spend_usd": round(SPEND["usd"], 3),
        "complete": complete,
    }
    rj.write_text(json.dumps(data, indent=2))


def main() -> int:
    levels = [3.0, 3.6, 4.2, 4.8, 5.3]
    per_level = 5
    instances = [
        sat.gen_instance(n_vars=20, alpha=a, master_seed=20260706, set_name="live-eval",
                         level_idx=li, index=i)
        for li, a in enumerate(levels) for i in range(per_level)
    ]
    design = f"{len(instances)} fresh instances, levels {levels}, via OpenRouter"
    print(f"{len(instances)} fresh instances; cap ${CAP_USD}; {WORKERS} workers", flush=True)

    rungs = [
        Rung(model="openai/gpt-oss-20b", frontier=4.63, sharpness=1.0,
             max_tokens=32768, price_out_per_m=0.16, retries=3),
        Rung(model="anthropic/claude-fable-5", frontier=7.2, sharpness=2.0,
             max_tokens=65536, price_out_per_m=49.5, retries=1),
    ]

    results: dict = {}

    def run_policy(name, attempt_fn):
        start_spend = SPEND["usd"]
        n = len(instances)

        def one(pair):
            i, inst = pair
            try:
                ok = attempt_fn(inst)
            except CapReached:
                return i, None
            print(f"  [{name}] {i + 1}/{n} alpha={inst.level_value} "
                  f"{'PASS' if ok else 'fail'} (spend ${SPEND['usd']:.2f})", flush=True)
            return i, ok

        outcomes: list[bool | None] = [None] * n
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            for i, ok in ex.map(one, enumerate(instances)):
                outcomes[i] = ok
        attempted = [o for o in outcomes if o is not None]
        solved = sum(1 for o in attempted if o)
        cost = SPEND["usd"] - start_spend
        results[name] = {
            "solved": f"{solved}/{len(attempted)}",
            "solve_rate": round(solved / max(len(attempted), 1), 3),
            "cost_usd": round(cost, 3),
            "cost_per_solved_usd": round(cost / max(solved, 1), 4),
        }
        if len(attempted) < n:
            results[name]["note"] = f"cap hit; {len(attempted)}/{n} attempted"
        print(name, results[name], flush=True)
        checkpoint(results, design, complete=False)

    def single(model, max_tokens=32768):
        def fn(inst):
            d = or_completion(model, [{"role": "user", "content": sat.render_prompt(inst)}], max_tokens)
            text = (d["choices"][0].get("message") or {}).get("content") or ""
            return sat.score(inst, text) == "pass"
        return fn

    run_policy("always_gpt_oss_20b", single("openai/gpt-oss-20b"))
    run_policy("always_o4_mini", single("openai/o4-mini"))

    def routed(inst):
        router = FormGuideRouter(
            rungs,
            verifier=lambda text, _inst=inst: sat.score(_inst, text) == "pass",
            completion_fn=or_completion,
        )
        resp = router.completion(
            [{"role": "user", "content": sat.render_prompt(inst)}],
            difficulty=inst.level_value,
        )
        text = (resp["choices"][0].get("message") or {}).get("content") or ""
        return sat.score(inst, text) == "pass"

    run_policy("formguide_router", routed)

    checkpoint(results, design, complete=True)
    print("appended live_eval to analysis/routing.json; total spend $", round(SPEND["usd"], 2), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
