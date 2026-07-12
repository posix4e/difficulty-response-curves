from __future__ import annotations

import hashlib
import gzip
import json
from pathlib import Path
import sqlite3
import tempfile
from typing import Any

from .analysis import auc, brier, brier_skill, log_loss


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit_retrospective(
    report_path: str | Path = "analysis/confidence-minimax.json",
    predictions_path: str | Path = "analysis/confidence-minimax-predictions.jsonl",
) -> dict[str, Any]:
    report_source, prediction_source = Path(report_path), Path(predictions_path)
    report = json.loads(report_source.read_text())
    rows = [json.loads(line) for line in prediction_source.read_text().splitlines() if line]
    labels = [row["label"] for row in rows]
    prior = [row["pred_curve"] for row in rows]
    checked = {}
    for name in ("curve", "metadata", "trace", "combined"):
        predictions = [row[f"pred_{name}"] for row in rows]
        calculated = {
            "brier": brier(labels, predictions),
            "brier_skill_vs_curve": brier_skill(labels, predictions, prior),
            "log_loss": log_loss(labels, predictions),
            "auc": auc(labels, predictions),
        }
        expected = report["metrics"][name]
        differences = {
            metric: abs(float(value) - float(expected[metric]))
            for metric, value in calculated.items()
        }
        checked[name] = {
            "calculated": {key: round(value, 6) for key, value in calculated.items()},
            "matches": all(value <= 1e-6 for value in differences.values()),
        }

    artifacts = {}
    provenance = report.get("provenance", {})
    for path_key, checksum_key in (
        ("compact_export", "compact_export_sha256"),
        ("trace_export", "trace_export_sha256"),
    ):
        source = Path(provenance[path_key])
        artifacts[path_key] = {
            "path": str(source),
            "matches": source.exists() and _sha256(source) == provenance[checksum_key],
        }
    passed = all(item["matches"] for item in checked.values()) and all(
        item["matches"] for item in artifacts.values()
    )
    return {
        "study": report["study"],
        "prediction_rows": len(rows),
        "metrics": checked,
        "artifacts": artifacts,
        "pass": passed,
    }


def _summary(rows: list[sqlite3.Row], field: str) -> dict[str, float | int | None]:
    values = [float(row[field]) for row in rows if row[field] is not None]
    return {
        "n": len(values),
        "mean": round(sum(values) / len(values), 6) if values else None,
    }


def audit_model_cohort(database: str | Path, model_id: str) -> dict[str, Any]:
    """Decide whether existing calls can support a confidence replication."""
    source = Path(database)
    temporary: tempfile.NamedTemporaryFile | None = None
    if source.suffix == ".gz":
        temporary = tempfile.NamedTemporaryFile(suffix=".sqlite")
        with gzip.open(source, "rb") as compressed:
            temporary.write(compressed.read())
            temporary.flush()
        database_path = Path(temporary.name)
    else:
        database_path = source
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        rows = list(
            connection.execute(
                """SELECT c.*, i.level_value
                   FROM calls c JOIN instances i USING(instance_id)
                   WHERE c.model_id=? ORDER BY c.call_id""",
                (model_id,),
            )
        )
    finally:
        connection.close()
        if temporary is not None:
            temporary.close()
    if not rows:
        raise ValueError(f"no calls found for {model_id}")

    correct = [row for row in rows if row["outcome"] == "pass"]
    silent = [row for row in rows if row["outcome"] == "fail_wrong"]
    loud = [row for row in rows if row["outcome"] not in {"pass", "fail_wrong"}]
    providers = sorted({str(row["provider_endpoint"] or "") for row in rows})
    levels: dict[float, dict[str, int]] = {}
    for row in rows:
        cell = levels.setdefault(float(row["level_value"]), {"correct": 0, "silent_wrong": 0, "loud": 0})
        if row["outcome"] == "pass":
            cell["correct"] += 1
        elif row["outcome"] == "fail_wrong":
            cell["silent_wrong"] += 1
        else:
            cell["loud"] += 1
    mixed_levels = sum(cell["correct"] > 0 and cell["silent_wrong"] > 0 for cell in levels.values())
    conditions = {
        "at_least_20_silent_wrong": len(silent) >= 20,
        "at_least_30_completed_calls": len(correct) + len(silent) >= 30,
        "single_provider_route": len(providers) == 1,
        "all_calls_provider_pinned": all(int(row["provider_pinned"] or 0) == 1 for row in rows),
        "at_least_3_mixed_outcome_levels": mixed_levels >= 3,
    }

    def features(group: list[sqlite3.Row]) -> dict[str, dict[str, float | int | None]]:
        augmented = []
        for row in group:
            record = dict(row)
            latency = record.get("latency_ms")
            tokens = record.get("completion_tokens")
            record["effective_billed_tps"] = (
                float(tokens) / (float(latency) / 1000.0)
                if tokens is not None and latency not in (None, 0)
                else None
            )
            augmented.append(record)
        return {
            name: _summary(augmented, name)
            for name in ("completion_tokens", "reasoning_tokens", "latency_ms", "effective_billed_tps")
        }

    return {
        "model": model_id,
        "claim_status": "Censored",
        "decision": "existing calls are not an eligible confidence-replication cohort",
        "counts": {
            "calls": len(rows),
            "instances": len({row["instance_id"] for row in rows}),
            "correct_completed": len(correct),
            "silently_wrong_completed": len(silent),
            "loud_failure": len(loud),
        },
        "providers": providers,
        "levels": {str(level): cell for level, cell in sorted(levels.items())},
        "eligibility": {**conditions, "pass": all(conditions.values())},
        "descriptive_features": {
            "correct_completed": features(correct),
            "silently_wrong_completed": features(silent),
        },
        "new_spend_usd": 0.0,
        "source": {"path": str(source), "sha256": _sha256(source)},
    }
