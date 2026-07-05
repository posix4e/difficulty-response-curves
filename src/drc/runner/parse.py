"""Outcome classification: task scoring plus transport-level pathologies.

Order of precedence (first match wins):
  error_api      -> transport failed after retries; excluded from fits
  fail_truncated -> finish_reason=length (incl. thinking budget burned dry)
  fail_empty     -> no visible text at all
  fail_refusal   -> no ANSWER line and refusal phrasing present
  fail_parse / fail_wrong / pass -> family scorer
"""

from __future__ import annotations

import re

from ..tasks import families
from ..tasks.base import Instance

_REFUSAL_RE = re.compile(
    r"\b(i can(?:no|[''’])t (?:help|assist|comply|solve)|i won[''’]t be able"
    r"|i[''’]m (?:not able|unable) to|i am (?:not able|unable) to"
    r"|i cannot (?:help|assist|provide|comply|solve)|against my (?:guidelines|policies)"
    r"|i must (?:decline|refuse))",
    re.IGNORECASE,
)


def extract_parsed(inst: Instance, text: str) -> str | None:
    """Compact representation of what the parser saw, for debugging/reanalysis."""
    if inst.family == "sat":
        from ..tasks.sat import parse_assignment

        a = parse_assignment(text, inst.params["n_vars"])
        return "".join("T" if v else "F" for v in a) if a is not None else None
    if inst.family == "dag":
        from ..tasks.dag import parse_answer

        v = parse_answer(text)
        return str(v) if v is not None else None
    return None


def classify(inst: Instance, text: str | None, finish_reason: str | None) -> str:
    if finish_reason in ("length", "max_tokens"):
        return "fail_truncated"
    if not text or not text.strip():
        return "fail_empty"
    outcome = families.score(inst, text)
    if outcome == "fail_parse" and _REFUSAL_RE.search(text):
        return "fail_refusal"
    return outcome
