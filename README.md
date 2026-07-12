# Can a model tell when it is wrong?

This repository now has one job: run and report a registered per-answer
confidence study.

A difficulty-response curve supplies a baseline probability of correctness.
The study asks whether metadata from one model call - token use, elapsed time,
finish reason, and provider records - improves that probability. Reasoning-text
features and trace-triggered model fan-out were tested, failed their registered
gates, and are not part of the runtime.

- [Plain-language research page](research/program.md)
- [Concise paper](paper/paper.pdf)
- [Frozen MiniMax protocol](research/studies/minimax-confidence-v1.md)
- [GLM-5.2 frontier scout and result](research/studies/glm-5.2-frontier-pilot-v1.md)
- [GLM-5.2 256K reliability follow-up and result](research/studies/glm-5.2-frontier-256k-siliconflow-v1.md)
- [Field journal](docs/journal.html)
- [Next-step runbook](NEXT.md)

## The whole workflow

```text
study.toml -> plan -> collect -> status -> one frozen analysis -> export
                              |
                              +-> correct / silent error / loud failure
```

The package has ten small modules and no plugin framework:

| Module | Responsibility |
|---|---|
| `types.py` | Shared records and the three-outcome taxonomy |
| `config.py` | One TOML study contract and explicit stopping rules |
| `sat.py` | Deterministic SAT generation, solving, parsing, and verification |
| `provider.py` | One pinned OpenRouter adapter |
| `store.py` | SQLite records and resumability |
| `runner.py` | Planning, provider enforcement, budgets, and stopping |
| `analysis.py` | Frozen metadata score and prospective metrics |
| `audit.py` | Recompute released metrics and verify checksums |
| `export.py` | Compact public data and separate raw traces |
| `cli.py` | Eight small commands |

## Install

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

No command reads an API key except `drc run`. The configured provider key is
read only from `OPENROUTER_API_KEY`.

## Commands

```bash
drc plan       # print the frozen design and worst-case admission cost
drc status     # labels, spend, provider continuity, and stopping state
drc run        # collect a newly named study under registered stopping rules
drc analyze    # one prospective read; refuses early or repeated analysis
drc export     # compact metadata plus a separate trace artifact and manifest
drc next       # state the next protocol-authorized action
drc audit      # recompute released metrics and verify frozen checksums
drc audit-model --model z-ai/glm-5  # test whether old calls form an eligible cohort
```

The checked-in `minimax-confidence-v1` config is deliberately
`collection_locked = true`. Its batch began under version 1 and must finish
under that exact collector. Version 2 may analyze it after the post-sentinel
and database snapshot, but must not add calls to its stage.

To start a future study, copy `configs/study.toml`, choose a new study name and
seed, set `collection_locked = false`, review `drc plan`, and commit the new
protocol before making calls.

## Safety invariants

- Provider fallback is disabled and endpoint mismatches stop admission.
- When a spend cap is configured, admission includes in-flight worst-case
  reserves. An unlimited-spend study must say so explicitly and remains bounded
  by its call and token limits.
- `(model, instance, sample, prompt version, stage)` is unique in SQLite.
- Correct completions, silent errors, and loud failures remain separate.
- The prospective command refuses to run before a stopping condition and both
  sentinel checks are present.
- A result file is write-once by default.
- Raw traces are never mixed into the compact public table.

## Tests and artifacts

```bash
PYTHONPATH=src python -m pytest -q
sh paper/build.sh
sh research/build.sh
```

Released data, frozen coefficients, generated figures, protocols, and the
journal are retained as the evidentiary record. Historical router and
speculative-controller code was removed rather than carried as dormant product
surface.

Code is MIT licensed. Research text and released study data are CC BY 4.0,
subject to provider terms.
