# Next steps

This is the operational handoff for the registered MiniMax confidence study.

## 1. Finish the active batch without changing its code

Leave the existing version 1 `minimax-confidence-v1` process on commit
`8eb0da5` running until one registered stop condition is reached:

- 60 correct and 60 silently wrong completed calls;
- 600 main-stage calls; or
- USD 38 main-stage spend.

Do not inspect prospective Brier skill, AUROC, calibration, or feature effects
while collection is active. Outcome counts and spend are allowed operational
checks.

Version 2's checked-in config is locked and will refuse to collect into this
stage.

## 2. Run the post-sentinel with version 1

After the main writer stops, use the original checkout and code:

```bash
.venv/bin/drc run-stage minimax-confidence-sentinel-post
```

Require six pre-sentinel and six post-sentinel calls, zero provider mismatches,
and the pinned Parasail endpoint. If continuity fails, report the deviation
before any efficacy analysis.

## 3. Freeze one database snapshot

Stop all database writers, checkpoint SQLite, and make a copy for analysis:

```bash
sqlite3 data/drc.sqlite 'PRAGMA wal_checkpoint(FULL);'
shasum -a 256 data/drc.sqlite
```

Record the checksum publicly before the one-look analysis. Copy that exact
snapshot into the version 2 workspace as `data/drc.sqlite`.

## 4. Verify readiness without looking at effects

```bash
drc status
drc next
```

`protocol.ready` must be true. The status output may show counts, spend, and
provider continuity, but not confidence metrics.

## 5. Take the single prospective look

```bash
drc analyze \
  --frozen analysis/confidence-minimax-frozen.json \
  --out analysis/confidence-minimax-prospective.json \
  --predictions analysis/confidence-minimax-prospective-predictions.jsonl
```

The command refuses to run early, refuses missing sentinels, and refuses to
overwrite an existing result. Publish the result, predictions, database
checksum, spend, and deviations together.

The claim passes only if Brier skill is at least 10%, its instance-bootstrap
95% interval excludes zero, and AUROC is at least 0.75.

## 6. Branch once, according to the frozen result

If the claim fails:

- label it **Not supported**;
- update the research page and paper;
- stop. Streaming remains unauthorized.

If the claim passes:

- label it **Supported**;
- commit a separate streaming protocol before calls;
- implement only the telemetry needed for time to first token, reasoning and
  answer channel timing, inter-chunk gaps, and observed output rate;
- enforce a separate USD 10 cap;
- run a no-effect-look instrumentation smoke before any hypothesis test.

Version 2 intentionally contains no streaming collection path yet. Passing the
prospective gate authorizes designing that small path; it does not authorize a
general router, model council, or trace-feature search.

## 7. Publish the final checkpoint

```bash
drc export --out data/exports/prospective-v1
sh paper/build.sh
sh research/build.sh
```

Then run tests, verify all manifest checksums, secret-scan released artifacts,
render every PDF page, inspect the website at desktop and mobile widths, and
merge the result without rewriting the registered interpretation.

## GLM replication decision

The existing GLM-5 pilot has been audited at zero spend. It contains 14 calls,
five silent errors, three unpinned provider routes, and no difficulty level
with both correct and silently wrong outcomes. It is **Censored** as a
confidence replication.

Do not pool those calls into MiniMax and do not fit a GLM confidence model to
them. A paid replication requires explicit decisions about the exact GLM
checkpoint, one pinned provider, frontier levels, stopping counts, and a new
budget.

Those decisions were subsequently frozen for a modern `z-ai/glm-5.2` scout.
The ten-call StreamLake-only scout produced four correct completions, zero
silent errors, and six loud failures for USD 0.281850. It failed its
cohort-discovery gate, so the registered thirty-call focus batch was not run.

Do not fit a confidence model to this scout. Any further GLM-5.2 calls require
a new reliability protocol that decides whether to increase the token cap,
lower reasoning effort, or change the output contract. That protocol must not
retroactively reinterpret the completed scout.

A 262,144-token follow-up on the same ten instances is now registered through
SiliconFlow with a USD 12 hard cap. It changes both provider and token cap
because StreamLake cannot serve 256K completions, so it is not a cap-only
comparison. Collection remains blocked until the exposed OpenRouter key is
rotated and `/Users/posix4e/src/.env-or` is replaced.
