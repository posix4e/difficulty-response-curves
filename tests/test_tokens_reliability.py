import numpy as np

from drc.stats.reliability import kendall_tau_exact, retest_z, spearman_brown, split_half
from drc.stats.tokens import level_means, peak_x
from drc.stats.twopl import InstanceObs

LEVELS = np.linspace(2.0, 5.6, 15)


def _obs_with_tokens(rng, peak_at=4.2, width=1.1, noise=0.05):
    obs = []
    for li, x in enumerate(LEVELS):
        for j in range(20):
            mean_log = 8.0 - ((x - peak_at) / width) ** 2 + rng.normal(0, noise)
            obs.append(InstanceObs(f"i{li}-{j}", li, float(x), 4, 2, mean_log))
    return obs


def test_peak_recovered():
    rng = np.random.default_rng(1)
    obs = _obs_with_tokens(rng, peak_at=4.2)
    pk = peak_x(obs)
    assert not pk["censored"]
    assert abs(pk["peak"] - 4.2) < 0.2
    assert pk["sag"] < 0  # falls after the peak


def test_peak_censored_at_grid_edge():
    rng = np.random.default_rng(2)
    obs = _obs_with_tokens(rng, peak_at=5.9)  # beyond the grid
    pk = peak_x(obs)
    assert pk["censored"]


def test_level_means_sorted_and_finite():
    rng = np.random.default_rng(3)
    xs, ms = level_means(_obs_with_tokens(rng))
    assert len(xs) == 15
    assert (np.diff(xs) > 0).all()
    assert np.isfinite(ms).all()


def test_split_half_partitions():
    obs = [InstanceObs(f"id{j}", 0, 2.0, 4, 2) for j in range(100)]
    a, b = split_half(obs)
    assert len(a) + len(b) == 100
    assert 25 < len(a) < 75  # hash parity is roughly balanced
    a2, b2 = split_half(obs)
    assert [o.instance_id for o in a] == [o.instance_id for o in a2]  # deterministic


def test_retest_z_and_spearman_brown():
    assert retest_z(4.0, 0.1, 4.0, 0.1) == 0.0
    assert abs(retest_z(4.0, 0.1, 4.28, 0.1) - 1.98) < 0.02
    assert abs(spearman_brown(0.8) - 8 / 9) < 1e-9


def test_kendall_exact_p():
    r = kendall_tau_exact([1, 2, 3, 4, 5, 6], [1, 2, 3, 4, 5, 6])
    assert abs(r["tau"] - 1.0) < 1e-9
    assert r["p_exact"] < 0.01  # 2/720
    r2 = kendall_tau_exact([1, 2, 3, 4, 5, 6], [2, 1, 4, 3, 6, 5])
    assert r2["p_exact"] > r["p_exact"]
