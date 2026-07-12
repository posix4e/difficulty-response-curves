import pytest

from drc.config import ModelCfg
from drc.runner.budget import USD, BudgetExceeded, BudgetGuard
from drc.runner.store import Store


def _store(tmp_path):
    return Store(tmp_path / "t.sqlite")


def _fake_call_row(stage, model, micro):
    return {
        "instance_id": "i0",
        "model_id": model,
        "sample_idx": 0,
        "stage": stage,
        "api_path": "openai",
        "prompt_version": 1,
        "outcome": "pass",
        "pass": 1,
        "cost_microdollars": micro,
    }


def test_stage_cap_blocks(tmp_path):
    store = _store(tmp_path)
    guard = BudgetGuard(store, {"pilot": 1.0})  # $1 cap
    # spend $0.90
    row = _fake_call_row("pilot", "m", int(0.9 * USD))
    store.conn.execute("INSERT OR IGNORE INTO instances (instance_id, family, task_version, set_name, level_idx, level_value, params_json, payload_json, witness_json, seed) VALUES ('i0','sat',1,'t',0,2.0,'{}','{}','[]',0)")
    store.record_call(row)
    # $0.05 more admits
    token = guard.admit("pilot", "m", int(0.05 * USD))
    # but a second $0.10 would cross the cap including the reserve
    with pytest.raises(BudgetExceeded):
        guard.admit("pilot", "m", int(0.10 * USD))
    guard.release(token)
    # after release, $0.05 fits again
    guard.admit("pilot", "m", int(0.05 * USD))


def test_global_soft_stop(tmp_path):
    from drc.config import SOFT_STOP_USD

    store = _store(tmp_path)
    guard = BudgetGuard(store, {})
    store.conn.execute("INSERT OR IGNORE INTO instances (instance_id, family, task_version, set_name, level_idx, level_value, params_json, payload_json, witness_json, seed) VALUES ('i0','sat',1,'t',0,2.0,'{}','{}','[]',0)")
    store.record_call(_fake_call_row("big", "m", int((SOFT_STOP_USD - 0.5) * USD)))
    with pytest.raises(BudgetExceeded, match="soft stop"):
        guard.admit("big", "m", int(1.0 * USD))


def test_p95_estimate_tracks_observations(tmp_path):
    guard = BudgetGuard(_store(tmp_path), {})
    assert guard.p95_estimate("m", 5000) == 5000  # fallback with no data
    for c in [100] * 95 + [900] * 5:
        guard.note_cost("m", c)
    assert guard.p95_estimate("m", 5000) in (100, 900)
    assert guard.p95_estimate("m", 5000) >= 100


def test_p95_reserve_is_seeded_from_persisted_model_costs(tmp_path):
    store = _store(tmp_path)
    store.conn.execute("INSERT OR IGNORE INTO instances (instance_id, family, task_version, set_name, level_idx, level_value, params_json, payload_json, witness_json, seed) VALUES ('i0','sat',1,'t',0,2.0,'{}','{}','[]',0)")
    for index, micro in enumerate((40_000, 50_000, 60_000, 70_000, 90_000)):
        row = _fake_call_row("history", "m", micro)
        row["sample_idx"] = index
        store.record_call(row)
    guard = BudgetGuard(store, {})
    assert guard.p95_estimate("m", 5_000) == 90_000


def test_summary_distinguishes_stage_from_global_spend(tmp_path):
    store = _store(tmp_path)
    store.conn.execute("INSERT OR IGNORE INTO instances (instance_id, family, task_version, set_name, level_idx, level_value, params_json, payload_json, witness_json, seed) VALUES ('i0','sat',1,'t',0,2.0,'{}','{}','[]',0)")
    store.record_call(_fake_call_row("history", "m", int(10 * USD)))
    store.record_call(_fake_call_row("prospective", "m", int(0.5 * USD)))
    summary = BudgetGuard(store, {"prospective": 1.0}).summary("prospective")
    assert summary["global_spent_usd"] == 10.5
    assert summary["stage_spent_usd"] == 0.5


def test_pricetable_margin():
    cfg = ModelCfg(
        model_id="x", tier="A", core=True, api_path="anthropic",
        price_in=1.0, price_out=5.0, max_completion_tokens=1000,
    )
    # 1000 in + 1000 out at $1/$5 per 1M = 6000 micro, +10% = 6600
    assert cfg.pricetable_microdollars(1000, 1000) == 6600
