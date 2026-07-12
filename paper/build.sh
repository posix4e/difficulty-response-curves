#!/bin/sh
# Build the paper: sync numbers, regenerate the settings table, lint the
# voice, compile. Run from the repo root: sh paper/build.sh
set -e
cd "$(dirname "$0")/.."
cp analysis/numbers.json paper/numbers.json
cp analysis/traces.json paper/traces.json
# round 2: confirmatory per-call gate + live four-arm race, read by paper.typ
cp analysis/percall-percall.json paper/percall.json
cp analysis/routing2.json paper/routing2.json
cp analysis/percall-judge.json paper/percall-judge.json
cp analysis/percall-consistency.json paper/percall-consistency.json
cp analysis/consistency-synth-gate.json paper/consistency-gate.json
cp analysis/routing3.json paper/routing3.json
cp research/figs/speculative-council.svg paper/figs/speculative-council.svg
cp analysis/speculative-replay.svg paper/figs/speculative-replay.svg
cp analysis/speculative-replay-sensitivity.svg paper/figs/speculative-replay-sensitivity.svg
# live adaptive-run records (C4's live arm), read by paper.typ if present
cp data/adaptive-claude-haiku-4.5.json paper/adaptive-haiku.json 2>/dev/null || echo '{}' > paper/adaptive-haiku.json
cp data/adaptive-o4-mini.json paper/adaptive-o4.json 2>/dev/null || echo '{}' > paper/adaptive-o4.json
.venv/bin/python paper/gen_settings_table.py
.venv/bin/python paper/lint.py paper/paper.typ
typst compile paper/paper.typ paper/paper.pdf
cp paper/paper.pdf docs/paper.pdf
echo "paper/paper.pdf built"
