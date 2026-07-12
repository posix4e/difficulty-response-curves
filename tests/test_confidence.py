import numpy as np

from drc.stats.confidence import (
    apply_design,
    assert_group_isolation,
    brier_skill,
    deterministic_group_folds,
    fit_design,
    fit_ridge_logistic,
    outcome_class,
    predict_ridge_logistic,
    protocol_request_matches,
    roc_auc,
    stopping_reason,
)


def test_outcome_classes_separate_silent_and_loud_failures():
    assert outcome_class("pass") == "correct_completed"
    assert outcome_class("fail_wrong") == "silently_wrong_completed"
    for outcome in ("fail_truncated", "fail_parse", "fail_refusal", "error_api"):
        assert outcome_class(outcome) == "loud_failure"


def test_group_folds_never_split_an_instance():
    rows = [
        {"instance_id": f"i-{level}-{instance}", "level_value": level, "sample": sample}
        for level in (6.3, 6.6, 6.9)
        for instance in range(10)
        for sample in range(4)
    ]
    folds = deterministic_group_folds(rows, k=5)
    assert_group_isolation(rows, folds)
    assert set(folds.values()) == set(range(5))
    assert len({folds[r["instance_id"]] for r in rows if r["instance_id"] == "i-6.3-0"}) == 1


def test_design_state_is_fit_on_training_rows_only():
    train = [{"x": 0.0, "z": None}, {"x": 2.0, "z": 4.0}]
    test = [{"x": 100.0, "z": None}]
    X_train, state = fit_design(train, ["x", "z"])
    X_test = apply_design(test, state)
    assert state.medians == [1.0, 4.0]
    assert X_train.shape[1] == 3  # x, z, and z missingness
    assert X_test[0, 0] > 50  # test value was not used to rescale training


def test_metrics_on_known_separation():
    y = [0, 0, 1, 1]
    p = [0.1, 0.2, 0.8, 0.9]
    baseline = [0.5] * 4
    assert roc_auc(y, p) == 1.0
    assert brier_skill(y, p, baseline) > 0.8


def test_ridge_logistic_learns_probability_direction():
    X = np.array([[-2.0], [-1.0], [1.0], [2.0]])
    y = np.array([0.0, 0.0, 1.0, 1.0])
    weights = fit_ridge_logistic(X, y)
    p = predict_ridge_logistic(X, weights)
    assert np.all(np.diff(p) > 0)


def test_prospective_stopping_rules_are_hard_caps():
    assert stopping_reason(60, 60, 200, 10.0) == "label_target"
    assert stopping_reason(10, 10, 600, 10.0) == "call_cap"
    assert stopping_reason(10, 10, 200, 40.0) == "spend_cap"
    assert stopping_reason(59, 60, 200, 10.0) is None


def test_frozen_provider_and_cap_must_both_match():
    good = '{"provider_only":["parasail"],"max_completion_tokens":65536}'
    assert protocol_request_matches(good, "parasail", 65536)
    assert not protocol_request_matches(good, "novita", 65536)
    assert not protocol_request_matches(good, "parasail", 32768)
    assert not protocol_request_matches("not json", "parasail", 65536)


def test_cross_fitted_curve_never_sees_held_out_instance(monkeypatch):
    import analysis.confidence as analysis_confidence

    rows = []
    for level_index, level in enumerate((6.3, 6.6, 6.9)):
        for instance in range(5):
            for label in (0, 1):
                row = {
                    "instance_id": f"i-{level}-{instance}",
                    "level_idx": level_index,
                    "level_value": level,
                    "label": label,
                }
                for name in analysis_confidence.METADATA_FEATURES + analysis_confidence.TRACE_FEATURES:
                    row[name] = float(label)
                rows.append(row)
    folds = deterministic_group_folds(rows, k=5)
    observed_training_groups = []

    class DummyCurve:
        x50 = 6.6

        def predict(self, values):
            return np.full(len(values), 0.5)

    def spy_fit(train):
        observed_training_groups.append({r["instance_id"] for r in train})
        return DummyCurve()

    monkeypatch.setattr(analysis_confidence, "fit_curve", spy_fit)
    analysis_confidence.cross_fitted_predictions(rows, folds)
    for fold, training_groups in enumerate(observed_training_groups):
        held_out = {iid for iid, assigned in folds.items() if assigned == fold}
        assert training_groups.isdisjoint(held_out)
