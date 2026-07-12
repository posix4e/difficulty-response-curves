# Version 2 migration

Version 2 is a deliberate contraction of scope. It preserves evidence, not
every experimental implementation.

## Command mapping

| Version 1 | Version 2 | Decision |
|---|---|---|
| `run-stage` and `sweep` | `run` | One runner and one study contract |
| `budget` | `status` | Spend belongs beside labels and provider checks |
| `analysis/confidence.py` | `analyze` | Frozen prospective analysis only |
| ad hoc export scripts | `export` | Deterministic compact/traces split |
| `hedge` and `council-experiment` | none | Frozen v0 gate failed; runtime removed |
| adaptive and router commands | none | Historical evidence only |
| multiple task families | SAT only | The registered confidence study uses SAT |

## Data compatibility

Version 2 reads the version 1 SQLite `instances` and `calls` columns used by
the MiniMax analysis. Copy the database only after its writer stops and the WAL
is checkpointed. Version 2 does not need hidden API keys or request headers to
analyze it.

Version 2 must not resume the in-flight v1 stage. The generator and prompt are
new implementations, so mixing their calls under the old study name would be
a protocol violation. The checked-in config enforces this with
`collection_locked = true`.

## Preserved evidence

These remain canonical and unchanged:

- `analysis/confidence-minimax.json` and the frozen coefficient file;
- compact and raw-trace exports with their checksums;
- the speculative replay result and sensitivity figure;
- both frozen protocols;
- the field journal and historical site pages.

The 13-page form-guide paper is replaced by a short confidence report. Old
router, consistency, and adaptive result JSON files remain available as
historical artifacts, but no runtime command depends on them.
