"""Round 2, Phase 3: the verifier-free router meets fresh puzzles.

Four arms per task family, all difficulty-aware for the starting rung,
differing only in what triggers retry/escalation:

  A. always_cheap     - cheap rung once, no retries
  B. always_premium   - closer rung once
  C. judged_router    - trace judge (hedge_tail threshold from Phase 0)
                        triggers retry, then escalation
  D. random_escalate  - escalates a seeded-random fraction of instances
                        matched to arm C's realized escalation rate;
                        isolates the judge's marginal value

Ground truth (SAT certificates / hidden code tests) scores every arm but
is NEVER visible to any routing decision. Fleet + judge threshold come
from analysis/fleet.json (written after the Phase 1 audit):

  {"cheap":   {"gateway": "or", "model": "...", "pin": null, "max_tokens": 32768},
   "mid":     {...} (optional),
   "closer":  {...},
   "judge":   {"feature": "hedge_tail", "threshold": 12.0},
   "retries": 1}

Results checkpoint to analysis/routing2.json after every arm x family.
Pre-registered success: arm C beats A and B on solve rate at $/solve
below B, on BOTH families.
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

from drc.tasks import sat, synth  # noqa: E402
from drc.stats.tracefeat import features  # noqa: E402

FLEET = json.loads((ROOT / "analysis" / "fleet.json").read_text())
OR_KEY = re.search(r"sk-or-[A-Za-z0-9_-]+", (Path.home() / "src" / ".env-or").read_text()).group(0)
sys.path.insert(0, str(ROOT / "src"))
from drc import config as _cfg  # noqa: E402
TR_KEY = _cfg.load_key()

SPEND = {"usd": 0.0}
_LOCK = threading.Lock()
CAP_USD = float(FLEET.get("cap_usd", 30.0))
WORKERS = 6
PRICE = FLEET.get("prices", {})  # model -> [$/M in, $/M out]


class CapReached(RuntimeError):
    pass


def completion(rung: dict, prompt: str) -> dict:
    with _LOCK:
        if SPEND["usd"] >= CAP_USD:
            raise CapReached(f"cap ${CAP_USD}")
    gw = rung.get("gateway", "or")
    url = ("https://openrouter.ai/api/v1/chat/completions" if gw == "or"
           else "https://api.trustedrouter.com/v1/chat/completions")
    key = OR_KEY if gw == "or" else TR_KEY
    body: dict = {
        "model": rung["model"],
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": rung.get("max_tokens", 32768),
        "max_completion_tokens": rung.get("max_tokens", 32768),
    }
    if rung.get("pin"):
        body["provider"] = {"only": [rung["pin"]], "allow_fallbacks": False}
    for attempt in range(3):
        try:
            r = httpx.post(url, headers={"Authorization": f"Bearer {key}"}, json=body, timeout=1800)
            d = r.json()
            if "choices" in d:
                u = d.get("usage") or {}
                pin, pout = PRICE.get(rung["model"], [1.0, 5.0])
                cost = (u.get("prompt_tokens", 0) * pin + u.get("completion_tokens", 0) * pout) / 1e6
                micro = u.get("cost_microdollars")
                if micro is not None:
                    cost = micro / 1e6
                with _LOCK:
                    SPEND["usd"] += cost
                msg = d["choices"][0].get("message") or {}
                return {
                    "content": msg.get("content") or "",
                    "reasoning": msg.get("reasoning") or msg.get("reasoning_content") or "",
                    "tokens": u.get("completion_tokens") or 0,
                    "finish": d["choices"][0].get("finish_reason"),
                }
        except CapReached:
            raise
        except Exception:
            pass
        time.sleep(10 * (attempt + 1))
    return {"content": "", "reasoning": "", "tokens": 0, "finish": "error"}


def judge_says_wrong(resp: dict) -> bool:
    if resp["finish"] in ("length", "max_tokens", "error") or not resp["content"].strip():
        return True  # loud failures are free to detect
    trace_text = resp["reasoning"] + "\n" + resp["content"]
    f = features(trace_text, resp["tokens"])
    j = FLEET["judge"]
    return f[j["feature"]] >= j["threshold"]


def render(inst) -> str:
    return sat.render_prompt(inst) if inst.family == "sat" else synth.render_prompt(inst)


def truth(inst, resp: dict) -> bool:
    text = (resp["reasoning"] + "\n" + resp["content"]) if inst.family == "sat" else resp["content"]
    mod = sat if inst.family == "sat" else synth
    return mod.score(inst, text) == "pass"


def gen_instances(family: str) -> list:
    if family == "sat":
        levels = FLEET.get("sat_levels", [3.0, 3.6, 4.2, 4.8, 5.3])
        return [sat.gen_instance(n_vars=20, alpha=a, master_seed=20260710,
                                 set_name="live2", level_idx=li, index=i)
                for li, a in enumerate(levels) for i in range(FLEET.get("per_level", 4))]
    levels = FLEET.get("code_levels", [2, 3, 4, 5, 6])
    return [synth.gen_instance(n_rules=int(d), master_seed=20260710,
                               set_name="live2", level_idx=li, index=i)
            for li, d in enumerate(levels) for i in range(FLEET.get("per_level", 4))]


def rung_ladder(inst) -> list[dict]:
    ladder = [FLEET["cheap"]]
    if "mid" in FLEET and inst.level_idx >= len(FLEET.get("sat_levels", [0] * 5)) // 2:
        ladder.append(FLEET["mid"])
    ladder.append(FLEET["closer"])
    return ladder


def arm_always(rung_key: str):
    def fn(inst, rng):
        resp = completion(FLEET[rung_key], render(inst))
        return truth(inst, resp), 0
    return fn


def arm_judged(inst, rng):
    retries = int(FLEET.get("retries", 1))
    escalations = 0
    for rung in rung_ladder(inst):
        for _try in range(1 + retries):
            resp = completion(rung, render(inst))
            if not judge_says_wrong(resp):
                return truth(inst, resp), escalations
        escalations += 1
    return truth(inst, resp), escalations  # last attempt stands


def make_arm_random(esc_rate: float):
    def fn(inst, rng):
        ladder = rung_ladder(inst)
        rung = ladder[-1] if rng.random() < esc_rate else ladder[0]
        resp = completion(rung, render(inst))
        return truth(inst, resp), int(rung is ladder[-1])
    return fn


def checkpoint(results: dict, complete: bool) -> None:
    p = ROOT / "analysis" / "routing2.json"
    data = json.loads(p.read_text()) if p.exists() else {}
    data["live_eval_v2"] = {"results": results, "total_spend_usd": round(SPEND["usd"], 3),
                            "complete": complete, "fleet": {k: FLEET[k] for k in ("cheap", "closer", "judge") if k in FLEET}}
    p.write_text(json.dumps(data, indent=2))


def run_arm(name: str, fn, instances, results: dict, family: str) -> None:
    start = SPEND["usd"]
    outcomes: list = [None] * len(instances)
    escs: list = [0] * len(instances)

    def one(pair):
        i, inst = pair
        rng = random.Random(hash((name, inst.instance_id)) & 0xFFFF)
        try:
            ok, esc = fn(inst, rng)
        except CapReached:
            return i, None, 0
        print(f"  [{family}/{name}] {i+1}/{len(instances)} lvl={inst.level_value} "
              f"{'PASS' if ok else 'fail'} esc={esc} (${SPEND['usd']:.2f})", flush=True)
        return i, ok, esc

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for i, ok, esc in ex.map(one, enumerate(instances)):
            outcomes[i], escs[i] = ok, esc
    done = [o for o in outcomes if o is not None]
    solved = sum(1 for o in done if o)
    cost = SPEND["usd"] - start
    results.setdefault(family, {})[name] = {
        "solved": f"{solved}/{len(done)}",
        "solve_rate": round(solved / max(len(done), 1), 3),
        "cost_usd": round(cost, 3),
        "cost_per_solved_usd": round(cost / max(solved, 1), 4),
        "escalation_rate": round(sum(1 for e in escs if e) / max(len(done), 1), 3),
    }
    print(family, name, results[family][name], flush=True)
    checkpoint(results, complete=False)


def main() -> int:
    results: dict = {}
    for family in ("sat", "synth"):
        instances = gen_instances(family)
        print(f"== {family}: {len(instances)} fresh instances ==", flush=True)
        run_arm("always_cheap", arm_always("cheap"), instances, results, family)
        run_arm("always_premium", arm_always("closer"), instances, results, family)
        run_arm("judged_router", arm_judged, instances, results, family)
        esc_rate = results[family]["judged_router"]["escalation_rate"]
        run_arm("random_escalate", make_arm_random(esc_rate), instances, results, family)
    checkpoint(results, complete=True)
    print("done; total spend $", round(SPEND["usd"], 2), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
