"""Phase 0 of the verifier-free routing study: can a call's OWN trace say
whether its answer is wrong?

The billing version of this died honestly (a1: token count within level,
AUC ~= 0.5). Whole-trace loop share also failed on R1 (0.387 - loops were
associated with PASSES, presumably loop-then-recover). This pass tests
finer cuts, with the hypothesis DECLARED BEFORE LOOKING:

  PRIMARY:   rep_tail   - shingle repetition over the last 30% of the trace
             ("still looping at the end = never escaped")
  SECONDARY: bt_tail    - backtrack-marker density in the last 30%
             hedge_tail - hedging language in the final 15% + answer region

Labels: pass vs fail_wrong ONLY. Truncations are excluded - finish_reason
detects those for free; the judge is needed for silent wrongness.

Evaluation: level-stratified pairwise AUC (every (fail, pass) pair within a
difficulty level; difficulty itself cannot do the predicting), with a
cluster bootstrap over instances for the CI. No trained weights - single
features only, so there is nothing to overfit.

Pre-registered gate (plan 2026-07-07): held-out/stratified AUC >= 0.65 on
at least 2 of 3 traced models funds the live arm.

Writes analysis/percall.json.
"""

from __future__ import annotations

import json
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from drc import config
from drc.runner.store import Store
from drc.stats.tracefeat import features  # noqa: F401  (single source of truth)

MODELS = {
    "deepseek/deepseek-r1-0528": ("deepseek/deepseek-r1-0528", "or/deepseek-r1-0528"),
    "minimax/minimax-m2.5": ("minimax/minimax-m2.5", "or/minimax-m2.5"),
    "qwen/qwen3-235b-a22b-thinking-2507": ("qwen/qwen3-235b-a22b-thinking-2507",),
}


def load_calls(store: Store, model_ids: tuple[str, ...], set_name: str | None = None) -> list[dict]:
    set_clause = "AND i.set_name = ?" if set_name else ""
    q = f"""SELECT c.model_id, i.instance_id, i.set_name, ROUND(i.level_value,2),
                   c.pass, c.completion_tokens, c.response_text
            FROM calls c JOIN instances i USING(instance_id)
            WHERE c.model_id IN ({','.join('?' * len(model_ids))})
              AND i.family='sat'
              AND c.outcome IN ('pass','fail_wrong')
              AND LENGTH(c.response_text) > 2000 {set_clause}"""
    params = model_ids + ((set_name,) if set_name else ())
    out = []
    for m, iid, s, lv, p, tok, txt in store.conn.execute(q, params):
        f = features(txt, tok)
        # route (model_id) is part of both keys: pairs never form across
        # doors - a per-call signal must beat its own route's variation
        f.update({"iid": (m, iid), "level": (m, s, lv), "pass": bool(p)})
        out.append(f)
    return out


def within_instance_pairs(calls: list[dict]) -> list[tuple[dict, dict]]:
    by_iid = defaultdict(list)
    for c in calls:
        by_iid[c["iid"]].append(c)
    pairs = []
    for group in by_iid.values():
        fails = [c for c in group if not c["pass"]]
        passes = [c for c in group if c["pass"]]
        pairs += [(f, p) for f in fails for p in passes]
    return pairs


def stratified_pairs(calls: list[dict]) -> list[tuple[dict, dict]]:
    """All (fail, pass) pairs within a (set, level) cell."""
    by_level = defaultdict(list)
    for c in calls:
        by_level[c["level"]].append(c)
    pairs = []
    for group in by_level.values():
        fails = [c for c in group if not c["pass"]]
        passes = [c for c in group if c["pass"]]
        if len(fails) >= 2 and len(passes) >= 2:
            pairs += [(f, p) for f in fails for p in passes]
    return pairs


def pair_auc(pairs: list[tuple[dict, dict]], feat: str) -> float:
    wins = sum(1.0 if f[feat] > p[feat] else (0.5 if f[feat] == p[feat] else 0.0) for f, p in pairs)
    return wins / len(pairs)


def bootstrap_ci(calls: list[dict], feat: str, b: int = 2000, seed: int = 20260707) -> tuple[float, float]:
    rng = random.Random(seed)
    iids = sorted({c["iid"] for c in calls})
    by_iid = defaultdict(list)
    for c in calls:
        by_iid[c["iid"]].append(c)
    vals = []
    for _ in range(b):
        sample = [c for iid in (rng.choice(iids) for _ in iids) for c in by_iid[iid]]
        pairs = stratified_pairs(sample)
        if pairs:
            vals.append(pair_auc(pairs, feat))
    vals.sort()
    return (vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals))]) if vals else (float("nan"),) * 2


FEATS = ["rep_tail", "bt_tail", "hedge_tail", "rep_full", "bt_full", "wait_tail", "tok"]


def main() -> None:
    # confirmatory mode: --set percall restricts to the purpose-built batch.
    # Pre-registered (before that data existed): PRIMARY hedge_tail,
    # SECONDARY bt_tail; gate = >= 0.65 on >= 2 of 3 models, confirmatory set.
    set_name = None
    if "--set" in sys.argv:
        set_name = sys.argv[sys.argv.index("--set") + 1]
    store = Store(config.DATA_DIR / "drc.sqlite")
    report: dict = {
        "set": set_name or "all",
        "exploratory_primary": "rep_tail",
        "confirmatory_primary": "hedge_tail",
        "gate": "AUC >= 0.65 on >= 2 of 3 models (confirmatory set)",
        "models": {},
    }
    for name, ids in MODELS.items():
        calls = load_calls(store, ids, set_name)
        pairs = stratified_pairs(calls)
        wpairs = within_instance_pairs(calls)
        entry: dict = {
            "n_traced": len(calls),
            "n_pairs": len(pairs),
            "n_within_instance_pairs": len(wpairs),
        }
        if pairs:
            entry["auc"] = {}
            for feat in FEATS:
                lo, hi = bootstrap_ci(calls, feat)
                entry["auc"][feat] = {"point": round(pair_auc(pairs, feat), 3),
                                      "ci95": [round(lo, 3), round(hi, 3)]}
        if wpairs:
            entry["auc_within_instance"] = {
                feat: round(pair_auc(wpairs, feat), 3) for feat in FEATS
            }
        report["models"][name] = entry
        print(name, json.dumps(entry, indent=1)[:500])
    out = Path(__file__).with_name(f"percall{'-' + set_name if set_name else ''}.json")
    out.write_text(json.dumps(report, indent=2))
    print(f"wrote {out.name}")


if __name__ == "__main__":
    main()
