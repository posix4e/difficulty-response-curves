from pathlib import Path

import pytest

from drc.config import load_config


def test_frozen_config_loads():
    config = load_config("configs/study.toml")
    assert config.name == "minimax-confidence-v1"
    assert config.model.provider == "Parasail"
    assert config.model.max_tokens == 65536
    assert config.stop.max_spend_microdollars == 38_000_000
    assert config.collection_locked


def test_config_requires_hard_caps(tmp_path: Path):
    source = tmp_path / "study.toml"
    source.write_text(
        """[study]
name='x'
[model]
record_id='x'
api_model='x'
base_url='https://example.invalid/v1'
key_env='KEY'
provider='P'
max_tokens=1
price_in_per_million=1
price_out_per_million=1
[task]
variables=3
difficulties=[1]
instances_per_level=1
samples_per_instance=1
seed=1
[stop]
correct=1
silent_wrong=1
max_calls=1
max_spend_usd=0
[sentinels]
before_stage='before'
after_stage='after'
calls_each=1
"""
    )
    with pytest.raises(ValueError, match="hard call and spend caps"):
        load_config(source)


def test_price_estimate_has_safety_margin():
    config = load_config("configs/study.toml")
    assert config.model.estimated_microdollars(1_000_000, 0) == 330_000


def test_explicit_unlimited_spend_keeps_call_cap():
    config = load_config("configs/glm-5.2-frontier-256k-siliconflow.toml")
    assert config.stop.max_calls == 10
    assert config.stop.max_spend_usd is None
    assert config.stop.max_spend_microdollars is None
