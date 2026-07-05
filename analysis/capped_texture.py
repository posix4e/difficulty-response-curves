"""Capped-frontier hypothesis (round 2, Phase 0, free): MiniMax's trace
markers currently peak BELOW its native frontier (offsets -1.5 to -2.1 vs
x50 = 6.58). Hypothesis: the pooled texture mixed two regimes, and the
effort peak tracks the frontier the model is ACTUALLY operating under -
6.58 uncapped, ~3.6 at the enforced 32k cap.

Regimes (established from the store):
  uncapped: stages pilot-sat + primary-minimax (4-5 July; caps not
            enforced by the gateway then - calls exceeded 32,768 tokens)
  capped:   stage adaptive-minimax-m2.5, model minimax/minimax-m2.5 only
            (6 July; enforcement arrived with the gateway's parameter fix -
            56/108 calls died at exactly 32,768)

Writes the per-regime peaks into analysis/capped_texture.json.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from drc import config
from drc.runner.store import Store
from traces import BACKTRACK, shingle_rep

REGIMES = {
    "uncapped": ("c.stage IN ('pilot-sat','primary-minimax')", 6.58),
    "capped_32k": ("c.stage='adaptive-minimax-m2.5'", 3.6),
}


def peaks_for(store: Store, where: str, x50: float, include_trunc: bool) -> dict | None:
    outcomes = "('pass','fail_wrong','fail_truncated')" if include_trunc else "('pass','fail_wrong')"
    rows = store.conn.execute(
        f"""SELECT ROUND(i.level_value,2), c.completion_tokens, c.response_text
            FROM calls c JOIN instances i USING(instance_id)
            WHERE c.model_id='minimax/minimax-m2.5' AND i.family='sat'
              AND {where} AND c.outcome IN {outcomes}
              AND LENGTH(c.response_text) > 2000"""
    ).fetchall()
    by_level: dict[float, dict] = defaultdict(lambda: {"n": 0, "tok": 0.0, "bt": 0.0, "rep": 0.0})
    for lv, tok, txt in rows:
        d = by_level[lv]
        d["n"] += 1
        d["tok"] += tok or 0
        d["bt"] += len(BACKTRACK.findall(txt)) / max((tok or 1) / 1000, 0.1)
        d["rep"] += shingle_rep(txt)
    usable = {lv: d for lv, d in by_level.items() if d["n"] >= 2}
    if len(usable) < 5:
        return None
    peaks = {}
    for name, key in (("tokens", "tok"), ("backtrack", "bt"), ("loops", "rep")):
        peak_lv = max(usable, key=lambda lv: usable[lv][key] / usable[lv]["n"])
        peaks[name] = {"peak_alpha": peak_lv, "offset_from_x50": round(peak_lv - x50, 2)}
    return {"x50": x50, "n_traced": len(rows), "n_levels": len(usable), "peaks": peaks,
            "levels": sorted(usable)}


def main() -> None:
    store = Store(config.DATA_DIR / "drc.sqlite")
    out: dict = {}
    for regime, (where, x50) in REGIMES.items():
        # capped runs die mid-thought at the wall; excluding truncations would
        # throw away exactly the calls that show peak effort, so report both
        for tr in (False, True):
            key = regime + ("_incl_trunc" if tr else "")
            r = peaks_for(store, where, x50, include_trunc=tr)
            if r:
                out[key] = r
    Path(__file__).with_name("capped_texture.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
