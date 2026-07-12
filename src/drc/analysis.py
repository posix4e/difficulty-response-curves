from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
from scipy.special import expit, logit

from .config import StudyConfig
from .store import Store
from .types import Outcome


def outcome_class(value: str) -> Outcome:
    return Outcome.from_runner(value)


def curve_probability(difficulty: float, curve: dict[str, float]) -> float:
    probability = (1.0 - float(curve["lapse"])) * expit(
        float(curve["a"]) * (float(curve["b"]) - difficulty)
    )
    return float(np.clip(probability, 1e-6, 1 - 1e-6))


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def metadata_features(row: dict[str, Any], frozen: dict[str, Any]) -> dict[str, float | None]:
    completion = _finite(row.get("completion_tokens"))
    reasoning = _finite(row.get("reasoning_tokens"))
    latency = _finite(row.get("latency_ms"))
    cap = float(frozen["cohort"]["max_completion_tokens"])
    curve = curve_probability(float(row["level_value"]), frozen["curve"])
    tps = None
    if completion is not None and latency is not None and latency > 0:
        tps = completion / (latency / 1000.0)
    finish = str(row.get("finish_reason") or "")
    return {
        "curve_logit": float(logit(curve)),
        "log_completion_tokens": math.log1p(completion) if completion is not None else None,
        "log_reasoning_tokens": math.log1p(reasoning) if reasoning is not None else None,
        "cap_fraction": completion / cap if completion is not None else None,
        "log_latency_ms": math.log1p(latency) if latency is not None else None,
        "log_effective_billed_tps": math.log1p(tps) if tps is not None else None,
        "attempt": _finite(row.get("attempt")) or 1.0,
        "finish_stop": float(finish in {"stop", "completed"}),
        "finish_other": float(finish not in {"stop", "completed"}),
    }


def frozen_prediction(row: dict[str, Any], frozen: dict[str, Any]) -> tuple[float, float]:
    values = metadata_features(row, frozen)
    design = frozen["design"]
    missing = set(design["missing_features"])
    columns: list[float] = []
    for index, name in enumerate(design["base_features"]):
        value = values.get(name)
        absent = value is None
        columns.append(float(design["medians"][index]) if absent else float(value))
        if name in missing:
            columns.append(float(absent))
    scaled = (
        np.asarray(columns, dtype=float) - np.asarray(design["means"], dtype=float)
    ) / np.asarray(design["scales"], dtype=float)
    weights = np.asarray(frozen["weights"], dtype=float)
    prediction = float(expit(np.append(scaled, 1.0) @ weights))
    prior = curve_probability(float(row["level_value"]), frozen["curve"])
    return prediction, prior


def brier(y: Sequence[float], p: Sequence[float]) -> float:
    return float(np.mean((np.asarray(y) - np.asarray(p)) ** 2))


def brier_skill(y: Sequence[float], p: Sequence[float], prior: Sequence[float]) -> float:
    baseline = brier(y, prior)
    return float(1 - brier(y, p) / baseline) if baseline else float("nan")


def log_loss(y: Sequence[float], p: Sequence[float]) -> float:
    labels = np.asarray(y, dtype=float)
    probabilities = np.clip(np.asarray(p, dtype=float), 1e-9, 1 - 1e-9)
    return float(-np.mean(labels * np.log(probabilities) + (1 - labels) * np.log(1 - probabilities)))


def auc(y: Sequence[float], p: Sequence[float]) -> float:
    labels, probabilities = np.asarray(y, dtype=int), np.asarray(p, dtype=float)
    positive = probabilities[labels == 1]
    negative = probabilities[labels == 0]
    if not len(positive) or not len(negative):
        return float("nan")
    wins = sum((a > b) + 0.5 * (a == b) for a in positive for b in negative)
    return float(wins / (len(positive) * len(negative)))


def clustered_interval(
    rows: Sequence[dict[str, Any]], replicates: int = 2000, seed: int = 20260712
) -> tuple[float, float]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["instance_id"]), []).append(row)
    identifiers = sorted(grouped)
    if len(identifiers) < 2:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    results = []
    for _ in range(replicates):
        sample = rng.choice(identifiers, size=len(identifiers), replace=True)
        batch = [row for identifier in sample for row in grouped[str(identifier)]]
        results.append(
            brier_skill(
                [row["label"] for row in batch],
                [row["prediction"] for row in batch],
                [row["curve_prior"] for row in batch],
            )
        )
    finite = np.asarray([value for value in results if math.isfinite(value)])
    if not len(finite):
        return float("nan"), float("nan")
    return float(np.quantile(finite, 0.025)), float(np.quantile(finite, 0.975))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def analyze(
    config: StudyConfig,
    frozen_path: str | Path,
    replicates: int = 2000,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    frozen_source = Path(frozen_path)
    frozen = json.loads(frozen_source.read_text())
    with Store(config.database) as store:
        raw = store.study_rows(config.name, config.model.record_id)
        status = store.status(config.name, config.model.record_id)

    completed = [row for row in raw if outcome_class(str(row["outcome"])) != Outcome.LOUD_FAILURE]
    predictions = []
    for row in completed:
        prediction, prior = frozen_prediction(row, frozen)
        label = int(outcome_class(str(row["outcome"])) == Outcome.CORRECT)
        predictions.append(
            {
                "instance_id": str(row["instance_id"]),
                "instance_hash": hashlib.sha256(str(row["instance_id"]).encode()).hexdigest()[:16],
                "difficulty": float(row["level_value"]),
                "label": label,
                "prediction": prediction,
                "curve_prior": prior,
                "call_id": int(row["call_id"]),
            }
        )

    labels = [row["label"] for row in predictions]
    scores = [row["prediction"] for row in predictions]
    priors = [row["curve_prior"] for row in predictions]
    if not labels or len(set(labels)) < 2:
        raise RuntimeError("prospective analysis requires correct and silently wrong completions")
    skill = brier_skill(labels, scores, priors)
    interval = clustered_interval(predictions, replicates=replicates)
    area = auc(labels, scores)
    gate = {
        "brier_skill_at_least_0_10": skill >= 0.10,
        "interval_excludes_zero": interval[0] > 0,
        "auc_at_least_0_75": area >= 0.75,
    }
    report = {
        "study": config.name,
        "status": "Supported" if all(gate.values()) else "Not supported",
        "counts": status.as_dict(),
        "completed_for_confidence": len(predictions),
        "metrics": {
            "brier": round(brier(labels, scores), 6),
            "curve_brier": round(brier(labels, priors), 6),
            "brier_skill": round(skill, 6),
            "brier_skill_ci95": [round(interval[0], 6), round(interval[1], 6)],
            "log_loss": round(log_loss(labels, scores), 6),
            "auc": round(area, 6),
        },
        "gate": {**gate, "pass": all(gate.values())},
        "provenance": {
            "frozen_model": str(frozen_source),
            "frozen_model_sha256": _sha256(frozen_source),
            "database": str(config.database),
            "database_sha256": _sha256(config.database),
            "bootstrap_replicates": replicates,
        },
    }
    return report, predictions
