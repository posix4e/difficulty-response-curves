from __future__ import annotations

import gzip
import hashlib
import io
import json
from pathlib import Path
from typing import Any, Iterable

from .config import StudyConfig
from .store import Store
from .types import Outcome
from .analysis import outcome_class


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_jsonl_gzip(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    count = 0
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with io.TextIOWrapper(compressed, encoding="utf-8") as text:
                for row in rows:
                    text.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
                    count += 1
    return count


def export(config: StudyConfig, destination: str | Path) -> dict[str, Any]:
    target = Path(destination)
    target.mkdir(parents=True, exist_ok=True)
    with Store(config.database) as store:
        calls = store.study_rows(config.name, config.model.record_id)
        stream_events = store.study_stream_events(config.name, config.model.record_id)

    compact = []
    traces = []
    for row in calls:
        identifier = hashlib.sha256(str(row["instance_id"]).encode()).hexdigest()[:16]
        compact.append(
            {
                "call_id": int(row["call_id"]),
                "instance_hash": identifier,
                "difficulty": float(row["level_value"]),
                "outcome": outcome_class(str(row["outcome"])).value,
                "finish_reason": row.get("finish_reason"),
                "completion_tokens": row.get("completion_tokens"),
                "reasoning_tokens": row.get("reasoning_tokens"),
                "latency_ms": row.get("latency_ms"),
                "cost_microdollars": int(row.get("cost_microdollars") or 0),
                "provider": row.get("provider_endpoint"),
            }
        )
        traces.append(
            {
                "call_id": int(row["call_id"]),
                "instance_hash": identifier,
                "response_text": row.get("response_text") or "",
                "reasoning_text": row.get("reasoning_text") or "",
            }
        )

    files = {
        "calls.jsonl.gz": compact,
        "stream-events.jsonl.gz": stream_events,
        "traces.jsonl.gz": traces,
    }
    manifest = {}
    for name, rows in files.items():
        path = target / name
        count = write_jsonl_gzip(path, rows)
        manifest[name] = {"rows": count, "bytes": path.stat().st_size, "sha256": sha256(path)}
    manifest_path = target / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest
