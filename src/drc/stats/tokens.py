"""C3: the effort marker. Mean log completion tokens per level, peak
located by a windowed quadratic fit, offset reported against x50 from a
JOINT bootstrap (the same instance resample drives both statistics, so
frontier uncertainty propagates into the offset CI).
"""

from __future__ import annotations

import numpy as np

from .twopl import InstanceObs


def level_means(obs: list[InstanceObs]) -> tuple[np.ndarray, np.ndarray]:
    """(x, mean over instances of mean-log-tokens), sorted by x; levels with
    no token data dropped."""
    groups: dict[int, list[InstanceObs]] = {}
    for o in obs:
        if np.isfinite(o.mean_log_tokens):
            groups.setdefault(o.level_idx, []).append(o)
    xs, ms = [], []
    for li in sorted(groups):
        g = groups[li]
        xs.append(g[0].x)
        ms.append(float(np.mean([o.mean_log_tokens for o in g])))
    return np.array(xs), np.array(ms)


def peak_x(obs: list[InstanceObs], window_steps: int = 3) -> dict[str, float | bool]:
    """Quadratic vertex on argmax +/- window_steps grid points (>=5 points).
    Censored when the vertex clamps to a window edge that is also a grid
    edge."""
    xs, ms = level_means(obs)
    if len(xs) < 5:
        return {"peak": float("nan"), "censored": True, "sag": float("nan")}
    i_max = int(np.argmax(ms))
    lo = max(0, i_max - window_steps)
    hi = min(len(xs), i_max + window_steps + 1)
    while hi - lo < 5:
        if lo > 0:
            lo -= 1
        elif hi < len(xs):
            hi += 1
        else:
            break
    wx, wm = xs[lo:hi], ms[lo:hi]
    coef = np.polyfit(wx, wm, 2)
    if coef[0] >= 0:  # convex: no interior peak; take empirical argmax
        vertex = xs[i_max]
    else:
        vertex = -coef[1] / (2 * coef[0])
    clamped = min(max(vertex, wx[0]), wx[-1])
    censored = bool(
        (np.isclose(clamped, wx[0]) and lo == 0)
        or (np.isclose(clamped, wx[-1]) and hi == len(xs))
    )
    # sag: mean log tokens 3 grid steps past the peak minus at the peak
    i_peak = int(np.argmin(np.abs(xs - clamped)))
    i_after = min(len(xs) - 1, i_peak + 3)
    sag = float(ms[i_after] - ms[i_peak]) if i_after > i_peak else float("nan")
    return {"peak": float(clamped), "censored": censored, "sag": sag}
