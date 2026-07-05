"""Calibrations expire: in our data the same pinned endpoint moved a
model's frontier a full dial unit within twelve hours. This wrapper
re-probes each rung with the adaptive search (~20-120 calls, cents to a
few dollars per model) and rewrites formguide.json.

    python recalibrate.py --cap-per-model 3.0
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

# formguide model string -> drc models.toml id
DRC_ID = {
    "openrouter/openai/gpt-oss-20b": "openai/gpt-oss-20b",
    "openrouter/openai/gpt-oss-120b": "openai/gpt-oss-120b",
    "openrouter/deepseek/deepseek-r1-0528": "deepseek/deepseek-r1-0528",
    "openrouter/anthropic/claude-haiku-4.5": "anthropic/claude-haiku-4.5",
    "openrouter/openai/o4-mini": "openai/o4-mini",
    "openrouter/minimax/minimax-m2.5": "minimax/minimax-m2.5",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cap-per-model", type=float, default=3.0)
    ap.add_argument("--eps", type=float, default=0.15)
    ap.add_argument("--only", default="", help="comma-separated substring filter")
    args = ap.parse_args()

    guide_path = HERE / "formguide.json"
    guide = json.loads(guide_path.read_text())
    for rung in guide["rungs"]:
        if args.only and not any(f in rung["model"] for f in args.only.split(",")):
            continue
        drc_id = DRC_ID.get(rung["model"])
        if not drc_id:
            print(f"skip {rung['model']}: no drc mapping")
            continue
        print(f"re-probing {drc_id} (cap ${args.cap_per_model}) ...")
        r = subprocess.run(
            [sys.executable, "-m", "drc.cli", "adaptive", "--model", drc_id,
             "--eps", str(args.eps), "--cap", str(args.cap_per_model),
             "--tag", f"recal-{date.today().isoformat()}"],
            cwd=ROOT, capture_output=True, text=True,
        )
        out_lines = [l for l in r.stdout.splitlines() if l.strip().startswith('"x50"')]
        result_file = sorted(ROOT.glob(f"data/adaptive-{drc_id.split('/')[-1]}*recal*.json"))
        if result_file:
            res = json.loads(result_file[-1].read_text())
            old = rung["frontier"]
            rung["frontier"] = round(res["x50"], 3)
            rung["calibrated_at"] = str(date.today())
            drift = rung["frontier"] - old
            flag = "  << DRIFT" if abs(drift) > 0.3 else ""
            print(f"  {drc_id}: {old} -> {rung['frontier']} ({drift:+.2f}){flag}")
        else:
            print(f"  {drc_id}: probe produced no result ({out_lines or r.stderr[-200:]})")
    guide["rungs"].sort(key=lambda r: r["frontier"])
    guide_path.write_text(json.dumps(guide, indent=2))
    print("formguide.json updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
