---
title: "Trace-Triggered Speculative Councils: Protocol v0"
subtitle: "A registered design for confidence as a control signal"
author: "Alex Newman"
date: "12 July 2026"
lang: en-GB
---

> **Frozen design; replay result: Not supported.** This document registered a
> proposed comparison before replay. The dated outcome addendum below records
> the failed zero-spend gate without changing its criteria. No speculative
> council calls were made. The frozen MiniMax confidence study is unchanged and
> continues under its own budget.

## Research question

For non-trivial tasks with an independently checkable completion condition,
can a live trace-risk policy launch backup models early enough to preserve the
quality of an always-on model council while reducing latency and billed work?

This is **speculative execution**, not ordinary answer ensembling. A model
council normally obtains several completed answers and ranks, votes, or fuses
them. The proposed controller begins with one observable primary, launches
challengers only after persistent evidence of trouble, accepts the first
candidate that passes an external verifier, and requests cancellation of the
losers. Council synthesis is an exception path after the race produces no
acceptable candidate.

![Trace-triggered speculative execution.](figs/speculative-council.svg)

## System under test

- **Primary:** an OpenAI-compatible GLM endpoint with streamed reasoning.
- **Challengers:** a fast Grok endpoint and an OpenAI frontier endpoint.
- **Handoff:** the original task, prior messages, tool results, files read,
  workspace revision, and policy metadata. Hidden chain of thought is not
  copied between providers.
- **Side effects:** paused before challenger launch. Candidates work in
  read-only lanes or isolated worktrees. Only an elected candidate may commit
  external changes.
- **Verification:** task-specific tests, certificates, schemas, or an external
  command. First-answer-wins is excluded from the primary study.
- **Cancellation:** cancellation requested, transport closure observed, and
  final reported usage are distinct events. Closing a stream is not assumed
  to stop provider billing immediately.

The named models are an initial operating point, not a claim that this ordering
is universally optimal. Routing must be re-measured by task family, provider,
and date.

## Frozen live-risk policy

Version 0 uses a small rolling dictionary over reasoning-channel text:

- backtracking markers;
- hedging and inability-to-verify markers;
- explicit give-up markers;
- repeated four-word shingles.

The score is evaluated over the last 320 words after at least 80 reasoning
words. The launch threshold is 4.0 and must be exceeded on two consecutive
observations. A single word such as "maybe" cannot trigger a hedge. These are
engineering defaults for offline replay, not validated production thresholds.

The policy emits its component counts, total score, words observed, and trigger
time. Feature embeddings, free-form model judges, and post-hoc threshold search
are excluded from v0.

## Comparator arms

Tasks are assigned by generated instance or repository task, never by model
call. All arms receive the same frozen context.

1. **GLM only:** wait for the primary and apply the same verifier.
2. **Always-on council:** launch GLM, Grok, and OpenAI together; wait for all
   configured candidates and synthesize or rank their completed answers.
3. **Fixed-delay hedge:** launch GLM, then launch both challengers after a
   pre-registered elapsed-time threshold if no verified result exists.
4. **Trace-triggered hedge:** launch challengers only when the frozen live-risk
   policy fires; otherwise allow GLM to finish alone.

If the primary completes but fails verification, both hedge arms launch their
challengers regardless of whether the earlier trigger fired. This is recorded
as post-completion fallback rather than early warning.

## Endpoints

Correctness is a gate, not a latency trade. A hedge arm is eligible for an
efficiency claim only if its task success is non-inferior to the always-on
council within a pre-registered margin.

Primary endpoints:

1. p95 wall time per verified successful task;
2. billed cost per verified successful task;
3. verified task success rate.

Secondary endpoints are median latency, time from primary start to hedge,
false-hedge rate, fraction of work cancelled, tokens observed before
cancellation, final provider-reported usage, verifier rejection rate, council
fallback rate, and winner share by task family.

The causal comparison for the trace is trace-triggered versus fixed-delay
hedging at matched challenger-launch rate. Always-on council answers whether
conditional fan-out preserves ensemble quality; GLM-only measures the value
and cost of any fan-out.

## Offline gate before spend

Replay timestamped historical traces without making API calls. For every
completed primary trace, simulate when the frozen policy would have launched
challengers. Proceed to a live pilot only if all of the following hold:

- at least 30 eligible tasks and 10 primary failures are present;
- the trace trigger precedes primary termination on at least 60% of failures;
- median simulated warning time is at least 15 seconds;
- false hedges occur on no more than 40% of verified primary successes;
- a matched-rate fixed-delay baseline is frozen before the live comparison.

Failure stops the live branch and is reported as **Not supported**. A separate
budget and one-look stopping rule must be registered before any live council
or hedge calls. No spend is authorised by this v0 document.

## Outcome addendum: 12 July 2026

**Not supported; timing censored; live branch stopped.** The executable policy
was replayed in frozen 40-word proxy chunks over all 89 historical calls with a
visible reasoning trace: 39 correct completions, 12 silently wrong completions,
and 38 loud failures.

- The trigger fired on 84 of 89 calls: 94.4% fan-out.
- It caught all 50 failures, including every silently wrong completion.
- It also fired on 34 of 39 correct completions: 87.2% false hedges, above the
  registered 40% ceiling.
- A completion-latency timer matched to the 94.4% launch rate also caught every
  failure.

Sensitivity replays at 20, 40, 80, and 160 words per proxy observation all
failed the non-timing gate. The coarsest setting reduced false hedges only to
51.3% while reducing failure recall to 88.0%. The failure is therefore not an
artifact of the reported 40-word proxy alone.

The old trace export contains full reasoning text but no timestamped chunks.
Trigger position was therefore replayed by delivered word count, and the
15-second warning-time condition is **Censored**. A proportional timing proxy
is published for diagnosis but cannot pass the gate. The false-hedge condition
fails without it, so the paid live comparison is not run and v0 is not retuned.

Reproducible artifacts: `analysis/speculative-replay.json` and
`analysis/speculative-replay-predictions.jsonl`. The exact replay and harness
source remains in Git history at commit `7cca5c9`. New API spend: USD 0.

## Safety and accounting invariants

- Candidate tasks never share a writable checkout.
- The pause hook runs once, before challenger launch.
- A winner is elected only after the same external verifier used by all arms.
- Unfinished tasks receive cancellation requests and are awaited to transport
  closure; absence of a final usage record is not recorded as zero cost.
- Worst-case authorised model cost, including a possible council judge, must
  fit below the run cap before the first request is admitted.
- Prompts and handoff context are secret-scanned before public release. Raw
  traces remain a separate checksummed artifact.

## Archived implementation

Version 1 released the `drc hedge` harness and the complete four-arm experiment
runner before replay. Their dry-run interface performed model, verifier, and
worst-case budget admission without making calls:

```sh
drc hedge \
  --prompt-file task.md \
  --primary or/glm-5 \
  --challenger or/grok-4-fast \
  --challenger or/gpt-5.5 \
  --verify-command './verify-answer' \
  --cap 5 \
  --out data/hedge/run.json \
  --dry-run
```

The failed gate closed this branch before live use. Version 2 therefore removes
the speculative controller from the executable product surface. The historical
commit preserves the implementation for audit, while the current CLI offers no
hedge or council command. This prevents a registered negative experiment from
quietly becoming a production feature.

## Positioning

[LLM-Blender](https://aclanthology.org/2023.acl-long.792/) ranks and fuses
completed outputs, while [Mixture-of-Agents](https://arxiv.org/abs/2406.04692)
passes multiple model outputs into later aggregation layers. Those are council
or ensemble designs. The systems analogue is a
[hedged request](https://research.google/pubs/the-tail-at-scale/): start a
secondary request when the primary looks slow and cancel outstanding replicas
after one succeeds. This protocol replaces a fixed time-only hedge trigger
with a small, auditable signal from the primary model's unfolding trajectory.
