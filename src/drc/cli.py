"""drc: run difficulty sweeps against your own key and fit the curves.

    drc run-stage pilot-sat            # run a configured stage
    drc gate --stages pilot-sat --grid sat-n20-main --out data/focus-sat.json
    drc budget                         # spend ledger
    drc fit --model openai/o4-mini --family sat --sets main
    drc sweep --model openai/gpt-oss-20b --grid sat-n20-main \
              --instances 10 --k 4 --cap 5.0   # ad-hoc sweep, your budget
    drc export --out data/exports
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

from . import config
from .runner.budget import BudgetGuard
from .runner.client import TRClient
from .runner.scheduler import Job, run_jobs
from .runner.store import Store
from .runner.sweep import plan_jobs
from .stats import bootstrap
from .stats.twopl import InstanceObs, fit_with_lapse_guard, gof_mc_pvalue

DB_PATH = config.DATA_DIR / "drc.sqlite"


def _log(msg: str) -> None:
    print(msg, flush=True)


def _store() -> Store:
    config.DATA_DIR.mkdir(exist_ok=True)
    return Store(DB_PATH)


def _stage_caps(stages) -> dict[str, float]:
    return {name: s.cap_usd for name, s in stages.items()}


def cmd_run_stage(args) -> int:
    models = config.load_models()
    grids = config.load_grids()
    stages = config.load_stages(models)
    if args.stage not in stages:
        _log(f"unknown stage {args.stage!r}; have: {', '.join(stages)}")
        return 2
    stage = stages[args.stage]
    if args.stream_telemetry:
        stage.stream_telemetry = True
    store = _store()
    guard = BudgetGuard(store, _stage_caps(stages))
    jobs = plan_jobs(stage, grids, models, store)
    _log(f"stage {stage.name}: {len(jobs)} calls to run (cap ${stage.cap_usd:.2f})")
    if args.dry_run or not jobs:
        return 0
    client = TRClient(config.load_key())
    try:
        summary = asyncio.run(run_jobs(jobs, models, client, store, guard, log=_log))
    finally:
        asyncio.run(client.aclose())
    _log(json.dumps(summary, indent=2, default=str))
    return 0


from .stats.collect import collect_obs as _collect_obs_impl


def _collect_obs(store: Store, model_id: str, family: str, sets: tuple[str, ...], stages: tuple[str, ...] | None) -> list[InstanceObs]:
    return _collect_obs_impl(store, model_id, family, sets, stages)


def cmd_gate(args) -> int:
    """Post-stage checkpoint: per-model coarse fit, parse health, token
    burn, provider endpoints, measured $/call; writes the focus file."""
    models = config.load_models()
    grids = config.load_grids()
    store = _store()
    target_grid = grids[args.grid]
    stage_names = tuple(args.stages.split(","))
    family = target_grid.family
    focus: dict[str, dict] = {}
    report: dict[str, dict] = {}
    for model_id in models:
        obs = _collect_obs(store, model_id, family, tuple(args.sets.split(",")), stage_names)
        if not obs:
            continue
        res = fit_with_lapse_guard(obs, quick=True)
        cur = store.conn.execute(
            """SELECT AVG(cost_microdollars) AS mean_cost,
                      SUM(outcome='fail_parse') * 1.0 / COUNT(*) AS parse_rate,
                      SUM(outcome='fail_truncated') * 1.0 / COUNT(*) AS trunc_rate,
                      COUNT(DISTINCT provider_endpoint) AS n_providers,
                      GROUP_CONCAT(DISTINCT provider_endpoint) AS endpoints
               FROM calls c JOIN instances i USING(instance_id)
               WHERE c.model_id=? AND i.family=? AND c.stage IN (%s)"""
            % ",".join("?" * len(stage_names)),
            (model_id, family, *stage_names),
        ).fetchone()
        toks = [
            r[0]
            for r in store.conn.execute(
                "SELECT completion_tokens FROM calls c JOIN instances i USING(instance_id) "
                "WHERE c.model_id=? AND i.family=? AND c.stage IN (%s) AND completion_tokens IS NOT NULL"
                % ",".join("?" * len(stage_names)),
                (model_id, family, *stage_names),
            )
        ]
        p95 = float(np.percentile(toks, 95)) if toks else 0.0
        x50 = res.x50
        if np.isfinite(x50):
            center = int(np.argmin(np.abs(np.array(target_grid.levels) - x50)))
        else:
            center = len(target_grid.levels) - 1 if x50 == float("inf") else 0
        focus[model_id] = {"center_level_idx": center, "x50": x50 if np.isfinite(x50) else str(x50)}
        report[model_id] = {
            "x50": round(x50, 3) if np.isfinite(x50) else str(x50),
            "a": round(res.a, 2) if np.isfinite(res.a) else None,
            "lapse": round(res.lapse, 3) if np.isfinite(res.lapse) else None,
            "flags": res.flags,
            "n_calls": res.n_calls,
            "mean_cost_usd": round((cur["mean_cost"] or 0) / 1e6, 5),
            "parse_fail_rate": round(cur["parse_rate"] or 0, 3),
            "trunc_rate": round(cur["trunc_rate"] or 0, 3),
            "token_p95": int(p95),
            "suggested_cap": int(min(32768, max(4096, 3 * p95))),
            "endpoints": (cur["endpoints"] or "").split(",")[:6],
        }
    out_path = Path(args.out)
    merged: dict = {}
    if out_path.exists():
        merged = json.loads(out_path.read_text())  # keep other models' centers
    merged.update(focus)
    out_path.write_text(json.dumps(merged, indent=2))
    _log(json.dumps(report, indent=2))
    _log(f"focus merged into {args.out} ({len(focus)} updated, {len(merged)} total)")
    return 0


def cmd_budget(_args) -> int:
    store = _store()
    _log(_ledger_text(store).rstrip())
    return 0


def _ledger_text(store: Store) -> str:
    lines = [
        f"{'stage':<24} {'model':<40} {'calls':>6} {'$':>8} {'avg_out':>8} "
        f"{'pass':>5} {'parse':>5} {'trunc':>5} {'err':>4}"
    ]
    for row in store.ledger():
        lines.append(
            f"{row['stage']:<24} {row['model_id']:<40} {row['n_calls']:>6} "
            f"{(row['micro'] or 0)/1e6:>8.2f} {row['avg_out'] or 0:>8.0f} "
            f"{row['n_pass'] or 0:>5} {row['n_parse'] or 0:>5} {row['n_trunc'] or 0:>5} {row['n_err'] or 0:>4}"
        )
    recorded = sum((row["micro"] or 0) for row in store.ledger()) / 1e6
    trusted_router = store.spent_microdollars() / 1e6
    lines += [
        "",
        f"RECORDED ALL SOURCES: ${recorded:.2f}",
        f"TRUSTEDROUTER-CAPPED LEDGER: ${trusted_router:.2f} of $300.00",
        "Unrecorded or deleted diagnostic calls are not included; see the field journal.",
    ]
    return "\n".join(lines) + "\n"


def cmd_fit(args) -> int:
    store = _store()
    sets = tuple(args.sets.split(","))
    stages = tuple(args.stages.split(",")) if args.stages else None
    obs = _collect_obs(store, args.model, args.family, sets, stages)
    if not obs:
        _log("no data")
        return 1
    res = fit_with_lapse_guard(obs)
    out = {
        "model": args.model, "family": args.family,
        "b": res.b, "a": res.a, "lapse": res.lapse, "x50": res.x50,
        "flags": res.flags, "n_instances": res.n_instances, "n_calls": res.n_calls,
    }
    if args.bootstrap:
        def stat(sample):
            r = fit_with_lapse_guard(sample, quick=True)
            return {"x50": r.x50, "a": r.a, "b": r.b, "lapse": r.lapse}

        boots = bootstrap.run(obs, stat, B=args.bootstrap, seed=71)
        for name in ("x50", "a", "b", "lapse"):
            if name in boots:
                lo, hi = bootstrap.percentile_ci(boots[name])
                out[f"{name}_ci"] = [round(lo, 4), round(hi, 4)]
    if args.gof:
        from .stats.decomp import frontier_icc

        icc = frontier_icc(obs)
        x2, p = gof_mc_pvalue(res, obs, icc, n_sims=500)
        out["gof_x2"], out["gof_p_mc"], out["icc_at_frontier"] = round(x2, 2), p, round(icc, 3)
    _log(json.dumps(out, indent=2, default=str))
    return 0


def cmd_sweep(args) -> int:
    """Ad-hoc sweep for outside users: one model, one grid, your budget."""
    models = config.load_models()
    grids = config.load_grids()
    if args.model not in models:
        _log(f"unknown model {args.model!r}; add it to configs/models.toml")
        return 2
    stage = config.StageCfg(
        name=args.stage, grid=args.grid, set_name=args.set_name,
        models=[args.model], n_instances=args.instances, k=args.k,
        cap_usd=args.cap, temperature=args.temperature,
        stream_telemetry=args.stream_telemetry,
    )
    store = _store()
    guard = BudgetGuard(store, {args.stage: args.cap})
    jobs = plan_jobs(stage, grids, models, store)
    _log(f"{len(jobs)} calls to run under ${args.cap:.2f} cap")
    if args.dry_run or not jobs:
        return 0
    client = TRClient(config.load_key())
    try:
        summary = asyncio.run(run_jobs(jobs, models, client, store, guard, log=_log))
    finally:
        asyncio.run(client.aclose())
    _log(json.dumps(summary, indent=2, default=str))
    return 0


def cmd_export(args) -> int:
    store = _store()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    import gzip
    import hashlib
    import shutil
    import sqlite3

    manifest = {}
    n = store.export_jsonl("instances", out_dir / "instances.jsonl.gz", "set_name != 'smoke'")
    manifest["instances.jsonl.gz"] = {"rows": n}
    n = store.export_jsonl(
        "calls", out_dir / "calls.jsonl.gz",
        "stage != 'smoke' AND instance_id IN (SELECT instance_id FROM instances WHERE set_name != 'smoke')",
    )
    manifest["calls.jsonl.gz"] = {"rows": n}
    n = store.export_jsonl("fits", out_dir / "fits.jsonl.gz")
    manifest["fits.jsonl.gz"] = {"rows": n}

    n = store.export_jsonl("stream_events", out_dir / "stream_events.jsonl.gz")
    manifest["stream_events.jsonl.gz"] = {"rows": n}

    snapshot = out_dir / ".drc.snapshot.sqlite"
    if snapshot.exists():
        snapshot.unlink()
    target = sqlite3.connect(snapshot)
    try:
        store.conn.backup(target)
    finally:
        target.close()
    with snapshot.open("rb") as src, (out_dir / "drc.sqlite.gz").open("wb") as raw:
        with gzip.GzipFile(filename="drc.sqlite", mode="wb", fileobj=raw, mtime=0) as dst:
            shutil.copyfileobj(src, dst)
    snapshot.unlink()
    (out_dir / "ledger.txt").write_text(_ledger_text(store))

    for path in sorted(out_dir.iterdir()):
        if not path.is_file() or path.name == "manifest.json" or path.name.startswith("."):
            continue
        entry = manifest.setdefault(path.name, {})
        if path.name.endswith(".jsonl.gz") and "rows" not in entry:
            with gzip.open(path, "rt", encoding="utf-8") as f:
                entry["rows"] = sum(1 for _ in f)
        entry["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        entry["bytes"] = path.stat().st_size
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    _log(json.dumps(manifest, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="drc", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("run-stage", help="run a stage from configs/stages.toml")
    p.add_argument("stage")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--stream-telemetry", action="store_true", help="capture opt-in SSE timing events")
    p.set_defaults(fn=cmd_run_stage)

    p = sub.add_parser("gate", help="post-stage checkpoint report + focus file")
    p.add_argument("--stages", required=True, help="comma-separated stage names to analyse")
    p.add_argument("--sets", default="pilot")
    p.add_argument("--grid", required=True, help="target grid for center mapping")
    p.add_argument("--out", required=True)
    p.set_defaults(fn=cmd_gate)

    p = sub.add_parser("budget", help="spend ledger")
    p.set_defaults(fn=cmd_budget)

    p = sub.add_parser("fit", help="fit the curve for one model")
    p.add_argument("--model", required=True)
    p.add_argument("--family", default="sat")
    p.add_argument("--sets", default="main")
    p.add_argument("--stages", default="")
    p.add_argument("--bootstrap", type=int, default=0, help="bootstrap replicates (0 = none)")
    p.add_argument("--gof", action="store_true")
    p.set_defaults(fn=cmd_fit)

    p = sub.add_parser("sweep", help="ad-hoc sweep: one model, one grid, capped spend")
    p.add_argument("--model", required=True)
    p.add_argument("--grid", default="sat-n20-main")
    p.add_argument("--instances", type=int, default=10)
    p.add_argument("--k", type=int, default=4)
    p.add_argument("--cap", type=float, default=5.0)
    p.add_argument("--set-name", default="adhoc")
    p.add_argument("--stage", default="adhoc")
    p.add_argument("--temperature", type=float, default=None)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--stream-telemetry", action="store_true", help="capture opt-in SSE timing events")
    p.set_defaults(fn=cmd_sweep)

    p = sub.add_parser("export", help="export JSONL.gz + sha256 manifest")
    p.add_argument("--out", default="data/exports")
    p.set_defaults(fn=cmd_export)

    from .adaptive.live import cmd_adaptive

    p = sub.add_parser("adaptive", help="C4: find the frontier adaptively, live")
    p.add_argument("--model", required=True)
    p.add_argument("--grid", default="sat-n20-main")
    p.add_argument("--a-prior", type=float, default=2.0, help="slope prior (pooled pilot)")
    p.add_argument("--lapse", type=float, default=0.03)
    p.add_argument("--eps", type=float, default=0.15, help="target SE(b)")
    p.add_argument("--max-calls", type=int, default=200)
    p.add_argument("--cap", type=float, default=3.0)
    p.add_argument("--seed", type=int, default=424242, help="master seed (fresh instances per replicate)")
    p.add_argument("--tag", default="", help="replicate tag (distinct stage + output file)")
    p.set_defaults(fn=cmd_adaptive)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
