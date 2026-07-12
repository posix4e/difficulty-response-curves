#!/bin/sh
set -eu
cd "$(dirname "$0")/.."

mkdir -p paper/figs docs output/pdf
cp analysis/confidence-minimax-ablation.svg paper/figs/
cp analysis/speculative-replay-sensitivity.svg paper/figs/

if rg -n '<pending>|PLACEHOLDER|TODO' paper/paper.typ; then
  echo "paper contains unresolved placeholders" >&2
  exit 1
fi

typst compile --root . paper/paper.typ paper/paper.pdf
cp paper/paper.pdf docs/paper.pdf
cp paper/paper.pdf output/pdf/confidence-signals-paper.pdf
echo "built paper/paper.pdf"
