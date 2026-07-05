"""Kill/resume semantics: rerunning a stage never duplicates a call and
retries only error_api rows. Uses an httpx MockTransport standing in for
TrustedRouter."""

import json

import httpx
import pytest

from drc.config import GridCfg, ModelCfg, StageCfg
from drc.runner.budget import BudgetGuard
from drc.runner.client import TRClient
from drc.runner.scheduler import run_jobs
from drc.runner.store import Store
from drc.runner.sweep import plan_jobs

MODEL = ModelCfg(
    model_id="mock/model", tier="A", core=True, api_path="openai",
    price_in=0.1, price_out=0.5, max_completion_tokens=2048,
)
GRID = GridCfg(name="g", family="sat", levels=(2.0, 3.0, 4.0), n_vars=6)
STAGE = StageCfg(
    name="teststage", grid="g", set_name="mockset", models=["mock/model"],
    n_instances=2, k=2, cap_usd=50.0,
)


def _mock_transport(fail_first_n: int = 0):
    state = {"calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        if state["calls"] <= fail_first_n:
            return httpx.Response(500, text="boom")
        body = json.loads(request.content)
        n = 6
        answer = "ANSWER: " + " ".join(f"x{i+1}=T" for i in range(n))
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": answer}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50, "cost_microdollars": 12},
                "trustedrouter": {"routing": {"selected_endpoint": "mock/model@mock/prepaid"}},
            },
        )

    return httpx.MockTransport(handler), state


async def test_full_run_then_resume_is_noop(tmp_path):
    store = Store(tmp_path / "t.sqlite")
    guard = BudgetGuard(store, {"teststage": 50.0})
    transport, state = _mock_transport()
    client = TRClient("k", transport=transport)

    jobs = plan_jobs(STAGE, {"g": GRID}, {"mock/model": MODEL}, store)
    assert len(jobs) == 3 * 2 * 2  # levels x instances x k
    summary = await run_jobs(jobs, {"mock/model": MODEL}, client, store, guard, log=lambda *_: None)
    assert summary["done"] == 12
    assert state["calls"] == 12

    # resume: nothing left to do, zero new HTTP calls
    jobs2 = plan_jobs(STAGE, {"g": GRID}, {"mock/model": MODEL}, store)
    assert jobs2 == []
    await client.aclose()


async def test_error_api_rows_are_retried_on_resume(tmp_path, monkeypatch):
    monkeypatch.setattr("drc.runner.client.MAX_RETRIES", 1)
    store = Store(tmp_path / "t.sqlite")
    guard = BudgetGuard(store, {"teststage": 50.0})
    transport, state = _mock_transport(fail_first_n=3)  # first 3 HTTP calls 500
    client = TRClient("k", transport=transport)

    jobs = plan_jobs(STAGE, {"g": GRID}, {"mock/model": MODEL}, store)
    await run_jobs(jobs, {"mock/model": MODEL}, client, store, guard, log=lambda *_: None)
    n_err = store.conn.execute("SELECT COUNT(*) FROM calls WHERE outcome='error_api'").fetchone()[0]
    assert n_err >= 1  # some failed hard with retries exhausted

    # resume regenerates exactly the failed jobs, deletes error rows, retries
    jobs2 = plan_jobs(STAGE, {"g": GRID}, {"mock/model": MODEL}, store)
    assert len(jobs2) == n_err
    await run_jobs(jobs2, {"mock/model": MODEL}, client, store, guard, log=lambda *_: None)
    rows = store.conn.execute(
        "SELECT COUNT(*), SUM(outcome='error_api') FROM calls WHERE stage='teststage'"
    ).fetchone()
    assert rows[0] == 12  # no duplicates
    assert rows[1] == 0  # every error row was retried to a scored outcome
    await client.aclose()


async def test_budget_stops_dispatch(tmp_path):
    store = Store(tmp_path / "t.sqlite")
    guard = BudgetGuard(store, {"teststage": 0.00002})  # 20 microdollars: ~1 call at est
    transport, _ = _mock_transport()
    client = TRClient("k", transport=transport)
    jobs = plan_jobs(STAGE, {"g": GRID}, {"mock/model": MODEL}, store)
    summary = await run_jobs(jobs, {"mock/model": MODEL}, client, store, guard, log=lambda *_: None)
    assert summary["stopped"]  # model stopped on budget
    assert summary["done"] < 12
    await client.aclose()
