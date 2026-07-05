import numpy as np

from drc.stats.tracefeat import extra_features, features

TRACE = ("<think>" + "let me try a rotation. wait, that's wrong. " * 60 +
         "I give up and will just guess the answer now. answer maybe?" +
         "</think>\nANSWER: x1=T x2=F")


def test_extra_features_deterministic_and_complete():
    a = extra_features(TRACE, 1200)
    b = extra_features(TRACE, 1200)
    assert a == b
    assert set(a) == {"hedge_ans", "giveup_full", "flip", "qmark_tail", "rep_tail_k4",
                      "wait_full", "bt_last10", "neg_tail", "len_ratio"}
    assert a["giveup_full"] > 0 and a["wait_full"] > 0 and a["rep_tail_k4"] > 0.5


def test_round2_features_unchanged_by_round3():
    f = features(TRACE, 1200)
    assert set(f) == {"rep_full", "rep_tail", "bt_full", "bt_tail", "wait_tail",
                      "hedge_tail", "tok"}


def test_logistic_deterministic():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis"))
    from judge import fit_logistic

    rng = np.random.default_rng(7)
    X = rng.normal(size=(60, 3))
    y = (X[:, 0] + 0.5 * X[:, 1] > 0).astype(float)
    w1 = fit_logistic(X, y)
    w2 = fit_logistic(X, y)
    assert np.array_equal(w1, w2)
    assert w1[0] > w1[2]  # informative feature outweighs the noise one
