"""Round 4, Phase 0: self-consistency as the verifier-free signal.

Rounds 2-3 established that a model's trace cannot grade its own answer
well enough to route. This round tests a different signal source
entirely: sample the same model twice on the same instance and treat
DISAGREEMENT as the wrongness flag. Round 1's mist finding predicts it
should work - 81% of variance at the frontier is within-instance, so
near-frontier answers are coin flips, and coin flips disagree.

PRE-REGISTERED before this file is first run (committed 2026-07-08,
before any agreement number was computed; the k=6 percall corpus is
frozen and this is the ONE look):

  Signal (deployment form): two samples of the cheap model; if parsed
  answers match exactly (SAT: the TFTF assignment string), trust the
  answer; else escalate. No ground truth touches the decision.

  Measurement on the k-sample corpus, per model, routes not mixed:
    - graded score per call = share of OTHER same-model-same-route
      samples of the same instance whose parsed_answer differs
      ("disagreement share"); stratified pairwise AUC of that score,
      same machinery as rounds 2-3 (pairs within a difficulty level).
    - binary operating stats = expectation over single random partners:
      recall (wrong calls flagged), FPR (correct calls flagged),
      escalation rate.

  GATE, evaluated once: AUC >= 0.75 AND recall >= 0.5 at FPR <= 0.25 on
  >= 2 of 3 models. Pass -> fund the live rematch (~$40 cap). Fail ->
  publish the addendum; the trilogy closes at $0 further spend.

  Known hazard, declared up front: on satisfiable SAT many assignments
  can be correct, so two RIGHT answers may disagree - this inflates FPR
  and escalation cost but never ships a wrong answer. The gate's FPR arm
  prices exactly this.

Writes analysis/percall-consistency.json.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from drc import config
from drc.runner.store import Store

from percall import MODELS, bootstrap_ci, pair_auc, stratified_pairs  # noqa: E402


def load_calls(store: Store, model_ids: tuple[str, ...]) -> list[dict]:
    q = f"""SELECT c.model_id, i.instance_id, i.set_name, ROUND(i.level_value,2),
                   c.pass, c.parsed_answer
            FROM calls c JOIN instances i USING(instance_id)
            WHERE c.model_id IN ({','.join('?' * len(model_ids))})
              AND i.family='sat' AND i.set_name='percall'
              AND c.outcome IN ('pass','fail_wrong')
              AND c.parsed_answer IS NOT NULL AND c.parsed_answer != ''"""
    out = []
    for m, iid, s, lv, p, ans in store.conn.execute(q, model_ids):
        out.append({"iid": (m, iid), "level": (m, s, lv), "pass": bool(p), "ans": ans})
    return out


def score_disagreement(calls: list[dict]) -> list[dict]:
    """Graded score = share of same-route partner samples that disagree."""
    by_iid = defaultdict(list)
    for c in calls:
        by_iid[c["iid"]].append(c)
    scored = []
    for group in by_iid.values():
        if len(group) < 2:
            continue
        for c in group:
            partners = [o for o in group if o is not c]
            dis = sum(1 for o in partners if o["ans"] != c["ans"]) / len(partners)
            scored.append({**c, "disagree": dis})
    return scored


def operating_stats(scored: list[dict]) -> dict:
    """Binary single-partner stats = the graded share IS the expectation
    over a uniformly random partner, so averages give exact expectations."""
    wrong = [c for c in scored if not c["pass"]]
    right = [c for c in scored if c["pass"]]
    return {
        "recall": round(sum(c["disagree"] for c in wrong) / max(len(wrong), 1), 3),
        "fpr": round(sum(c["disagree"] for c in right) / max(len(right), 1), 3),
        "escalation_rate": round(sum(c["disagree"] for c in scored) / max(len(scored), 1), 3),
        "p_correct_given_agree": round(
            sum((1 - c["disagree"]) for c in right)
            / max(sum(1 - c["disagree"] for c in scored), 1e-9), 3),
        "p_correct_given_disagree": round(
            sum(c["disagree"] for c in right)
            / max(sum(c["disagree"] for c in scored), 1e-9), 3),
    }


def main() -> None:
    store = Store(config.DATA_DIR / "drc.sqlite")
    report: dict = {
        "preregistered": "graded-disagreement stratified AUC >= 0.75 AND recall >= 0.5 at "
                         "FPR <= 0.25 on >= 2 of 3 models; frozen percall corpus; ONE look",
        "models": {},
    }
    clears = 0
    for name, ids in MODELS.items():
        calls = load_calls(store, ids)
        scored = score_disagreement(calls)
        # feature key must exist for stratified machinery reuse
        for c in scored:
            c["judge"] = c["disagree"]
        pairs = stratified_pairs(scored)
        entry: dict = {"n_scored": len(scored), "n_pairs": len(pairs)}
        if pairs:
            auc = pair_auc(pairs, "judge")
            lo, hi = bootstrap_ci(scored, "judge")
            stats = operating_stats(scored)
            ok = auc >= 0.75 and stats["recall"] >= 0.5 and stats["fpr"] <= 0.25
            entry.update({"auc": round(auc, 3), "auc_ci95": [round(lo, 3), round(hi, 3)],
                          **stats, "clears_gate": ok})
            clears += ok
        report["models"][name] = entry
        print(name, json.dumps(entry))
    report["gate"] = {"models_clearing": clears, "pass": clears >= 2}
    print("GATE:", report["gate"])
    Path(__file__).with_name("percall-consistency.json").write_text(json.dumps(report, indent=2))
    print("wrote percall-consistency.json")


if __name__ == "__main__":
    main()
