"""Shared instance representation and deterministic seed streams.

Task modules (sat, dag) are pure: no I/O, no network. Everything an
instance needs to be re-scored later lives in the Instance record.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from typing import Any

TASK_VERSION = 1
CANARY = "[canary: drc-eval-2026-c9d1e4a7-do-not-train]"


def seed_for(master_seed: int, family: str, set_name: str, level_idx: int, index: int) -> int:
    """Named seed stream: independent instances across sets by construction."""
    key = f"{master_seed}|{family}|{set_name}|{level_idx}|{index}".encode()
    # 63 bits: stays within SQLite's signed INTEGER range
    return int.from_bytes(hashlib.sha256(key).digest()[:8], "big") >> 1


def instance_id_for(family: str, set_name: str, level_idx: int, index: int, master_seed: int) -> str:
    key = f"{family}|{TASK_VERSION}|{level_idx}|{set_name}|{index}|{master_seed}".encode()
    return hashlib.sha256(key).hexdigest()[:16]


@dataclass
class Instance:
    instance_id: str
    family: str  # "sat" | "dag"
    task_version: int
    set_name: str  # "pilot" | "main" | "retest" | "adaptive-*" | "temp" | "n50"
    level_idx: int
    level_value: float
    params: dict[str, Any]
    payload: dict[str, Any]
    witness: Any
    seed: int
    rejection_count: int = 0
    solver_used: str = ""
    gen_ms: float = 0.0

    def to_row(self) -> dict[str, Any]:
        d = asdict(self)
        d["params_json"] = json.dumps(d.pop("params"), sort_keys=True)
        d["payload_json"] = json.dumps(d.pop("payload"), sort_keys=True)
        d["witness_json"] = json.dumps(d.pop("witness"), sort_keys=True)
        return d

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "Instance":
        return cls(
            instance_id=row["instance_id"],
            family=row["family"],
            task_version=row["task_version"],
            set_name=row["set_name"],
            level_idx=row["level_idx"],
            level_value=row["level_value"],
            params=json.loads(row["params_json"]),
            payload=json.loads(row["payload_json"]),
            witness=json.loads(row["witness_json"]),
            seed=row["seed"],
            rejection_count=row.get("rejection_count", 0),
            solver_used=row.get("solver_used", ""),
            gen_ms=row.get("gen_ms", 0.0),
        )
