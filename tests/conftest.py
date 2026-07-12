from __future__ import annotations

from pathlib import Path

import pytest

from drc.config import ModelConfig, SentinelConfig, StopConfig, StudyConfig, TaskConfig


@pytest.fixture
def study_config(tmp_path: Path) -> StudyConfig:
    return StudyConfig(
        name="test-study",
        prompt_version=1,
        database=tmp_path / "study.sqlite",
        concurrency=2,
        collection_locked=False,
        model=ModelConfig(
            record_id="or/minimax-m2.5",
            api_model="minimax/minimax-m2.5",
            base_url="https://example.invalid/v1",
            key_env="TEST_OPENROUTER_KEY",
            provider="Parasail",
            max_tokens=100,
            temperature=1.0,
            reasoning_effort="medium",
            price_in_per_million=0.30,
            price_out_per_million=1.20,
        ),
        task=TaskConfig(
            variables=6,
            difficulties=(2.0,),
            instances_per_level=1,
            samples_per_instance=2,
            seed=11,
        ),
        stop=StopConfig(correct=10, silent_wrong=10, max_calls=2, max_spend_usd=1.0),
        sentinels=SentinelConfig(
            before_stage="sentinel-before", after_stage="sentinel-after", calls_each=1
        ),
    )
