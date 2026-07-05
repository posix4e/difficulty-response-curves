"""SAT solving for instance generation. Never used at scoring time.

Chain: pysat (if importable; installed via `pip install --pre python-sat`
on Python 3.14) -> pure-Python DPLL. Both return one satisfying
assignment as a list of bools (index 0 = x1) or None if unsatisfiable.
Clauses are DIMACS-style tuples of nonzero ints; -k means NOT x_k.
"""

from __future__ import annotations

from itertools import product

try:
    from pysat.solvers import Minisat22  # type: ignore

    _HAVE_PYSAT = True
except Exception:  # pragma: no cover - environment dependent
    _HAVE_PYSAT = False

SOLVER_NAME = "pysat-minisat22" if _HAVE_PYSAT else "dpll"


def solve(clauses: list[tuple[int, ...]], n_vars: int) -> list[bool] | None:
    if _HAVE_PYSAT:
        with Minisat22(bootstrap_with=[list(c) for c in clauses]) as s:
            if not s.solve():
                return None
            model = s.get_model()
            out = [False] * n_vars
            for lit in model:
                if abs(lit) <= n_vars:
                    out[abs(lit) - 1] = lit > 0
            return out
    return dpll_solve(clauses, n_vars)


def dpll_solve(clauses: list[tuple[int, ...]], n_vars: int) -> list[bool] | None:
    """DPLL with unit propagation, pure-literal elimination and
    Jeroslow-Wang branching. Fine for n <= 50."""
    assignment: dict[int, bool] = {}
    result = _dpll([list(c) for c in clauses], assignment)
    if result is None:
        return None
    return [result.get(v, False) for v in range(1, n_vars + 1)]


def _simplify(clauses: list[list[int]], lit: int) -> list[list[int]] | None:
    """Assign lit true; drop satisfied clauses, shrink others.
    Returns None on an empty-clause conflict."""
    out: list[list[int]] = []
    for c in clauses:
        if lit in c:
            continue
        if -lit in c:
            reduced = [x for x in c if x != -lit]
            if not reduced:
                return None
            out.append(reduced)
        else:
            out.append(c)
    return out


def _dpll(clauses: list[list[int]], assignment: dict[int, bool]) -> dict[int, bool] | None:
    # Unit propagation
    while True:
        units = [c[0] for c in clauses if len(c) == 1]
        if not units:
            break
        for lit in units:
            var, val = abs(lit), lit > 0
            if var in assignment:
                if assignment[var] != val:
                    return None
                continue
            assignment[var] = val
            nxt = _simplify(clauses, lit)
            if nxt is None:
                return None
            clauses = nxt

    if not clauses:
        return assignment

    # Pure literal elimination
    polarity: dict[int, int] = {}  # var -> bitmask 1=pos seen, 2=neg seen
    for c in clauses:
        for lit in c:
            polarity[abs(lit)] = polarity.get(abs(lit), 0) | (1 if lit > 0 else 2)
    pures = [v if m == 1 else -v for v, m in polarity.items() if m in (1, 2)]
    if pures:
        for lit in pures:
            if abs(lit) in assignment:
                continue
            assignment[abs(lit)] = lit > 0
            nxt = _simplify(clauses, lit)
            if nxt is None:
                return None
            clauses = nxt
        return _dpll(clauses, assignment)

    # Jeroslow-Wang branching: prefer literals frequent in short clauses
    scores: dict[int, float] = {}
    for c in clauses:
        w = 2.0 ** -len(c)
        for lit in c:
            scores[lit] = scores.get(lit, 0.0) + w
    branch = max(scores, key=lambda l: scores[l])

    for lit in (branch, -branch):
        nxt = _simplify(clauses, lit)
        if nxt is None:
            continue
        sub = dict(assignment)
        sub[abs(lit)] = lit > 0
        result = _dpll(nxt, sub)
        if result is not None:
            return result
    return None


def brute_force(clauses: list[tuple[int, ...]], n_vars: int) -> list[bool] | None:
    """Exhaustive reference for tests (n <= ~16)."""
    for bits in product((False, True), repeat=n_vars):
        if all(any((lit > 0) == bits[abs(lit) - 1] for lit in c) for c in clauses):
            return list(bits)
    return None


def check_assignment(clauses: list[tuple[int, ...]], assignment: list[bool]) -> bool:
    return all(any((lit > 0) == assignment[abs(lit) - 1] for lit in c) for c in clauses)
