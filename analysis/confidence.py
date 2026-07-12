#!/usr/bin/env python3
"""Retrospective MiniMax confidence analysis and reproducible study export.

Run from the repository root:

    .venv/bin/python analysis/confidence.py

No API calls are made. The source is the local SQLite call store; outputs are
the result JSON, per-call out-of-fold predictions, a frozen model when the gate
passes, compact and raw-trace exports, and three SVG figures.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
from typing import Iterable

import matplotlib.pyplot as plt
import numpy as np
from scipy.special import expit, logit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from drc.stats.confidence import (  # noqa: E402
    DesignState,
    apply_design,
    assert_group_isolation,
    clustered_brier_skill_ci,
    deterministic_group_folds,
    fit_design,
    fit_ridge_logistic,
    metric_summary,
    outcome_class,
    predict_ridge_logistic,
    protocol_request_matches,
    risk_coverage,
    stopping_reason,
)
from drc.stats.tracefeat import extra_features, features  # noqa: E402
from drc.stats.twopl import InstanceObs, fit_with_lapse_guard  # noqa: E402


STUDY = "minimax-confidence-v1"
MODEL = "or/minimax-m2.5"
PROVIDER = "openrouter/Parasail"
SET_NAME = "percall"
PROSPECTIVE_SET = "minimax-confidence-v1"
PROSPECTIVE_STAGE = "minimax-confidence-v1"
SENTINEL_SET = "minimax-confidence-sentinel-v1"
SENTINEL_STAGES = (
    "minimax-confidence-sentinel-pre",
    "minimax-confidence-sentinel-post",
)
CAP_TOKENS = 65536
EXPECTED_LEVELS = (6.3, 6.6, 6.9)
TRACE_FEATURES = [
    "rep_tail", "bt_tail", "hedge_tail", "rep_full", "bt_full", "wait_tail",
    "hedge_ans", "giveup_full", "flip", "qmark_tail", "rep_tail_k4",
    "wait_full", "bt_last10", "neg_tail", "len_ratio", "trace_visible",
]
METADATA_FEATURES = [
    "log_completion_tokens", "log_reasoning_tokens", "cap_fraction",
    "log_latency_ms", "log_effective_billed_tps", "attempt",
    "finish_stop", "finish_other",
]
MODEL_FEATURES = {
    "metadata": ["curve_logit", *METADATA_FEATURES],
    "trace": ["curve_logit", *TRACE_FEATURES],
    "combined": ["curve_logit", *METADATA_FEATURES, *TRACE_FEATURES],
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def git_sha() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def _visible_trace(text: str) -> str | None:
    match = re.search(r"<think>(.*?)(?:</think>|$)", text or "", re.S)
    if not match:
        return None
    trace = match.group(1).strip()
    return trace if len(trace) >= 200 else None


def load_cohort(
    db: Path,
    *,
    set_name: str = SET_NAME,
    stages: tuple[str, ...] | None = None,
    expected_levels: tuple[float, ...] = EXPECTED_LEVELS,
) -> list[dict]:
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    query = """
        SELECT c.call_id, c.instance_id, c.model_id, c.sample_idx, c.stage,
               c.prompt_version, c.request_json, c.response_text, c.finish_reason,
               c.outcome, c.pass, c.prompt_tokens, c.completion_tokens,
               c.reasoning_tokens, c.cost_microdollars, c.provider_endpoint,
               c.provider_mismatch, c.http_status, c.attempt, c.latency_ms,
               c.ts_start, c.ts_end, i.level_idx, i.level_value, i.set_name,
               i.family
        FROM calls c JOIN instances i USING(instance_id)
        WHERE c.model_id=? AND i.set_name=?
          AND i.family='sat'
        ORDER BY c.call_id
    """
    rows = [dict(row) for row in con.execute(query, (MODEL, set_name))]
    con.close()
    if stages is not None:
        rows = [row for row in rows if row["stage"] in stages]
    if not rows:
        raise RuntimeError(f"MiniMax confidence cohort is empty for set {set_name}")
    levels = tuple(sorted({round(float(r["level_value"]), 1) for r in rows}))
    if levels != expected_levels:
        raise RuntimeError(f"cohort levels changed: {levels}, expected {expected_levels}")
    for row in rows:
        if row["provider_endpoint"] != PROVIDER or row["provider_mismatch"]:
            raise RuntimeError(
                f"call {row['call_id']} violates provider continuity: "
                f"{row['provider_endpoint']!r}"
            )
        if not protocol_request_matches(row["request_json"], "parasail", CAP_TOKENS):
            raise RuntimeError(f"call {row['call_id']} violates the frozen provider/cap protocol")
        row["outcome_class"] = outcome_class(str(row["outcome"]))
        row["label"] = 1 if row["outcome_class"] == "correct_completed" else 0
        trace = _visible_trace(row["response_text"] or "")
        row["trace_visible"] = 1.0 if trace else 0.0
        if trace:
            tf = features(row["response_text"] or "", row["completion_tokens"])
            tf.update(extra_features(row["response_text"] or "", row["completion_tokens"]))
            for name in TRACE_FEATURES:
                if name != "trace_visible":
                    row[name] = float(tf[name])
        else:
            for name in TRACE_FEATURES:
                if name != "trace_visible":
                    row[name] = None
        completion = float(row["completion_tokens"] or 0)
        reasoning = row["reasoning_tokens"]
        latency = float(row["latency_ms"] or 0)
        tps = completion / (latency / 1000.0) if completion > 0 and latency > 0 else None
        row.update({
            "log_completion_tokens": math.log1p(completion) if completion > 0 else None,
            "log_reasoning_tokens": math.log1p(float(reasoning)) if reasoning else None,
            "cap_fraction": completion / CAP_TOKENS if completion > 0 else None,
            "log_latency_ms": math.log1p(latency) if latency > 0 else None,
            "effective_billed_tps": tps,
            "log_effective_billed_tps": math.log1p(tps) if tps and tps > 0 else None,
            "finish_stop": 1.0 if row["finish_reason"] in ("stop", "end_turn") else 0.0,
            "finish_other": 0.0 if row["finish_reason"] in ("stop", "end_turn") else 1.0,
        })
    return rows


def fit_curve(rows: list[dict]):
    grouped: dict[tuple[str, int, float], list[dict]] = defaultdict(list)
    for row in rows:
        grouped[(row["instance_id"], int(row["level_idx"]), float(row["level_value"]))].append(row)
    obs = [
        InstanceObs(iid, level_idx, level, len(group), sum(int(r["label"]) for r in group))
        for (iid, level_idx, level), group in grouped.items()
    ]
    return fit_with_lapse_guard(obs, quick=True)


def curve_predictions(fit, rows: list[dict]) -> np.ndarray:
    p = fit.predict(np.asarray([r["level_value"] for r in rows], dtype=float))
    return np.clip(p, 1e-5, 1 - 1e-5)


def cross_fitted_predictions(rows: list[dict], folds: dict[str, int]) -> tuple[dict[str, np.ndarray], dict]:
    out = {name: np.full(len(rows), np.nan) for name in ("curve", *MODEL_FEATURES)}
    fold_fits: dict[str, list[dict]] = {name: [] for name in MODEL_FEATURES}
    for fold in sorted(set(folds.values())):
        train_idx = [i for i, r in enumerate(rows) if folds[r["instance_id"]] != fold]
        test_idx = [i for i, r in enumerate(rows) if folds[r["instance_id"]] == fold]
        train = [rows[i] for i in train_idx]
        test = [rows[i] for i in test_idx]
        curve = fit_curve(train)
        train_curve = curve_predictions(curve, train)
        test_curve = curve_predictions(curve, test)
        out["curve"][test_idx] = test_curve
        for r, p in zip(train, train_curve):
            r["curve_logit"] = float(logit(p))
        for r, p in zip(test, test_curve):
            r["curve_logit"] = float(logit(p))
        y_train = np.asarray([r["label"] for r in train], dtype=float)
        for model_name, names in MODEL_FEATURES.items():
            X_train, design = fit_design(train, names)
            weights = fit_ridge_logistic(X_train, y_train, l2=1.0)
            X_test = apply_design(test, design)
            out[model_name][test_idx] = predict_ridge_logistic(X_test, weights)
            fold_fits[model_name].append({
                "fold": fold,
                "n_train": len(train),
                "n_test": len(test),
                "curve_x50": curve.x50,
                "expanded_features": design.expanded_features,
            })
    for name, values in out.items():
        if not np.isfinite(values).all():
            raise RuntimeError(f"missing out-of-fold predictions for {name}")
    return out, fold_fits


def fit_frozen(rows: list[dict], model_name: str) -> dict:
    curve = fit_curve(rows)
    p = curve_predictions(curve, rows)
    for row, value in zip(rows, p):
        row["curve_logit"] = float(logit(value))
    X, design = fit_design(rows, MODEL_FEATURES[model_name])
    weights = fit_ridge_logistic(X, np.asarray([r["label"] for r in rows]), l2=1.0)
    return {
        "study": STUDY,
        "status": "frozen_after_retrospective_gate",
        "model_class": model_name,
        "cohort": {
            "model": MODEL,
            "provider_endpoint": PROVIDER,
            "set_name": SET_NAME,
            "levels": list(EXPECTED_LEVELS),
            "max_completion_tokens": CAP_TOKENS,
        },
        "curve": {"b": curve.b, "a": curve.a, "lapse": curve.lapse, "x50": curve.x50},
        "design": design.as_dict(),
        "weights": [float(v) for v in weights],
    }


def forward_stage_holdout(rows: list[dict], model_name: str) -> dict:
    """Secondary drift check: train on the first batch, test on its fresh-seed top-up."""
    train = [r for r in rows if r["stage"] == "percall-minimax-or"]
    test = [r for r in rows if r["stage"] == "percall-minimax-or2"]
    if not train or not test:
        return {"available": False}
    curve = fit_curve(train)
    p_train = curve_predictions(curve, train)
    p_test = curve_predictions(curve, test)
    for row, value in zip(train, p_train):
        row["curve_logit"] = float(logit(value))
    for row, value in zip(test, p_test):
        row["curve_logit"] = float(logit(value))
    X_train, design = fit_design(train, MODEL_FEATURES[model_name])
    weights = fit_ridge_logistic(X_train, np.asarray([r["label"] for r in train]), l2=1.0)
    pred = predict_ridge_logistic(apply_design(test, design), weights)
    return {
        "available": True,
        "train_stage": "percall-minimax-or",
        "test_stage": "percall-minimax-or2",
        "n_train": len(train),
        "n_test": len(test),
        "n_test_silent_wrong": sum(not r["label"] for r in test),
        "metrics": metric_summary([r["label"] for r in test], pred, p_test),
    }


def feature_diagnostics(rows: list[dict]) -> dict:
    out = {}
    for name in ("completion_tokens", "reasoning_tokens", "latency_ms", "effective_billed_tps"):
        entry = {}
        for label, label_name in ((1, "correct"), (0, "silent_wrong")):
            values = [float(r[name]) for r in rows if r["label"] == label and r.get(name) is not None]
            entry[label_name] = {
                "n": len(values),
                "mean": round(float(np.mean(values)), 6) if values else None,
                "median": round(float(np.median(values)), 6) if values else None,
            }
        out[name] = entry
    return out


def frozen_predictions(rows: list[dict], frozen: dict) -> tuple[np.ndarray, np.ndarray]:
    """Apply the registered curve and confidence coefficients without refitting."""
    curve = frozen["curve"]
    levels = np.asarray([r["level_value"] for r in rows], dtype=float)
    prior = (1 - float(curve["lapse"])) * expit(
        float(curve["a"]) * (float(curve["b"]) - levels)
    )
    prior = np.clip(prior, 1e-5, 1 - 1e-5)
    for row, value in zip(rows, prior):
        row["curve_logit"] = float(logit(value))
    design = DesignState(**frozen["design"])
    prediction = predict_ridge_logistic(
        apply_design(rows, design), np.asarray(frozen["weights"], dtype=float)
    )
    return prior, prediction


def prospective_one_look(args: argparse.Namespace) -> int:
    """Run the single registered prospective read after a hard stop."""
    frozen = json.loads(args.frozen.read_text())
    if frozen.get("status") != "frozen_after_retrospective_gate":
        raise RuntimeError("prospective model is not a registered frozen model")

    rows = load_cohort(
        args.db, set_name=PROSPECTIVE_SET, stages=(PROSPECTIVE_STAGE,)
    )
    sentinels = load_cohort(
        args.db, set_name=SENTINEL_SET, stages=SENTINEL_STAGES
    )
    sentinel_counts = {
        stage: sum(row["stage"] == stage for row in sentinels)
        for stage in SENTINEL_STAGES
    }
    if any(sentinel_counts[stage] < 6 for stage in SENTINEL_STAGES):
        raise RuntimeError(f"both six-call sentinels are required: {sentinel_counts}")

    completed = [r for r in rows if r["outcome_class"] != "loud_failure"]
    counts = {
        "all_calls": len(rows),
        "correct_completed": sum(r["outcome_class"] == "correct_completed" for r in rows),
        "silently_wrong_completed": sum(
            r["outcome_class"] == "silently_wrong_completed" for r in rows
        ),
        "loud_failure": sum(r["outcome_class"] == "loud_failure" for r in rows),
        "instances_completed": len({r["instance_id"] for r in completed}),
    }
    main_spend = sum(r["cost_microdollars"] or 0 for r in rows) / 1_000_000
    reason = stopping_reason(
        counts["correct_completed"],
        counts["silently_wrong_completed"],
        counts["all_calls"],
        main_spend,
        max_spend_usd=38.0,
    )
    if reason is None:
        raise RuntimeError(
            "prospective run has not reached its label, call, or spend stop; "
            "the registered one-look analysis is locked"
        )
    if not completed or len({r["label"] for r in completed}) < 2:
        raise RuntimeError("prospective completed cohort lacks both outcome classes")

    prior, prediction = frozen_predictions(completed, frozen)
    for row, p0, p1 in zip(completed, prior, prediction):
        row["pred_curve"] = float(p0)
        row["pred_frozen"] = float(p1)
    metrics = metric_summary([r["label"] for r in completed], prediction, prior)
    lo, hi = clustered_brier_skill_ci(
        completed, "pred_frozen", "pred_curve", B=args.bootstrap
    )
    metrics["brier_skill_ci95"] = [round(lo, 6), round(hi, 6)]
    metrics["risk_coverage"] = risk_coverage(
        [r["label"] for r in completed], prediction
    )
    gate = {
        "brier_skill_at_least_0_10": metrics["brier_skill_vs_curve"] >= 0.10,
        "brier_skill_ci_excludes_zero": lo > 0,
        "auc_at_least_0_75": metrics["auc"] >= 0.75,
    }
    gate["pass"] = all(gate.values())

    prediction_path = ROOT / "analysis" / "confidence-minimax-prospective-predictions.jsonl"
    write_jsonl(prediction_path, ({
        "call_id": row["call_id"],
        "instance_id_hash": hashlib.sha256(row["instance_id"].encode()).hexdigest(),
        "level_value": row["level_value"],
        "outcome_class": row["outcome_class"],
        "label": row["label"],
        "pred_curve": row["pred_curve"],
        "pred_frozen": row["pred_frozen"],
    } for row in completed))
    report = {
        "study": STUDY,
        "status": "prospective_single_analysis_complete",
        "claim_status": "Supported" if gate["pass"] else "Not supported",
        "stopping_reason": reason,
        "cohort": {
            "model": MODEL,
            "provider_endpoint": PROVIDER,
            "set_name": PROSPECTIVE_SET,
            "levels": list(EXPECTED_LEVELS),
            "max_completion_tokens": CAP_TOKENS,
            "counts": counts,
            "sentinel_counts": sentinel_counts,
        },
        "frozen_model": {
            "path": str(args.frozen.relative_to(ROOT)),
            "sha256": sha256_file(args.frozen),
            "model_class": frozen["model_class"],
        },
        "metrics": metrics,
        "prospective_gate": gate,
        "provenance": {
            "code_git_sha": git_sha(),
            "source_db_sha256": sha256_file(args.db),
            "bootstrap_replicates": args.bootstrap,
            "predictions": str(prediction_path.relative_to(ROOT)),
            "prospective_spend_usd": round(main_spend, 6),
            "sentinel_spend_usd": round(
                sum(r["cost_microdollars"] or 0 for r in sentinels) / 1_000_000, 6
            ),
        },
    }
    args.prospective_out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


def _json_value(value):
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def write_jsonl(path: Path, rows: Iterable[dict], gzip_output: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if gzip_output:
        raw = path.open("wb")
        compressed = gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0)
        stream = io.TextIOWrapper(compressed, encoding="utf-8")
    else:
        raw = None
        compressed = None
        stream = path.open("w", encoding="utf-8")
    try:
        for row in rows:
            clean = {key: _json_value(value) for key, value in row.items()}
            stream.write(json.dumps(clean, sort_keys=True) + "\n")
    finally:
        stream.close()
        if compressed is not None and not compressed.closed:
            compressed.close()
        if raw is not None and not raw.closed:
            raw.close()


def make_figures(rows: list[dict], metrics: dict, out_dir: Path) -> list[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    y = np.asarray([r["label"] for r in rows], dtype=float)
    colours = {"curve": "#6b7280", "metadata": "#2b6cb0", "trace": "#b7791f", "combined": "#176b51"}

    fig, ax = plt.subplots(figsize=(6.4, 4.4))
    for name in colours:
        p = np.asarray([r[f"pred_{name}"] for r in rows])
        bins = np.quantile(p, np.linspace(0, 1, 6))
        bins = np.unique(bins)
        xs, ys = [], []
        for lo, hi in zip(bins[:-1], bins[1:]):
            mask = (p >= lo) & (p <= hi if hi == bins[-1] else p < hi)
            if mask.any():
                xs.append(float(p[mask].mean())); ys.append(float(y[mask].mean()))
        ax.plot(xs, ys, marker="o", label=name, color=colours[name])
    ax.plot([0, 1], [0, 1], linestyle="--", color="#999999", linewidth=1)
    ax.set(xlabel="mean predicted probability", ylabel="observed accuracy", title="Out-of-fold calibration")
    ax.legend(frameon=False)
    fig.tight_layout()
    calibration = out_dir / "confidence-minimax-calibration.svg"
    fig.savefig(calibration); plt.close(fig)

    fig, ax = plt.subplots(figsize=(6.4, 4.4))
    coverages = np.linspace(0.1, 1.0, 10)
    for name in colours:
        p = np.asarray([r[f"pred_{name}"] for r in rows])
        order = np.argsort(-p)
        acc = [float(y[order[:max(1, int(np.ceil(len(y) * c))) ]].mean()) for c in coverages]
        ax.plot(coverages, acc, label=name, color=colours[name])
    ax.set(xlabel="coverage retained", ylabel="accuracy", ylim=(0, 1.03), title="Risk-coverage curve")
    ax.legend(frameon=False)
    fig.tight_layout()
    risk = out_dir / "confidence-minimax-risk-coverage.svg"
    fig.savefig(risk); plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(7.4, 3.7))
    names = list(colours)
    axes[0].bar(names, [metrics[n]["brier_skill_vs_curve"] for n in names], color=[colours[n] for n in names])
    axes[0].axhline(0.10, color="#9b2c2c", linestyle="--", linewidth=1)
    axes[0].set(title="Brier skill vs curve", ylabel="skill")
    axes[1].bar(names, [metrics[n]["auc"] for n in names], color=[colours[n] for n in names])
    axes[1].axhline(0.75, color="#9b2c2c", linestyle="--", linewidth=1)
    axes[1].set(title="AUROC", ylim=(0.4, 1.0))
    for ax in axes: ax.tick_params(axis="x", rotation=30)
    fig.tight_layout()
    ablation = out_dir / "confidence-minimax-ablation.svg"
    fig.savefig(ablation); plt.close(fig)
    return [str(p.relative_to(ROOT)) for p in (calibration, risk, ablation)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "drc.sqlite")
    parser.add_argument("--out", type=Path, default=ROOT / "analysis" / "confidence-minimax.json")
    parser.add_argument("--bootstrap", type=int, default=2000)
    parser.add_argument("--prospective-one-look", action="store_true")
    parser.add_argument(
        "--frozen", type=Path,
        default=ROOT / "analysis" / "confidence-minimax-frozen.json",
    )
    parser.add_argument(
        "--prospective-out", type=Path,
        default=ROOT / "analysis" / "confidence-minimax-prospective.json",
    )
    args = parser.parse_args()

    if args.prospective_one_look:
        return prospective_one_look(args)

    all_rows = load_cohort(args.db)
    completed = [r for r in all_rows if r["outcome_class"] != "loud_failure"]
    folds = deterministic_group_folds(completed, k=5)
    assert_group_isolation(completed, folds)
    predictions, fold_fits = cross_fitted_predictions(completed, folds)
    for i, row in enumerate(completed):
        row["fold"] = folds[row["instance_id"]]
        for name, values in predictions.items():
            row[f"pred_{name}"] = float(values[i])

    y = [r["label"] for r in completed]
    curve = [r["pred_curve"] for r in completed]
    metrics = {}
    for name in ("curve", *MODEL_FEATURES):
        p = [r[f"pred_{name}"] for r in completed]
        metrics[name] = metric_summary(y, p, curve)
        lo, hi = clustered_brier_skill_ci(
            completed, f"pred_{name}", "pred_curve", B=args.bootstrap
        ) if name != "curve" else (0.0, 0.0)
        metrics[name]["brier_skill_ci95"] = [round(lo, 6), round(hi, 6)]
        metrics[name]["risk_coverage"] = risk_coverage(y, p)

    candidates = sorted(MODEL_FEATURES, key=lambda name: metrics[name]["brier_skill_vs_curve"], reverse=True)
    selected = candidates[0]
    counts = {
        "all_calls": len(all_rows),
        "correct_completed": sum(r["outcome_class"] == "correct_completed" for r in all_rows),
        "silently_wrong_completed": sum(r["outcome_class"] == "silently_wrong_completed" for r in all_rows),
        "loud_failure": sum(r["outcome_class"] == "loud_failure" for r in all_rows),
        "visible_trace_completed": sum(r["trace_visible"] == 1 and r["outcome_class"] != "loud_failure" for r in all_rows),
        "instances_completed": len({r["instance_id"] for r in completed}),
    }
    gate = {
        "minimum_silent_wrong": counts["silently_wrong_completed"] >= 20,
        "auc_at_least_0_75": metrics[selected]["auc"] >= 0.75,
        "brier_skill_at_least_0_10": metrics[selected]["brier_skill_vs_curve"] >= 0.10,
        "selected_model_class": selected,
    }
    gate["pass"] = all(v for k, v in gate.items() if k not in {"selected_model_class", "pass"})

    predictions_path = ROOT / "analysis" / "confidence-minimax-predictions.jsonl"
    public_keys = [
        "call_id", "instance_id_hash", "sample_idx", "stage", "level_idx", "level_value",
        "outcome_class", "label", "fold", "completion_tokens", "reasoning_tokens",
        "cost_microdollars", "latency_ms", "effective_billed_tps", "attempt",
        "finish_reason", "trace_visible", *TRACE_FEATURES,
        "pred_curve", "pred_metadata", "pred_trace", "pred_combined",
    ]
    compact = []
    completed_by_call = {r["call_id"]: r for r in completed}
    for row in all_rows:
        merged = dict(row)
        if row["call_id"] in completed_by_call:
            merged.update(completed_by_call[row["call_id"]])
        merged["instance_id_hash"] = hashlib.sha256(row["instance_id"].encode()).hexdigest()
        compact.append({key: merged.get(key) for key in public_keys if key != "instance_id"})
    write_jsonl(predictions_path, [r for r in compact if r.get("fold") is not None])

    compact_path = ROOT / "data" / "exports" / f"{STUDY}.jsonl.gz"
    traces_path = ROOT / "data" / "exports" / f"{STUDY}-traces.jsonl.gz"
    write_jsonl(compact_path, compact, gzip_output=True)
    trace_export = [{
        "call_id": r["call_id"],
        "instance_id_hash": hashlib.sha256(r["instance_id"].encode()).hexdigest(),
        "sample_idx": r["sample_idx"],
        "stage": r["stage"],
        "level_value": r["level_value"],
        "outcome": r["outcome"],
        "response_text": r["response_text"],
    } for r in all_rows]
    write_jsonl(traces_path, trace_export, gzip_output=True)

    figures = make_figures(completed, metrics, ROOT / "analysis")
    report = {
        "study": STUDY,
        "status": "exploratory_retrospective",
        "claim_status": "Exploratory",
        "cohort": {
            "model": MODEL,
            "provider_endpoint": PROVIDER,
            "set_name": SET_NAME,
            "levels": list(EXPECTED_LEVELS),
            "max_completion_tokens": CAP_TOKENS,
            "counts": counts,
        },
        "feature_groups": {"metadata": METADATA_FEATURES, "trace": TRACE_FEATURES},
        "metrics": metrics,
        "diagnostics": {
            "feature_summaries": feature_diagnostics(completed),
            "forward_stage_holdout": forward_stage_holdout(completed, selected),
            "note": "Forward holdout is secondary and has six silently wrong test calls; prospective validation remains required.",
        },
        "folds": fold_fits,
        "retrospective_gate": gate,
        "provenance": {
            "code_git_sha": git_sha(),
            "source_db_sha256": sha256_file(args.db),
            "bootstrap_replicates": args.bootstrap,
            "compact_export": str(compact_path.relative_to(ROOT)),
            "compact_export_sha256": sha256_file(compact_path),
            "trace_export": str(traces_path.relative_to(ROOT)),
            "trace_export_sha256": sha256_file(traces_path),
            "predictions": str(predictions_path.relative_to(ROOT)),
            "figures": figures,
            "recorded_spend_usd": round(sum(r["cost_microdollars"] or 0 for r in all_rows) / 1_000_000, 6),
            "new_spend_usd": 0.0,
        },
    }
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    if gate["pass"]:
        frozen = fit_frozen(completed, selected)
        frozen["provenance"] = {
            "code_git_sha": git_sha(),
            "source_db_sha256": report["provenance"]["source_db_sha256"],
            "training_rows": len(completed),
        }
        frozen_path = ROOT / "analysis" / "confidence-minimax-frozen.json"
        frozen_path.write_text(json.dumps(frozen, indent=2) + "\n")
        report["frozen_model"] = str(frozen_path.relative_to(ROOT))
        args.out.write_text(json.dumps(report, indent=2) + "\n")

    print(json.dumps({"counts": counts, "metrics": metrics, "gate": gate}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
