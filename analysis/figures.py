"""The four figures. Reads numbers.json + the store; writes SVG to
paper/figs/ and docs/figs/.

Palette: validated 8-slot categorical (dataviz reference instance),
assigned in fixed roster order — colour follows the model, never its rank.
Below-contrast slots carry direct labels everywhere (relief rule).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from drc import config
from drc.runner.store import Store
from drc.stats.collect import collect_obs
from drc.stats.twopl import FitResult

N = json.loads((ROOT / "analysis" / "numbers.json").read_text())

SLOTS = ["#2a78d6", "#1baf7a", "#eda100", "#008300", "#4a3aa7", "#e34948", "#e87ba4", "#eb6834"]
ROSTER = [
    "openai/gpt-oss-20b",
    "openai/gpt-oss-120b",
    "minimax/minimax-m2.5",
    "qwen/qwen3-235b-a22b-thinking-2507",
    "deepseek/deepseek-r1-0528",
    "openai/o4-mini",
    "z-ai/glm-5",
    "anthropic/claude-haiku-4.5",
]
COLOR = {m: SLOTS[i] for i, m in enumerate(ROSTER)}
INK, INK2, GRID = "#1a1a19", "#5f5e56", "#e4e3db"

plt.rcParams.update({
    "font.size": 9,
    "axes.edgecolor": INK2,
    "axes.labelcolor": INK,
    "text.color": INK,
    "xtick.color": INK2,
    "ytick.color": INK2,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "grid.color": GRID,
    "grid.linewidth": 0.6,
    "svg.fonttype": "none",
})

FIGS = [ROOT / "paper" / "figs", ROOT / "docs" / "figs"]
for d in FIGS:
    d.mkdir(parents=True, exist_ok=True)


def fitted(m):
    e = N["models"].get(m, {})
    s = e.get("sat", {})
    return s if isinstance(s.get("x50"), (int, float)) else None


def save(fig, name):
    for d in FIGS:
        fig.savefig(d / name, bbox_inches="tight")
    plt.close(fig)
    print("wrote", name)


def level_pass_rates(store, m):
    obs = collect_obs(store, m, "sat", ("main",))
    by = {}
    for o in obs:
        d = by.setdefault(o.level_idx, {"x": o.x, "k": 0, "y": 0})
        d["k"] += o.k
        d["y"] += o.y
    xs = np.array([d["x"] for d in by.values()])
    ps = np.array([d["y"] / d["k"] for d in by.values()])
    ks = np.array([d["k"] for d in by.values()])
    order = np.argsort(xs)
    return xs[order], ps[order], ks[order]


def fig1_curves(store):
    fig, ax = plt.subplots(figsize=(6.4, 4.2))
    all_x = [x for m in ROSTER if fitted(m) for x in fitted(m)["token_curve"]["x"]]
    x_lo, x_hi = min(all_x) - 0.15, max(all_x) + 0.15
    xg = np.linspace(x_lo, x_hi, 400)
    label_slots = []
    for m in ROSTER:
        s = fitted(m)
        if not s:
            continue
        c = COLOR[m]
        xs, ps, ks = level_pass_rates(store, m)
        ax.scatter(xs, ps, s=10 + 14 * (ks / ks.max()), color=c, alpha=0.45, edgecolors="none", zorder=2)
        r = FitResult(b=s["b"], a=s["a"], lapse=s["lapse"], x50=s["x50"], loglik=0, lam_max=0.3)
        ax.plot(xg, r.predict(xg), color=c, lw=1.8, zorder=3)
        ax.plot([s["x50"]], [0.5], marker="|", ms=9, mew=1.8, color=c, zorder=4)
        label_slots.append((s["x50"], N["models"][m]["label"], c))
    ax.axhline(0.5, color=GRID, lw=0.8, zorder=1)
    # staggered direct labels along the top, sorted by frontier; spread
    # labels horizontally when frontiers bunch up
    label_slots.sort()
    n_lab = len(label_slots)
    if n_lab:
        spread = np.linspace(x_lo + 0.35, x_hi - 0.35, n_lab)
        for i, (x50, lab, c) in enumerate(label_slots):
            lx = 0.45 * x50 + 0.55 * spread[i]
            ax.annotate(
                lab, xy=(x50, 0.5), xytext=(lx, 1.055 + 0.07 * (i % 2)),
                ha="center", fontsize=7, color=c,
                arrowprops=dict(arrowstyle="-", color=c, lw=0.6, alpha=0.45,
                                connectionstyle="arc3,rad=0.12"),
            )
    ax.set_xlabel("clause-to-variable ratio α  (random 3-SAT, n = 20, satisfiable-only)")
    ax.set_ylabel("pass rate (certificate checked)")
    ax.set_ylim(-0.02, 1.18)
    ax.set_xlim(x_lo, x_hi)
    ax.grid(True, axis="y", alpha=0.5)
    save(fig, "fig1_curves.svg")


def fig2_formguide():
    rows = []
    for m in ROSTER:
        s = fitted(m)
        if not s or "x50_ci" not in s:
            continue
        e = N["models"][m]
        rt = e.get("retest", {})
        rows.append({
            "label": e["label"], "c": COLOR[m],
            "x50": s["x50"], "ci": s["x50_ci"],
            "a": s["a"], "a_ci": s.get("a_ci"),
            "retest": rt.get("x50") if isinstance(rt.get("x50"), (int, float)) else None,
        })
    rows.sort(key=lambda r: r["x50"])
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(6.4, 0.55 + 0.42 * len(rows)), sharey=True,
                                   gridspec_kw={"width_ratios": [2.1, 1.0]})
    ys = np.arange(len(rows))
    for y, r in zip(ys, rows):
        ax1.plot(r["ci"], [y, y], color=r["c"], lw=2.2, solid_capstyle="round")
        ax1.plot([r["x50"]], [y], "o", ms=5.5, color=r["c"])
        if r["retest"] is not None:
            ax1.plot([r["retest"]], [y], "o", ms=6.5, mfc="none", mec=r["c"], mew=1.4)
        if r["a_ci"]:
            ax2.plot(r["a_ci"], [y, y], color=r["c"], lw=2.2, solid_capstyle="round")
        ax2.plot([r["a"]], [y], "o", ms=5.5, color=r["c"])
    ax1.set_yticks(ys, [r["label"] for r in rows])
    ax1.set_xlabel("frontier x50 (α units) — filled: main run, open: retest")
    ax2.set_xlabel("sharpness a")
    for ax in (ax1, ax2):
        ax.grid(True, axis="x", alpha=0.5)
    save(fig, "fig2_formguide.svg")


def fig3_variance():
    rows = []
    for m in ROSTER:
        s = fitted(m)
        c2 = (s or {}).get("c2_center")
        if not c2:
            continue
        rows.append({
            "label": N["models"][m]["label"], "c": COLOR[m],
            "w": c2["within_share"], "ci": c2.get("within_share_ci"),
            "x": c2["x"], "k": c2["k_min"], "n": c2["n_instances"],
        })
    rows.sort(key=lambda r: r["w"])
    fig, ax = plt.subplots(figsize=(6.4, 0.55 + 0.42 * len(rows)))
    ys = np.arange(len(rows))
    for y, r in zip(ys, rows):
        ax.barh(y, r["w"], height=0.62, color=r["c"], alpha=0.85, edgecolor="none")
        ax.barh(y, 1 - r["w"], left=r["w"], height=0.62, color=r["c"], alpha=0.22, edgecolor="none")
        if r["ci"]:
            ax.plot(r["ci"], [y, y], color=INK, lw=1.1)
        ax.text(0.02, y, f"{100*r['w']:.0f}% within", va="center", fontsize=7.5,
                color="white" if r["w"] > 0.25 else INK)
        ax.text(1.01, y, f"α≈{r['x']:.2f}, k={r['k']}", va="center", fontsize=7, color=INK2)
    ax.set_yticks(ys, [r["label"] for r in rows])
    ax.set_xlim(0, 1.0)
    ax.set_xlabel("share of outcome variance at the frontier level — solid: within-instance, faint: between-instance")
    save(fig, "fig3_variance.svg")


def fig4_effort():
    fig, ax = plt.subplots(figsize=(6.4, 4.0))
    for m in ROSTER:
        s = fitted(m)
        if not s or "token_curve" not in s:
            continue
        c = COLOR[m]
        tc = s["token_curve"]
        ax.plot(tc["x"], tc["mean_log_tokens"], color=c, lw=1.8, label=N["models"][m]["label"])
        if s.get("peak") is not None and not s.get("peak_censored"):
            ms_at = np.interp(s["peak"], tc["x"], tc["mean_log_tokens"])
            ax.plot([s["peak"]], [ms_at], marker="^", ms=6, color=c, zorder=4)
        ax.axvline(s["x50"], color=c, lw=0.8, alpha=0.35, ymax=0.08)
    ax.set_xlabel("clause-to-variable ratio α   (▲ effort peak · tick at base: x50)")
    ax.set_ylabel("mean log completion tokens")
    ax.grid(True, axis="y", alpha=0.5)
    ax.legend(fontsize=7, ncols=2, frameon=False, loc="lower right")
    # efficiency inset
    c4 = N["claims"].get("C4", {}).get("per_model", {})
    if c4:
        lines = ["adaptive vs uniform (matched CI width)"]
        for lab, d in c4.items():
            if d.get("efficiency_ratio"):
                lines.append(f"{lab}: {d['efficiency_ratio']:.1f}×  ({d['adaptive_calls']} calls)")
        ax.text(
            0.02, 0.97, "\n".join(lines), transform=ax.transAxes, va="top", fontsize=7,
            color=INK, bbox=dict(fc="#fcfcfb", ec=GRID, lw=0.8, boxstyle="round,pad=0.4"),
        )
    save(fig, "fig4_effort.svg")


if __name__ == "__main__":
    store = Store(config.DATA_DIR / "drc.sqlite")
    fig1_curves(store)
    fig2_formguide()
    fig3_variance()
    fig4_effort()
