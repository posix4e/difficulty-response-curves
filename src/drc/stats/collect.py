"""Build per-instance observations from the store, for fitting and analysis."""

from __future__ import annotations

import numpy as np

from ..runner.store import Store
from .twopl import InstanceObs


def collect_obs(
    store: Store,
    model_id: str,
    family: str,
    sets: tuple[str, ...],
    stages: tuple[str, ...] | None = None,
) -> list[InstanceObs]:
    rows = store.outcomes(model_id, family, sets, stages)
    by_inst: dict[str, dict] = {}
    for r in rows:
        d = by_inst.setdefault(
            r["instance_id"],
            {"level_idx": r["level_idx"], "x": r["level_value"], "k": 0, "y": 0, "logtok": []},
        )
        d["k"] += 1
        d["y"] += r["pass"]
        if r["completion_tokens"]:
            d["logtok"].append(np.log(r["completion_tokens"]))
    return [
        InstanceObs(
            iid, d["level_idx"], d["x"], d["k"], d["y"],
            float(np.mean(d["logtok"])) if d["logtok"] else float("nan"),
        )
        for iid, d in by_inst.items()
    ]


def outcome_rates(store: Store, model_id: str, family: str, sets: tuple[str, ...]) -> dict[str, float]:
    q = """SELECT COUNT(*) AS n,
                  SUM(outcome='fail_parse') * 1.0 / COUNT(*) AS parse,
                  SUM(outcome='fail_truncated') * 1.0 / COUNT(*) AS trunc,
                  SUM(outcome='fail_refusal') * 1.0 / COUNT(*) AS refusal,
                  SUM(outcome='fail_empty') * 1.0 / COUNT(*) AS empty,
                  SUM(provider_mismatch) * 1.0 / COUNT(*) AS mismatch
           FROM calls c JOIN instances i USING(instance_id)
           WHERE c.model_id=? AND i.family=? AND c.outcome != 'error_api'
             AND i.set_name IN (%s)""" % ",".join("?" * len(sets))
    row = store.conn.execute(q, (model_id, family, *sets)).fetchone()
    return {k: (row[k] or 0.0) for k in ("n", "parse", "trunc", "refusal", "empty", "mismatch")}
