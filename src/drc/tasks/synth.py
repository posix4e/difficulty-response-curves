"""Program synthesis from examples: the redesigned code-with-tests family.

The first design (pipeline-programs, code.py) showed the model the rule
specs, which made the task transcription - R1 went 58/60 across D=2..40
and the dial was flat. Here the pipeline is HIDDEN: the model sees only
input/output example pairs and must induce a `transform(xs)` that
generalizes. Difficulty knob: D, the number of hidden rules composed.
Induction is a search problem; transcription was not.

Certificate unchanged: six hidden tests (disjoint from the examples)
computed by the reference interpreter; scoring reuses code.py's
subprocess harness. Failure stays silent by construction.

v3 (easy-rules): the first pilot put R1's frontier at D=1 - the two
conditional rules (negate_if_even_sum, drop_last_if_odd_count) fire on
~half of inputs and made low-D functions under-determined: R1 fit all
8 examples at D=2 yet failed 4/6 hidden tests. The library here keeps
only deterministic, position-visible rules and shows 12 examples, so
difficulty comes from composition depth rather than ambiguity.
"""

from __future__ import annotations

import random
import time

from .base import CANARY, TASK_VERSION, Instance, instance_id_for, seed_for
from . import code

N_EXAMPLES = 12
_EXCLUDED = {"negate_if_even_sum", "drop_last_if_odd_count"}
RULES = [r for r in code.RULES if r[0] not in _EXCLUDED]


def gen_instance(
    *,
    n_rules: int,
    master_seed: int,
    set_name: str,
    level_idx: int,
    index: int,
) -> Instance:
    seed = seed_for(master_seed, "synth", set_name, level_idx, index)
    rng = random.Random(seed)
    t0 = time.perf_counter()
    L = rng.randint(*code.LIST_LEN)
    rule_list: list[tuple[str, dict]] = []
    while len(rule_list) < n_rules:
        name, gen_p, _, _ = RULES[rng.randrange(len(RULES))]
        # consecutive duplicates collapse effective depth (sort∘sort ~ sort)
        if rule_list and rule_list[-1][0] == name:
            continue
        rule_list.append((name, gen_p(rng, L)))
    examples: list[list[list[int]]] = []
    for _e in range(N_EXAMPLES):
        xs = [rng.randint(*code.VAL_RANGE) for _ in range(rng.randint(*code.LIST_LEN))]
        examples.append([xs, code.reference(rule_list, xs)])
    seen = {tuple(xs) for xs, _ in examples}
    tests: list[list[list[int]]] = []
    while len(tests) < code.N_TESTS:
        xs = [rng.randint(*code.VAL_RANGE) for _ in range(rng.randint(*code.LIST_LEN))]
        if tuple(xs) in seen:
            continue
        seen.add(tuple(xs))
        tests.append([xs, code.reference(rule_list, xs)])
    return Instance(
        instance_id=instance_id_for("synth", set_name, level_idx, index, master_seed),
        family="synth",
        task_version=TASK_VERSION,
        set_name=set_name,
        level_idx=level_idx,
        level_value=float(n_rules),
        params={"n_rules": n_rules},
        payload={"rules": [[n, p] for n, p in rule_list],
                 "examples": examples, "variant": "easy-v3"},
        witness=tests,
        seed=seed,
        gen_ms=(time.perf_counter() - t0) * 1000,
    )


def render_prompt(inst: Instance) -> str:
    lines = [
        CANARY,
        "A hidden deterministic procedure transforms a list of integers into a new list.",
        f"Here are {N_EXAMPLES} input -> output examples of the procedure:",
        "",
    ]
    for xs, ys in inst.payload["examples"]:
        lines.append(f"{xs} -> {ys}")
    lines += [
        "",
        "Work out what the procedure does and implement it as a Python function",
        "`transform(xs)` that reproduces the hidden procedure on ANY list of integers,",
        "not just these examples.",
        "",
        "Reply with a single fenced Python code block containing the complete function:",
        "```python",
        "def transform(xs):",
        "    ...",
        "```",
    ]
    return "\n".join(lines)


extract_code = code.extract_code


def score(inst: Instance, text: str) -> str:
    """-> 'pass' | 'fail_wrong' | 'fail_parse'"""
    src = code.extract_code(text)
    if src is None:
        return "fail_parse"
    return "pass" if code.run_tests(src, inst.witness).get("ok") else "fail_wrong"
