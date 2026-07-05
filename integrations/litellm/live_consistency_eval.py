"""Round 5, live arm: the consistency router meets fresh synthesis puzzles.

Four arms, synth family only (the unique-answer family that motivates the
round; SAT's multiplicity verdict is already published):

  A. always_cheap        - one R1 call
  B. always_premium      - one GPT-5.5 call
  C. consistency_router  - two R1 calls; if their programs agree
                           functionally on 8 seeded probe inputs, ship;
                           else escalate to the closer (terminal, one
                           attempt). No trace judge, no ground truth.
  D. quota_random        - escalates exactly as many instances as C
                           realized, chosen by seeded draw (the round-2
                           control's rate-matching flaw, fixed).

Per-instance records (agreement bit, escalated, outcome, cost) land in
analysis/routing3.json so counterfactuals stay possible afterwards -
round 2's other lesson.

Pre-registered bar (plan 2026-07-08): C beats D on solve rate at equal
escalation count AND beats both single arms on solve rate at $/solve
below B. Runs only after the congate offline gate passes.
"""

from __future__ import annotations

import json
import random
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
sys.path.insert(0, str(ROOT / "analysis"))

from drc.tasks import code, synth  # noqa: E402
from consistency_synth import probe_inputs, run_program  # noqa: E402

OR_KEY = re.search(r"sk-or-[A-Za-z0-9_-]+", (Path.home() / "src" / ".env-or").read_text()).group(0)

CHEAP = {"model": "deepseek/deepseek-r1-0528", "pin": "deepinfra", "price": (0.5, 2.18)}
CLOSER = {"model": "openai/gpt-5.5", "pin": None, "price": (5.5, 33.0)}
LEVELS = [1, 2, 3, 4, 5]
PER_LEVEL = 5
MASTER_SEED = 20260712
CAP_USD = 25.0
WORKERS = 6

SPEND = {"usd": 0.0}
_LOCK = threading.Lock()


class CapReached(RuntimeError):
    pass


def completion(rung: dict, prompt: str) -> dict:
    with _LOCK:
        if SPEND["usd"] >= CAP_USD:
            raise CapReached(f"cap ${CAP_USD}")
    body: dict = {
        "model": rung["model"],
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 32768,
        "max_completion_tokens": 32768,
    }
    if rung.get("pin"):
        body["provider"] = {"only": [rung["pin"]], "allow_fallbacks": False}
    for attempt in range(3):
        try:
            r = httpx.post("https://openrouter.ai/api/v1/chat/completions",
                           headers={"Authorization": f"Bearer {OR_KEY}"}, json=body, timeout=1800)
            d = r.json()
            if "choices" in d:
                u = d.get("usage") or {}
                pin, pout = rung["price"]
                with _LOCK:
                    SPEND["usd"] += (u.get("prompt_tokens", 0) * pin
                                     + u.get("completion_tokens", 0) * pout) / 1e6
                msg = d["choices"][0].get("message") or {}
                return {"content": msg.get("content") or "",
                        "finish": d["choices"][0].get("finish_reason")}
        except CapReached:
            raise
        except Exception:
            pass
        time.sleep(10 * (attempt + 1))
    return {"content": "", "finish": "error"}


def gen_instances() -> list:
    return [synth.gen_instance(n_rules=d, master_seed=MASTER_SEED, set_name="live3",
                               level_idx=li, index=i)
            for li, d in enumerate(LEVELS) for i in range(PER_LEVEL)]


def truth(inst, resp: dict) -> bool:
    return synth.score(inst, resp["content"]) == "pass"


def arm_cheap(inst, rng):
    r = completion(CHEAP, synth.render_prompt(inst))
    return truth(inst, r), False, {}


def arm_premium(inst, rng):
    r = completion(CLOSER, synth.render_prompt(inst))
    return truth(inst, r), False, {}


def arm_consistency(inst, rng):
    prompt = synth.render_prompt(inst)
    r1, r2 = completion(CHEAP, prompt), completion(CHEAP, prompt)
    probes = probe_inputs(inst.instance_id)
    o1 = run_program(code.extract_code(r1["content"]), probes)
    o2 = run_program(code.extract_code(r2["content"]), probes)
    agree = o1 is not None and o1 == o2
    if agree:
        return truth(inst, r1), False, {"agree": True}
    r3 = completion(CLOSER, prompt)
    return truth(inst, r3), True, {"agree": False}


def make_arm_random(esc_ids: set):
    def fn(inst, rng):
        if inst.instance_id in esc_ids:
            r = completion(CLOSER, synth.render_prompt(inst))
            return truth(inst, r), True, {}
        r = completion(CHEAP, synth.render_prompt(inst))
        return truth(inst, r), False, {}
    return fn


def run_arm(name, fn, instances, results, records):
    start = SPEND["usd"]
    out = [None] * len(instances)

    def one(pair):
        i, inst = pair
        rng = random.Random(hash((name, inst.instance_id)) & 0xFFFF)
        try:
            ok, esc, extra = fn(inst, rng)
        except CapReached:
            return i, None
        rec = {"arm": name, "iid": inst.instance_id, "level": inst.level_value,
               "pass": ok, "escalated": esc, **extra}
        records.append(rec)
        print(f"  [{name}] {i+1}/{len(instances)} D={int(inst.level_value)} "
              f"{'PASS' if ok else 'fail'}{' esc' if esc else ''} (${SPEND['usd']:.2f})", flush=True)
        return i, (ok, esc)

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for i, res in ex.map(one, enumerate(instances)):
            out[i] = res
    done = [r for r in out if r is not None]
    solved = sum(1 for ok, _ in done if ok)
    cost = SPEND["usd"] - start
    results[name] = {
        "solved": f"{solved}/{len(done)}", "solve_rate": round(solved / max(len(done), 1), 3),
        "cost_usd": round(cost, 3), "cost_per_solved_usd": round(cost / max(solved, 1), 4),
        "n_escalated": sum(1 for _, e in done if e),
    }
    print(name, results[name], flush=True)
    p = ROOT / "analysis" / "routing3.json"
    data = json.loads(p.read_text()) if p.exists() else {}
    data["live_consistency"] = {"results": results, "records": records,
                                "total_spend_usd": round(SPEND["usd"], 3)}
    p.write_text(json.dumps(data, indent=2))


def main() -> int:
    instances = gen_instances()
    results: dict = {}
    records: list = []
    print(f"== synth: {len(instances)} fresh instances ==", flush=True)
    run_arm("always_cheap", arm_cheap, instances, results, records)
    run_arm("always_premium", arm_premium, instances, results, records)
    run_arm("consistency_router", arm_consistency, instances, results, records)
    n_esc = results["consistency_router"]["n_escalated"]
    ids = sorted(i.instance_id for i in instances)
    esc_ids = set(random.Random(MASTER_SEED).sample(ids, n_esc))
    run_arm("quota_random", make_arm_random(esc_ids), instances, results, records)
    print("done; total $", round(SPEND["usd"], 2), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
