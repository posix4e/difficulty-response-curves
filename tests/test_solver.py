import random

from drc.tasks.solver import brute_force, check_assignment, dpll_solve, solve


def _random_instance(rng, n_vars, m):
    clauses = []
    while len(clauses) < m:
        vs = rng.sample(range(1, n_vars + 1), 3)
        clauses.append(tuple(sorted(v if rng.random() < 0.5 else -v for v in vs)))
    return clauses


def test_dpll_agrees_with_brute_force():
    rng = random.Random(7)
    for trial in range(500):
        n = rng.randint(4, 12)
        m = rng.randint(2, round(5.5 * n))
        clauses = _random_instance(rng, n, m)
        ref = brute_force(clauses, n)
        got = dpll_solve(clauses, n)
        assert (ref is None) == (got is None), f"trial {trial}: SAT disagreement"
        if got is not None:
            assert check_assignment(clauses, got)


def test_default_solver_agrees_with_brute_force():
    rng = random.Random(11)
    for trial in range(200):
        n = rng.randint(4, 10)
        m = rng.randint(2, round(5.5 * n))
        clauses = _random_instance(rng, n, m)
        ref = brute_force(clauses, n)
        got = solve(clauses, n)
        assert (ref is None) == (got is None), f"trial {trial}: SAT disagreement"
        if got is not None:
            assert check_assignment(clauses, got)


def test_dpll_solves_n50_near_threshold():
    rng = random.Random(3)
    sat_count = 0
    for _ in range(10):
        clauses = _random_instance(rng, 50, 215)  # alpha = 4.3
        result = dpll_solve(clauses, 50)
        if result is not None:
            sat_count += 1
            assert check_assignment(clauses, result)
    # near-threshold: some of each side expected, but no assertion on the split
    assert 0 <= sat_count <= 10
