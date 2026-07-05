import numpy as np
import pytest

from drc.stats import bootstrap
from drc.stats.twopl import (
    FitResult,
    InstanceObs,
    fit,
    fit_with_lapse_guard,
    gof_mc_pvalue,
    simulate_obs,
    x50_of,
)

LEVELS = np.linspace(2.0, 5.6, 15)


def _synthetic(rng, b, a, lapse, icc=0.15, n_inst=30, k=8):
    truth = FitResult(b=b, a=a, lapse=lapse, x50=x50_of(b, a, lapse), loglik=0, lam_max=0.15)
    template = [
        InstanceObs(f"i{li}-{j}", li, float(x), k, 0)
        for li, x in enumerate(LEVELS)
        for j in range(n_inst)
    ]
    return simulate_obs(rng, truth, template, icc), truth


def test_recovers_known_parameters():
    rng = np.random.default_rng(11)
    obs, truth = _synthetic(rng, b=4.0, a=2.5, lapse=0.05)
    res = fit_with_lapse_guard(obs)
    assert abs(res.x50 - truth.x50) < 0.15
    assert abs(res.b - truth.b) < 0.2
    assert 0.6 * truth.a < res.a < 1.6 * truth.a
    assert abs(res.lapse - truth.lapse) < 0.06


def test_recovery_across_parameter_grid():
    rng = np.random.default_rng(5)
    for b in (3.0, 4.5):
        for a in (1.2, 4.0):
            obs, truth = _synthetic(rng, b=b, a=a, lapse=0.02)
            res = fit_with_lapse_guard(obs)
            assert abs(res.x50 - truth.x50) < 0.25, (b, a, res.x50, truth.x50)


def test_censoring_flags():
    all_pass = [InstanceObs(f"i{li}-{j}", li, float(x), 4, 4) for li, x in enumerate(LEVELS) for j in range(5)]
    res = fit(all_pass)
    assert res.x50 == float("inf") and "censored_above_grid" in res.flags
    all_fail = [InstanceObs(f"i{li}-{j}", li, float(x), 4, 0) for li, x in enumerate(LEVELS) for j in range(5)]
    res = fit(all_fail)
    assert res.x50 == float("-inf") and "censored_below_grid" in res.flags


def test_lapse_guard_widens_on_low_plateau():
    rng = np.random.default_rng(3)
    obs, _ = _synthetic(rng, b=4.5, a=3.0, lapse=0.25, n_inst=40)
    res = fit_with_lapse_guard(obs)
    assert "high_lapse_widened_bound" in res.flags
    assert res.lapse > 0.15  # found the true-ish lapse beyond the default bound


def test_bootstrap_ci_covers_truth():
    rng = np.random.default_rng(17)
    obs, truth = _synthetic(rng, b=4.0, a=2.5, lapse=0.05)

    def stat(sample):
        r = fit_with_lapse_guard(sample, quick=True)
        return {"x50": r.x50}

    out = bootstrap.run(obs, stat, B=200, seed=7)
    lo, hi = bootstrap.percentile_ci(out["x50"])
    assert lo < truth.x50 < hi
    assert hi - lo < 0.5  # sane width at this design size


def test_gof_reasonable_on_well_specified_data():
    rng = np.random.default_rng(23)
    obs, _ = _synthetic(rng, b=4.0, a=2.5, lapse=0.05, icc=0.2)
    res = fit_with_lapse_guard(obs)
    _, p = gof_mc_pvalue(res, obs, icc=0.2, n_sims=100, seed=1)
    assert p > 0.01  # should not reject its own generating model
