from __future__ import annotations

import hashlib
import json
import math
import random
import re
from typing import Iterable

from .types import Instance


def _simplify(
    clauses: tuple[tuple[int, ...], ...], variable: int, value: bool
) -> tuple[tuple[int, ...], ...] | None:
    true_literal = variable if value else -variable
    false_literal = -true_literal
    remaining: list[tuple[int, ...]] = []
    for clause in clauses:
        if true_literal in clause:
            continue
        reduced = tuple(literal for literal in clause if literal != false_literal)
        if not reduced:
            return None
        remaining.append(reduced)
    return tuple(remaining)


def solve(clauses: Iterable[Iterable[int]], variables: int) -> tuple[bool, ...] | None:
    """Deterministic DPLL for the small SAT instances used by the study."""
    initial = tuple(tuple(int(literal) for literal in clause) for clause in clauses)

    def search(
        current: tuple[tuple[int, ...], ...], assignment: dict[int, bool]
    ) -> dict[int, bool] | None:
        if not current:
            return assignment
        unit = next((clause[0] for clause in current if len(clause) == 1), None)
        variable = abs(unit) if unit is not None else abs(min(current, key=len)[0])
        values = (unit > 0,) if unit is not None else (False, True)
        for value in values:
            reduced = _simplify(current, variable, value)
            if reduced is None:
                continue
            result = search(reduced, {**assignment, variable: value})
            if result is not None:
                return result
        return None

    result = search(initial, {})
    if result is None:
        return None
    return tuple(bool(result.get(index, False)) for index in range(1, variables + 1))


def verify(clauses: Iterable[Iterable[int]], assignment: Iterable[bool]) -> bool:
    values = tuple(bool(value) for value in assignment)
    for clause in clauses:
        if not any(values[abs(literal) - 1] == (literal > 0) for literal in clause):
            return False
    return True


def _prompt(variables: int, clauses: tuple[tuple[int, int, int], ...]) -> str:
    rendered = "\n".join(" ".join(map(str, clause)) for clause in clauses)
    return (
        f"Find a satisfying assignment for this 3-SAT formula with {variables} variables.\n"
        "Positive integers mean the variable is true; negative integers mean false.\n"
        "Return exactly one final line: FINAL: followed by one 0 or 1 for each variable.\n\n"
        f"{rendered}\n"
    )


def generate(seed: int, difficulty: float, variables: int = 20) -> Instance:
    """Sample uniform random 3-CNF formulas until one is satisfiable."""
    rng = random.Random(seed)
    clause_count = max(1, int(round(difficulty * variables)))
    for _ in range(10_000):
        clauses = []
        for _ in range(clause_count):
            names = rng.sample(range(1, variables + 1), 3)
            clause = tuple(name if rng.random() < 0.5 else -name for name in names)
            clauses.append(clause)
        frozen = tuple(clauses)
        witness = solve(frozen, variables)
        if witness is None:
            continue
        payload = json.dumps(
            {"variables": variables, "difficulty": difficulty, "clauses": frozen},
            sort_keys=True,
            separators=(",", ":"),
        )
        instance_id = hashlib.sha256(payload.encode()).hexdigest()[:24]
        return Instance(
            instance_id=instance_id,
            difficulty=float(difficulty),
            prompt=_prompt(variables, frozen),
            clauses=frozen,
            witness=witness,
            seed=seed,
        )
    raise RuntimeError("could not sample a satisfiable formula")


def parse_assignment(text: str, variables: int) -> tuple[bool, ...] | None:
    matches = re.findall(r"(?im)^\s*FINAL\s*:\s*((?:[01][\s,]*)+)\s*$", text)
    if not matches:
        return None
    bits = re.findall(r"[01]", matches[-1])
    if len(bits) != variables:
        return None
    return tuple(bit == "1" for bit in bits)


def planned_instances(config_seed: int, difficulties: tuple[float, ...], count: int, variables: int) -> list[Instance]:
    instances = []
    for level_index, difficulty in enumerate(difficulties):
        for instance_index in range(count):
            seed = config_seed + level_index * 100_000 + instance_index
            instances.append(generate(seed, difficulty, variables))
    return instances
