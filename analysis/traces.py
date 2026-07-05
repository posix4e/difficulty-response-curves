"""Trace availability and trace-texture signals, computed from the released
store. Writes analysis/traces.json (read by the paper and site).

Two questions:
1. Availability — of the reasoning you are billed for, how much text does
   each model x route actually deliver? (delivered_share = chars received /
   (billed tokens x 3.7 chars-per-token))
2. Texture — where traces ARE delivered, does trace structure (loop share =
   fraction of repeated 12-word shingles; backtracking-marker density)
   locate the frontier better than raw token count?
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from drc import config
from drc.runner.store import Store

BACKTRACK = re.compile(
    r"\b(wait|hmm+|actually|let me (re|try again)|that's wrong|doesn't work|start over|backtrack)\b",
    re.I,
)


def shingle_rep(text: str, k: int = 12) -> float:
    words = text.split()
    if len(words) < 3 * k:
        return 0.0
    shingles = [" ".join(words[i : i + k]) for i in range(0, len(words) - k, k)]
    return 1 - len(set(shingles)) / len(shingles)


def availability(store: Store) -> list[dict]:
    rows = store.conn.execute(
        """SELECT c.model_id,
                  COALESCE(substr(c.provider_endpoint, instr(c.provider_endpoint,'@')+1),
                           c.provider_endpoint, '?') AS route,
                  COUNT(*) n, AVG(c.completion_tokens) tok,
                  AVG(LENGTH(c.response_text)) chars
           FROM calls c
           WHERE c.outcome IN ('pass','fail_wrong') AND c.completion_tokens > 500
           GROUP BY c.model_id, route HAVING n >= 6"""
    ).fetchall()
    out = []
    for m, route, n, tok, chars in rows:
        out.append(
            {
                "model": m,
                "route": route,
                "n": n,
                "avg_billed_tokens": round(tok),
                "delivered_share": round(chars / (tok * 3.7), 3),
            }
        )
    return sorted(out, key=lambda r: (r["model"], r["route"]))


def texture(store: Store) -> dict:
    results = {}
    for model, x50 in (
        ("deepseek/deepseek-r1-0528", 3.78),
        ("qwen/qwen3-235b-a22b-thinking-2507", 4.19),
        ("minimax/minimax-m2.5", 6.58),
    ):
        rows = store.conn.execute(
            """SELECT i.level_value, c.completion_tokens, c.response_text
               FROM calls c JOIN instances i USING(instance_id)
               WHERE c.model_id=? AND i.family='sat'
                 AND c.outcome IN ('pass','fail_wrong') AND LENGTH(c.response_text) > 2000""",
            (model,),
        ).fetchall()
        by_level: dict[float, dict] = {}
        for lv, tok, txt in rows:
            d = by_level.setdefault(round(lv, 2), {"n": 0, "tok": 0.0, "bt": 0.0, "rep": 0.0})
            d["n"] += 1
            d["tok"] += tok or 0
            d["bt"] += len(BACKTRACK.findall(txt)) / max((tok or 1) / 1000, 0.1)
            d["rep"] += shingle_rep(txt)
        if len(by_level) < 5:
            continue
        peaks = {}
        for name, key in (("tokens", "tok"), ("backtrack", "bt"), ("loops", "rep")):
            peak_lv = max(by_level, key=lambda lv: by_level[lv][key] / by_level[lv]["n"])
            peaks[name] = {"peak_alpha": peak_lv, "offset_from_x50": round(peak_lv - x50, 2)}
        results[model] = {"x50": x50, "n_traced": len(rows), "peaks": peaks}
    return results


if __name__ == "__main__":
    store = Store(config.DATA_DIR / "drc.sqlite")
    out = {"availability": availability(store), "texture": texture(store)}
    Path(__file__).with_name("traces.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out["texture"], indent=1))
    print(f"{len(out['availability'])} availability rows written")
