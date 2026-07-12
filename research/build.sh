#!/bin/sh
set -eu
cd "$(dirname "$0")/.."

mkdir -p docs output/pdf tmp/pdfs
mkdir -p docs/data docs/figs

for figure in analysis/confidence-minimax-*.svg; do
  [ -f "$figure" ] && cp "$figure" docs/figs/
done
for figure in analysis/speculative-replay*.svg; do
  [ -f "$figure" ] && cp "$figure" docs/figs/
done
for figure in research/figs/*.svg; do
  [ -f "$figure" ] && cp "$figure" docs/figs/
done
if [ -f analysis/confidence-minimax.json ]; then
  cp analysis/confidence-minimax.json docs/data/confidence-minimax.json
fi
[ -f analysis/speculative-replay.json ] && cp analysis/speculative-replay.json docs/data/speculative-replay.json
[ -f analysis/speculative-replay-predictions.jsonl ] && cp analysis/speculative-replay-predictions.jsonl docs/data/speculative-replay-predictions.jsonl
[ -f analysis/glm-existing-data-audit.json ] && cp analysis/glm-existing-data-audit.json docs/data/glm-existing-data-audit.json
for artifact in data/exports/*; do
  [ -f "$artifact" ] && cp "$artifact" docs/data/
done

pandoc research/program.md \
  --resource-path=docs:research:. \
  --standalone --embed-resources --css research/style.css \
  --metadata title-prefix="Difficulty-Response Curves" \
  --output docs/research.html

pandoc research/studies/minimax-confidence-v1.md \
  --resource-path=docs:research:. \
  --standalone --embed-resources --css research/style.css \
  --metadata title-prefix="Difficulty-Response Curves" \
  --output docs/minimax-confidence-protocol.html

pandoc research/studies/speculative-council-v0.md \
  --resource-path=docs:research:. \
  --standalone --embed-resources --css research/style.css \
  --metadata title-prefix="Difficulty-Response Curves" \
  --output docs/speculative-council-protocol.html

# Pandoc's default source-code CSS carries trailing spaces on each generated
# rule. Keep checked-in HTML clean and deterministic for Git whitespace checks.
perl -pi -e 's/[ \t]+$//' docs/research.html docs/minimax-confidence-protocol.html docs/speculative-council-protocol.html

# The living research page is the public front door. Historical pages remain
# addressable, but the old dashboard is no longer the default explanation.
cp docs/research.html docs/index.html

pandoc research/program.md \
  --resource-path=docs:research:. \
  --pdf-engine=typst \
  --variable papersize=a4 \
  --variable margin-top=24mm \
  --variable margin-bottom=24mm \
  --variable margin-left=24mm \
  --variable margin-right=24mm \
  --output output/pdf/confidence-signals-research-program.pdf

pandoc research/studies/minimax-confidence-v1.md \
  --resource-path=docs:research:. \
  --pdf-engine=typst \
  --variable papersize=a4 \
  --variable margin-top=24mm \
  --variable margin-bottom=24mm \
  --variable margin-left=24mm \
  --variable margin-right=24mm \
  --output output/pdf/minimax-confidence-protocol-v1.pdf

pandoc research/studies/speculative-council-v0.md \
  --resource-path=docs:research:. \
  --pdf-engine=typst \
  --variable papersize=a4 \
  --variable margin-top=24mm \
  --variable margin-bottom=24mm \
  --variable margin-left=24mm \
  --variable margin-right=24mm \
  --output output/pdf/speculative-council-protocol-v0.pdf

cp output/pdf/confidence-signals-research-program.pdf docs/research-program.pdf
cp output/pdf/minimax-confidence-protocol-v1.pdf docs/minimax-confidence-protocol.pdf
cp output/pdf/speculative-council-protocol-v0.pdf docs/speculative-council-protocol.pdf

if rg -n "<pending>|PLACEHOLDER|TODO" research/program.md research/studies/*.md; then
  echo "research build contains unresolved placeholders" >&2
  exit 1
fi

echo "built research HTML and PDF artefacts"
