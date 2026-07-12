from drc import config


def test_minimax_confidence_stages_preserve_budget_and_protocol():
    models = config.load_models()
    stages = config.load_stages(models)
    pre = stages["minimax-confidence-sentinel-pre"]
    study = stages["minimax-confidence-v1"]
    post = stages["minimax-confidence-sentinel-post"]
    stream = stages["minimax-confidence-stream-smoke"]
    assert pre.cap_usd + study.cap_usd + post.cap_usd == 40.0
    assert study.n_instances * study.k * 3 == 600
    assert (study.stop_correct, study.stop_silent_wrong) == (60, 60)
    assert study.required_provider_endpoint == "openrouter/Parasail"
    assert stream.cap_usd == 10.0 and stream.stream_telemetry
