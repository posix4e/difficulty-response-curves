"""No gateway key ever ships: scan every tracked file for live key material.

Round 1 leaked a key into session transcripts once (scrubbed since). The
repo and its data exports are published wholesale, so this guard runs with
the suite — a real key in any tracked file fails the build before any
commit or publish can carry it. Patterns require 20+ key characters after
the vendor prefix so the regex *literals* in probe/analysis code (which
mention the prefix) don't trip it.
"""

import re
import subprocess
import gzip
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEY = re.compile(rb"sk-(?:tr|or)-[A-Za-z0-9_-]{20,}")


def tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    return [ROOT / line for line in out.splitlines()]


def test_no_gateway_keys_in_tracked_files():
    offenders = []
    for path in tracked_files():
        if not path.is_file():
            continue
        raw = path.read_bytes()
        if path.suffix == ".gz":
            try:
                raw = gzip.decompress(raw)
            except (gzip.BadGzipFile, EOFError):
                pass
        if KEY.search(raw):
            offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, f"gateway key material in tracked files: {offenders}"
