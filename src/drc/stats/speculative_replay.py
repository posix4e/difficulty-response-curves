"""Offline replay helpers for the frozen trace-risk policy."""

from __future__ import annotations

from dataclasses import asdict
import math
import re
from statistics import median
from typing import Callable, Sequence

import numpy as np

from drc.runner.speculative import RiskSnapshot, TraceRiskPolicy
from drc.stats.confidence import outcome_class


PolicyFactory = Callable[[], TraceRiskPolicy]
THINK = re.compile(r"<think>(.*?)(?:</think>|$)", re.S)


def visible_reasoning(text: str) -> str | None:
    match = THINK.search(text or "")
    if not match:
        return None
    reasoning = match.group(1).strip()
    return reasoning or None


def replay_reasoning(
    reasoning: str,
    policy_factory: PolicyFactory,
    *,
    chunk_words: int = 40,
) -> dict:
    if chunk_words < 1:
        raise ValueError("chunk_words must be positive")
    words = reasoning.split()
    policy = policy_factory()
    trigger: RiskSnapshot | None = None
    trigger_words: int | None = None
    observations = 0
    for start in range(0, len(words), chunk_words):
        snapshot = policy.observe(" ".join(words[start : start + chunk_words]))
        observations += 1
        if snapshot.triggered and trigger is None:
            trigger = snapshot
            trigger_words = min(len(words), start + chunk_words)
    fraction = trigger_words / len(words) if trigger_words is not None and words else None
    return {
        "trace_words": len(words),
        "observations": observations,
        "triggered": trigger is not None,
        "trigger_words": trigger_words,
        "trigger_fraction": round(fraction, 6) if fraction is not None else None,
        "trigger": asdict(trigger) if trigger else None,
    }


def matched_fixed_delay(rows: Sequence[dict], launch_rate: float) -> dict:
    latencies = np.asarray(
        [float(row["latency_ms"]) for row in rows if row.get("latency_ms") is not None],
        dtype=float,
    )
    if not len(latencies) or launch_rate <= 0:
        return {"available": False}
    delay = float(np.quantile(latencies, max(0.0, min(1.0, 1 - launch_rate))))
    eligible = [row for row in rows if row.get("latency_ms") is not None]
    launches = [row for row in eligible if float(row["latency_ms"]) > delay]
    failures = [row for row in eligible if row["outcome_class"] != "correct_completed"]
    caught = [row for row in failures if float(row["latency_ms"]) > delay]
    return {
        "available": True,
        "delay_ms": round(delay, 3),
        "launch_rate": round(len(launches) / len(eligible), 6),
        "failure_recall": round(len(caught) / len(failures), 6) if failures else None,
        "note": "Matched using end-to-end completion latency; this is a retrospective proxy, not a live timer result.",
    }


def summarize_replay(rows: Sequence[dict]) -> dict:
    if not rows:
        return {
            "status": "Censored",
            "reason": "no visible traces were eligible for replay",
            "counts": {"eligible": 0},
        }
    correct = [row for row in rows if row["outcome_class"] == "correct_completed"]
    silent = [row for row in rows if row["outcome_class"] == "silently_wrong_completed"]
    loud = [row for row in rows if row["outcome_class"] == "loud_failure"]
    failures = [*silent, *loud]
    triggered = [row for row in rows if row["triggered"]]

    def rate(group: Sequence[dict]) -> float | None:
        return round(sum(bool(row["triggered"]) for row in group) / len(group), 6) if group else None

    proxy_warning = [
        float(row["latency_ms"]) * (1 - float(row["trigger_fraction"]))
        for row in triggered
        if row.get("latency_ms") is not None and row.get("trigger_fraction") is not None
    ]
    launch_rate = len(triggered) / len(rows)
    replay_conditions = {
        "at_least_30_eligible": len(rows) >= 30,
        "at_least_10_failures": len(failures) >= 10,
        "failure_trigger_recall_at_least_0_60": (rate(failures) or 0) >= 0.60,
        "correct_false_hedge_at_most_0_40": (rate(correct) or 0) <= 0.40,
    }
    return {
        "status": "Censored",
        "reason": (
            "historical exports have full traces but no timestamped chunks; "
            "the registered 15-second warning-time condition cannot be evaluated"
        ),
        "counts": {
            "eligible": len(rows),
            "correct": len(correct),
            "silently_wrong": len(silent),
            "loud_failure": len(loud),
            "failures": len(failures),
            "triggered": len(triggered),
        },
        "trace_trigger": {
            "launch_rate": round(launch_rate, 6),
            "failure_recall": rate(failures),
            "silent_wrong_recall": rate(silent),
            "loud_failure_recall": rate(loud),
            "correct_false_hedge_rate": rate(correct),
            "median_trigger_fraction": round(
                median(float(row["trigger_fraction"]) for row in triggered), 6
            ) if triggered else None,
            "median_proxy_warning_ms": round(median(proxy_warning), 3) if proxy_warning else None,
            "timing_label": "Proxy only: latency multiplied by remaining trace fraction.",
        },
        "matched_fixed_delay": matched_fixed_delay(rows, launch_rate),
        "non_timing_conditions": replay_conditions,
        "gate_pass": False,
    }


def prepare_replay_row(raw: dict, compact: dict, replay: dict) -> dict:
    latency = compact.get("latency_ms")
    fraction = replay.get("trigger_fraction")
    proxy_trigger_ms = (
        float(latency) * float(fraction)
        if latency is not None and fraction is not None and math.isfinite(float(latency))
        else None
    )
    return {
        "call_id": raw["call_id"],
        "instance_id_hash": raw.get("instance_id_hash"),
        "outcome_class": compact.get("outcome_class") or outcome_class(str(raw.get("outcome", ""))),
        "latency_ms": latency,
        **replay,
        "proxy_trigger_ms": round(proxy_trigger_ms, 3) if proxy_trigger_ms is not None else None,
    }
