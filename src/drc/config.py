from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import tomllib


@dataclass(frozen=True)
class ModelConfig:
    record_id: str
    api_model: str
    base_url: str
    key_env: str
    provider: str
    max_tokens: int
    temperature: float
    reasoning_effort: str
    price_in_per_million: float
    price_out_per_million: float

    def key(self) -> str:
        value = os.environ.get(self.key_env, "").strip()
        if not value:
            raise RuntimeError(f"missing API key in {self.key_env}")
        return value

    def estimated_microdollars(self, prompt_tokens: int, completion_tokens: int) -> int:
        raw = (
            prompt_tokens * self.price_in_per_million
            + completion_tokens * self.price_out_per_million
        )
        return int(round(raw * 1.10))


@dataclass(frozen=True)
class TaskConfig:
    variables: int
    difficulties: tuple[float, ...]
    instances_per_level: int
    samples_per_instance: int
    seed: int


@dataclass(frozen=True)
class StopConfig:
    correct: int
    silent_wrong: int
    max_calls: int
    max_spend_usd: float | None

    @property
    def max_spend_microdollars(self) -> int | None:
        if self.max_spend_usd is None:
            return None
        return int(round(self.max_spend_usd * 1_000_000))


@dataclass(frozen=True)
class SentinelConfig:
    before_stage: str
    after_stage: str
    calls_each: int


@dataclass(frozen=True)
class StudyConfig:
    name: str
    prompt_version: int
    database: Path
    concurrency: int
    collection_locked: bool
    model: ModelConfig
    task: TaskConfig
    stop: StopConfig
    sentinels: SentinelConfig

    def validate(self) -> None:
        if not self.name or self.prompt_version < 1:
            raise ValueError("study name and positive prompt version are required")
        if self.concurrency < 1:
            raise ValueError("concurrency must be positive")
        if self.model.max_tokens < 1 or not self.model.provider:
            raise ValueError("model token cap and provider pin are required")
        if not 0 <= self.model.temperature <= 2:
            raise ValueError("temperature must be between zero and two")
        if self.model.reasoning_effort not in {
            "none", "minimal", "low", "medium", "high", "xhigh", "max"
        }:
            raise ValueError("unsupported reasoning effort")
        if self.task.variables < 3 or not self.task.difficulties:
            raise ValueError("SAT task configuration is incomplete")
        if self.task.instances_per_level < 1 or self.task.samples_per_instance < 1:
            raise ValueError("task replication must be positive")
        if self.stop.max_calls < 1:
            raise ValueError("hard call cap is required")
        if self.stop.max_spend_usd is not None and self.stop.max_spend_usd <= 0:
            raise ValueError("hard call and spend caps are required")


def load_config(path: str | Path = "configs/study.toml") -> StudyConfig:
    source = Path(path)
    raw = tomllib.loads(source.read_text())
    study, model, task, stop, sentinels = (
        raw[name] for name in ("study", "model", "task", "stop", "sentinels")
    )
    database = Path(study.get("database", "data/drc.sqlite"))
    if not database.is_absolute():
        database = (source.parent.parent / database).resolve()
    raw_spend = stop.get("max_spend_usd")
    max_spend = (
        None
        if isinstance(raw_spend, str) and raw_spend.strip().lower() == "unlimited"
        else float(raw_spend)
    )
    config = StudyConfig(
        name=str(study["name"]),
        prompt_version=int(study.get("prompt_version", 1)),
        database=database,
        concurrency=int(study.get("concurrency", 4)),
        collection_locked=bool(study.get("collection_locked", False)),
        model=ModelConfig(
            record_id=str(model["record_id"]),
            api_model=str(model["api_model"]),
            base_url=str(model["base_url"]).rstrip("/"),
            key_env=str(model["key_env"]),
            provider=str(model["provider"]),
            max_tokens=int(model["max_tokens"]),
            temperature=float(model.get("temperature", 1.0)),
            reasoning_effort=str(model.get("reasoning_effort", "medium")),
            price_in_per_million=float(model["price_in_per_million"]),
            price_out_per_million=float(model["price_out_per_million"]),
        ),
        task=TaskConfig(
            variables=int(task["variables"]),
            difficulties=tuple(float(value) for value in task["difficulties"]),
            instances_per_level=int(task["instances_per_level"]),
            samples_per_instance=int(task["samples_per_instance"]),
            seed=int(task["seed"]),
        ),
        stop=StopConfig(
            correct=int(stop["correct"]),
            silent_wrong=int(stop["silent_wrong"]),
            max_calls=int(stop["max_calls"]),
            max_spend_usd=max_spend,
        ),
        sentinels=SentinelConfig(
            before_stage=str(sentinels["before_stage"]),
            after_stage=str(sentinels["after_stage"]),
            calls_each=int(sentinels["calls_each"]),
        ),
    )
    config.validate()
    return config
