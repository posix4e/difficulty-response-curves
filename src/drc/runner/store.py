"""SQLite store: single source of truth for instances, calls, fits.

The idempotency key on calls -- (model_id, instance_id, sample_idx,
prompt_version, stage) -- makes every sweep rerunnable: completed rows
are skipped, error_api rows are deleted and retried.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from ..tasks.base import Instance

SCHEMA = """
CREATE TABLE IF NOT EXISTS instances (
  instance_id TEXT PRIMARY KEY,
  family TEXT NOT NULL,
  task_version INTEGER NOT NULL,
  set_name TEXT NOT NULL,
  level_idx INTEGER NOT NULL,
  level_value REAL NOT NULL,
  params_json TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  witness_json TEXT NOT NULL,
  seed INTEGER NOT NULL,
  rejection_count INTEGER NOT NULL DEFAULT 0,
  solver_used TEXT NOT NULL DEFAULT '',
  gen_ms REAL NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS calls (
  call_id INTEGER PRIMARY KEY AUTOINCREMENT,
  instance_id TEXT NOT NULL REFERENCES instances(instance_id),
  model_id TEXT NOT NULL,
  sample_idx INTEGER NOT NULL,
  stage TEXT NOT NULL,
  api_path TEXT NOT NULL,
  prompt_version INTEGER NOT NULL,
  prompt_sha256 TEXT,
  request_json TEXT,
  response_text TEXT,
  finish_reason TEXT,
  parsed_answer TEXT,
  outcome TEXT NOT NULL,
  pass INTEGER NOT NULL,
  prompt_tokens INTEGER,
  completion_tokens INTEGER,
  reasoning_tokens INTEGER,
  cost_microdollars INTEGER NOT NULL DEFAULT 0,
  cost_source TEXT NOT NULL DEFAULT 'api',
  provider_endpoint TEXT,
  provider_pinned INTEGER NOT NULL DEFAULT 0,
  provider_mismatch INTEGER NOT NULL DEFAULT 0,
  http_status INTEGER,
  attempt INTEGER NOT NULL DEFAULT 1,
  latency_ms REAL,
  ttft_ms REAL,
  first_reasoning_ms REAL,
  first_answer_ms REAL,
  stream_duration_ms REAL,
  observed_chars INTEGER,
  ts_start TEXT,
  ts_end TEXT,
  UNIQUE(model_id, instance_id, sample_idx, prompt_version, stage)
);
CREATE INDEX IF NOT EXISTS idx_calls_model_stage ON calls(model_id, stage);
CREATE INDEX IF NOT EXISTS idx_calls_instance ON calls(instance_id);
CREATE TABLE IF NOT EXISTS stream_events (
  call_id INTEGER NOT NULL REFERENCES calls(call_id),
  seq INTEGER NOT NULL,
  elapsed_ms REAL NOT NULL,
  channel TEXT NOT NULL,
  char_count INTEGER NOT NULL,
  PRIMARY KEY(call_id, seq)
);
CREATE TABLE IF NOT EXISTS fits (
  fit_id INTEGER PRIMARY KEY AUTOINCREMENT,
  model_id TEXT NOT NULL,
  family TEXT NOT NULL,
  stage TEXT NOT NULL,
  filter_json TEXT NOT NULL DEFAULT '{}',
  b REAL, a REAL, lapse REAL, x50 REAL,
  ci_json TEXT,
  loglik REAL, deviance REAL, gof_x2 REAL, gof_p_mc REAL,
  n_calls INTEGER, n_instances INTEGER,
  flags_json TEXT NOT NULL DEFAULT '[]',
  code_git_sha TEXT,
  boot_seed INTEGER,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(SCHEMA)
        self._migrate_calls()
        self.conn.commit()

    def _migrate_calls(self) -> None:
        """Add opt-in telemetry columns to stores created before protocol v1."""
        existing = {row[1] for row in self.conn.execute("PRAGMA table_info(calls)")}
        additions = {
            "ttft_ms": "REAL",
            "first_reasoning_ms": "REAL",
            "first_answer_ms": "REAL",
            "stream_duration_ms": "REAL",
            "observed_chars": "INTEGER",
        }
        for name, sql_type in additions.items():
            if name not in existing:
                self.conn.execute(f"ALTER TABLE calls ADD COLUMN {name} {sql_type}")

    def close(self) -> None:
        self.conn.close()

    # -- instances ---------------------------------------------------------

    def upsert_instance(self, inst: Instance) -> None:
        row = inst.to_row()
        with self._lock:
            self.conn.execute(
                """INSERT OR IGNORE INTO instances
                   (instance_id, family, task_version, set_name, level_idx, level_value,
                    params_json, payload_json, witness_json, seed, rejection_count,
                    solver_used, gen_ms)
                   VALUES (:instance_id, :family, :task_version, :set_name, :level_idx,
                    :level_value, :params_json, :payload_json, :witness_json, :seed,
                    :rejection_count, :solver_used, :gen_ms)""",
                row,
            )
            self.conn.commit()

    def get_instance(self, instance_id: str) -> Instance | None:
        cur = self.conn.execute("SELECT * FROM instances WHERE instance_id=?", (instance_id,))
        row = cur.fetchone()
        return Instance.from_row(dict(row)) if row else None

    def instances_for(self, family: str, set_name: str) -> list[Instance]:
        cur = self.conn.execute(
            "SELECT * FROM instances WHERE family=? AND set_name=? ORDER BY level_idx, instance_id",
            (family, set_name),
        )
        return [Instance.from_row(dict(r)) for r in cur.fetchall()]

    # -- calls --------------------------------------------------------------

    def existing_keys(self, stage: str) -> set[tuple[str, str, int]]:
        """Terminal (model_id, instance_id, sample_idx) for a stage.
        error_api rows are not terminal: they are deleted here so the
        caller re-enqueues them."""
        with self._lock:
            self.conn.execute("DELETE FROM calls WHERE stage=? AND outcome='error_api'", (stage,))
            self.conn.commit()
        cur = self.conn.execute(
            "SELECT model_id, instance_id, sample_idx FROM calls WHERE stage=?", (stage,)
        )
        return {(r[0], r[1], r[2]) for r in cur.fetchall()}

    def record_call(self, row: dict[str, Any]) -> int:
        cols = ",".join(row)
        placeholders = ",".join(":" + c for c in row)
        with self._lock:
            self.conn.execute(
                f"INSERT OR IGNORE INTO calls ({cols}) VALUES ({placeholders})", row
            )
            self.conn.commit()
            found = self.conn.execute(
                """SELECT call_id FROM calls WHERE model_id=? AND instance_id=?
                   AND sample_idx=? AND prompt_version=? AND stage=?""",
                (row["model_id"], row["instance_id"], row["sample_idx"], row["prompt_version"], row["stage"]),
            ).fetchone()
            if found is None:
                raise RuntimeError("recorded call could not be resolved")
            return int(found[0])

    def record_stream_events(self, call_id: int, events: list[dict[str, Any]]) -> None:
        if not events:
            return
        rows = [dict(event, call_id=call_id) for event in events]
        with self._lock:
            self.conn.executemany(
                """INSERT OR REPLACE INTO stream_events
                   (call_id, seq, elapsed_ms, channel, char_count)
                   VALUES (:call_id, :seq, :elapsed_ms, :channel, :char_count)""",
                rows,
            )
            self.conn.commit()

    def outcome_counts(self, stage: str, model_id: str) -> dict[str, int]:
        row = self.conn.execute(
            """SELECT SUM(outcome='pass'), SUM(outcome='fail_wrong'), COUNT(*)
               FROM calls WHERE stage=? AND model_id=? AND outcome != 'error_api'""",
            (stage, model_id),
        ).fetchone()
        return {"correct": int(row[0] or 0), "silent_wrong": int(row[1] or 0), "recorded": int(row[2] or 0)}

    def spent_microdollars(self, stage: str | None = None) -> int:
        if stage:
            q = "SELECT COALESCE(SUM(cost_microdollars),0) FROM calls WHERE stage=?"
            return int(self.conn.execute(q, (stage,)).fetchone()[0])
        # global ledger tracks the TrustedRouter $300 promise; other-gateway
        # spend (cost_source='openrouter') has its own budget and stage caps
        q = "SELECT COALESCE(SUM(cost_microdollars),0) FROM calls WHERE cost_source != 'openrouter'"
        return int(self.conn.execute(q).fetchone()[0])

    def recent_model_costs(self, model_id: str, limit: int = 500) -> list[int]:
        """Return persisted costs for reserve seeding, newest first."""
        rows = self.conn.execute(
            """SELECT cost_microdollars FROM calls
               WHERE model_id=? AND cost_microdollars > 0
               ORDER BY call_id DESC LIMIT ?""",
            (model_id, limit),
        ).fetchall()
        return [int(row[0]) for row in rows]

    def ledger(self) -> list[dict[str, Any]]:
        cur = self.conn.execute(
            """SELECT stage, model_id, COUNT(*) AS n_calls,
                      SUM(cost_microdollars) AS micro,
                      AVG(completion_tokens) AS avg_out,
                      SUM(pass) AS n_pass,
                      SUM(outcome='fail_parse') AS n_parse,
                      SUM(outcome='fail_truncated') AS n_trunc,
                      SUM(outcome='error_api') AS n_err
               FROM calls GROUP BY stage, model_id ORDER BY stage, model_id"""
        )
        return [dict(r) for r in cur.fetchall()]

    def outcomes(
        self, model_id: str, family: str, set_names: tuple[str, ...], stages: tuple[str, ...] | None = None
    ) -> list[dict[str, Any]]:
        """Per-call rows joined with level info, for fitting."""
        q = """SELECT c.instance_id, i.level_idx, i.level_value, c.sample_idx, c.pass,
                      c.outcome, c.completion_tokens, c.reasoning_tokens, c.stage
               FROM calls c JOIN instances i ON i.instance_id = c.instance_id
               WHERE c.model_id=? AND i.family=? AND c.outcome != 'error_api'
                 AND i.set_name IN (%s)""" % ",".join("?" * len(set_names))
        args: list[Any] = [model_id, family, *set_names]
        if stages:
            q += " AND c.stage IN (%s)" % ",".join("?" * len(stages))
            args += list(stages)
        cur = self.conn.execute(q, args)
        return [dict(r) for r in cur.fetchall()]

    def record_fit(self, row: dict[str, Any]) -> None:
        cols = ",".join(row)
        placeholders = ",".join(":" + c for c in row)
        with self._lock:
            self.conn.execute(f"INSERT INTO fits ({cols}) VALUES ({placeholders})", row)
            self.conn.commit()

    # -- export --------------------------------------------------------------

    def export_jsonl(self, table: str, out_path: Path, where: str = "", args: tuple = ()) -> int:
        q = f"SELECT * FROM {table}"
        if where:
            q += f" WHERE {where}"
        import gzip
        import io

        n = 0
        with out_path.open("wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
                with io.TextIOWrapper(compressed, encoding="utf-8") as f:
                    for row in self.conn.execute(q, args):
                        f.write(json.dumps(dict(row), default=str) + "\n")
                        n += 1
        return n
