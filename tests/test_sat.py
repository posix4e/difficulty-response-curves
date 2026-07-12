from drc.sat import generate, parse_assignment, solve, verify


def test_solver_finds_certificate():
    clauses = ((1, 2, 3), (-1, 2, 3), (1, -2, 3))
    assignment = solve(clauses, 3)
    assert assignment is not None
    assert verify(clauses, assignment)


def test_solver_reports_unsatisfiable():
    assert solve(((1,), (-1,)), 1) is None


def test_generation_is_deterministic_and_satisfiable():
    first = generate(17, 2.0, 6)
    second = generate(17, 2.0, 6)
    assert first == second
    assert verify(first.clauses, first.witness)
    assert len(first.clauses) == 12


def test_parser_requires_exact_final_assignment():
    assert parse_assignment("work\nFINAL: 1 0 1", 3) == (True, False, True)
    assert parse_assignment("work\nFINAL: 101", 3) == (True, False, True)
    assert parse_assignment("FINAL: 1 0", 3) is None
    assert parse_assignment("FINAL: 10", 3) is None
    assert parse_assignment("1 0 1", 3) is None


def test_verifier_rejects_wrong_assignment():
    assert not verify(((1, 2, 3),), (False, False, False))
