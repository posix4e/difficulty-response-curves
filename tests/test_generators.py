from drc.tasks import dag, sat
from drc.tasks.solver import check_assignment


def test_sat_generation_deterministic():
    kwargs = dict(n_vars=20, alpha=4.3, master_seed=42, set_name="main", level_idx=9, index=3)
    a = sat.gen_instance(**kwargs)
    b = sat.gen_instance(**kwargs)
    assert a.payload == b.payload
    assert a.instance_id == b.instance_id
    assert a.witness == b.witness


def test_sat_instances_differ_across_sets_and_indices():
    base = dict(n_vars=20, alpha=4.3, master_seed=42, level_idx=9)
    a = sat.gen_instance(set_name="main", index=0, **base)
    b = sat.gen_instance(set_name="retest", index=0, **base)
    c = sat.gen_instance(set_name="main", index=1, **base)
    assert a.payload != b.payload
    assert a.payload != c.payload


def test_sat_witness_satisfies_and_clause_shape():
    inst = sat.gen_instance(n_vars=20, alpha=5.6, master_seed=1, set_name="t", level_idx=14, index=0)
    clauses = [tuple(c) for c in inst.payload["clauses"]]
    assert len(clauses) == round(5.6 * 20)
    assert len(set(clauses)) == len(clauses)  # no duplicate clauses
    for c in clauses:
        assert len({abs(l) for l in c}) == 3  # distinct variables
    assert check_assignment(clauses, inst.witness)


def test_sat_prompt_contains_canary_and_format_line():
    inst = sat.gen_instance(n_vars=20, alpha=3.0, master_seed=1, set_name="t", level_idx=4, index=0)
    p = sat.render_prompt(inst)
    assert "canary" in p
    assert "ANSWER:" in p
    assert "This instance is satisfiable." in p
    clause_lines = [l for l in p.splitlines() if l.startswith("(") and " OR " in l]
    assert len(clause_lines) == inst.params["m_clauses"]


def test_dag_deterministic_and_depth_chain():
    kwargs = dict(n_ops=42, master_seed=42, set_name="main", level_idx=9, index=3)
    a = dag.gen_instance(**kwargs)
    b = dag.gen_instance(**kwargs)
    assert a.payload == b.payload and a.witness == b.witness
    # chain property: op j consumes node (n_leaves + j - 1)
    n_leaves = a.params["n_leaves"]
    for j, (op, left, right) in enumerate(a.payload["ops"]):
        assert left == n_leaves + j - 1
        assert 0 <= right < n_leaves + j
    assert a.witness == dag.evaluate(a)


def test_dag_magnitudes_bounded():
    for n_ops in (2, 9, 21, 42):
        for idx in range(20):
            inst = dag.gen_instance(n_ops=n_ops, master_seed=7, set_name="t", level_idx=0, index=idx)
            values = list(inst.payload["leaves"])
            for op, left, right in inst.payload["ops"]:
                values.append(dag._apply(op, values[left], values[right]))
            assert all(abs(v) <= 999 for v in values)


def test_dag_prompt_renders_result_line():
    inst = dag.gen_instance(n_ops=6, master_seed=7, set_name="t", level_idx=1, index=0)
    p = dag.render_prompt(inst)
    assert "result =" in p
    assert "ANSWER: <integer>" in p
    n_lines = len([l for l in p.splitlines() if "=" in l and "ANSWER" not in l])
    assert n_lines == inst.params["n_leaves"] + inst.params["n_ops"]
