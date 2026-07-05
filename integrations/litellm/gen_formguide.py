"""Generate formguide.json (the router's config) from the measured card:
analysis/numbers.json + analysis/routing.json. Never hand-typed."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
N = json.loads((ROOT / "analysis" / "numbers.json").read_text())

# litellm model strings via OpenRouter for portability
LITELLM_MODEL = {
    "openai/gpt-oss-20b": "openrouter/openai/gpt-oss-20b",
    "openai/gpt-oss-120b": "openrouter/openai/gpt-oss-120b",
    "deepseek/deepseek-r1-0528": "openrouter/deepseek/deepseek-r1-0528",
    "anthropic/claude-haiku-4.5": "openrouter/anthropic/claude-haiku-4.5",
    "openai/o4-mini": "openrouter/openai/o4-mini",
    "minimax/minimax-m2.5": "openrouter/minimax/minimax-m2.5",
}
PRICE_OUT = {
    "openai/gpt-oss-20b": 0.22, "openai/gpt-oss-120b": 0.55,
    "deepseek/deepseek-r1-0528": 2.75, "anthropic/claude-haiku-4.5": 5.5,
    "openai/o4-mini": 4.84, "minimax/minimax-m2.5": 1.32,
}
# budget-elastic models need generous caps (measured: MiniMax loses ~3 dial
# units when capped at 32k)
BUDGET = {"minimax/minimax-m2.5": 65536}

rungs = []
for mid, entry in N["models"].items():
    s = entry.get("sat", {})
    if not isinstance(s.get("x50"), (int, float)) or mid not in LITELLM_MODEL:
        continue
    rungs.append(
        {
            "model": LITELLM_MODEL[mid],
            "frontier": s["x50"],
            "sharpness": s.get("a") or 1.5,
            "max_tokens": BUDGET.get(mid, 32768),
            "price_out_per_m": PRICE_OUT[mid],
            "retries": 3,
            "calibrated_at": str(date.today()),
            "notes": " ".join(s.get("flags", [])),
        }
    )
rungs.sort(key=lambda r: r["frontier"])
out = {
    "task_family": "sat-n20 (difficulty = clause/variable ratio)",
    "policy": "start at cheapest rung covering difficulty; retry within mist; escalate by frontier order",
    "provenance": "generated from analysis/numbers.json; recalibrate with recalibrate.py",
    "rungs": rungs,
}
Path(__file__).with_name("formguide.json").write_text(json.dumps(out, indent=2))
print(f"wrote formguide.json with {len(rungs)} rungs (frontier order: "
      + " -> ".join(r["model"].split("/")[-1] for r in rungs) + ")")
