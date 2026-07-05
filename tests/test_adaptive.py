import numpy as np

from drc.stats.c4_eval import matched_efficiency, simulate_adaptive
from drc.stats.twopl import FitResult, x50_of

LEVELS = tuple(np.linspace(2.0, 5.6, 15))


def _truth(b=4.1, a=2.5, lapse=0.04):
    return FitResult(b=b, a=a, lapse=lapse, x50=x50_of(b, a, lapse), loglik=0, lam_max=0.15)


def test_adaptive_converges_to_truth():
    truth = _truth()
    errs, calls = [], []
    for seed in range(10):
        run = simulate_adaptive(
            truth, icc=0.25, levels=LEVELS, a_prior_mu=np.log(2.5),
            eps_target=0.12, max_calls=200, seed=seed,
        )
        errs.append(abs(run.b_final - truth.b))
        calls.append(run.calls_used)
    assert np.median(errs) < 0.3, (np.median(errs), errs)
    assert np.median(calls) <= 200
    assert min(calls) >= 16  # phase 1 alone is at least 4 probes x 4 instances


def test_adaptive_uses_fewer_calls_for_looser_target():
    truth = _truth()
    tight = simulate_adaptive(truth, 0.25, LEVELS, np.log(2.5), eps_target=0.10, max_calls=300, seed=3)
    loose = simulate_adaptive(truth, 0.25, LEVELS, np.log(2.5), eps_target=0.30, max_calls=300, seed=3)
    assert loose.calls_used <= tight.calls_used


def test_matched_efficiency_interpolates():
    curve = {100: 0.8, 200: 0.5, 400: 0.32, 800: 0.2}
    ratio = matched_efficiency(curve, adaptive_calls=100, adaptive_width=0.32)
    assert 3.5 < ratio < 4.5  # 400 uniform calls / 100 adaptive
