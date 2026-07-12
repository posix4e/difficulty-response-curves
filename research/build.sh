#!/bin/sh
set -eu
cd "$(dirname "$0")/.."

mkdir -p docs output/pdf tmp/pdfs

pandoc research/program.md \
  --standalone --embed-resources --css research/style.css \
  --metadata title-prefix="Difficulty-Response Curves" \
  --output docs/research.html

pandoc research/studies/minimax-confidence-v1.md \
  --standalone --embed-resources --css research/style.css \
  --metadata title-prefix="Difficulty-Response Curves" \
  --output docs/minimax-confidence-protocol.html

pandoc research/program.md \
  --pdf-engine=typst \
  --variable papersize=a4 \
  --variable margin-top=24mm \
  --variable margin-bottom=24mm \
  --variable margin-left=24mm \
  --variable margin-right=24mm \
  --output output/pdf/confidence-signals-research-program.pdf

pandoc research/studies/minimax-confidence-v1.md \
  --pdf-engine=typst \
  --variable papersize=a4 \
  --variable margin-top=24mm \
  --variable margin-bottom=24mm \
  --variable margin-left=24mm \
  --variable margin-right=24mm \
  --output output/pdf/minimax-confidence-protocol-v1.pdf

cp output/pdf/confidence-signals-research-program.pdf docs/research-program.pdf
cp output/pdf/minimax-confidence-protocol-v1.pdf docs/minimax-confidence-protocol.pdf

if rg -n "<pending>|PLACEHOLDER|TODO" research/program.md research/studies/minimax-confidence-v1.md; then
  echo "research build contains unresolved placeholders" >&2
  exit 1
fi

echo "built research HTML and PDF artefacts"
