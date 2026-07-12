# Difficulty–Response Curves: A Form Guide for Reasoning Models

Ask where a reasoning model stops being able to reason and the honest answer
today is a shrug and a leaderboard number. This repo does better with old
tools: item response theory, pointed at language models.

We sweep procedurally generated tasks with a scalar difficulty knob — random
3-SAT across the clause-to-variable ratio, depth-controlled DAG arithmetic as
a second opinion — draw repeated samples per instance, and fit two-parameter
logistic difficulty–response curves. Each model gets a datasheet: a frontier
**x50** (the difficulty where its pass rate crosses one half) and a sharpness
**a**, both with cluster-bootstrap confidence intervals.

- **Living research programme**: [`research/program.md`](research/program.md) · **Frozen MiniMax protocol**: [`research/studies/minimax-confidence-v1.md`](research/studies/minimax-confidence-v1.md)
- **Paper**: [`paper/paper.pdf`](paper/paper.pdf) · **Site**: https://posix4e.github.io/difficulty-response-curves/
- **Raw data**: every API call, released as JSONL.gz in [Releases](../../releases) with a sha256 manifest.
- **Everything below is reproducible**: `analysis/run_analysis.py` regenerates
  every number in the paper from the raw data; the abstract's numbers are read
  from `analysis/numbers.json` at compile time, not typed in.

## Measure your own model

You need an OpenAI-compatible endpoint. We used [TrustedRouter](https://trustedrouter.com);
anything that speaks `POST /v1/chat/completions` works with a base-URL change
in `src/drc/runner/client.py`.

```bash
python3 -m venv .venv && .venv/bin/pip install -e .
export TRUSTEDROUTER_API_KEY=sk-tr-...        # or drop a key file at ~/src/.env-tr

# add your model to configs/models.toml, then:
.venv/bin/drc sweep --model openai/gpt-oss-20b --grid sat-n20-main \
    --instances 15 --k 4 --cap 2.0            # hard dollar cap, enforced per call

.venv/bin/drc fit --model openai/gpt-oss-20b --sets adhoc --stages adhoc \
    --bootstrap 2000 --gof                    # frontier + sharpness with CIs

.venv/bin/drc adaptive --model openai/gpt-oss-20b --cap 2.0   # find x50 the fast way
.venv/bin/drc budget                          # where every microdollar went
```

The sweep is resumable: kill it, rerun the same command, and finished calls
are never repeated (idempotency key in SQLite). Failed transport calls retry
on the next run. Every call records tokens, cost in microdollars, and the
provider endpoint that actually served it.

## What is in the box

| path | what |
|---|---|
| `src/drc/tasks/` | instance generators + verifiers (pure, no I/O): satisfiable-only 3-SAT with certificate scoring; depth-controlled DAG arithmetic |
| `src/drc/runner/` | async runner: AIMD concurrency, provider pinning, budget guard with in-flight reserve, SQLite store |
| `src/drc/stats/` | penalized 2PL+lapse MLE, stratified cluster bootstrap, variance decomposition (C2), token-effort peak (C3), reliability (C1) |
| `src/drc/adaptive/` | bracket-then-refine frontier search (C4), simulator + live runner |
| `configs/` | model roster (prices, pins, caps), difficulty grids, stage designs |
| `analysis/` | `run_analysis.py` → `numbers.json`; figure scripts |
| `paper/` | Typst source; compiles against `analysis/numbers.json` |
| `docs/` | the GitHub Pages site |

## Protocol notes (the short version)

- **Guess-proof scoring.** SAT instances are rejection-sampled to be
  satisfiable and the model must output a full assignment; a pass is a
  checked certificate, not a label match. No guessing floor, so the curve
  needs no third parameter.
- **Parse failures count as failures**, disclosed per model; truncation is
  counted, disclosed, and flags any contaminated cell.
- **Provider pinned** per model (`provider.only`), endpoint recorded per call.
- **Budget is enforced, not estimated**: the runner admits a call only if the
  ledger plus in-flight reserve stays under the cap.
- **Contamination**: every instance is freshly generated from named seed
  streams; a fixed canary string rides in every prompt.

## Tests

```bash
.venv/bin/python -m pytest    # 37 tests: solver vs brute force, parse fixtures,
                              # fit recovery on synthetic data, budget caps, kill/resume
```

## License

Code is MIT licensed. Research text and released study data are CC BY 4.0,
subject to provider terms. See [`LICENSE`](LICENSE) and
[`LICENSE-RESEARCH.md`](LICENSE-RESEARCH.md).
