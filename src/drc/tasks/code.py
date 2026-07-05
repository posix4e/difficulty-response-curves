"""Pipeline programs: the code-with-tests family (round 2).

The spec lists D sequential transformation rules over a list of integers;
the model writes one Python function `transform(xs)`. Difficulty knob:
D, the number of rules. Rules are individually trivial but stateful -
conditionals read the current list, two rules change its length - so
difficulty comes from tracking compounding state, not from any single
step. Failure is silent by construction: wrong code still runs.

Certificate: six hidden input/output tests computed by the reference
interpreter at generation time (the model never sees them). Scoring runs
the extracted function in an isolated subprocess against the tests.
"""

from __future__ import annotations

import json
import random
import re
import subprocess
import sys
import time

from .base import CANARY, TASK_VERSION, Instance, instance_id_for, seed_for

N_TESTS = 6
LIST_LEN = (8, 12)
VAL_RANGE = (-9, 9)
EXEC_TIMEOUT_S = 10


# ---- rule library ------------------------------------------------------------
# each entry: (name, gen_params(rng, hint_len) -> dict,
#              spec(params) -> str, apply(params, xs) -> new xs)

def _r_rotate(p, xs):
    k = p["k"] % len(xs) if xs else 0
    return xs[-k:] + xs[:-k] if k else list(xs)

def _r_reverse_seg(p, xs):
    i, j = p["i"], p["j"]
    if i > len(xs):
        return list(xs)
    j = min(j, len(xs))
    return xs[: i - 1] + xs[i - 1 : j][::-1] + xs[j:]

def _r_swap_pairs(p, xs):
    out = list(xs)
    for a in range(0, len(out) - 1, 2):
        out[a], out[a + 1] = out[a + 1], out[a]
    return out

def _r_add_odd_pos(p, xs):
    return [x + p["v"] if (idx % 2 == 0) else x for idx, x in enumerate(xs)]

def _r_diff_left(p, xs):
    return [xs[0]] + [xs[i] - xs[i - 1] for i in range(1, len(xs))]

def _r_max_front(p, xs):
    if not xs:
        return []
    m = max(xs)
    i = xs.index(m)
    return [xs[i]] + xs[:i] + xs[i + 1 :]

def _r_negate_if_even_sum(p, xs):
    return [-x for x in xs] if sum(xs) % 2 == 0 else list(xs)

def _r_insert_len(p, xs):
    pos = min(p["p"], len(xs))
    return xs[:pos] + [len(xs)] + xs[pos:]

def _r_drop_last_if_odd_count(p, xs):
    return xs[:-1] if len(xs) % 2 == 1 else list(xs)

def _r_sort_prefix(p, xs):
    h = min(p["h"], len(xs))
    return sorted(xs[:h]) + xs[h:]


RULES = [
    ("rotate",
     lambda rng, L: {"k": rng.randint(1, 5)},
     lambda p: f"Rotate the list to the right by {p['k']} positions.",
     _r_rotate),
    ("reverse_seg",
     lambda rng, L: (lambda i, j: {"i": i, "j": j})(rng.randint(1, 4), rng.randint(5, L)),
     lambda p: f"Reverse the segment from position {p['i']} to position {p['j']} "
               f"(1-indexed, inclusive; ignore positions beyond the end of the list).",
     _r_reverse_seg),
    ("swap_pairs",
     lambda rng, L: {},
     lambda p: "Swap each adjacent pair of elements (positions 1-2, 3-4, and so on); "
               "if the list has odd length the last element stays where it is.",
     _r_swap_pairs),
    ("add_odd_pos",
     lambda rng, L: {"v": rng.choice([-3, -2, 2, 3])},
     lambda p: f"Add {p['v']} to every element at an odd position (1-indexed: the 1st, 3rd, 5th, ...).",
     _r_add_odd_pos),
    ("diff_left",
     lambda rng, L: {},
     lambda p: "Replace every element (except the first) with the difference between it and its "
               "left neighbour, computed simultaneously from the list as it was before this rule; "
               "the first element keeps its value.",
     _r_diff_left),
    ("max_front",
     lambda rng, L: {},
     lambda p: "Move the largest element to the front (the first occurrence, if tied); "
               "all other elements keep their relative order.",
     _r_max_front),
    ("negate_if_even_sum",
     lambda rng, L: {},
     lambda p: "If the sum of the list is even, negate every element; otherwise leave the list unchanged.",
     _r_negate_if_even_sum),
    ("insert_len",
     lambda rng, L: {"p": rng.randint(1, 6)},
     lambda p: f"Insert the CURRENT length of the list as a new element after position {p['p']} "
               f"(1-indexed; if the list is shorter than {p['p']}, append it at the end).",
     _r_insert_len),
    ("drop_last_if_odd_count",
     lambda rng, L: {},
     lambda p: "If the list currently has an odd number of elements, remove the last element.",
     _r_drop_last_if_odd_count),
    ("sort_prefix",
     lambda rng, L: {"h": rng.randint(3, 6)},
     lambda p: f"Sort the first {p['h']} elements in ascending order; the rest of the list is untouched.",
     _r_sort_prefix),
]
_RULE_BY_NAME = {name: (spec, fn) for name, _, spec, fn in RULES}


def reference(rule_list: list[tuple[str, dict]], xs: list[int]) -> list[int]:
    out = list(xs)
    for name, params in rule_list:
        _, fn = _RULE_BY_NAME[name]
        out = fn(params, out)
    return out


def gen_instance(
    *,
    n_rules: int,
    master_seed: int,
    set_name: str,
    level_idx: int,
    index: int,
) -> Instance:
    seed = seed_for(master_seed, "code", set_name, level_idx, index)
    rng = random.Random(seed)
    t0 = time.perf_counter()
    L = rng.randint(*LIST_LEN)
    rule_list: list[tuple[str, dict]] = []
    for _ in range(n_rules):
        name, gen_p, _, _ = RULES[rng.randrange(len(RULES))]
        rule_list.append((name, gen_p(rng, L)))
    tests: list[list[list[int]]] = []
    for _t in range(N_TESTS):
        xs = [rng.randint(*VAL_RANGE) for _ in range(rng.randint(*LIST_LEN))]
        tests.append([xs, reference(rule_list, xs)])
    specs = [_RULE_BY_NAME[name][0](params) for name, params in rule_list]
    return Instance(
        instance_id=instance_id_for("code", set_name, level_idx, index, master_seed),
        family="code",
        task_version=TASK_VERSION,
        set_name=set_name,
        level_idx=level_idx,
        level_value=float(n_rules),
        params={"n_rules": n_rules},
        payload={"rules": [[n, p] for n, p in rule_list], "specs": specs},
        witness=tests,
        seed=seed,
        gen_ms=(time.perf_counter() - t0) * 1000,
    )


def render_prompt(inst: Instance) -> str:
    lines = [
        CANARY,
        "Implement a Python function `transform(xs)` that takes a list of integers and",
        f"applies the following {inst.params['n_rules']} rules IN ORDER, each rule operating on the",
        "result of the previous one:",
    ]
    for i, spec in enumerate(inst.payload["specs"], 1):
        lines.append(f"{i}. {spec}")
    lines += [
        "",
        "Reply with a single fenced Python code block containing the complete function:",
        "```python",
        "def transform(xs):",
        "    ...",
        "```",
    ]
    return "\n".join(lines)


_FENCE_RE = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.S)


def extract_code(text: str) -> str | None:
    """Last fenced block containing `def transform`; else last bare
    `def transform` to end of text."""
    blocks = [b for b in _FENCE_RE.findall(text) if "def transform" in b]
    if blocks:
        return blocks[-1]
    i = text.rfind("def transform")
    return text[i:] if i >= 0 else None


_HARNESS = """
import json, sys
ns = {}
try:
    exec(sys.argv[1], ns)
    fn = ns["transform"]
    results = []
    for xs, want in json.loads(sys.argv[2]):
        got = fn(list(xs))
        results.append(list(got) == list(want))
    print(json.dumps({"ok": all(results), "per_test": results}))
except Exception as e:
    print(json.dumps({"ok": False, "error": type(e).__name__}))
"""


def run_tests(code: str, tests: list) -> dict:
    try:
        r = subprocess.run(
            [sys.executable, "-I", "-c", _HARNESS, code, json.dumps(tests)],
            capture_output=True, text=True, timeout=EXEC_TIMEOUT_S,
        )
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (subprocess.TimeoutExpired, json.JSONDecodeError, IndexError):
        return {"ok": False, "error": "timeout_or_no_output"}


def score(inst: Instance, text: str) -> str:
    """-> 'pass' | 'fail_wrong' | 'fail_parse'"""
    code = extract_code(text)
    if code is None:
        return "fail_parse"
    return "pass" if run_tests(code, inst.witness).get("ok") else "fail_wrong"
