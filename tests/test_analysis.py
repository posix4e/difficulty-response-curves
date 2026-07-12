import json
import math

from drc.analysis import (
    auc,
    brier,
    brier_skill,
    clustered_interval,
    curve_probability,
    frozen_prediction,
    log_loss,
    outcome_class,
)
from drc.types import Outcome


def test_outcome_taxonomy_is_mutually_exclusive():
    assert outcome_class("pass") == Outcome.CORRECT
    assert outcome_class("fail_wrong") == Outcome.SILENT_WRONG
    for value in ("fail_parse", "fail_truncated", "error_api", "provider_mismatch"):
        assert outcome_class(value) == Outcome.LOUD_FAILURE


def test_metrics_on_known_values():
    labels = [0, 0, 1, 1]
    perfect = [0.0, 0.1, 0.9, 1.0]
    prior = [0.5] * 4
    assert brier(labels, perfect) < 0.01
    assert brier_skill(labels, perfect, prior) > 0.95
    assert auc(labels, perfect) == 1.0
    assert log_loss(labels, perfect) < 0.06


def test_curve_probability_falls_with_difficulty():
    curve = {"b": 7.9, "a": 0.7, "lapse": 0.01}
    assert curve_probability(6.3, curve) > curve_probability(6.9, curve)


def test_frozen_model_predicts_from_public_json():
    frozen = json.loads(open("analysis/confidence-minimax-frozen.json").read())
    row = {
        "level_value": 6.6,
        "completion_tokens": 40_000,
        "reasoning_tokens": 30_000,
        "latency_ms": 500_000,
        "attempt": 1,
        "finish_reason": "stop",
    }
    prediction, prior = frozen_prediction(row, frozen)
    assert 0 < prediction < 1
    assert 0 < prior < 1


def test_clustered_interval_is_deterministic():
    rows = [
        {"instance_id": "a", "label": 1, "prediction": 0.9, "curve_prior": 0.6},
        {"instance_id": "a", "label": 1, "prediction": 0.8, "curve_prior": 0.6},
        {"instance_id": "b", "label": 0, "prediction": 0.2, "curve_prior": 0.6},
        {"instance_id": "b", "label": 0, "prediction": 0.1, "curve_prior": 0.6},
    ]
    first = clustered_interval(rows, replicates=100, seed=7)
    second = clustered_interval(rows, replicates=100, seed=7)
    assert first == second
    assert all(math.isfinite(value) for value in first)
