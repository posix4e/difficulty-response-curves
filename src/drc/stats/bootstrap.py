"""Stratified cluster bootstrap. The instance is the cluster: a resampled
instance carries all its samples (and its token statistics). Levels are
design points, never resampled. Percentile CIs.
"""

from __future__ import annotations

from typing import Callable, Sequence

import numpy as np

from .twopl import InstanceObs

B_HEADLINE = 2000
B_NESTED = 500


def resample(rng: np.random.Generator, obs: Sequence[InstanceObs]) -> list[InstanceObs]:
    by_level: dict[int, list[InstanceObs]] = {}
    for o in obs:
        by_level.setdefault(o.level_idx, []).append(o)
    out: list[InstanceObs] = []
    for li in sorted(by_level):
        group = by_level[li]
        idx = rng.integers(0, len(group), size=len(group))
        out.extend(group[i] for i in idx)
    return out


def run(
    obs: Sequence[InstanceObs],
    stat_fn: Callable[[list[InstanceObs]], dict[str, float]],
    B: int = B_HEADLINE,
    seed: int = 71,
) -> dict[str, np.ndarray]:
    """stat_fn maps a resampled dataset to named statistics; returns arrays
    of length <= B per name (replicates where stat_fn raised or returned
    NaN are dropped, count reported under '_dropped')."""
    rng = np.random.default_rng(seed)
    acc: dict[str, list[float]] = {}
    dropped = 0
    for _ in range(B):
        sample = resample(rng, obs)
        try:
            stats = stat_fn(sample)
        except Exception:
            dropped += 1
            continue
        if any(not np.isfinite(v) for v in stats.values()):
            dropped += 1
            continue
        for name, v in stats.items():
            acc.setdefault(name, []).append(float(v))
    out = {name: np.array(vals) for name, vals in acc.items()}
    out["_dropped"] = np.array([dropped])
    return out


def percentile_ci(samples: np.ndarray, level: float = 0.95) -> tuple[float, float]:
    lo = (1 - level) / 2
    return float(np.quantile(samples, lo)), float(np.quantile(samples, 1 - lo))
