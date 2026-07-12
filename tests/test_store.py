from drc.sat import generate
from drc.store import Store


def call_row(instance_id: str, sample: int, outcome: str, cost: int = 10) -> dict:
    return {
        "instance_id": instance_id,
        "model_id": "model",
        "sample_idx": sample,
        "stage": "study",
        "api_path": "openai",
        "prompt_version": 1,
        "request_json": "{}",
        "outcome": outcome,
        "pass": int(outcome == "pass"),
        "cost_microdollars": cost,
    }


def test_store_is_resumable_and_counts_all_outcomes(tmp_path):
    instance = generate(3, 2.0, 6)
    with Store(tmp_path / "calls.sqlite") as store:
        store.add_instance(instance, "study", 0)
        store.record_call(call_row(instance.instance_id, 0, "pass"))
        store.record_call(call_row(instance.instance_id, 1, "fail_wrong"))
        store.record_call(call_row(instance.instance_id, 2, "error_api"))
        assert store.completed_keys("study", "model") == {
            (instance.instance_id, 0),
            (instance.instance_id, 1),
            (instance.instance_id, 2),
        }
        status = store.status("study", "model")
        assert (status.calls, status.correct, status.silent_wrong, status.loud) == (3, 1, 1, 1)
        assert status.spend_microdollars == 30


def test_duplicate_key_replaces_without_double_counting(tmp_path):
    instance = generate(4, 2.0, 6)
    with Store(tmp_path / "calls.sqlite") as store:
        store.add_instance(instance, "study", 0)
        store.record_call(call_row(instance.instance_id, 0, "error_api"))
        store.record_call(call_row(instance.instance_id, 0, "pass"))
        assert store.status("study", "model").calls == 1
        assert store.status("study", "model").correct == 1


def test_route_status_detects_protocol_deviations(tmp_path):
    instance = generate(5, 2.0, 6)
    with Store(tmp_path / "calls.sqlite") as store:
        store.add_instance(instance, "study", 0)
        row = call_row(instance.instance_id, 0, "pass")
        row.update(provider_mismatch=1, provider_pinned=0)
        store.record_call(row)
        assert store.route_status("study", "model") == {
            "calls": 1,
            "mismatches": 1,
            "unpinned": 1,
        }
