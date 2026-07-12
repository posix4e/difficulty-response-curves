from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any


class Outcome(StrEnum):
    CORRECT = "correct_completed"
    SILENT_WRONG = "silently_wrong_completed"
    LOUD_FAILURE = "loud_failure"

    @classmethod
    def from_runner(cls, value: str) -> "Outcome":
        if value == "pass":
            return cls.CORRECT
        if value == "fail_wrong":
            return cls.SILENT_WRONG
        return cls.LOUD_FAILURE


@dataclass(frozen=True)
class Instance:
    instance_id: str
    difficulty: float
    prompt: str
    clauses: tuple[tuple[int, int, int], ...]
    witness: tuple[bool, ...]
    seed: int

    def public_dict(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "difficulty": self.difficulty,
            "prompt": self.prompt,
            "clauses": [list(clause) for clause in self.clauses],
            "seed": self.seed,
        }


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    cost_microdollars: int = 0


@dataclass(frozen=True)
class ProviderResponse:
    text: str
    finish_reason: str
    provider: str
    usage: Usage
    latency_ms: float
    http_status: int = 200
    error: str | None = None


@dataclass(frozen=True)
class CallPlan:
    instance: Instance
    sample_index: int

    @property
    def key(self) -> tuple[str, int]:
        return self.instance.instance_id, self.sample_index


@dataclass(frozen=True)
class StudyStatus:
    calls: int
    correct: int
    silent_wrong: int
    loud: int
    spend_microdollars: int

    def as_dict(self) -> dict[str, int | float]:
        result = asdict(self)
        result["spend_usd"] = round(self.spend_microdollars / 1_000_000, 6)
        return result
