"""Turn a stage config into a concrete, resumable job list.

Instance generation is deterministic in (set_name, level_idx, index,
master_seed), so backbone and top-up stages that share a set name hit
the same instances, and a rerun of any stage regenerates identical jobs
and skips the ones already answered.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..config import GridCfg, ModelCfg, StageCfg
from ..tasks import code, dag, sat, synth
from ..tasks.base import Instance
from .scheduler import Job
from .store import Store


def plan_jobs(
    stage: StageCfg,
    grids: dict[str, GridCfg],
    models: dict[str, ModelCfg],
    store: Store,
) -> list[Job]:
    grid = grids[stage.grid]
    focus: dict[str, int] = {}
    if stage.focus_from:
        raw = json.loads(Path(stage.focus_from).read_text())
        focus = {m: int(v["center_level_idx"]) for m, v in raw.items()}

    # per (model, level_idx) -> number of samples this stage contributes
    def k_for(model_id: str, level_idx: int) -> int:
        if not stage.focus_from:
            return stage.k
        if model_id not in focus:
            return 0
        center = focus[model_id]
        k = 0
        if stage.window_width < 0 or abs(level_idx - center) <= stage.window_width:
            k += stage.k
        if stage.focus_k and abs(level_idx - center) <= stage.focus_width:
            k += stage.focus_k
        if stage.c2_k and level_idx == center:
            k += stage.c2_k
        return k

    # which (level_idx, index) instances are needed at all
    needed_levels = sorted(
        {
            li
            for li in range(len(grid.levels))
            for m in stage.models
            if k_for(m, li) > 0
        }
    )
    instances: dict[tuple[int, int], Instance] = {}
    for li in needed_levels:
        for idx in range(stage.n_instances):
            inst = _gen(grid, stage, li, idx)
            store.upsert_instance(inst)
            instances[(li, idx)] = inst

    existing = store.existing_keys(stage.name)
    jobs: list[Job] = []
    for model_id in stage.models:
        for li in needed_levels:
            k = k_for(model_id, li)
            for idx in range(stage.n_instances):
                inst = instances[(li, idx)]
                for s in range(k):
                    if (model_id, inst.instance_id, s) in existing:
                        continue
                    jobs.append(
                        Job(
                            inst=inst,
                            model_id=model_id,
                            sample_idx=s,
                            stage=stage.name,
                            temperature=stage.temperature,
                        )
                    )
    return jobs


def _gen(grid: GridCfg, stage: StageCfg, level_idx: int, index: int) -> Instance:
    if grid.family == "sat":
        return sat.gen_instance(
            n_vars=grid.n_vars,
            alpha=grid.levels[level_idx],
            master_seed=stage.master_seed,
            set_name=stage.set_name,
            level_idx=level_idx,
            index=index,
        )
    if grid.family == "dag":
        return dag.gen_instance(
            n_ops=int(grid.levels[level_idx]),
            master_seed=stage.master_seed,
            set_name=stage.set_name,
            level_idx=level_idx,
            index=index,
        )
    if grid.family == "code":
        return code.gen_instance(
            n_rules=int(grid.levels[level_idx]),
            master_seed=stage.master_seed,
            set_name=stage.set_name,
            level_idx=level_idx,
            index=index,
        )
    if grid.family == "synth":
        return synth.gen_instance(
            n_rules=int(grid.levels[level_idx]),
            master_seed=stage.master_seed,
            set_name=stage.set_name,
            level_idx=level_idx,
            index=index,
        )
    raise ValueError(f"unknown family {grid.family}")
