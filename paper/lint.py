"""Voice lint for the paper source. Fails the build on banned words,
American spellings of the common -our/-ise words, and more than one
"In this work, we".

    .venv/bin/python paper/lint.py paper/paper.typ
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

BANNED = [
    r"\bdelve[sd]?\b",
    r"\bshowcas(?:e[sd]?|ing)\b",
    r"\bleverag(?:e[sd]?|ing)\b",
    r"\blandscape\b",
    r"\bparadigm\b",
    r"\bit is worth noting\b",
    r"\bemergen(?:t|ce)\b",
    r"\bmoreover\b",
    r"\bfurthermore\b",
    r"\bdive into\b",
    r"\bunderscore[sd]?\b",
    r"\bpivotal\b",
    r"\bcrucial\b",
]
# robust is allowed only as a statistics term
ROBUST_OK = re.compile(r"\brobust(?:ness)?\b(?=[^.]*\b(?:standard error|SE|estimator|statistic|cluster)\b)", re.IGNORECASE)
US_SPELLINGS = [
    (r"\bbehavior", "behaviour"),
    (r"\bcolor", "colour"),
    (r"\bmodeling\b", "modelling"),
    (r"\bmodeled\b", "modelled"),
    (r"\bcenter", "centre (in prose)"),
    (r"\banalyze", "analyse"),
    (r"\bsummariz", "summaris"),
    (r"\bcharacteriz", "characteris"),
    (r"\bfavor\b", "favour"),
    (r"\blabeled\b", "labelled"),
]


CODE_LINE = re.compile(
    r"^\s*(#|\.\.|\)|\(|\[\*|let\s|//)|=>|\.at\(|align:|key:|digits:|columns:|stroke:|inset:|table\.header|_center|_ci"
)


def lint(path: Path) -> int:
    text = path.read_text()
    # strip fenced blocks, then any line that looks like typst code rather than prose
    prose = re.sub(r"```.*?```", "", text, flags=re.S)
    prose = "\n".join("" if CODE_LINE.search(l) else l for l in prose.splitlines())
    prose = re.sub(r"json\([^)]*\)", "", prose)
    problems: list[str] = []
    for pat in BANNED:
        for m in re.finditer(pat, prose, re.IGNORECASE):
            line = prose[: m.start()].count("\n") + 1
            problems.append(f"banned word near line {line}: {m.group(0)!r}")
    for m in re.finditer(r"\brobust\w*\b", prose, re.IGNORECASE):
        span = prose[max(0, m.start() - 80): m.end() + 80]
        if not ROBUST_OK.search(span):
            line = prose[: m.start()].count("\n") + 1
            problems.append(f"'robust' outside a statistical sense near line {line}")
    for pat, fix in US_SPELLINGS:
        for m in re.finditer(pat, prose, re.IGNORECASE):
            line = prose[: m.start()].count("\n") + 1
            problems.append(f"US spelling near line {line}: {m.group(0)!r} -> {fix}")
    n_itw = len(re.findall(r"\bIn this work,? we\b", prose, re.IGNORECASE))
    if n_itw > 1:
        problems.append(f"'In this work, we' appears {n_itw} times; the corridor awaits")
    if problems:
        print(f"{path}: {len(problems)} voice problems")
        for p in problems:
            print("  -", p)
        return 1
    print(f"{path}: voice clean")
    return 0


if __name__ == "__main__":
    sys.exit(lint(Path(sys.argv[1] if len(sys.argv) > 1 else "paper/paper.typ")))
