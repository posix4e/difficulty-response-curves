"""C1: reliability. Split-half from the main run (free), test-retest
z-scores per model (paid), Kendall tau rank stability with an exact
permutation p-value (n models is small, so tau and per-model z are the
headline, not Pearson r -- though r is reported too).
"""

from __future__ import annotations

import hashlib
from itertools import permutations

import numpy as np
from scipy.stats import kendalltau, pearsonr, spearmanr

from .twopl import InstanceObs


def split_half(obs: list[InstanceObs]) -> tuple[list[InstanceObs], list[InstanceObs]]:
    """Deterministic parity split by instance-id hash."""
    a, b = [], []
    for o in obs:
        h = int(hashlib.sha256(o.instance_id.encode()).hexdigest()[-1], 16)
        (a if h % 2 == 0 else b).append(o)
    return a, b


def spearman_brown(r: float) -> float:
    return 2 * r / (1 + r) if r > -1 else float("nan")


def cross_model_correlations(vals1: list[float], vals2: list[float]) -> dict[str, float]:
    v1, v2 = np.asarray(vals1), np.asarray(vals2)
    out: dict[str, float] = {}
    out["pearson_r"] = float(pearsonr(v1, v2)[0]) if len(v1) > 2 else float("nan")
    out["spearman_rho"] = float(spearmanr(v1, v2)[0]) if len(v1) > 2 else float("nan")
    return out


def retest_z(x50_1: float, se_1: float, x50_2: float, se_2: float) -> float:
    return abs(x50_2 - x50_1) / np.sqrt(se_1**2 + se_2**2)


def kendall_tau_exact(vals1: list[float], vals2: list[float]) -> dict[str, float]:
    """Exact permutation p for |tau| under the null of random ranking."""
    tau_obs = float(kendalltau(vals1, vals2)[0])
    n = len(vals1)
    if n > 8:
        return {"tau": tau_obs, "p_exact": float("nan")}
    count = 0
    total = 0
    v1 = list(vals1)
    for perm in permutations(vals2):
        t = float(kendalltau(v1, perm)[0])
        total += 1
        if abs(t) >= abs(tau_obs) - 1e-12:
            count += 1
    return {"tau": tau_obs, "p_exact": count / total}
