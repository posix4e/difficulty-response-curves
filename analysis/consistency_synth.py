"""Round 5: self-consistency where answers are unique.

Round 4's autopsy: disagreement between two samples has perfect recall
and perfect precision-on-agreement, but satisfiable SAT admits many
correct assignments, so correct answers disagree too (FPR 76-94%) and
the economics die. The synth family should collapse that multiplicity:
"agreement" here means two extracted programs produce identical outputs
on shared probe inputs - functional equivalence - and two CORRECT
inductions are the same hidden function by definition. No ground truth
touches the check: probe inputs are seeded random lists, both programs
just run.

Modes:
  --explore   exploratory look at the existing v3 pilot pairs
              (set codepilot2, k=2, 24 instances). Labeled exploratory;
              it informs the gate batch design. The gate corpus is fresh.
  --gate      the ONE pre-registered look at the fresh gate batch
              (set congate). PRE-REGISTERED before the batch launched
              (committed 2026-07-08, before any congate call existed):
              PRIMARY: recall >= 0.9 AND FPR <= 0.25, binary partner
              expectations over same-instance sample pairs, functional
              agreement on 8 seeded probe inputs (crash/no-code counts
              as disagreement - loud failures escalate anyway).
              Stratified AUC reported, not gated (the cheap rung's
              frontier sits between D=1 and D=2, so mixed cells
              concentrate at D=1).
              Pass -> fund the live rematch (~$25 cap). Fail -> publish
              the addendum; the multiplicity door closes too.

Writes analysis/consistency-synth-<mode>.json.
"""

from __future__ import annotations

import json
import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from drc import config
from drc.runner.store import Store
from drc.tasks import code

from percall import pair_auc, stratified_pairs  # noqa: E402

N_PROBES = 8
PROBE_LIST_LEN = (8, 12)
PROBE_VAL = (-9, 9)


def probe_inputs(instance_id: str) -> list[list[int]]:
    rng = random.Random(f"probe-{instance_id}")
    return [
        [rng.randint(*PROBE_VAL) for _ in range(rng.randint(*PROBE_LIST_LEN))]
        for _ in range(N_PROBES)
    ]


def run_program(src: str | None, probes: list[list[int]]) -> list | None:
    """Outputs on probe inputs, or None if no code / crash / timeout."""
    if src is None:
        return None
    wrapper = (
        "import json\n" + src + "\n"
        f"_probes = {probes!r}\n"
        "print('===OUT===' + json.dumps([transform(list(p)) for p in _probes]))\n"
    )
    import subprocess
    try:
        r = subprocess.run(
            [sys.executable, "-I", "-c", wrapper],
            capture_output=True, text=True, timeout=code.EXEC_TIMEOUT_S,
        )
        for line in r.stdout.splitlines():
            if line.startswith("===OUT==="):
                return json.loads(line[len("===OUT==="):])
    except Exception:
        pass
    return None


def load_pairs(store: Store, set_name: str) -> dict:
    q = """SELECT i.instance_id, ROUND(i.level_value,2), c.pass, c.response_text
           FROM calls c JOIN instances i USING(instance_id)
           WHERE i.family='synth' AND i.set_name=?
             AND c.model_id='or/deepseek-r1-0528'
             AND c.outcome IN ('pass','fail_wrong','fail_parse')"""
    by_iid = defaultdict(list)
    for iid, lv, p, txt in store.conn.execute(q, (set_name,)):
        by_iid[(iid, lv)].append({"pass": bool(p), "src": code.extract_code(txt)})
    return by_iid


def main() -> None:
    mode = "gate" if "--gate" in sys.argv else "explore"
    set_name = "congate" if mode == "gate" else "codepilot2"
    store = Store(config.DATA_DIR / "drc.sqlite")
    by_iid = load_pairs(store, set_name)
    scored = []
    for (iid, lv), group in sorted(by_iid.items()):
        if len(group) < 2:
            continue
        probes = probe_inputs(iid)
        outs = [run_program(g["src"], probes) for g in group]
        for i, g in enumerate(group):
            partners = [o for j, o in enumerate(outs) if j != i]
            mine = outs[i]
            dis = sum(1 for o in partners if mine is None or o is None or o != mine) / len(partners)
            scored.append({"iid": iid, "level": ("r1", set_name, lv), "pass": g["pass"],
                           "judge": dis, "disagree": dis})
    wrong = [c for c in scored if not c["pass"]]
    right = [c for c in scored if c["pass"]]
    pairs = stratified_pairs(scored)
    report = {
        "mode": mode, "set": set_name, "n_scored": len(scored),
        "n_wrong": len(wrong), "n_right": len(right), "n_pairs": len(pairs),
        "recall": round(sum(c["disagree"] for c in wrong) / max(len(wrong), 1), 3),
        "fpr": round(sum(c["disagree"] for c in right) / max(len(right), 1), 3),
        "escalation_rate": round(sum(c["disagree"] for c in scored) / max(len(scored), 1), 3),
        "auc_reported": round(pair_auc(pairs, "judge"), 3) if pairs else None,
    }
    if mode == "gate":
        report["preregistered"] = "recall >= 0.9 AND fpr <= 0.25, one look"
        report["clears_gate"] = report["recall"] >= 0.9 and report["fpr"] <= 0.25
    print(json.dumps(report, indent=1))
    Path(__file__).with_name(f"consistency-synth-{mode}.json").write_text(json.dumps(report, indent=2))
    print(f"wrote consistency-synth-{mode}.json")


if __name__ == "__main__":
    main()
