#!/usr/bin/env python3
"""Zero-spend proxy replay of the frozen speculative-council trace policy."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from drc.runner.speculative import TraceRiskPolicy  # noqa: E402
from drc.stats.speculative_replay import (  # noqa: E402
    prepare_replay_row,
    replay_reasoning,
    summarize_replay,
    visible_reasoning,
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_gzip_jsonl(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream]


def git_sha() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def policy_factory() -> TraceRiskPolicy:
    return TraceRiskPolicy(
        threshold=4.0,
        persistence=2,
        min_words=80,
        window_words=320,
    )


def write_predictions(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))


def make_figure(rows: list[dict], path: Path) -> None:
    groups = {
        "correct": [row for row in rows if row["outcome_class"] == "correct_completed"],
        "silent wrong": [row for row in rows if row["outcome_class"] == "silently_wrong_completed"],
        "loud failure": [row for row in rows if row["outcome_class"] == "loud_failure"],
    }
    colours = {"correct": "#2b6cb0", "silent wrong": "#b7791f", "loud failure": "#9b2c2c"}
    fig, ax = plt.subplots(figsize=(7.6, 4.8))
    for label, group in groups.items():
        values = [row["trigger_fraction"] for row in group if row["trigger_fraction"] is not None]
        if values:
            ax.hist(values, bins=[0, .2, .4, .6, .8, 1.0], alpha=.55, label=f"{label} (n={len(values)})", color=colours[label])
    ax.set(
        xlabel="trigger position (fraction of delivered reasoning words)",
        ylabel="calls",
        title="Untimestamped proxy replay of the frozen trace-risk policy",
        xlim=(0, 1),
    )
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def make_sensitivity_figure(sensitivity: list[dict], path: Path) -> None:
    chunks = [row["chunk_words"] for row in sensitivity]
    fig, ax = plt.subplots(figsize=(6.8, 4.2))
    ax.plot(chunks, [row["failure_recall"] for row in sensitivity], marker="o", label="failure recall", color="#176b51")
    ax.plot(chunks, [row["correct_false_hedge_rate"] for row in sensitivity], marker="o", label="correct false hedges", color="#9b2c2c")
    ax.plot(chunks, [row["launch_rate"] for row in sensitivity], marker="o", label="all-call fan-out", color="#2b6cb0")
    ax.axhline(.40, color="#9b2c2c", linestyle="--", linewidth=1, label="false-hedge ceiling")
    ax.set(
        xlabel="proxy observation size (reasoning words)",
        ylabel="rate",
        ylim=(0, 1.03),
        title="Proxy replay is sensitive to chunking but fails every gate",
    )
    ax.legend(frameon=False, loc="lower left")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--traces", type=Path,
        default=ROOT / "data" / "exports" / "minimax-confidence-v1-traces.jsonl.gz",
    )
    parser.add_argument(
        "--compact", type=Path,
        default=ROOT / "data" / "exports" / "minimax-confidence-v1.jsonl.gz",
    )
    parser.add_argument(
        "--out", type=Path,
        default=ROOT / "analysis" / "speculative-replay.json",
    )
    parser.add_argument("--chunk-words", type=int, default=40)
    parser.add_argument("--sensitivity-chunks", default="20,40,80,160")
    args = parser.parse_args()

    compact = {row["call_id"]: row for row in read_gzip_jsonl(args.compact)}
    raw_rows = read_gzip_jsonl(args.traces)
    def build_rows(chunk_words: int) -> list[dict]:
        rows = []
        for raw in raw_rows:
            reasoning = visible_reasoning(raw.get("response_text") or "")
            if not reasoning or raw["call_id"] not in compact:
                continue
            replay = replay_reasoning(
                reasoning, policy_factory, chunk_words=chunk_words
            )
            rows.append(prepare_replay_row(raw, compact[raw["call_id"]], replay))
        return rows

    replay_rows = build_rows(args.chunk_words)
    sensitivity = []
    for chunk_words in [int(value) for value in args.sensitivity_chunks.split(",")]:
        rows = replay_rows if chunk_words == args.chunk_words else build_rows(chunk_words)
        summary = summarize_replay(rows)
        rates = summary["trace_trigger"]
        sensitivity.append({
            "chunk_words": chunk_words,
            "launch_rate": rates["launch_rate"],
            "failure_recall": rates["failure_recall"],
            "correct_false_hedge_rate": rates["correct_false_hedge_rate"],
            "non_timing_gate_pass": all(summary["non_timing_conditions"].values()),
        })

    predictions = ROOT / "analysis" / "speculative-replay-predictions.jsonl"
    figure = ROOT / "analysis" / "speculative-replay.svg"
    sensitivity_figure = ROOT / "analysis" / "speculative-replay-sensitivity.svg"
    write_predictions(predictions, replay_rows)
    make_figure(replay_rows, figure)
    make_sensitivity_figure(sensitivity, sensitivity_figure)
    results = summarize_replay(replay_rows)
    results["proxy_chunk_sensitivity"] = sensitivity
    report = {
        "study": "speculative-council-v0",
        "claim_status": "Censored",
        "mode": "untimestamped_word_chunk_proxy_replay",
        "policy": {
            "threshold": 4.0,
            "persistence": 2,
            "min_words": 80,
            "window_words": 320,
            "proxy_chunk_words": args.chunk_words,
        },
        "results": results,
        "provenance": {
            "code_git_sha": git_sha(),
            "traces": str(args.traces.relative_to(ROOT)),
            "traces_sha256": sha256(args.traces),
            "compact": str(args.compact.relative_to(ROOT)),
            "compact_sha256": sha256(args.compact),
            "predictions": str(predictions.relative_to(ROOT)),
            "predictions_sha256": sha256(predictions),
            "figure": str(figure.relative_to(ROOT)),
            "figure_sha256": sha256(figure),
            "sensitivity_figure": str(sensitivity_figure.relative_to(ROOT)),
            "sensitivity_figure_sha256": sha256(sensitivity_figure),
            "new_spend_usd": 0.0,
        },
    }
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
