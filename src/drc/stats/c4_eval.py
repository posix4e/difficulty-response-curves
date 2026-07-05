"""C4 evaluation: adaptive vs uniform at matched CI width.

Simulation arm: each core model's fitted curve + frontier ICC becomes a
ground truth; adaptive runs are simulated with beta-binomial instance
effects. Uniform baseline: level-balanced cluster subsamples of the real
sweep data at increasing call counts give a CI-width-vs-calls curve;
interpolation yields the uniform call count needed to match the adaptive
run's achieved width. Efficiency ratio = uniform calls / adaptive calls.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..adaptive.bisect import AdaptiveState, bracket_step, fit_b, next_level, se_b_bootstrap
from .bootstrap import percentile_ci
from .twopl import FitResult, InstanceObs, fit_with_lapse_guard, x50_of


@dataclass
class SimulatedRun:
    calls_used: int
    b_final: float
    se_final: float
    ci_width: float


def _draw_instance(rng, truth: FitResult, icc: float, x: float, level_idx: int, k: int, tag: str) -> InstanceObs:
    mu = float(truth.predict(np.array([x]))[0])
    mu = min(max(mu, 1e-6), 1 - 1e-6)
    icc = min(max(icc, 1e-6), 0.95)
    nu = (1 - icc) / icc
    p_i = rng.beta(max(mu * nu, 1e-3), max((1 - mu) * nu, 1e-3))
    return InstanceObs(tag, level_idx, x, k, int(rng.binomial(k, p_i)))


def simulate_adaptive(
    truth: FitResult,
    icc: float,
    levels: tuple[float, ...],
    a_prior_mu: float,
    a_prior_sd: float = 0.5,
    eps_target: float = 0.15,
    max_calls: int = 200,
    probe_instances: int = 4,
    batch_instances: int = 4,
    batch_k: int = 2,
    seed: int = 0,
) -> SimulatedRun:
    rng = np.random.default_rng(seed)
    lapse = min(truth.lapse if np.isfinite(truth.lapse) else 0.02, 0.14)
    state = AdaptiveState()
    tag = 0

    # Phase 1: bisection bracket
    lo, hi = 0, len(levels) - 1
    probes = 0
    while lo < hi and probes < 4:
        mid = (lo + hi) // 2
        passes = 0
        for _ in range(probe_instances):
            o = _draw_instance(rng, truth, icc, levels[mid], mid, 1, f"a{tag}")
            tag += 1
            state.history.append(o)
            state.calls_used += 1
            passes += o.y
        lo, hi = bracket_step(passes / probe_instances, lo, hi, mid)
        probes += 1

    # Phase 2: info-refinement at the level nearest current x50
    while state.calls_used < max_calls:
        li = next_level(state, levels, a_prior_mu, a_prior_sd, lapse)
        for _ in range(batch_instances):
            o = _draw_instance(rng, truth, icc, levels[li], li, batch_k, f"a{tag}")
            tag += 1
            state.history.append(o)
            state.calls_used += batch_k
        se = se_b_bootstrap(state.history, a_prior_mu, a_prior_sd, lapse, levels[0], levels[-1], B=100, seed=tag)
        if np.isfinite(se) and se <= eps_target:
            break
    b, _a = fit_b(state.history, a_prior_mu, a_prior_sd, lapse, levels[0], levels[-1])
    se = se_b_bootstrap(state.history, a_prior_mu, a_prior_sd, lapse, levels[0], levels[-1], B=200, seed=1)
    return SimulatedRun(state.calls_used, b, se, ci_width=2 * 1.96 * se)


def uniform_width_curve(
    obs: list[InstanceObs],
    call_targets: list[int],
    n_draws: int = 100,
    seed: int = 9,
) -> dict[int, float]:
    """Mean 95% CI width of x50 from level-balanced cluster subsamples of
    the real sweep at each call budget."""
    rng = np.random.default_rng(seed)
    by_level: dict[int, list[InstanceObs]] = {}
    for o in obs:
        by_level.setdefault(o.level_idx, []).append(o)
    n_levels = len(by_level)
    out: dict[int, float] = {}
    for target in call_targets:
        widths = []
        for _ in range(n_draws):
            sample: list[InstanceObs] = []
            for group in by_level.values():
                per_level_calls = target / n_levels
                chosen: list[InstanceObs] = []
                order = rng.permutation(len(group))
                calls = 0
                for i in order:
                    if calls >= per_level_calls:
                        break
                    chosen.append(group[i])
                    calls += group[i].k
                sample.extend(chosen)
            try:
                boots = []
                for _b in range(60):
                    res_sample = _cluster_resample(rng, sample)
                    r = fit_with_lapse_guard(res_sample, quick=True)
                    if np.isfinite(r.x50):
                        boots.append(r.x50)
                if len(boots) > 30:
                    lo, hi = percentile_ci(np.array(boots))
                    widths.append(hi - lo)
            except Exception:
                continue
        out[target] = float(np.mean(widths)) if widths else float("nan")
    return out


def _cluster_resample(rng, obs: list[InstanceObs]) -> list[InstanceObs]:
    by_level: dict[int, list[InstanceObs]] = {}
    for o in obs:
        by_level.setdefault(o.level_idx, []).append(o)
    out: list[InstanceObs] = []
    for group in by_level.values():
        idx = rng.integers(0, len(group), size=len(group))
        out.extend(group[i] for i in idx)
    return out


def matched_efficiency(
    width_curve: dict[int, float], adaptive_calls: int, adaptive_width: float
) -> float:
    """Interpolate the uniform calls needed to reach adaptive_width;
    return the ratio uniform/adaptive."""
    pts = sorted((c, w) for c, w in width_curve.items() if np.isfinite(w))
    if not pts or not np.isfinite(adaptive_width):
        return float("nan")
    calls = np.array([p[0] for p in pts], dtype=float)
    widths = np.array([p[1] for p in pts], dtype=float)
    # widths shrink with calls; interpolate in log-log
    if adaptive_width <= widths.min():
        return float(calls.max() / adaptive_calls)  # lower bound
    if adaptive_width >= widths.max():
        return float(calls.min() / adaptive_calls)
    uniform_calls = float(np.exp(np.interp(np.log(adaptive_width), np.log(widths[::-1]), np.log(calls[::-1]))))
    return uniform_calls / adaptive_calls
