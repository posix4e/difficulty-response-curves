"""Two-parameter logistic difficulty-response curve with an upper lapse.

    P(x) = (1 - lapse) * sigmoid(a * (b - x))

Higher x = harder. b is the logistic midpoint; the reported frontier is
x50, the level where the fitted curve crosses one half:

    x50 = b - logit(0.5 / (1 - lapse)) / a

Point estimates are penalized MLE (MAP): the log-a prior keeps the
slope finite under complete separation, the lapse prior shrinks gently
toward small lapses. All uncertainty comes from the cluster bootstrap
(bootstrap.py), never from the Hessian.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit, logit

LAM_MAX_DEFAULT = 0.15
A_SEPARATION_FLAG = 25.0


@dataclass
class InstanceObs:
    """Per-instance aggregate: k samples, y passes, at difficulty x."""

    instance_id: str
    level_idx: int
    x: float
    k: int
    y: int
    mean_log_tokens: float = float("nan")


@dataclass
class FitResult:
    b: float
    a: float
    lapse: float
    x50: float
    loglik: float
    lam_max: float
    flags: list[str] = field(default_factory=list)
    n_instances: int = 0
    n_calls: int = 0

    def predict(self, x: np.ndarray) -> np.ndarray:
        return (1 - self.lapse) * expit(self.a * (self.b - np.asarray(x, dtype=float)))


def x50_of(b: float, a: float, lapse: float) -> float:
    if lapse >= 0.5:
        return float("nan")
    return b - float(logit(0.5 / (1 - lapse))) / a


def _neg_log_post(theta: np.ndarray, x: np.ndarray, y: np.ndarray, k: np.ndarray, lam_max: float) -> float:
    b, log_a, u = theta
    a = np.exp(log_a)
    t = expit(u)  # lapse / lam_max
    lam = lam_max * t
    p = (1 - lam) * expit(a * (b - x))
    p = np.clip(p, 1e-9, 1 - 1e-9)
    ll = float(np.sum(y * np.log(p) + (k - y) * np.log(1 - p)))
    lp_a = -0.5 * ((log_a - np.log(2.0)) / 1.5) ** 2
    # Beta(2, 38) on t, plus the sigmoid Jacobian (proper MAP in u-space)
    t_c = min(max(t, 1e-12), 1 - 1e-12)
    lp_lam = (2 - 1) * np.log(t_c) + (38 - 1) * np.log(1 - t_c) + np.log(t_c * (1 - t_c))
    return -(ll + lp_a + lp_lam)


def fit(obs: list[InstanceObs], lam_max: float = LAM_MAX_DEFAULT, quick: bool = False) -> FitResult:
    x = np.array([o.x for o in obs], dtype=float)
    y = np.array([o.y for o in obs], dtype=float)
    k = np.array([o.k for o in obs], dtype=float)
    grid_min, grid_max = float(x.min()), float(x.max())

    flags: list[str] = []
    if y.sum() == 0:
        return FitResult(
            b=float("nan"), a=float("nan"), lapse=float("nan"), x50=float("-inf"),
            loglik=0.0, lam_max=lam_max, flags=["censored_below_grid"],
            n_instances=len(obs), n_calls=int(k.sum()),
        )
    if (y == k).all():
        return FitResult(
            b=float("nan"), a=float("nan"), lapse=float("nan"), x50=float("inf"),
            loglik=0.0, lam_max=lam_max, flags=["censored_above_grid"],
            n_instances=len(obs), n_calls=int(k.sum()),
        )

    bounds = [(grid_min - 1.0, grid_max + 1.0), (np.log(0.05), np.log(200.0)), (-12.0, 12.0)]
    b_inits = np.quantile(x, [0.2, 0.35, 0.5, 0.65, 0.8])
    a_inits = [np.log(0.7), np.log(2.0), np.log(6.0)]
    if quick:
        b_inits = np.quantile(x, [0.3, 0.5, 0.7])
        a_inits = [np.log(2.0)]

    best = None
    for b0 in b_inits:
        for la0 in a_inits:
            res = minimize(
                _neg_log_post, x0=np.array([b0, la0, -3.0]),
                args=(x, y, k, lam_max), method="L-BFGS-B", bounds=bounds,
            )
            if best is None or res.fun < best.fun:
                best = res
    assert best is not None
    b_hat, log_a_hat, u_hat = best.x
    a_hat = float(np.exp(log_a_hat))
    lam_hat = lam_max * float(expit(u_hat))
    if a_hat > A_SEPARATION_FLAG:
        flags.append("separation_penalty_dominated")
    result = FitResult(
        b=float(b_hat), a=a_hat, lapse=lam_hat,
        x50=x50_of(float(b_hat), a_hat, lam_hat),
        loglik=-float(best.fun), lam_max=lam_max, flags=flags,
        n_instances=len(obs), n_calls=int(k.sum()),
    )
    return result


def fit_with_lapse_guard(obs: list[InstanceObs], quick: bool = False) -> FitResult:
    """Standard fit, but if the easy-side plateau sits below 0.85 the lapse
    bound is widened to 0.30 and the fit is flagged."""
    result = fit(obs, LAM_MAX_DEFAULT, quick=quick)
    if not np.isfinite(result.x50):
        return result
    by_level: dict[int, list[InstanceObs]] = {}
    for o in obs:
        by_level.setdefault(o.level_idx, []).append(o)
    easiest = sorted(by_level)[:3]
    rates = [sum(o.y for o in by_level[li]) / max(1, sum(o.k for o in by_level[li])) for li in easiest]
    if rates and max(rates) < 0.85:
        result = fit(obs, 0.30, quick=quick)
        result.flags.append("high_lapse_widened_bound")
    return result


def pearson_x2(fitres: FitResult, obs: list[InstanceObs]) -> float:
    """Level-wise Pearson X^2 against the fitted curve."""
    by_level: dict[int, list[InstanceObs]] = {}
    for o in obs:
        by_level.setdefault(o.level_idx, []).append(o)
    x2 = 0.0
    for li, group in by_level.items():
        n = sum(o.k for o in group)
        y = sum(o.y for o in group)
        p_hat = y / n
        p_fit = float(fitres.predict(np.array([group[0].x]))[0])
        p_fit = min(max(p_fit, 1e-9), 1 - 1e-9)
        x2 += n * (p_hat - p_fit) ** 2 / (p_fit * (1 - p_fit))
    return x2


def simulate_obs(
    rng: np.random.Generator,
    fitres: FitResult,
    template: list[InstanceObs],
    icc: float,
) -> list[InstanceObs]:
    """Parametric simulation from a fitted curve with beta-binomial
    instance effects at intraclass correlation icc."""
    icc = min(max(icc, 1e-6), 0.95)
    nu = (1 - icc) / icc  # alpha + beta
    out: list[InstanceObs] = []
    for o in template:
        mu = float(fitres.predict(np.array([o.x]))[0])
        mu = min(max(mu, 1e-6), 1 - 1e-6)
        alpha, beta = max(mu * nu, 1e-3), max((1 - mu) * nu, 1e-3)
        p_i = rng.beta(alpha, beta)
        y = int(rng.binomial(o.k, p_i))
        out.append(InstanceObs(o.instance_id, o.level_idx, o.x, o.k, y))
    return out


def gof_mc_pvalue(
    fitres: FitResult,
    obs: list[InstanceObs],
    icc: float,
    n_sims: int = 1000,
    seed: int = 90210,
) -> tuple[float, float]:
    """Monte-Carlo calibrated goodness of fit: simulate datasets from the
    fitted curve with instance effects, refit, compare X^2. Returns
    (x2_observed, p_mc)."""
    x2_obs = pearson_x2(fitres, obs)
    rng = np.random.default_rng(seed)
    exceed = 0
    for _ in range(n_sims):
        sim = simulate_obs(rng, fitres, obs, icc)
        try:
            sim_fit = fit_with_lapse_guard(sim, quick=True)
            if not np.isfinite(sim_fit.x50):
                exceed += 1  # degenerate sims count as extreme
                continue
            if pearson_x2(sim_fit, sim) >= x2_obs:
                exceed += 1
        except Exception:
            continue
    return x2_obs, exceed / n_sims
