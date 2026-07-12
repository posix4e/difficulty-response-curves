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
import shlex
import subprocess
import sys
from pathlib import Path

import numpy as np

from . import config
from .runner.budget import BudgetGuard
from .runner.client import TRClient
from .runner.council_experiment import Arm, FourArmExperiment, write_experiment_result
from .runner.scheduler import Job, run_jobs
from .runner.speculative import (
    CandidateResult,
    HandoffContext,
    ModelCandidate,
    SpeculativeCouncil,
    TraceRiskPolicy,
    accept_first_complete,
    regex_verifier,
)
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


async def _run_stage_async(jobs, models, store, guard):
    """Keep the HTTP client and its shutdown on one event loop."""
    client = TRClient(config.load_key())
    try:
        return await run_jobs(jobs, models, client, store, guard, log=_log)
    finally:
        await client.aclose()


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
    summary = asyncio.run(_run_stage_async(jobs, models, store, guard))
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


def _hedge_authorized_max(models, ids: list[str], prompt: str) -> float:
    input_tokens = max(1, len(prompt) // 4)
    return sum(
        models[model_id].pricetable_microdollars(
            input_tokens, models[model_id].max_completion_tokens
        )
        for model_id in ids
    ) / 1_000_000


async def _command_verifier(command: str, result: CandidateResult) -> bool:
    argv = shlex.split(command)
    if not argv:
        return False
    process = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await process.communicate((result.text or "").encode())
    return process.returncode == 0


def _handoff_from_args(args) -> HandoffContext:
    prompt = Path(args.prompt_file).read_text() if args.prompt_file else args.prompt
    context_payload = {}
    if args.context_json:
        context_payload = json.loads(Path(args.context_json).read_text())
    return HandoffContext(
        prompt=prompt,
        messages=tuple(context_payload.get("messages", ())),
        tool_results=tuple(context_payload.get("tool_results", ())),
        files_read=tuple(context_payload.get("files_read", ())),
        workspace_revision=str(context_payload.get("workspace_revision", "")),
        metadata=dict(context_payload.get("metadata", {})),
    )


def _verifier_from_args(args):
    if args.verify_command:
        async def verifier(result):
            return await _command_verifier(args.verify_command, result)
        return verifier
    if args.accept_regex:
        return regex_verifier(args.accept_regex)
    return accept_first_complete


def _judge_for(client, cfg, temperature):
    judge = ModelCandidate(client, cfg, temperature)

    async def council_judge(base_context, results):
        candidates = "\n\n".join(
            f"## {item.model}\n{item.text or '[no answer]'}" for item in results
        )
        judge_context = HandoffContext(
            prompt=(
                base_context.render()
                + "\n\nYou are the council judge. Produce one independently checkable "
                "answer from the candidate reports below. Do not vote by model name.\n\n"
                + candidates
            ),
            metadata={"role": "council_judge"},
        )
        return await judge.run(judge_context)

    return council_judge


async def _run_hedge_async(args, models, context: HandoffContext) -> dict:
    client = TRClient(config.load_key())
    try:
        primary = ModelCandidate(client, models[args.primary], args.temperature)
        challengers = [
            ModelCandidate(client, models[model_id], args.temperature)
            for model_id in args.challenger
        ]
        verifier = _verifier_from_args(args)

        async def pause(_context, snapshot):
            _log(
                f"[hedge] trace risk {snapshot.score:.2f}; side effects paused; "
                f"launching {len(challengers)} challengers"
            )

        council_judge = None
        if args.judge_model:
            council_judge = _judge_for(
                client, models[args.judge_model], args.temperature
            )

        policy = TraceRiskPolicy(
            threshold=args.risk_threshold,
            persistence=args.risk_persistence,
            min_words=args.risk_min_words,
            window_words=args.risk_window_words,
        )
        result = await SpeculativeCouncil(
            primary,
            challengers,
            policy=policy,
            verifier=verifier,
            pause_side_effects=pause,
            council_judge=council_judge,
        ).run(context)
        return result.as_dict()
    finally:
        await client.aclose()


def cmd_hedge(args) -> int:
    models = config.load_models()
    if not args.challenger:
        args.challenger = ["or/grok-4-fast", "or/gpt-5.5"]
    ids = [args.primary, *args.challenger]
    if args.judge_model:
        ids.append(args.judge_model)
    missing = [model_id for model_id in ids if model_id not in models]
    if missing:
        _log(f"unknown models: {', '.join(missing)}")
        return 2
    if any(models[model_id].api_path != "openai" for model_id in ids):
        _log("hedge currently requires OpenAI-compatible streaming models")
        return 2
    if not (args.verify_command or args.accept_regex or args.accept_first):
        _log("refusing first-answer-wins: provide --verify-command, --accept-regex, or explicit --accept-first")
        return 2

    context = _handoff_from_args(args)
    authorized = _hedge_authorized_max(models, ids, context.render())
    plan = {
        "primary": args.primary,
        "challengers": args.challenger,
        "judge_model": args.judge_model or None,
        "risk": {
            "threshold": args.risk_threshold,
            "persistence": args.risk_persistence,
            "min_words": args.risk_min_words,
            "window_words": args.risk_window_words,
        },
        "authorized_worst_case_usd": round(authorized, 6),
        "cap_usd": args.cap,
    }
    if authorized > args.cap:
        _log(json.dumps(plan, indent=2))
        _log("worst-case candidate authorization exceeds --cap; no calls launched")
        return 2
    if args.dry_run:
        _log(json.dumps(plan, indent=2))
        return 0
    result = asyncio.run(_run_hedge_async(args, models, context))
    result["plan"] = plan
    payload = json.dumps(result, indent=2, default=str) + "\n"
    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload)
    _log(payload.rstrip())
    return 0 if result.get("winner") else 1


async def _run_council_experiment_async(args, models, context, arms, plan):
    client = TRClient(config.load_key())
    try:
        verifier = _verifier_from_args(args)
        judge = _judge_for(client, models[args.judge_model], args.temperature)

        async def pause(_context, snapshot):
            reason = f"trace score {snapshot.score:.2f}" if snapshot else "timer or primary rejection"
            _log(f"[experiment] side effects paused: {reason}")

        experiment = FourArmExperiment(
            runner_factory=lambda model_id: ModelCandidate(
                client, models[model_id], args.temperature
            ),
            primary_model=args.primary,
            challenger_models=args.challenger,
            judge=judge,
            verifier=verifier,
            policy_factory=lambda: TraceRiskPolicy(
                threshold=args.risk_threshold,
                persistence=args.risk_persistence,
                min_words=args.risk_min_words,
                window_words=args.risk_window_words,
            ),
            fixed_delay_ms=args.fixed_delay_ms,
            pause_side_effects=pause,
        )
        return await experiment.run(
            context,
            task_id=args.task_id,
            seed=args.seed,
            arms=arms,
            plan=plan,
        )
    finally:
        await client.aclose()


def cmd_council_experiment(args) -> int:
    models = config.load_models()
    if not args.challenger:
        args.challenger = ["or/grok-4-fast", "or/gpt-5.5"]
    ids = [args.primary, *args.challenger, args.judge_model]
    missing = [model_id for model_id in ids if model_id not in models]
    if missing:
        _log(f"unknown models: {', '.join(missing)}")
        return 2
    if not (args.verify_command or args.accept_regex):
        _log("the registered experiment requires --verify-command or --accept-regex")
        return 2
    if any(models[model_id].api_path != "openai" for model_id in ids):
        _log("council experiment currently requires OpenAI-compatible streaming models")
        return 2

    try:
        arms = [Arm(value) for value in args.arm] if args.arm else list(Arm)
    except ValueError as exc:
        _log(str(exc))
        return 2
    context = _handoff_from_args(args)
    primary_cost = _hedge_authorized_max(models, [args.primary], context.render())
    full_cost = _hedge_authorized_max(models, ids, context.render())
    authorized = sum(
        primary_cost if arm is Arm.PRIMARY_ONLY else full_cost for arm in arms
    )
    plan = {
        "primary": args.primary,
        "challengers": args.challenger,
        "judge_model": args.judge_model,
        "arms": [arm.value for arm in arms],
        "fixed_delay_ms": args.fixed_delay_ms,
        "risk": {
            "threshold": args.risk_threshold,
            "persistence": args.risk_persistence,
            "min_words": args.risk_min_words,
            "window_words": args.risk_window_words,
        },
        "authorized_worst_case_usd": round(authorized, 6),
        "cap_usd": args.cap,
    }
    if authorized > args.cap:
        _log(json.dumps(plan, indent=2))
        _log("worst-case four-arm authorization exceeds --cap; no calls launched")
        return 2
    if args.dry_run:
        _log(json.dumps(plan, indent=2))
        return 0
    result = asyncio.run(
        _run_council_experiment_async(args, models, context, arms, plan)
    )
    output = Path(args.out)
    write_experiment_result(output, result)
    _log(json.dumps(result.as_dict(), indent=2))
    return 0 if all(arm.verified for arm in result.arms) else 1


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

    p = sub.add_parser("hedge", help="trace-triggered speculative model race")
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument("--prompt")
    source.add_argument("--prompt-file")
    p.add_argument("--context-json", help="structured handoff metadata copied to every candidate")
    p.add_argument("--primary", default="or/glm-5")
    p.add_argument("--challenger", action="append", default=[])
    p.add_argument("--judge-model", default="", help="optional council fallback after all candidates fail verification")
    verify = p.add_mutually_exclusive_group()
    verify.add_argument("--verify-command", help="command reads candidate answer on stdin; exit 0 accepts")
    verify.add_argument("--accept-regex", help="accept only answers matching this expression")
    verify.add_argument("--accept-first", action="store_true", help="unsafe latency-only mode")
    p.add_argument("--risk-threshold", type=float, default=4.0)
    p.add_argument("--risk-persistence", type=int, default=2)
    p.add_argument("--risk-min-words", type=int, default=80)
    p.add_argument("--risk-window-words", type=int, default=320)
    p.add_argument("--temperature", type=float, default=None)
    p.add_argument("--cap", type=float, default=5.0)
    p.add_argument("--out", default="")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_hedge)

    p = sub.add_parser("council-experiment", help="run the registered four-arm council comparison")
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument("--prompt")
    source.add_argument("--prompt-file")
    p.add_argument("--context-json")
    p.add_argument("--task-id", required=True)
    p.add_argument("--primary", default="or/glm-5")
    p.add_argument("--challenger", action="append", default=[])
    p.add_argument("--judge-model", default="or/gpt-5.5")
    verify = p.add_mutually_exclusive_group()
    verify.add_argument("--verify-command")
    verify.add_argument("--accept-regex")
    p.add_argument("--arm", action="append", choices=[arm.value for arm in Arm], default=[])
    p.add_argument("--fixed-delay-ms", type=float, default=30_000)
    p.add_argument("--risk-threshold", type=float, default=4.0)
    p.add_argument("--risk-persistence", type=int, default=2)
    p.add_argument("--risk-min-words", type=int, default=80)
    p.add_argument("--risk-window-words", type=int, default=320)
    p.add_argument("--temperature", type=float, default=None)
    p.add_argument("--seed", type=int, default=20260712)
    p.add_argument("--cap", type=float, default=20.0)
    p.add_argument("--out", default="data/hedge/experiment.json")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_council_experiment)

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
