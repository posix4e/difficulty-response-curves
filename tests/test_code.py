import pytest

from drc.tasks import code
from drc.tasks.base import CANARY


def _inst(n_rules=6, index=0):
    return code.gen_instance(
        n_rules=n_rules, master_seed=42, set_name="t", level_idx=0, index=index
    )


def test_determinism():
    a, b = _inst(), _inst()
    assert a.instance_id == b.instance_id
    assert a.payload == b.payload
    assert a.witness == b.witness
    assert _inst(index=1).payload != a.payload or _inst(index=1).witness != a.witness


def test_reference_rules_hand_checked():
    assert code._r_diff_left({}, [3, 5, 2]) == [3, 2, -3]
    assert code._r_insert_len({"p": 2}, [7, 8, 9]) == [7, 8, 3, 9]
    assert code._r_insert_len({"p": 9}, [7, 8]) == [7, 8, 2]
    assert code._r_negate_if_even_sum({}, [1, 3]) == [-1, -3]
    assert code._r_negate_if_even_sum({}, [1, 2]) == [1, 2]
    assert code._r_rotate({"k": 2}, [1, 2, 3, 4, 5]) == [4, 5, 1, 2, 3]
    assert code._r_reverse_seg({"i": 2, "j": 4}, [1, 2, 3, 4, 5]) == [1, 4, 3, 2, 5]
    assert code._r_reverse_seg({"i": 9, "j": 12}, [1, 2]) == [1, 2]
    assert code._r_swap_pairs({}, [1, 2, 3, 4, 5]) == [2, 1, 4, 3, 5]
    assert code._r_max_front({}, [3, 9, 1, 9]) == [9, 3, 1, 9]
    assert code._r_sort_prefix({"h": 3}, [5, 1, 4, 0]) == [1, 4, 5, 0]
    assert code._r_drop_last_if_odd_count({}, [1, 2, 3]) == [1, 2]
    assert code._r_add_odd_pos({"v": 2}, [1, 1, 1, 1]) == [3, 1, 3, 1]


def test_witness_matches_reference():
    inst = _inst(n_rules=8)
    rules = [(n, p) for n, p in inst.payload["rules"]]
    for xs, want in inst.witness:
        assert code.reference(rules, xs) == want


def _solution_source(inst) -> str:
    """Emit a standalone correct solution by inlining the rule pipeline."""
    lines = ["def transform(xs):", "    xs = list(xs)"]
    for name, p in inst.payload["rules"]:
        if name == "rotate":
            lines.append(f"    k = {p['k']} % len(xs) if xs else 0")
            lines.append("    xs = xs[-k:] + xs[:-k] if k else xs")
        elif name == "reverse_seg":
            i, j = p["i"], p["j"]
            lines.append(f"    xs = xs if {i} > len(xs) else xs[:{i}-1] + xs[{i}-1:min({j},len(xs))][::-1] + xs[min({j},len(xs)):]")
        elif name == "swap_pairs":
            lines.append("    xs = [xs[a+1] if a%2==0 and a+1<len(xs) else (xs[a-1] if a%2==1 else xs[a]) for a in range(len(xs))]")
        elif name == "add_odd_pos":
            lines.append(f"    xs = [x + {p['v']} if i % 2 == 0 else x for i, x in enumerate(xs)]")
        elif name == "diff_left":
            lines.append("    xs = [xs[0]] + [xs[i] - xs[i-1] for i in range(1, len(xs))]")
        elif name == "max_front":
            lines.append("    m = xs.index(max(xs)); xs = [xs[m]] + xs[:m] + xs[m+1:]")
        elif name == "negate_if_even_sum":
            lines.append("    xs = [-x for x in xs] if sum(xs) % 2 == 0 else xs")
        elif name == "insert_len":
            lines.append(f"    pos = min({p['p']}, len(xs)); xs = xs[:pos] + [len(xs)] + xs[pos:]")
        elif name == "drop_last_if_odd_count":
            lines.append("    xs = xs[:-1] if len(xs) % 2 == 1 else xs")
        elif name == "sort_prefix":
            lines.append(f"    h = min({p['h']}, len(xs)); xs = sorted(xs[:h]) + xs[h:]")
    lines.append("    return xs")
    return "\n".join(lines)


def test_score_correct_solution_passes():
    inst = _inst(n_rules=10)
    reply = "Some reasoning here.\n```python\n" + _solution_source(inst) + "\n```\n"
    assert code.score(inst, reply) == "pass"


def test_score_wrong_solution_fails():
    inst = _inst(n_rules=6)
    reply = "```python\ndef transform(xs):\n    return list(xs)\n```"
    assert code.score(inst, reply) == "fail_wrong"


def test_score_crashing_and_missing_code():
    inst = _inst()
    assert code.score(inst, "```python\ndef transform(xs):\n    return 1/0\n```") == "fail_wrong"
    assert code.score(inst, "I refuse to write code today.") == "fail_parse"


def test_extract_last_block_wins():
    text = ("```python\ndef transform(xs):\n    return []\n```\n wait no \n"
            "```python\ndef transform(xs):\n    return xs\n```")
    assert "return xs" in code.extract_code(text)


def test_prompt_has_canary_and_all_rules():
    inst = _inst(n_rules=9)
    prompt = code.render_prompt(inst)
    assert CANARY in prompt
    assert prompt.count("\n1. ") == 1 and "9. " in prompt
