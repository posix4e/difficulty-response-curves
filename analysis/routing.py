"""Can billing metrics and trace texture drive a model router?

Three offline experiments on the released store — no API calls:

A1 SELF-SIGNAL. Within one model at one difficulty level, do that call's
   own signals (completion tokens; loop share where traces exist) predict
   the call's failure? AUC per model. This is the escalation trigger: a
   router sees the signal before it sees correctness.

A2 TRANSFER. Across models on the SAME instance (main-set instances are
   shared), does the cheap model's signal predict "the premium model is
   needed here" (cheap fails)? This is the cascade's routing signal.

A3 REPLAY. Simulate router policies over shared instances with recorded
   outcomes and real per-call costs: always-cheap, always-premium,
   retry-k (mist-aware), cascade-on-verify, cascade-on-token-threshold.
   Output cost-per-solved vs solve-rate per policy.

Kill condition, in the house style: if AUCs hover at 0.5 the practical
pitch dies and this file says so in routing.json.
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from drc import config
from drc.runner.store import Store

OUT = Path(__file__).with_name("routing.json")


def shingle_rep(text: str, k: int = 12) -> float:
    words = text.split()
    if len(words) < 3 * k:
        return 0.0
    sh = [" ".join(words[i : i + k]) for i in range(0, len(words) - k, k)]
    return 1 - len(set(sh)) / len(sh)


def auc(scores_pos: list[float], scores_neg: list[float]) -> float:
    """Probability a random failure outscores a random pass (rank AUC)."""
    if not scores_pos or not scores_neg:
        return float("nan")
    pos = np.array(scores_pos)
    neg = np.array(scores_neg)
    # Mann-Whitney U
    allv = np.concatenate([pos, neg])
    ranks = allv.argsort().argsort().astype(float) + 1
    # tie handling: average ranks
    order = np.argsort(allv, kind="mergesort")
    sorted_v = allv[order]
    avg = ranks.copy()
    i = 0
    while i < len(sorted_v):
        j = i
        while j + 1 < len(sorted_v) and sorted_v[j + 1] == sorted_v[i]:
            j += 1
        if j > i:
            avg_rank = (i + j) / 2 + 1
            for k2 in range(i, j + 1):
                avg[order[k2]] = avg_rank
        i = j + 1
    r_pos = avg[: len(pos)].sum()
    u = r_pos - len(pos) * (len(pos) + 1) / 2
    return float(u / (len(pos) * len(neg)))


def load_calls(store: Store) -> list[dict]:
    rows = store.conn.execute(
        """SELECT c.model_id, c.instance_id, i.level_idx, i.level_value, c.pass,
                  c.completion_tokens tok, c.cost_microdollars cost,
                  CASE WHEN LENGTH(c.response_text) > 2000 THEN c.response_text ELSE NULL END trace
           FROM calls c JOIN instances i USING(instance_id)
           WHERE i.family='sat' AND i.set_name='main'
             AND c.outcome IN ('pass','fail_wrong','fail_parse')
             AND c.completion_tokens > 100"""
    ).fetchall()
    out = []
    for m, iid, li, lv, p, tok, cost, trace in rows:
        out.append(
            {
                "model": m, "iid": iid, "level": li, "alpha": lv, "pass": p,
                "tok": tok, "cost": cost,
                "loops": shingle_rep(trace) if trace else None,
            }
        )
    return out


def a1_self_signal(calls: list[dict]) -> dict:
    """Per model: AUC of signal for predicting failure, computed within
    difficulty levels then pooled (level-stratified, so difficulty itself
    doesn't do the predicting)."""
    res = {}
    by_model = defaultdict(list)
    for c in calls:
        by_model[c["model"]].append(c)
    for m, cs in by_model.items():
        by_level = defaultdict(list)
        for c in cs:
            by_level[c["level"]].append(c)
        tok_pos, tok_neg, loop_pos, loop_neg = [], [], [], []
        for lvl, group in by_level.items():
            fails = [c for c in group if not c["pass"]]
            passes = [c for c in group if c["pass"]]
            if len(fails) < 3 or len(passes) < 3:
                continue
            # normalise within level (z-ish via level median) then pool
            med = np.median([c["tok"] for c in group])
            tok_pos += [c["tok"] / med for c in fails]
            tok_neg += [c["tok"] / med for c in passes]
            lf = [c["loops"] for c in fails if c["loops"] is not None]
            lp = [c["loops"] for c in passes if c["loops"] is not None]
            loop_pos += lf
            loop_neg += lp
        entry = {
            "n_fail": len(tok_pos), "n_pass": len(tok_neg),
            "auc_tokens": round(auc(tok_pos, tok_neg), 3) if tok_pos and tok_neg else None,
        }
        if len(loop_pos) >= 20 and len(loop_neg) >= 20:
            entry["auc_loops"] = round(auc(loop_pos, loop_neg), 3)
            entry["n_traced"] = len(loop_pos) + len(loop_neg)
        res[m] = entry
    return res


def a2_transfer(calls: list[dict], cheap: str, strong: str) -> dict | None:
    """Does the cheap model's signal on an instance predict 'cheap fails
    here' (escalation needed), evaluated only where we know the strong
    model's result too?"""
    cheap_by_iid = defaultdict(list)
    strong_by_iid = defaultdict(list)
    for c in calls:
        if c["model"] == cheap:
            cheap_by_iid[c["iid"]].append(c)
        elif c["model"] == strong:
            strong_by_iid[c["iid"]].append(c)
    shared = set(cheap_by_iid) & set(strong_by_iid)
    if len(shared) < 30:
        return None
    sig_pos, sig_neg = [], []  # pos = escalation needed (cheap majority-fails)
    strong_would_solve = 0
    for iid in shared:
        cc = cheap_by_iid[iid]
        med = np.median([x["tok"] for x in cc])
        cheap_fail = np.mean([not x["pass"] for x in cc]) >= 0.5
        # signal = mean normalised tokens of cheap attempts on this instance
        level_meds = [x["tok"] for x in calls if x["model"] == cheap and x["level"] == cc[0]["level"]]
        norm = np.mean([x["tok"] for x in cc]) / max(np.median(level_meds), 1)
        (sig_pos if cheap_fail else sig_neg).append(norm)
        if cheap_fail and any(x["pass"] for x in strong_by_iid[iid]):
            strong_would_solve += 1
    return {
        "n_shared_instances": len(shared),
        "n_escalation_needed": len(sig_pos),
        "auc_cheap_tokens_predict_escalation": round(auc(sig_pos, sig_neg), 3),
        "strong_solves_when_cheap_fails": f"{strong_would_solve}/{len(sig_pos)}",
    }


def a3_replay(calls: list[dict], cheap: str, strong: str, tok_threshold_pct: float = 75) -> dict | None:
    """Replay policies on shared instances. Costs in microdollars from the
    ledger. Retry/cascade draw randomly (seeded) among recorded attempts."""
    rng = np.random.default_rng(7)
    cheap_by_iid = defaultdict(list)
    strong_by_iid = defaultdict(list)
    for c in calls:
        if c["model"] == cheap:
            cheap_by_iid[c["iid"]].append(c)
        elif c["model"] == strong:
            strong_by_iid[c["iid"]].append(c)
    shared = sorted(set(cheap_by_iid) & set(strong_by_iid))
    if len(shared) < 30:
        return None
    # token threshold per level from cheap model's distribution
    level_thresh = {}
    by_level = defaultdict(list)
    for c in calls:
        if c["model"] == cheap:
            by_level[c["level"]].append(c["tok"])
    for lvl, toks in by_level.items():
        level_thresh[lvl] = np.percentile(toks, tok_threshold_pct)

    def draw(pool):
        return pool[rng.integers(0, len(pool))]

    policies = {}

    def run_policy(name, fn, reps=200):
        solved, cost = 0, 0
        for _ in range(reps):
            s, c = 0, 0
            for iid in shared:
                ok, spent = fn(iid)
                s += ok
                c += spent
            solved += s
            cost += c
        n = reps * len(shared)
        policies[name] = {
            "solve_rate": round(solved / n, 3),
            "cost_per_instance_usd": round(cost / n / 1e6, 5),
            "cost_per_solved_usd": round((cost / 1e6) / max(solved, 1), 5),
        }

    run_policy("always_cheap", lambda iid: (lambda a: (a["pass"], a["cost"]))(draw(cheap_by_iid[iid])))
    run_policy("always_strong", lambda iid: (lambda a: (a["pass"], a["cost"]))(draw(strong_by_iid[iid])))

    def retry3(iid):
        cost = 0
        for _ in range(3):
            a = draw(cheap_by_iid[iid])
            cost += a["cost"]
            if a["pass"]:
                return 1, cost
        return 0, cost

    run_policy("cheap_retry3", retry3)

    def cascade_verify(iid):
        a = draw(cheap_by_iid[iid])
        if a["pass"]:
            return 1, a["cost"]
        b = draw(strong_by_iid[iid])
        return b["pass"], a["cost"] + b["cost"]

    run_policy("cascade_on_verify", cascade_verify)

    def cascade_tokens(iid):
        a = draw(cheap_by_iid[iid])
        if a["tok"] <= level_thresh[a["level"]] and a["pass"]:
            return 1, a["cost"]
        if a["tok"] <= level_thresh[a["level"]]:
            # signal said fine but it failed: accept the miss (no verifier!)
            return 0, a["cost"]
        b = draw(strong_by_iid[iid])
        return b["pass"], a["cost"] + b["cost"]

    run_policy("cascade_on_token_signal_no_verifier", cascade_tokens)

    def cascade_tokens_verify(iid):
        a = draw(cheap_by_iid[iid])
        if a["pass"]:
            return 1, a["cost"]
        if a["tok"] > level_thresh[a["level"]]:
            b = draw(strong_by_iid[iid])
            return b["pass"], a["cost"] + b["cost"]
        # verifier caught a failure the signal missed: retry cheap once then escalate
        a2 = draw(cheap_by_iid[iid])
        if a2["pass"]:
            return 1, a["cost"] + a2["cost"]
        b = draw(strong_by_iid[iid])
        return b["pass"], a["cost"] + a2["cost"] + b["cost"]

    run_policy("cascade_signal_plus_verifier", cascade_tokens_verify)

    return {"pair": f"{cheap} -> {strong}", "n_shared_instances": len(shared), "policies": policies}


if __name__ == "__main__":
    store = Store(config.DATA_DIR / "drc.sqlite")
    calls = load_calls(store)
    print(f"{len(calls)} scored main-set calls loaded")
    out = {"a1_self_signal": a1_self_signal(calls), "a2_transfer": {}, "a3_replay": {}}
    pairs = [
        ("openai/gpt-oss-20b", "openai/o4-mini"),
        ("openai/gpt-oss-20b", "anthropic/claude-haiku-4.5"),
        ("openai/gpt-oss-120b", "anthropic/claude-haiku-4.5"),
        ("deepseek/deepseek-r1-0528", "anthropic/claude-haiku-4.5"),
    ]
    for cheap, strong in pairs:
        key = f"{cheap.split('/')[-1]}->{strong.split('/')[-1]}"
        t = a2_transfer(calls, cheap, strong)
        if t:
            out["a2_transfer"][key] = t
        r = a3_replay(calls, cheap, strong)
        if r:
            out["a3_replay"][key] = r
    # verdict
    aucs = [v.get("auc_tokens") for v in out["a1_self_signal"].values() if v.get("auc_tokens")]
    out["verdict"] = {
        "median_self_auc_tokens": round(float(np.median(aucs)), 3) if aucs else None,
        "kill_condition_triggered": bool(aucs and abs(np.median(aucs) - 0.5) < 0.05),
    }
    OUT.write_text(json.dumps(out, indent=2))
    print(json.dumps(out["a1_self_signal"], indent=1)[:800])
    print("verdict:", out["verdict"])
    print(f"wrote {OUT}")
