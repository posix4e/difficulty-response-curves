"""Leakage-safe helpers for per-call confidence experiments.

The confidence target is correctness conditional on a normally completed
answer. Loud delivery failures are classified separately. All evaluation
folds are grouped by generated instance so repeated samples of one puzzle
never cross the train/test boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Iterable, Mapping, Sequence

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit, logit


LOUD_OUTCOMES = {
    "fail_truncated",
    "fail_parse",
    "fail_refusal",
    "error_api",
    "error_timeout",
    "error_malformed",
}


def outcome_class(outcome: str) -> str:
    """Map runner outcomes to the study's three mutually exclusive classes."""
    if outcome == "pass":
        return "correct_completed"
    if outcome == "fail_wrong":
        return "silently_wrong_completed"
    return "loud_failure"


def protocol_request_matches(request_json: str, provider: str, max_tokens: int) -> bool:
    """Validate the frozen provider pin and token cap recorded on a call."""
    try:
        request = json.loads(request_json or "{}")
    except json.JSONDecodeError:
        return False
    return (
        request.get("provider_only") == [provider]
        and request.get("max_completion_tokens") == max_tokens
    )


def deterministic_group_folds(
    rows: Sequence[Mapping[str, object]], k: int = 5
) -> dict[str, int]:
    """Assign whole instances to deterministic, difficulty-balanced folds."""
    if k < 2:
        raise ValueError("k must be at least 2")
    by_level: dict[float, set[str]] = {}
    for row in rows:
        iid = str(row["instance_id"])
        level = float(row["level_value"])
        by_level.setdefault(level, set()).add(iid)
    assignment: dict[str, int] = {}
    for level in sorted(by_level):
        groups = sorted(
            by_level[level],
            key=lambda iid: hashlib.sha256(f"{level}:{iid}".encode()).hexdigest(),
        )
        for index, iid in enumerate(groups):
            assignment[iid] = index % k
    return assignment


def assert_group_isolation(
    rows: Sequence[Mapping[str, object]], assignment: Mapping[str, int]
) -> None:
    seen: dict[str, set[int]] = {}
    for row in rows:
        iid = str(row["instance_id"])
        seen.setdefault(iid, set()).add(int(assignment[iid]))
    leaking = {iid: folds for iid, folds in seen.items() if len(folds) != 1}
    if leaking:
        raise AssertionError(f"instances cross folds: {leaking}")


@dataclass
class DesignState:
    base_features: list[str]
    expanded_features: list[str]
    medians: list[float]
    means: list[float]
    scales: list[float]
    missing_features: list[str]

    def as_dict(self) -> dict:
        return {
            "base_features": self.base_features,
            "expanded_features": self.expanded_features,
            "medians": self.medians,
            "means": self.means,
            "scales": self.scales,
            "missing_features": self.missing_features,
        }


def _raw_matrix(rows: Sequence[Mapping[str, object]], features: Sequence[str]) -> np.ndarray:
    out = np.full((len(rows), len(features)), np.nan, dtype=float)
    for i, row in enumerate(rows):
        for j, name in enumerate(features):
            value = row.get(name)
            if value is not None:
                try:
                    out[i, j] = float(value)
                except (TypeError, ValueError):
                    pass
    return out


def fit_design(
    rows: Sequence[Mapping[str, object]], features: Sequence[str]
) -> tuple[np.ndarray, DesignState]:
    raw = _raw_matrix(rows, features)
    medians = []
    missing_columns = []
    expanded = []
    columns = []
    for j, name in enumerate(features):
        col = raw[:, j]
        finite = np.isfinite(col)
        median = float(np.median(col[finite])) if finite.any() else 0.0
        medians.append(median)
        columns.append(np.where(finite, col, median))
        expanded.append(name)
        if not finite.all():
            columns.append((~finite).astype(float))
            missing_columns.append(name)
            expanded.append(name + "__missing")
    X = np.column_stack(columns) if columns else np.empty((len(rows), 0))
    means = X.mean(axis=0) if X.size else np.array([], dtype=float)
    scales = X.std(axis=0) if X.size else np.array([], dtype=float)
    scales = np.where(scales < 1e-9, 1.0, scales)
    X = (X - means) / scales
    state = DesignState(
        base_features=list(features),
        expanded_features=expanded,
        medians=[float(v) for v in medians],
        means=[float(v) for v in means],
        scales=[float(v) for v in scales],
        missing_features=missing_columns,
    )
    return X, state


def apply_design(rows: Sequence[Mapping[str, object]], state: DesignState) -> np.ndarray:
    raw = _raw_matrix(rows, state.base_features)
    columns = []
    missing = set(state.missing_features)
    for j, name in enumerate(state.base_features):
        col = raw[:, j]
        finite = np.isfinite(col)
        columns.append(np.where(finite, col, state.medians[j]))
        if name in missing:
            columns.append((~finite).astype(float))
    X = np.column_stack(columns) if columns else np.empty((len(rows), 0))
    return (X - np.asarray(state.means)) / np.asarray(state.scales)


def fit_ridge_logistic(X: np.ndarray, y: np.ndarray, l2: float = 1.0) -> np.ndarray:
    """Fit deterministic logistic regression; final coefficient is bias."""
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float)
    if len(np.unique(y)) < 2:
        raise ValueError("logistic regression requires both outcome classes")
    Xb = np.column_stack([X, np.ones(len(X))])

    def objective(w: np.ndarray) -> tuple[float, np.ndarray]:
        z = Xb @ w
        p = expit(z)
        eps = 1e-12
        loss = -np.mean(y * np.log(p + eps) + (1 - y) * np.log(1 - p + eps))
        loss += 0.5 * l2 * float(np.sum(w[:-1] ** 2)) / len(y)
        grad = Xb.T @ (p - y) / len(y)
        grad[:-1] += l2 * w[:-1] / len(y)
        return float(loss), grad

    prevalence = np.clip(float(y.mean()), 1e-5, 1 - 1e-5)
    init = np.zeros(Xb.shape[1], dtype=float)
    init[-1] = float(logit(prevalence))
    result = minimize(objective, init, method="L-BFGS-B", jac=True)
    if not result.success:
        raise RuntimeError(f"confidence fit failed: {result.message}")
    return np.asarray(result.x, dtype=float)


def predict_ridge_logistic(X: np.ndarray, weights: np.ndarray) -> np.ndarray:
    return expit(np.column_stack([X, np.ones(len(X))]) @ np.asarray(weights))


def brier_score(y: Iterable[float], p: Iterable[float]) -> float:
    yv, pv = np.asarray(list(y), dtype=float), np.asarray(list(p), dtype=float)
    return float(np.mean((pv - yv) ** 2))


def brier_skill(y: Iterable[float], p: Iterable[float], baseline: Iterable[float]) -> float:
    b0 = brier_score(y, baseline)
    return float(1 - brier_score(y, p) / b0) if b0 > 0 else float("nan")


def log_loss(y: Iterable[float], p: Iterable[float]) -> float:
    yv, pv = np.asarray(list(y), dtype=float), np.asarray(list(p), dtype=float)
    pv = np.clip(pv, 1e-9, 1 - 1e-9)
    return float(-np.mean(yv * np.log(pv) + (1 - yv) * np.log(1 - pv)))


def roc_auc(y: Iterable[float], p: Iterable[float]) -> float:
    yv, pv = np.asarray(list(y), dtype=int), np.asarray(list(p), dtype=float)
    pos, neg = pv[yv == 1], pv[yv == 0]
    if not len(pos) or not len(neg):
        return float("nan")
    wins = sum((a > b) + 0.5 * (a == b) for a in pos for b in neg)
    return float(wins / (len(pos) * len(neg)))


def metric_summary(y: Sequence[float], p: Sequence[float], baseline: Sequence[float]) -> dict:
    return {
        "brier": round(brier_score(y, p), 6),
        "brier_skill_vs_curve": round(brier_skill(y, p, baseline), 6),
        "log_loss": round(log_loss(y, p), 6),
        "auc": round(roc_auc(y, p), 6),
    }


def clustered_brier_skill_ci(
    rows: Sequence[Mapping[str, object]],
    prediction_key: str,
    baseline_key: str,
    B: int = 2000,
    seed: int = 20260712,
) -> tuple[float, float]:
    by_instance: dict[str, list[Mapping[str, object]]] = {}
    for row in rows:
        by_instance.setdefault(str(row["instance_id"]), []).append(row)
    ids = sorted(by_instance)
    rng = np.random.default_rng(seed)
    values = []
    for _ in range(B):
        sampled = rng.choice(ids, size=len(ids), replace=True)
        batch = [row for iid in sampled for row in by_instance[iid]]
        values.append(
            brier_skill(
                [float(r["label"]) for r in batch],
                [float(r[prediction_key]) for r in batch],
                [float(r[baseline_key]) for r in batch],
            )
        )
    return float(np.quantile(values, 0.025)), float(np.quantile(values, 0.975))


def risk_coverage(y: Sequence[float], p: Sequence[float], coverages=(0.25, 0.5, 0.75, 1.0)) -> list[dict]:
    yv, pv = np.asarray(y, dtype=float), np.asarray(p, dtype=float)
    order = np.argsort(-pv, kind="stable")
    out = []
    for coverage in coverages:
        n = max(1, int(np.ceil(len(yv) * coverage)))
        chosen = order[:n]
        out.append({
            "coverage": float(coverage),
            "n": int(n),
            "accuracy": round(float(yv[chosen].mean()), 6),
            "mean_confidence": round(float(pv[chosen].mean()), 6),
        })
    return out


def stopping_reason(
    correct: int,
    silent_wrong: int,
    admitted: int,
    spent_usd: float,
    target_each: int = 60,
    max_calls: int = 600,
    max_spend_usd: float = 40.0,
) -> str | None:
    if correct >= target_each and silent_wrong >= target_each:
        return "label_target"
    if admitted >= max_calls:
        return "call_cap"
    if spent_usd >= max_spend_usd:
        return "spend_cap"
    return None
