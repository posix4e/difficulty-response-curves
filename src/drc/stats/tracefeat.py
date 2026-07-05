"""Per-call trace features, shared between the offline Phase-0 analysis
(analysis/percall.py) and the live trace judge (round 2). One definition,
two consumers - the judge must score exactly what the gate validated.
"""

from __future__ import annotations

import re

BACKTRACK = re.compile(
    r"\b(wait|hmm+|actually|let me (re|try again)|that's wrong|doesn't work|start over|backtrack)\b",
    re.I,
)
HEDGE = re.compile(
    r"\b(probably|not (entirely |completely )?sure|might be|i think|guess|unsure|"
    r"can'?t (find|verify)|cannot (find|verify)|give up|hopefully|approximately|best i can)\b",
    re.I,
)
WAIT = re.compile(r"\bwait\b", re.I)


def shingle_rep(text: str, k: int = 12) -> float:
    words = text.split()
    if len(words) < 3 * k:
        return 0.0
    shingles = [" ".join(words[i : i + k]) for i in range(0, len(words) - k, k)]
    return 1 - len(set(shingles)) / len(shingles)


def split_trace(text: str) -> tuple[str, str]:
    """(trace, answer_region). Uses <think> tags when present."""
    m = re.search(r"<think>(.*?)(?:</think>|$)", text, re.S)
    if m:
        return m.group(1), text[m.end():]
    return (text[:-500] if len(text) > 1000 else text), text[-500:]


GIVEUP = re.compile(
    r"\b(give up|giving up|run(ning)? out|too (hard|complex|difficult)|"
    r"can'?t solve|cannot solve|no solution found|best guess|just guess|"
    r"randomly (pick|assign|choose)|arbitrarily)\b",
    re.I,
)
NEGMARK = re.compile(r"\b(wrong|mistake|error|contradiction|conflict|violat\w+|fails?)\b", re.I)
ANSMARK = re.compile(r"\banswer\b", re.I)


def extra_features(text: str, tokens: int | None) -> dict:
    """Round-3 candidate features. Kept out of features() so the round-2
    seven stay byte-identical for reproducibility."""
    trace, answer = split_trace(text)
    words = trace.split()
    n = len(words)
    tail = " ".join(words[int(n * 0.7):]) if n > 40 else trace
    tail10 = " ".join(words[int(n * 0.9):]) if n > 40 else trace
    kw_full = max(n / 1000.0, 0.1)
    kw_tail = max(len(tail.split()) / 1000.0, 0.1)
    kw_t10 = max(len(tail10.split()) / 1000.0, 0.1)
    kw_ans = max(len(answer.split()) / 1000.0, 0.1)
    return {
        "hedge_ans": len(HEDGE.findall(answer)) / kw_ans,
        "giveup_full": len(GIVEUP.findall(trace + " " + answer)) / kw_full,
        "flip": max(len(ANSMARK.findall(trace)) - 1, 0) / kw_full,
        "qmark_tail": tail.count("?") / kw_tail,
        "rep_tail_k4": shingle_rep(tail, k=4),
        "wait_full": len(WAIT.findall(trace)) / kw_full,
        "bt_last10": len(BACKTRACK.findall(tail10)) / kw_t10,
        "neg_tail": len(NEGMARK.findall(tail)) / kw_tail,
        "len_ratio": (len(trace) + len(answer)) / max((tokens or 1) * 3.7, 1.0),
    }


def features(text: str, tokens: int | None) -> dict:
    trace, answer = split_trace(text)
    words = trace.split()
    n = len(words)
    tail = " ".join(words[int(n * 0.7):]) if n > 40 else trace
    tail15 = " ".join(words[int(n * 0.85):]) if n > 40 else trace
    kw = max(n / 1000.0, 0.1)
    kw_tail = max(len(tail.split()) / 1000.0, 0.1)
    return {
        "rep_full": shingle_rep(trace),
        "rep_tail": shingle_rep(tail),
        "bt_full": len(BACKTRACK.findall(trace)) / kw,
        "bt_tail": len(BACKTRACK.findall(tail)) / kw_tail,
        "wait_tail": len(WAIT.findall(tail)) / kw_tail,
        "hedge_tail": len(HEDGE.findall(tail15 + " " + answer)) / max(len((tail15 + answer).split()) / 1000.0, 0.1),
        "tok": float(tokens or 0),
    }
