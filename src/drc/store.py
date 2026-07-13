from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import threading
from typing import Any, Iterable

from .types import Instance, StreamEvent, StudyStatus


SCHEMA = """
CREATE TABLE IF NOT EXISTS instances (
  instance_id TEXT PRIMARY KEY,
  family TEXT NOT NULL DEFAULT 'sat',
  task_version INTEGER NOT NULL DEFAULT 2,
  set_name TEXT NOT NULL,
  level_idx INTEGER NOT NULL DEFAULT 0,
  level_value REAL NOT NULL,
  params_json TEXT NOT NULL DEFAULT '{}',
  payload_json TEXT NOT NULL,
  witness_json TEXT NOT NULL,
  seed INTEGER NOT NULL,
  rejection_count INTEGER NOT NULL DEFAULT 0,
  solver_used TEXT NOT NULL DEFAULT 'drc-v2-dpll',
  gen_ms REAL NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS calls (
  call_id INTEGER PRIMARY KEY AUTOINCREMENT,
  instance_id TEXT NOT NULL REFERENCES instances(instance_id),
  model_id TEXT NOT NULL,
  sample_idx INTEGER NOT NULL,
  stage TEXT NOT NULL,
  api_path TEXT NOT NULL DEFAULT 'openai',
  prompt_version INTEGER NOT NULL,
  prompt_sha256 TEXT,
  request_json TEXT NOT NULL,
  response_text TEXT,
  reasoning_text TEXT,
  error_text TEXT,
  raw_response_text TEXT,
  generation_id TEXT,
  finish_reason TEXT,
  parsed_answer TEXT,
  outcome TEXT NOT NULL,
  pass INTEGER NOT NULL,
  prompt_tokens INTEGER,
  completion_tokens INTEGER,
  reasoning_tokens INTEGER,
  cost_microdollars INTEGER NOT NULL DEFAULT 0,
  cost_source TEXT NOT NULL DEFAULT 'provider',
  provider_endpoint TEXT,
  provider_pinned INTEGER NOT NULL DEFAULT 1,
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
CREATE INDEX IF NOT EXISTS idx_calls_stage ON calls(stage, model_id);
CREATE INDEX IF NOT EXISTS idx_calls_instance ON calls(instance_id);
CREATE TABLE IF NOT EXISTS stream_events (
  call_id INTEGER NOT NULL REFERENCES calls(call_id),
  seq INTEGER NOT NULL,
  elapsed_ms REAL NOT NULL,
  channel TEXT NOT NULL,
  char_count INTEGER NOT NULL,
  PRIMARY KEY(call_id, seq)
);
"""


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.executescript(SCHEMA)
        columns = {
            str(row[1]) for row in self.connection.execute("PRAGMA table_info(calls)")
        }
        migrations = {
            "reasoning_text": "TEXT",
            "error_text": "TEXT",
            "raw_response_text": "TEXT",
            "generation_id": "TEXT",
        }
        for name, declaration in migrations.items():
            if name not in columns:
                self.connection.execute(
                    f"ALTER TABLE calls ADD COLUMN {name} {declaration}"
                )
        self.connection.commit()
        self._lock = threading.Lock()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self.connection.close()

    def add_instance(self, instance: Instance, study: str, level_index: int) -> None:
        payload = {
            "prompt": instance.prompt,
            "clauses": [list(clause) for clause in instance.clauses],
        }
        with self._lock:
            self.connection.execute(
                """INSERT OR IGNORE INTO instances
                (instance_id, set_name, level_idx, level_value, params_json,
                 payload_json, witness_json, seed)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    instance.instance_id,
                    study,
                    level_index,
                    instance.difficulty,
                    json.dumps({"variables": len(instance.witness)}, sort_keys=True),
                    json.dumps(payload, sort_keys=True),
                    json.dumps(list(instance.witness)),
                    instance.seed,
                ),
            )
            self.connection.commit()

    def completed_keys(self, study: str, model_id: str) -> set[tuple[str, int]]:
        rows = self.connection.execute(
            """SELECT instance_id, sample_idx FROM calls
               WHERE stage=? AND model_id=?""",
            (study, model_id),
        )
        return {(str(row[0]), int(row[1])) for row in rows}

    def record_call(self, row: dict[str, Any]) -> int:
        columns = tuple(row)
        sql = (
            f"INSERT OR REPLACE INTO calls ({','.join(columns)}) "
            f"VALUES ({','.join('?' for _ in columns)})"
        )
        with self._lock:
            cursor = self.connection.execute(sql, tuple(row[column] for column in columns))
            self.connection.commit()
            return int(cursor.lastrowid)

    def record_stream_events(
        self, call_id: int, events: Iterable[StreamEvent]
    ) -> None:
        rows = [
            (call_id, event.sequence, event.elapsed_ms, event.channel, event.char_count)
            for event in events
        ]
        if not rows:
            return
        with self._lock:
            self.connection.executemany(
                """INSERT OR REPLACE INTO stream_events
                   (call_id, seq, elapsed_ms, channel, char_count)
                   VALUES (?, ?, ?, ?, ?)""",
                rows,
            )
            self.connection.commit()

    def status(self, study: str, model_id: str) -> StudyStatus:
        row = self.connection.execute(
            """SELECT COUNT(*) AS calls,
               SUM(outcome='pass') AS correct,
               SUM(outcome='fail_wrong') AS silent_wrong,
               SUM(outcome NOT IN ('pass','fail_wrong')) AS loud,
               COALESCE(SUM(cost_microdollars), 0) AS spend
               FROM calls WHERE stage=? AND model_id=?""",
            (study, model_id),
        ).fetchone()
        return StudyStatus(
            calls=int(row["calls"] or 0),
            correct=int(row["correct"] or 0),
            silent_wrong=int(row["silent_wrong"] or 0),
            loud=int(row["loud"] or 0),
            spend_microdollars=int(row["spend"] or 0),
        )

    def study_rows(self, study: str, model_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """SELECT c.*, i.level_value, i.seed, i.payload_json
               FROM calls c JOIN instances i USING(instance_id)
               WHERE c.stage=? AND c.model_id=?
               ORDER BY c.call_id""",
            (study, model_id),
        )
        return [dict(row) for row in rows]

    def study_stream_events(self, study: str, model_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """SELECT s.call_id, s.seq, s.elapsed_ms, s.channel, s.char_count
               FROM stream_events s JOIN calls c USING(call_id)
               WHERE c.stage=? AND c.model_id=?
               ORDER BY s.call_id, s.seq""",
            (study, model_id),
        )
        return [dict(row) for row in rows]

    def update_score(
        self, call_id: int, outcome: str, parsed_answer: str | None
    ) -> None:
        with self._lock:
            self.connection.execute(
                "UPDATE calls SET outcome=?, pass=?, parsed_answer=? WHERE call_id=?",
                (outcome, int(outcome == "pass"), parsed_answer, call_id),
            )
            self.connection.commit()

    def all_instances(self, study: str) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self.connection.execute(
                "SELECT * FROM instances WHERE set_name=? ORDER BY level_idx, instance_id",
                (study,),
            )
        ]

    def route_status(self, study: str, model_id: str) -> dict[str, int]:
        row = self.connection.execute(
            """SELECT COUNT(*) AS calls,
               COALESCE(SUM(provider_mismatch), 0) AS mismatches,
               COALESCE(SUM(provider_pinned=0), 0) AS unpinned
               FROM calls WHERE stage=? AND model_id=?""",
            (study, model_id),
        ).fetchone()
        return {name: int(row[name] or 0) for name in ("calls", "mismatches", "unpinned")}
