import json

import httpx

from drc.config import ModelCfg
from drc.runner.client import TRClient
from drc.runner.store import Store


async def test_openai_stream_captures_reasoning_and_answer_events(monkeypatch):
    monkeypatch.setenv("OPENROUTER_TEST_KEY", "test-key")
    model = ModelCfg(
        model_id="or/mock",
        tier="test",
        core=False,
        api_path="openai",
        price_in=0.1,
        price_out=0.2,
        max_completion_tokens=1024,
        provider_only=("parasail",),
        base_url="https://openrouter.ai/api",
        key_env="OPENROUTER_TEST_KEY",
        api_model="mock/model",
    )
    chunks = [
        {"provider": "Parasail", "choices": [{"delta": {"reasoning": "wait, try again"}}]},
        {"provider": "Parasail", "choices": [{"delta": {"content": "ANSWER: x1=T"}, "finish_reason": "stop"}]},
        {
            "provider": "Parasail",
            "choices": [],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 20,
                "completion_tokens_details": {"reasoning_tokens": 12},
                "cost_microdollars": 7,
            },
        },
    ]
    payload = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=payload, headers={"content-type": "text/event-stream"})

    client = TRClient("unused", transport=httpx.MockTransport(handler))
    result = await client.call(model, "prompt", stream_telemetry=True)
    await client.aclose()
    assert result.error is None
    assert result.provider_endpoint == "openrouter/Parasail"
    assert result.text == "<think>wait, try again</think>\nANSWER: x1=T"
    assert [event["channel"] for event in result.stream_events] == ["reasoning", "answer"]
    assert result.ttft_ms is not None
    assert result.first_reasoning_ms is not None
    assert result.first_answer_ms is not None
    assert result.observed_chars == len("wait, try again") + len("ANSWER: x1=T")
    assert result.reasoning_tokens == 12


def test_store_persists_stream_events_and_migrates_columns(tmp_path):
    store = Store(tmp_path / "t.sqlite")
    columns = {row[1] for row in store.conn.execute("PRAGMA table_info(calls)")}
    assert {"ttft_ms", "first_reasoning_ms", "first_answer_ms", "stream_duration_ms", "observed_chars"} <= columns
    call_id = store.record_call({
        "instance_id": "i",
        "model_id": "m",
        "sample_idx": 0,
        "stage": "s",
        "api_path": "openai",
        "prompt_version": 1,
        "outcome": "pass",
        "pass": 1,
        "ttft_ms": 12.0,
        "observed_chars": 8,
    })
    store.record_stream_events(call_id, [
        {"seq": 0, "elapsed_ms": 12.0, "channel": "reasoning", "char_count": 3},
        {"seq": 1, "elapsed_ms": 18.0, "channel": "answer", "char_count": 5},
    ])
    rows = store.conn.execute(
        "SELECT seq, channel, char_count FROM stream_events WHERE call_id=? ORDER BY seq", (call_id,)
    ).fetchall()
    assert [tuple(row) for row in rows] == [(0, "reasoning", 3), (1, "answer", 5)]
