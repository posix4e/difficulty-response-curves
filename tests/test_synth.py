from drc.tasks import code, synth
from drc.tasks.base import CANARY

from test_code import _solution_source


def _inst(n_rules=3, index=0):
    return synth.gen_instance(
        n_rules=n_rules, master_seed=42, set_name="t", level_idx=0, index=index
    )


def test_determinism():
    a, b = _inst(), _inst()
    assert a.instance_id == b.instance_id
    assert a.payload == b.payload
    assert a.witness == b.witness
    assert _inst(index=1).payload != a.payload


def test_examples_and_tests_match_reference():
    inst = _inst(n_rules=5)
    rules = [(n, p) for n, p in inst.payload["rules"]]
    for xs, want in inst.payload["examples"] + inst.witness:
        assert code.reference(rules, xs) == want


def test_examples_disjoint_from_hidden_tests():
    inst = _inst(n_rules=4)
    example_inputs = {tuple(xs) for xs, _ in inst.payload["examples"]}
    for xs, _ in inst.witness:
        assert tuple(xs) not in example_inputs


def test_correct_solution_passes():
    inst = _inst(n_rules=6)
    reply = "I studied the examples.\n```python\n" + _solution_source(inst) + "\n```\n"
    assert synth.score(inst, reply) == "pass"


def test_identity_fails():
    inst = _inst(n_rules=3)
    assert synth.score(inst, "```python\ndef transform(xs):\n    return list(xs)\n```") == "fail_wrong"
    assert synth.score(inst, "no code, just vibes") == "fail_parse"


def test_prompt_shows_examples_not_rules():
    inst = _inst(n_rules=4)
    prompt = synth.render_prompt(inst)
    assert CANARY in prompt
    assert prompt.count("] -> [") == synth.N_EXAMPLES
    # the hidden pipeline must not leak into the prompt
    for word in ("Rotate", "Swap", "Sort", "negate", "Insert"):
        assert word not in prompt
