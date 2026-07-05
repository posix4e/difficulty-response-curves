"""C2: decompose outcome variance near the frontier into within-instance
(same instance, different samples) and between-instance parts.

At one level with n instances of k samples each, p_hat_i = y_i / k:

    sigma2_W = mean_i[ k/(k-1) * p_hat_i (1 - p_hat_i) ]      (unbiased for E[p(1-p)])
    sigma2_B = s^2(p_hat_i) - mean_i[ p_hat_i(1-p_hat_i) ] / (k-1)   (unbiased for Var(p))

Self-check identity: E[sigma2_W + sigma2_B] = pbar(1-pbar).
Reported: within share W = sigma2_W / (sigma2_W + sigma2_B); ICC = 1 - W.
"""

from __future__ import annotations

import numpy as np

from .twopl import InstanceObs


def decompose_level(group: list[InstanceObs]) -> dict[str, float]:
    """group = instances at one level, all with k >= 2."""
    ks = np.array([o.k for o in group], dtype=float)
    ys = np.array([o.y for o in group], dtype=float)
    if len(group) < 3 or (ks < 2).any():
        return {"within": float("nan"), "between_raw": float("nan"), "within_share": float("nan")}
    p = ys / ks
    var_terms = p * (1 - p)
    within = float(np.mean(ks / (ks - 1) * var_terms))
    between_raw = float(np.var(p, ddof=1) - np.mean(var_terms / (ks - 1)))
    between = max(0.0, between_raw)
    total = within + between
    share = within / total if total > 0 else float("nan")
    return {
        "within": within,
        "between_raw": between_raw,
        "between": between,
        "within_share": share,
        "icc": 1.0 - share if np.isfinite(share) else float("nan"),
        "pbar": float(np.mean(p)),
        "n_instances": float(len(group)),
        "k_min": float(ks.min()),
    }


def by_level(obs: list[InstanceObs], min_k: int = 2) -> dict[int, dict[str, float]]:
    groups: dict[int, list[InstanceObs]] = {}
    for o in obs:
        if o.k >= min_k:
            groups.setdefault(o.level_idx, []).append(o)
    return {li: decompose_level(g) for li, g in sorted(groups.items())}


def frontier_icc(obs: list[InstanceObs], x50: float | None = None) -> float:
    """ICC at the level nearest the frontier (highest-k data preferred).
    Used to calibrate the GOF parametric bootstrap; falls back to the
    level with pass rate nearest 0.5 when no x50 is supplied."""
    groups: dict[int, list[InstanceObs]] = {}
    for o in obs:
        groups.setdefault(o.level_idx, []).append(o)
    best_li, best_score = None, float("inf")
    for li, g in groups.items():
        ks = [o.k for o in g]
        if max(ks) < 2:
            continue
        if x50 is not None and np.isfinite(x50):
            score = abs(g[0].x - x50)
        else:
            pbar = sum(o.y for o in g) / max(1, sum(o.k for o in g))
            score = abs(pbar - 0.5)
        # prefer high-k levels: soft penalty for low k
        score += 0.0 if np.mean(ks) >= 8 else 0.25
        if score < best_score:
            best_li, best_score = li, score
    if best_li is None:
        return 0.1
    d = decompose_level([o for o in groups[best_li] if o.k >= 2])
    icc = d.get("icc", float("nan"))
    return float(icc) if np.isfinite(icc) else 0.1
