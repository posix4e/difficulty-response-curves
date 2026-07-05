import numpy as np

from drc.stats.decomp import decompose_level, frontier_icc
from drc.stats.twopl import InstanceObs


def _simulate_level(rng, n_inst, k, mu, icc):
    if icc <= 0:
        ps = np.full(n_inst, mu)
    else:
        nu = (1 - icc) / icc
        ps = rng.beta(mu * nu, (1 - mu) * nu, size=n_inst)
    return [
        InstanceObs(f"i{j}", 0, 4.0, k, int(rng.binomial(k, p)))
        for j, p in enumerate(ps)
    ]


def test_decomposition_recovers_icc():
    rng = np.random.default_rng(2)
    for icc_true in (0.05, 0.3, 0.6):
        estimates = []
        for _ in range(200):
            group = _simulate_level(rng, n_inst=30, k=16, mu=0.5, icc=icc_true)
            d = decompose_level(group)
            if np.isfinite(d["icc"]):
                estimates.append(d["icc"])
        assert abs(np.mean(estimates) - icc_true) < 0.05, icc_true


def test_pure_bernoulli_gives_high_within_share():
    rng = np.random.default_rng(3)
    shares = []
    for _ in range(200):
        group = _simulate_level(rng, n_inst=30, k=16, mu=0.5, icc=0.0)
        shares.append(decompose_level(group)["within_share"])
    assert np.mean(shares) > 0.95  # all variance is within-instance


def test_identity_within_plus_between_matches_total():
    rng = np.random.default_rng(4)
    group = _simulate_level(rng, n_inst=500, k=16, mu=0.4, icc=0.25)
    d = decompose_level(group)
    pbar = d["pbar"]
    assert abs((d["within"] + d["between_raw"]) - pbar * (1 - pbar)) < 0.02


def test_frontier_icc_prefers_level_near_half():
    rng = np.random.default_rng(5)
    obs = []
    for li, mu in enumerate([0.95, 0.5, 0.05]):
        for j, o in enumerate(_simulate_level(rng, 25, 16, mu, 0.4)):
            obs.append(InstanceObs(f"L{li}i{j}", li, float(li), o.k, o.y))
    icc = frontier_icc(obs)
    assert 0.15 < icc < 0.7  # pulled from the mu=0.5 level with icc 0.4