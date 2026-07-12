import asyncio

import pytest

import drc.cli as cli


@pytest.mark.asyncio
async def test_stage_client_is_created_and_closed_on_same_loop(monkeypatch):
    events = []

    class FakeClient:
        def __init__(self, _key):
            self.loop = asyncio.get_running_loop()
            events.append("created")

        async def aclose(self):
            assert asyncio.get_running_loop() is self.loop
            events.append("closed")

    async def fake_run_jobs(*_args, **_kwargs):
        events.append("ran")
        return {"done": 0}

    monkeypatch.setattr(cli, "TRClient", FakeClient)
    monkeypatch.setattr(cli.config, "load_key", lambda: "test")
    monkeypatch.setattr(cli, "run_jobs", fake_run_jobs)
    result = await cli._run_stage_async([], {}, object(), object())
    assert result == {"done": 0}
    assert events == ["created", "ran", "closed"]
