import gzip
import json

from drc.export import export
from drc.sat import generate
from drc.store import Store
from drc.types import StreamEvent


def test_export_separates_compact_metadata_from_raw_text(study_config, tmp_path):
    instance = generate(4, 2.0, 6)
    with Store(study_config.database) as store:
        store.add_instance(instance, study_config.name, 0)
        call_id = store.record_call(
            {
                "instance_id": instance.instance_id,
                "model_id": study_config.model.record_id,
                "sample_idx": 0,
                "stage": study_config.name,
                "api_path": "openai",
                "prompt_version": 1,
                "request_json": "{}",
                "response_text": "private trace text",
                "reasoning_text": "private reasoning text",
                "finish_reason": "stop",
                "outcome": "pass",
                "pass": 1,
                "provider_endpoint": "Parasail",
            }
        )
        store.record_stream_events(
            call_id, (StreamEvent(0, 12.5, "reasoning", 4),)
        )
    destination = tmp_path / "export"
    manifest = export(study_config, destination)
    assert manifest["calls.jsonl.gz"]["rows"] == 1
    assert manifest["stream-events.jsonl.gz"]["rows"] == 1
    with gzip.open(destination / "calls.jsonl.gz", "rt") as stream:
        compact = json.loads(stream.readline())
    with gzip.open(destination / "traces.jsonl.gz", "rt") as stream:
        trace = json.loads(stream.readline())
    with gzip.open(destination / "stream-events.jsonl.gz", "rt") as stream:
        event = json.loads(stream.readline())
    assert "response_text" not in compact
    assert "reasoning_text" not in compact
    assert trace["response_text"] == "private trace text"
    assert trace["reasoning_text"] == "private reasoning text"
    assert event == {
        "call_id": call_id,
        "channel": "reasoning",
        "char_count": 4,
        "elapsed_ms": 12.5,
        "seq": 0,
    }
    assert len(compact["instance_hash"]) == 16


def test_export_is_byte_reproducible(study_config, tmp_path):
    first = export(study_config, tmp_path / "first")
    second = export(study_config, tmp_path / "second")
    assert first["calls.jsonl.gz"]["sha256"] == second["calls.jsonl.gz"]["sha256"]
