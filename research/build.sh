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
[ -f analysis/glm-5.2-frontier-scout-v1.json ] && cp analysis/glm-5.2-frontier-scout-v1.json docs/data/glm-5.2-frontier-scout-v1.json
[ -f analysis/glm-5.2-frontier-256k-siliconflow-v1.json ] && cp analysis/glm-5.2-frontier-256k-siliconflow-v1.json docs/data/glm-5.2-frontier-256k-siliconflow-v1.json
[ -f analysis/glm-5.2-streaming-smoke-v1.json ] && cp analysis/glm-5.2-streaming-smoke-v1.json docs/data/glm-5.2-streaming-smoke-v1.json
if [ -d data/exports/glm-5.2-frontier-scout-v1 ]; then
  mkdir -p docs/data/glm-5.2-frontier-scout-v1
  cp data/exports/glm-5.2-frontier-scout-v1/* docs/data/glm-5.2-frontier-scout-v1/
fi
if [ -d data/exports/glm-5.2-streaming-smoke-v1 ]; then
  mkdir -p docs/data/glm-5.2-streaming-smoke-v1
  cp data/exports/glm-5.2-streaming-smoke-v1/* docs/data/glm-5.2-streaming-smoke-v1/
fi
if [ -d data/exports/glm-5.2-frontier-256k-siliconflow-v1 ]; then
  mkdir -p docs/data/glm-5.2-frontier-256k-siliconflow-v1
  cp data/exports/glm-5.2-frontier-256k-siliconflow-v1/* docs/data/glm-5.2-frontier-256k-siliconflow-v1/
fi
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

pandoc research/studies/glm-5.2-frontier-pilot-v1.md \
  --resource-path=docs:research:. \
  --standalone --embed-resources --css research/style.css \
  --metadata title-prefix="Difficulty-Response Curves" \
  --output docs/glm-5.2-frontier-pilot.html

pandoc research/studies/glm-5.2-frontier-256k-siliconflow-v1.md \
  --resource-path=docs:research:. \
  --standalone --embed-resources --css research/style.css \
  --metadata title-prefix="Difficulty-Response Curves" \
  --output docs/glm-5.2-frontier-256k-siliconflow.html

pandoc research/studies/glm-5.2-streaming-smoke-v1.md \
  --resource-path=docs:research:. \
  --standalone --embed-resources --css research/style.css \
  --metadata title-prefix="Difficulty-Response Curves" \
  --output docs/glm-5.2-streaming-smoke.html

# Pandoc's default source-code CSS carries trailing spaces on each generated
# rule. Keep checked-in HTML clean and deterministic for Git whitespace checks.
perl -pi -e 's/[ \t]+$//' docs/research.html docs/minimax-confidence-protocol.html docs/speculative-council-protocol.html docs/glm-5.2-frontier-pilot.html docs/glm-5.2-frontier-256k-siliconflow.html docs/glm-5.2-streaming-smoke.html

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

pandoc research/studies/glm-5.2-frontier-pilot-v1.md \
  --resource-path=docs:research:. \
  --pdf-engine=typst \
  --variable papersize=a4 \
  --variable fontsize=10pt \
  --variable margin-top=18mm \
  --variable margin-bottom=18mm \
  --variable margin-left=20mm \
  --variable margin-right=20mm \
  --output output/pdf/glm-5.2-frontier-pilot-v1.pdf

pandoc research/studies/glm-5.2-frontier-256k-siliconflow-v1.md \
  --resource-path=docs:research:. \
  --pdf-engine=typst \
  --variable papersize=a4 \
  --variable fontsize=10pt \
  --variable margin-top=18mm \
  --variable margin-bottom=18mm \
  --variable margin-left=20mm \
  --variable margin-right=20mm \
  --output output/pdf/glm-5.2-frontier-256k-siliconflow-v1.pdf

pandoc research/studies/glm-5.2-streaming-smoke-v1.md \
  --resource-path=docs:research:. \
  --pdf-engine=typst \
  --variable papersize=a4 \
  --variable fontsize=9.5pt \
  --variable margin-top=14mm \
  --variable margin-bottom=14mm \
  --variable margin-left=18mm \
  --variable margin-right=18mm \
  --output output/pdf/glm-5.2-streaming-smoke-v1.pdf

cp output/pdf/confidence-signals-research-program.pdf docs/research-program.pdf
cp output/pdf/minimax-confidence-protocol-v1.pdf docs/minimax-confidence-protocol.pdf
cp output/pdf/speculative-council-protocol-v0.pdf docs/speculative-council-protocol.pdf
cp output/pdf/glm-5.2-frontier-pilot-v1.pdf docs/glm-5.2-frontier-pilot.pdf
cp output/pdf/glm-5.2-frontier-256k-siliconflow-v1.pdf docs/glm-5.2-frontier-256k-siliconflow.pdf
cp output/pdf/glm-5.2-streaming-smoke-v1.pdf docs/glm-5.2-streaming-smoke.pdf

if rg -n "<pending>|PLACEHOLDER|TODO" research/program.md research/studies/*.md; then
  echo "research build contains unresolved placeholders" >&2
  exit 1
fi

echo "built research HTML and PDF artefacts"
