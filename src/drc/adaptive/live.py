"""Run the C4 adaptive procedure for real against one model.

Sequential by design (each batch depends on the last), so it is slow in
wall-clock but tiny in calls. Instances are fresh (set adaptive-<slug>),
every call lands in the store under stage adaptive-<slug> like any other.
"""

from __future__ import annotations

import asyncio
import json

import numpy as np

from .. import config
from ..runner.budget import BudgetGuard
from ..runner.client import TRClient
from ..runner.scheduler import Job, run_jobs
from ..runner.store import Store
from ..runner.sweep import _gen
from ..stats.collect import collect_obs
from ..stats.twopl import x50_of
from .bisect import AdaptiveState, bracket_step, fit_b, next_level, se_b_bootstrap


async def run_live(
    model_id: str,
    grid_name: str = "sat-n20-main",
    a_prior_mu: float = float(np.log(2.0)),
    a_prior_sd: float = 0.5,
    lapse: float = 0.03,
    eps_target: float = 0.15,
    max_calls: int = 200,
    probe_instances: int = 4,
    batch_instances: int = 4,
    batch_k: int = 2,
    cap_usd: float = 3.0,
    master_seed: int = 424242,
    tag: str = "",
    log=print,
) -> dict:
    models = config.load_models()
    grids = config.load_grids()
    grid = grids[grid_name]
    levels = grid.levels
    slug = model_id.split("/")[-1][:24]
    stage_name = f"adaptive-{slug}-{tag}" if tag else f"adaptive-{slug}"
    store = Store(config.DATA_DIR / "drc.sqlite")
    guard = BudgetGuard(store, {stage_name: cap_usd})
    client = TRClient(config.load_key())
    stage_stub = config.StageCfg(
        name=stage_name, grid=grid_name, set_name=stage_name, models=[model_id],
        n_instances=10_000, k=1, cap_usd=cap_usd, master_seed=master_seed,
    )
    used_indices: dict[int, int] = {}  # level_idx -> next fresh instance index
    calls_used = 0
    history_log: list[dict] = []

    async def probe(level_idx: int, n_inst: int, k: int) -> None:
        nonlocal calls_used
        jobs = []
        for _ in range(n_inst):
            idx = used_indices.get(level_idx, 0)
            used_indices[level_idx] = idx + 1
            inst = _gen(grid, stage_stub, level_idx, idx)
            store.upsert_instance(inst)
            for s in range(k):
                jobs.append(Job(inst=inst, model_id=model_id, sample_idx=s, stage=stage_name))
        await run_jobs(jobs, models, client, store, guard, log=log)
        calls_used += len(jobs)

    def current_obs():
        return collect_obs(store, model_id, grid.family, (stage_name,), (stage_name,))

    try:
        # Phase 1: bracket
        lo, hi = 0, len(levels) - 1
        probes = 0
        while lo < hi and probes < 4 and calls_used < max_calls:
            mid = (lo + hi) // 2
            before = {o.instance_id: o for o in current_obs()}
            await probe(mid, probe_instances, 1)
            after = current_obs()
            fresh = [o for o in after if o.instance_id not in before and o.level_idx == mid]
            rate = float(np.mean([o.y / o.k for o in fresh])) if fresh else 0.0
            lo, hi = bracket_step(rate, lo, hi, mid)
            probes += 1
            history_log.append({"phase": 1, "level": mid, "rate": rate, "calls": calls_used})
            log(f"[adaptive] probe level {mid} (alpha={levels[mid]}): pass {rate:.2f} -> bracket [{lo},{hi}]")

        # Phase 2: refine
        se = float("inf")
        while calls_used < max_calls:
            obs = current_obs()
            state = AdaptiveState(history=obs)
            li = next_level(state, levels, a_prior_mu, a_prior_sd, lapse)
            await probe(li, batch_instances, batch_k)
            obs = current_obs()
            se = se_b_bootstrap(obs, a_prior_mu, a_prior_sd, lapse, levels[0], levels[-1], B=150)
            b, a = fit_b(obs, a_prior_mu, a_prior_sd, lapse, levels[0], levels[-1])
            history_log.append({"phase": 2, "level": li, "b": b, "se": se, "calls": calls_used})
            log(f"[adaptive] batch at level {li}: b={b:.3f} se={se:.3f} calls={calls_used}")
            if np.isfinite(se) and se <= eps_target:
                break
        obs = current_obs()
        b, a = fit_b(obs, a_prior_mu, a_prior_sd, lapse, levels[0], levels[-1])
        x50 = x50_of(b, a, lapse)
        spent = store.spent_microdollars(stage_name) / 1e6
        return {
            "model": model_id, "stage": stage_name, "b": b, "a": a, "x50": x50,
            "se_b": se, "calls_used": calls_used, "spent_usd": round(spent, 4),
            "history": history_log,
        }
    finally:
        await client.aclose()


def cmd_adaptive(args) -> int:
    result = asyncio.run(
        run_live(
            args.model,
            grid_name=args.grid,
            a_prior_mu=float(np.log(args.a_prior)),
            lapse=args.lapse,
            eps_target=args.eps,
            max_calls=args.max_calls,
            cap_usd=args.cap,
            master_seed=args.seed,
            tag=args.tag,
        )
    )
    suffix = f"-{args.tag}" if args.tag else ""
    out = config.DATA_DIR / f"adaptive-{args.model.split('/')[-1]}{suffix}.json"
    out.write_text(json.dumps(result, indent=2, default=str))
    print(json.dumps({k: v for k, v in result.items() if k != "history"}, indent=2, default=str))
    print(f"written to {out}")
    return 0
