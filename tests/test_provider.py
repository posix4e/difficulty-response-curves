import pytest

from drc.provider import OpenRouter, SSEDecoder


def test_sse_decoder_ignores_comments_and_joins_data_fields():
    decoder = SSEDecoder()
    assert decoder.feed(": OPENROUTER PROCESSING") == ()
    assert decoder.feed("data: {\"part\":") == ()
    assert decoder.feed("data: 1}") == ()
    assert decoder.feed("") == ('{"part":\n1}',)


def test_sse_decoder_flushes_final_event_without_blank_line():
    decoder = SSEDecoder()
    decoder.feed("data: [DONE]")
    assert decoder.finish() == ("[DONE]",)


@pytest.mark.asyncio
async def test_long_generation_has_no_read_timeout(study_config):
    provider = OpenRouter(study_config.model)
    try:
        assert provider.client.timeout.read is None
        assert provider.client.timeout.connect == 30.0
    finally:
        await provider.close()
