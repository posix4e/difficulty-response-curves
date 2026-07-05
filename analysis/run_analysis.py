"""Compute every reported number from the store, into analysis/numbers.json.

The paper and the site read numbers.json; nothing is hand-typed. Rerun:

    .venv/bin/python analysis/run_analysis.py            # full
    .venv/bin/python analysis/run_analysis.py --fast     # B=200, no C4 sims
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from drc import config
from drc.runner.store import Store
from drc.stats import bootstrap, decomp, tokens
from drc.stats.c4_eval import matched_efficiency, simulate_adaptive, uniform_width_curve
from drc.stats.collect import collect_obs, outcome_rates
from drc.stats.reliability import (
    cross_model_correlations,
    kendall_tau_exact,
    retest_z,
    spearman_brown,
    split_half,
)
from drc.stats.twopl import fit_with_lapse_guard, gof_mc_pvalue

LABELS = {
    "openai/gpt-oss-20b": "gpt-oss-20b",
    "openai/gpt-oss-120b": "gpt-oss-120b",
    "minimax/minimax-m2.5": "MiniMax-M2.5",
    "qwen/qwen3-235b-a22b-thinking-2507": "Qwen3-235B-Think",
    "deepseek/deepseek-r1-0528": "DeepSeek-R1-0528",
    "openai/o4-mini": "o4-mini",
    "z-ai/glm-5": "GLM-5",
    "anthropic/claude-haiku-4.5": "Haiku-4.5-Think",
}

OUT = Path(__file__).resolve().parent / "numbers.json"


def _ci(arr: np.ndarray) -> list[float]:
    lo, hi = bootstrap.percentile_ci(arr)
    return [round(lo, 4), round(hi, 4)]


def analyse_model_family(store, model_id, family, sets, B, do_gof=True) -> dict | None:
    obs = collect_obs(store, model_id, family, sets)
    if len(obs) < 10:
        return None
    res = fit_with_lapse_guard(obs)
    out: dict = {
        "b": round(res.b, 4) if np.isfinite(res.b) else str(res.b),
        "a": round(res.a, 4) if np.isfinite(res.a) else None,
        "lapse": round(res.lapse, 4) if np.isfinite(res.lapse) else None,
        "x50": round(res.x50, 4) if np.isfinite(res.x50) else str(res.x50),
        "flags": res.flags,
        "n_instances": res.n_instances,
        "n_calls": res.n_calls,
        "rates": outcome_rates(store, model_id, family, sets),
    }
    if not np.isfinite(res.x50):
        return out

    # joint bootstrap: curve params + token peak + offset on the same resamples
    grid_xs = sorted({o.x for o in obs})

    def stat(sample):
        r = fit_with_lapse_guard(sample, quick=True)
        d = {"x50": r.x50, "a": r.a, "b": r.b, "lapse": r.lapse}
        pk = tokens.peak_x(sample)
        d["peak"] = pk["peak"]
        d["offset"] = pk["peak"] - r.x50
        d["sag"] = pk["sag"]
        return d

    boots = bootstrap.run(obs, stat, B=B, seed=71)
    for name in ("x50", "a", "b", "lapse", "peak", "offset", "sag"):
        if name in boots and len(boots[name]):
            out[f"{name}_ci"] = _ci(boots[name])
    out["x50_se"] = round(float(np.std(boots["x50"], ddof=1)), 4) if "x50" in boots else None

    pk = tokens.peak_x(obs)
    out["peak"] = round(pk["peak"], 4) if np.isfinite(pk["peak"]) else None
    out["peak_censored"] = bool(pk["censored"])
    out["offset"] = round(pk["peak"] - res.x50, 4) if np.isfinite(pk["peak"]) else None
    out["sag"] = round(pk["sag"], 4) if np.isfinite(pk["sag"]) else None
    xs, ms = tokens.level_means(obs)
    out["token_curve"] = {"x": [round(v, 4) for v in xs.tolist()], "mean_log_tokens": [round(v, 4) for v in ms.tolist()]}

    # C2 at the highest-k level nearest the frontier + profile
    prof = decomp.by_level(obs, min_k=8)
    out["c2_profile"] = {
        str(li): {k: (round(v, 4) if np.isfinite(v) else None) for k, v in d.items()}
        for li, d in prof.items()
    }
    center_li = None
    best = (0.0, float("inf"))
    for li, d in prof.items():
        if not np.isfinite(d.get("within_share", float("nan"))):
            continue
        kmin = d.get("k_min", 0)
        dist = abs([o.x for o in obs if o.level_idx == li][0] - res.x50)
        key = (-kmin, dist)
        if center_li is None or key < best:
            center_li, best = li, key
    if center_li is not None:
        group = [o for o in obs if o.level_idx == center_li and o.k >= 2]

        def c2_stat(sample):
            g = [o for o in sample if o.level_idx == center_li and o.k >= 2]
            d = decomp.decompose_level(g)
            return {"within_share": d["within_share"]}

        c2_boots = bootstrap.run(obs, c2_stat, B=B, seed=72)
        d = decomp.decompose_level(group)
        out["c2_center"] = {
            "level_idx": center_li,
            "x": group[0].x,
            "k_min": int(min(o.k for o in group)),
            "n_instances": len(group),
            "within_share": round(d["within_share"], 4),
            "within_share_ci": _ci(c2_boots["within_share"]) if "within_share" in c2_boots else None,
            "icc": round(d["icc"], 4),
            "pbar": round(d["pbar"], 4),
        }

    if do_gof:
        icc = decomp.frontier_icc(obs, res.x50)
        x2, p = gof_mc_pvalue(res, obs, icc, n_sims=300)
        out["gof_x2"], out["gof_p_mc"], out["frontier_icc"] = round(x2, 2), round(p, 4), round(icc, 4)

    # split-half (C1 free tier)
    half_a, half_b = split_half(obs)
    ra = fit_with_lapse_guard(half_a, quick=True)
    rb = fit_with_lapse_guard(half_b, quick=True)
    if np.isfinite(ra.x50) and np.isfinite(rb.x50):
        out["split_half"] = {"x50_a": round(ra.x50, 4), "x50_b": round(rb.x50, 4)}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true", help="B=200, skip C4 sims and GOF")
    ap.add_argument("--skip-c4", action="store_true")
    args = ap.parse_args()
    B = 200 if args.fast else bootstrap.B_HEADLINE

    store = Store(config.DATA_DIR / "drc.sqlite")
    models = config.load_models()
    out: dict = {"models": {}, "claims": {}, "abstract": {}}

    # per-model analyses
    for model_id in models:
        entry: dict = {"label": LABELS.get(model_id, model_id), "tier": models[model_id].tier}
        sat = analyse_model_family(store, model_id, "sat", ("main",), B, do_gof=not args.fast)
        if sat:
            entry["sat"] = sat
        retest = analyse_model_family(store, model_id, "sat", ("retest",), max(200, B // 4), do_gof=False)
        if retest:
            entry["retest"] = retest
        dagres = analyse_model_family(store, model_id, "dag", ("main",), max(200, B // 4), do_gof=False)
        if dagres:
            entry["dag"] = dagres
        if len(entry) > 2:
            out["models"][model_id] = entry

    fitted = {
        m: e for m, e in out["models"].items()
        if isinstance(e.get("sat", {}).get("x50"), (int, float))
    }

    # ---- C1 reliability ----
    c1: dict = {}
    sh = [
        (e["sat"]["split_half"]["x50_a"], e["sat"]["split_half"]["x50_b"])
        for e in fitted.values()
        if "split_half" in e["sat"]
    ]
    if len(sh) >= 4:
        corr = cross_model_correlations([p[0] for p in sh], [p[1] for p in sh])
        c1["split_half_r"] = round(corr["pearson_r"], 4)
        c1["split_half_spearman_brown"] = round(spearman_brown(corr["pearson_r"]), 4)
    both = {
        m: e for m, e in fitted.items()
        if isinstance(e.get("retest", {}).get("x50"), (int, float)) and e["retest"].get("x50_se")
    }
    if len(both) >= 3:
        run1 = [e["sat"]["x50"] for e in both.values()]
        run2 = [e["retest"]["x50"] for e in both.values()]
        c1.update({f"retest_{k}": round(v, 4) for k, v in cross_model_correlations(run1, run2).items()})
        c1["kendall"] = kendall_tau_exact(run1, run2)
        zs, inside = {}, 0
        for m, e in both.items():
            z = retest_z(e["sat"]["x50"], e["sat"]["x50_se"] or 0.05, e["retest"]["x50"], e["retest"]["x50_se"] or 0.05)
            zs[LABELS.get(m, m)] = round(float(z), 3)
            lo, hi = e["sat"]["x50_ci"]
            inside += int(lo <= e["retest"]["x50"] <= hi)
        c1["retest_z"] = zs
        c1["retest_inside_ci"] = f"{inside}/{len(both)}"
        c1["ci_widths_run1"] = {
            LABELS.get(m, m): round(e["sat"]["x50_ci"][1] - e["sat"]["x50_ci"][0], 3) for m, e in both.items()
        }
    out["claims"]["C1"] = c1

    # ---- C2 headline ----
    shares = {
        LABELS.get(m, m): e["sat"]["c2_center"]["within_share"]
        for m, e in fitted.items()
        if e["sat"].get("c2_center") and e["sat"]["c2_center"]["k_min"] >= 12
    }
    out["claims"]["C2"] = {
        "within_share_by_model": shares,
        "median_within_share": round(float(np.median(list(shares.values()))), 4) if shares else None,
    }

    # ---- C3 headline ----
    offsets = {
        LABELS.get(m, m): {"offset": e["sat"]["offset"], "ci": e["sat"].get("offset_ci"), "sag": e["sat"]["sag"], "censored": e["sat"]["peak_censored"]}
        for m, e in fitted.items()
        if e["sat"].get("offset") is not None
    }
    abs_offsets = [abs(v["offset"]) for v in offsets.values() if not v["censored"]]
    out["claims"]["C3"] = {
        "offsets_by_model": offsets,
        "median_abs_offset": round(float(np.median(abs_offsets)), 4) if abs_offsets else None,
        "max_abs_offset": round(float(np.max(abs_offsets)), 4) if abs_offsets else None,
    }

    # ---- C4 ----
    if not args.skip_c4 and not args.fast:
        from drc.stats.twopl import FitResult, x50_of

        pooled_log_a = float(np.mean([np.log(e["sat"]["a"]) for e in fitted.values() if e["sat"].get("a")]))
        c4: dict = {"per_model": {}}
        ratios = []
        for m, e in fitted.items():
            s = e["sat"]
            levels = tuple(s["token_curve"]["x"])  # the model's own grid (minimax runs extended)
            truth = FitResult(b=s["b"], a=s["a"], lapse=s["lapse"], x50=s["x50"], loglik=0, lam_max=0.15)
            icc = 1 - s["c2_center"]["within_share"] if s.get("c2_center") else 0.2
            runs = [
                simulate_adaptive(truth, icc, levels, pooled_log_a, eps_target=0.10, max_calls=200, seed=sd)
                for sd in range(60)
            ]
            calls = int(np.median([r.calls_used for r in runs]))
            width = float(np.median([r.ci_width for r in runs]))
            bias = float(np.median([r.b_final - truth.b for r in runs]))
            obs = collect_obs(store, m, "sat", ("main",))
            curve = uniform_width_curve(obs, [240, 480, 960, 1440, 1920], n_draws=40)
            ratio = matched_efficiency(curve, calls, width)
            c4["per_model"][LABELS.get(m, m)] = {
                "adaptive_calls": calls,
                "adaptive_width": round(width, 3),
                "bias": round(bias, 3),
                "uniform_curve": {str(k): round(v, 3) for k, v in curve.items() if np.isfinite(v)},
                "efficiency_ratio": round(ratio, 2) if np.isfinite(ratio) else None,
            }
            if np.isfinite(ratio):
                ratios.append(ratio)
        c4["median_efficiency_ratio"] = round(float(np.median(ratios)), 2) if ratios else None
        out["claims"]["C4"] = c4

    # ---- abstract brackets ----
    out["abstract"] = {
        "X_reliability_r": out["claims"]["C1"].get("retest_pearson_r")
        or out["claims"]["C1"].get("split_half_spearman_brown"),
        "Y_within_pct": round(100 * out["claims"]["C2"]["median_within_share"], 1)
        if out["claims"]["C2"].get("median_within_share") is not None
        else None,
        "Z_offset_units": out["claims"]["C3"].get("median_abs_offset"),
        "W_efficiency": out["claims"].get("C4", {}).get("median_efficiency_ratio"),
    }

    # provenance
    sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=config.REPO_ROOT).stdout.strip()
    out["provenance"] = {
        "git_sha": sha,
        "bootstrap_B": B,
        "spend_usd": round(store.spent_microdollars() / 1e6, 2),
    }
    OUT.write_text(json.dumps(out, indent=2, default=str))
    print(f"wrote {OUT}")
    print(json.dumps(out["abstract"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
