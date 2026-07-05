"""C4: haggle your way to the frontier. Bracket-then-refine:

Phase 1  bisection over the level grid; each probe = a few fresh
         instances x 1 sample; move harder on pass-rate >= 0.5.
Phase 2  batches at the grid level nearest the current x50 estimate
         (information about b is maximised where P is near one half),
         refit after each batch, stop when SE(b) <= eps or the call
         budget runs out.

The b-refit uses the pilot-pooled slope as a prior (LogNormal, sd 0.5)
and a fixed lapse: with so few points, a and lapse are not the target.
SE comes from a small cluster bootstrap over instances -- consistent
with the rest of the toolkit, no information-matrix asymptotics.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit

from ..stats.twopl import InstanceObs, x50_of


@dataclass
class AdaptiveState:
    history: list[InstanceObs] = field(default_factory=list)
    probes: list[dict] = field(default_factory=list)
    calls_used: int = 0
    b_est: float = float("nan")
    se_est: float = float("nan")
    stopped: str = ""


def fit_b(
    obs: list[InstanceObs], a_prior_mu: float, a_prior_sd: float, lapse: float,
    grid_lo: float, grid_hi: float,
) -> tuple[float, float]:
    """MAP for (b, log a) with informative slope prior and fixed lapse.
    Returns (b, a)."""
    x = np.array([o.x for o in obs], dtype=float)
    y = np.array([o.y for o in obs], dtype=float)
    k = np.array([o.k for o in obs], dtype=float)

    def nlp(theta):
        b, log_a = theta
        a = np.exp(log_a)
        p = (1 - lapse) * expit(a * (b - x))
        p = np.clip(p, 1e-9, 1 - 1e-9)
        ll = np.sum(y * np.log(p) + (k - y) * np.log(1 - p))
        lp = -0.5 * ((log_a - a_prior_mu) / a_prior_sd) ** 2
        return -(ll + lp)

    best = None
    for b0 in np.linspace(grid_lo, grid_hi, 4):
        res = minimize(
            nlp, x0=np.array([b0, a_prior_mu]), method="L-BFGS-B",
            bounds=[(grid_lo - 1, grid_hi + 1), (np.log(0.05), np.log(200))],
        )
        if best is None or res.fun < best.fun:
            best = res
    return float(best.x[0]), float(np.exp(best.x[1]))


def se_b_bootstrap(
    obs: list[InstanceObs], a_prior_mu: float, a_prior_sd: float, lapse: float,
    grid_lo: float, grid_hi: float, B: int = 200, seed: int = 5,
) -> float:
    rng = np.random.default_rng(seed)
    by_level: dict[int, list[InstanceObs]] = {}
    for o in obs:
        by_level.setdefault(o.level_idx, []).append(o)
    bs = []
    for _ in range(B):
        sample: list[InstanceObs] = []
        for group in by_level.values():
            idx = rng.integers(0, len(group), size=len(group))
            sample.extend(group[i] for i in idx)
        try:
            b, _ = fit_b(sample, a_prior_mu, a_prior_sd, lapse, grid_lo, grid_hi)
            bs.append(b)
        except Exception:
            continue
    return float(np.std(bs, ddof=1)) if len(bs) > 10 else float("nan")


def next_level(
    state: AdaptiveState, levels: tuple[float, ...],
    a_prior_mu: float, a_prior_sd: float, lapse: float,
) -> int:
    """Level index to probe next, given everything seen so far."""
    if not state.history:
        return len(levels) // 2
    b, a = fit_b(state.history, a_prior_mu, a_prior_sd, lapse, levels[0], levels[-1])
    x50 = x50_of(b, a, lapse)
    return int(np.argmin(np.abs(np.array(levels) - x50)))


def bracket_step(pass_rate: float, lo: int, hi: int, mid: int) -> tuple[int, int]:
    """Bisection update: pass-rate >= 0.5 means this level is still easy
    (frontier is harder / higher)."""
    if pass_rate >= 0.5:
        return mid + 1, hi
    return lo, mid - 1
