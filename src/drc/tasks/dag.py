"""DAG arithmetic with controlled depth (the check family).

Difficulty knob: op count. Each op node takes the immediately previous
node as its first operand (guaranteeing dependency depth = op count) and
a uniformly chosen earlier node as its second, so every node feeds the
final value. Leaves are small integers; any op whose result exceeds
|v| > 999 is locally resampled, keeping per-step arithmetic small so
difficulty comes from length and structure, not bignum multiplication.
"""

from __future__ import annotations

import random
import re
import time

from .base import CANARY, TASK_VERSION, Instance, instance_id_for, seed_for

MAX_ABS = 999
OPS = ("+", "-", "*")


def _name(i: int) -> str:
    # a..z, then a1..z1, a2.. ; final op node is renamed "result" at render
    letters = "abcdefghijklmnopqrstuvwxyz"
    return letters[i % 26] + (str(i // 26) if i >= 26 else "")


def gen_instance(
    *,
    n_ops: int,
    master_seed: int,
    set_name: str,
    level_idx: int,
    index: int,
) -> Instance:
    seed = seed_for(master_seed, "dag", set_name, level_idx, index)
    rng = random.Random(seed)
    t0 = time.perf_counter()
    n_leaves = max(2, n_ops // 3 + 1)
    values: list[int] = [rng.randint(-9, 9) for _ in range(n_leaves)]
    ops: list[tuple[str, int, int]] = []  # (op, i_left, i_right) into node list
    for _ in range(n_ops):
        left = len(values) - 1  # chain: previous node
        for _attempt in range(200):
            op = rng.choice(OPS)
            right = rng.randrange(len(values))
            v = _apply(op, values[left], values[right])
            if abs(v) <= MAX_ABS:
                break
        else:
            # deterministic fallback: subtract the previous node from itself-ish
            op, right = "-", min(range(len(values)), key=lambda i: abs(values[i]))
            v = _apply(op, values[left], values[right])
        ops.append((op, left, right))
        values.append(v)
    return Instance(
        instance_id=instance_id_for("dag", set_name, level_idx, index, master_seed),
        family="dag",
        task_version=TASK_VERSION,
        set_name=set_name,
        level_idx=level_idx,
        level_value=float(n_ops),
        params={"n_ops": n_ops, "n_leaves": n_leaves},
        payload={"leaves": values[:n_leaves], "ops": [list(o) for o in ops]},
        witness=values[-1],
        seed=seed,
        solver_used="eval",
        gen_ms=(time.perf_counter() - t0) * 1000,
    )


def _apply(op: str, a: int, b: int) -> int:
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    return a * b


def evaluate(inst: Instance) -> int:
    values = list(inst.payload["leaves"])
    for op, left, right in inst.payload["ops"]:
        values.append(_apply(op, values[left], values[right]))
    return values[-1]


def render_prompt(inst: Instance) -> str:
    n_leaves = inst.params["n_leaves"]
    n_nodes = n_leaves + inst.params["n_ops"]
    names = [_name(i) for i in range(n_nodes)]
    names[-1] = "result"
    lines = [
        CANARY,
        "Below is a list of integer assignments. Each line defines a value using earlier lines.",
    ]
    for i, leaf in enumerate(inst.payload["leaves"]):
        lines.append(f"{names[i]} = {leaf}")
    for j, (op, left, right) in enumerate(inst.payload["ops"]):
        lines.append(f"{names[n_leaves + j]} = {names[left]} {op} {names[right]}")
    lines += [
        "Compute the exact integer value of result.",
        "End your reply with exactly one line in this format:",
        "ANSWER: <integer>",
    ]
    return "\n".join(lines)


_INT_RE = re.compile(r"ANSWER\s*:\s*[^\d+-]*([+-]?[\d][\d,_ ]*)", re.IGNORECASE)


def parse_answer(text: str) -> int | None:
    matches = list(_INT_RE.finditer(text))
    if not matches:
        return None
    raw = matches[-1].group(1).replace(",", "").replace("_", "").replace(" ", "")
    try:
        return int(raw)
    except ValueError:
        return None


def score(inst: Instance, text: str) -> str:
    parsed = parse_answer(text)
    if parsed is None:
        return "fail_parse"
    return "pass" if parsed == inst.witness else "fail_wrong"
