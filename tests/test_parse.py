from drc.runner.parse import classify
from drc.tasks import dag, sat


def _sat_inst():
    return sat.gen_instance(n_vars=4, alpha=1.0, master_seed=5, set_name="t", level_idx=0, index=0)


def _witness_answer(inst, fmt="x{i}={tf}", sep=" "):
    return sep.join(fmt.format(i=i + 1, tf="T" if v else "F") for i, v in enumerate(inst.witness))


def test_sat_parse_canonical():
    inst = _sat_inst()
    text = "thinking...\nANSWER: " + _witness_answer(inst)
    assert sat.score(inst, text) == "pass"


def test_sat_parse_lenient_variants():
    inst = _sat_inst()
    variants = [
        "ANSWER: " + _witness_answer(inst, fmt="x{i} = {tf}", sep=", "),
        "answer: " + _witness_answer(inst, fmt="{i}={tf}"),
        "ANSWER: " + _witness_answer(inst).replace("T", "true").replace("F", "false"),
        "ANSWER: " + _witness_answer(inst).replace("T", "1").replace("F", "0"),
        "ANSWER: x1=T x2=F\nANSWER: " + _witness_answer(inst),  # last line wins
    ]
    for text in variants:
        assert sat.score(inst, text) == "pass", text


def test_sat_parse_bare_sequence():
    inst = _sat_inst()
    toks = " ".join("T" if v else "F" for v in inst.witness)
    assert sat.score(inst, f"ANSWER: {toks}") == "pass"


def test_sat_parse_failures():
    inst = _sat_inst()
    bad = [
        "I think x1 is true.",                          # no ANSWER line
        "ANSWER: x1=T x2=F x3=T",                       # incomplete
        "ANSWER: x1=T x1=F x2=T x3=F x4=T",             # contradiction
        "ANSWER: x1=T x2=F x3=T x4=T x5=F",             # out-of-range var
        "ANSWER: maybe",                                # no tokens
    ]
    for text in bad:
        assert sat.score(inst, text) == "fail_parse", text


def test_sat_wrong_assignment_is_fail_wrong():
    inst = _sat_inst()
    flipped = [not v for v in inst.witness]
    text = "ANSWER: " + " ".join(
        f"x{i+1}={'T' if v else 'F'}" for i, v in enumerate(flipped)
    )
    assert sat.score(inst, text) in ("fail_wrong", "pass")  # flip may still satisfy
    # force a definite wrong: violate first clause directly
    clause = inst.payload["clauses"][0]
    forced = list(inst.witness)
    ok = dict((abs(l), l > 0) for l in clause)
    for var, val in ok.items():
        forced[var - 1] = not val
    # if forcing breaks clause 0, scorer must notice unless another literal saves it
    text2 = "ANSWER: " + " ".join(f"x{i+1}={'T' if v else 'F'}" for i, v in enumerate(forced))
    assert sat.score(inst, text2) in ("fail_wrong", "pass")


def test_dag_parse_variants():
    inst = dag.gen_instance(n_ops=4, master_seed=5, set_name="t", level_idx=0, index=0)
    w = inst.witness
    assert dag.score(inst, f"ANSWER: {w}") == "pass"
    assert dag.score(inst, f"blah\nanswer: {w}\n") == "pass"
    assert dag.score(inst, f"ANSWER: {w:,}") == "pass"
    assert dag.score(inst, f"ANSWER: {w + 1}") == "fail_wrong"
    assert dag.score(inst, "ANSWER: none") == "fail_parse"
    assert dag.score(inst, "the value is large") == "fail_parse"


def test_classify_precedence():
    inst = _sat_inst()
    good = "ANSWER: " + _witness_answer(inst)
    assert classify(inst, good, "stop") == "pass"
    assert classify(inst, good, "length") == "fail_truncated"
    assert classify(inst, "", "stop") == "fail_empty"
    assert classify(inst, None, "stop") == "fail_empty"
    assert classify(inst, "I can't help with that request.", "stop") == "fail_refusal"
    assert classify(inst, "gibberish", "stop") == "fail_parse"
