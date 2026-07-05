"""Satisfiable-only random 3-SAT with a full-assignment certificate.

Difficulty knob: clause-to-variable ratio alpha. m = round(alpha * n).
Instances are rejection-sampled to satisfiability at generation time;
the rejection count per accepted instance is stored (it is free data on
P(SAT | alpha)). Scoring never consults the stored witness: any
assignment that satisfies every clause passes.
"""

from __future__ import annotations

import random
import re
import time

from .base import CANARY, TASK_VERSION, Instance, instance_id_for, seed_for
from .solver import SOLVER_NAME, check_assignment, solve

MAX_REJECTIONS = 20_000


def gen_instance(
    *,
    n_vars: int,
    alpha: float,
    master_seed: int,
    set_name: str,
    level_idx: int,
    index: int,
) -> Instance:
    seed = seed_for(master_seed, "sat", set_name, level_idx, index)
    rng = random.Random(seed)
    m = round(alpha * n_vars)
    t0 = time.perf_counter()
    rejections = 0
    while True:
        clauses = _sample_clauses(rng, n_vars, m)
        witness = solve(clauses, n_vars)
        if witness is not None:
            break
        rejections += 1
        if rejections > MAX_REJECTIONS:
            raise RuntimeError(f"no satisfiable draw after {MAX_REJECTIONS} tries at alpha={alpha}, n={n_vars}")
    return Instance(
        instance_id=instance_id_for("sat", set_name, level_idx, index, master_seed),
        family="sat",
        task_version=TASK_VERSION,
        set_name=set_name,
        level_idx=level_idx,
        level_value=alpha,
        params={"n_vars": n_vars, "m_clauses": m},
        payload={"clauses": [list(c) for c in clauses]},
        witness=[bool(b) for b in witness],
        seed=seed,
        rejection_count=rejections,
        solver_used=SOLVER_NAME,
        gen_ms=(time.perf_counter() - t0) * 1000,
    )


def _sample_clauses(rng: random.Random, n_vars: int, m: int) -> list[tuple[int, ...]]:
    """m distinct clauses; each = 3 distinct variables, independent polarities."""
    seen: set[tuple[int, ...]] = set()
    clauses: list[tuple[int, ...]] = []
    while len(clauses) < m:
        vs = rng.sample(range(1, n_vars + 1), 3)
        clause = tuple(sorted(v if rng.random() < 0.5 else -v for v in vs))
        if clause in seen:
            continue
        seen.add(clause)
        clauses.append(clause)
    return clauses


def render_prompt(inst: Instance) -> str:
    n = inst.params["n_vars"]
    lines = [
        CANARY,
        f"You are given a Boolean satisfiability problem with {n} variables x1..x{n}.",
        "Find an assignment that makes ALL clauses true. This instance is satisfiable.",
        "Clauses (each requires at least one listed literal true):",
    ]
    for clause in inst.payload["clauses"]:
        lits = [f"x{lit}" if lit > 0 else f"NOT x{-lit}" for lit in clause]
        lines.append("(" + " OR ".join(lits) + ")")
    lines += [
        "End your reply with exactly one line in this format, assigning every variable:",
        f"ANSWER: x1=T x2=F x3=T ... x{n}=F",
    ]
    return "\n".join(lines)


_PAIR_RE = re.compile(r"(?:x\s*)?(\d+)\s*[=:]\s*(T(?:RUE)?|F(?:ALSE)?|1|0)", re.IGNORECASE)
_BARE_RE = re.compile(r"\b(T|F|TRUE|FALSE|1|0)\b", re.IGNORECASE)


def parse_assignment(text: str, n_vars: int) -> list[bool] | None:
    """Last ANSWER: line; lenient tokens, strict semantics (every variable
    assigned exactly once, no contradictions)."""
    line = _last_answer_line(text)
    if line is None:
        return None
    seen: dict[int, bool] = {}
    pairs = _PAIR_RE.findall(line)
    if pairs:
        for var_s, val_s in pairs:
            var = int(var_s)
            val = val_s.upper() in ("T", "TRUE", "1")
            if var in seen and seen[var] != val:
                return None
            seen[var] = val
    else:
        toks = _BARE_RE.findall(line)
        if len(toks) != n_vars:
            return None
        seen = {i + 1: t.upper() in ("T", "TRUE", "1") for i, t in enumerate(toks)}
    if set(seen) != set(range(1, n_vars + 1)):
        return None
    return [seen[v] for v in range(1, n_vars + 1)]


def _last_answer_line(text: str) -> str | None:
    matches = list(re.finditer(r"ANSWER\s*:(.*)$", text, re.IGNORECASE | re.MULTILINE))
    if not matches:
        return None
    return matches[-1].group(1)


def score(inst: Instance, text: str) -> str:
    """-> 'pass' | 'fail_wrong' | 'fail_parse'"""
    assignment = parse_assignment(text, inst.params["n_vars"])
    if assignment is None:
        return "fail_parse"
    clauses = [tuple(c) for c in inst.payload["clauses"]]
    return "pass" if check_assignment(clauses, assignment) else "fail_wrong"
