---
title: "Can a model tell when it is wrong?"
subtitle: "A living study of confidence signals at the MiniMax frontier"
author: "Alex Newman"
date: "13 July 2026"
lang: en-GB
---

<nav class="page-nav" aria-label="Research links">
  <a href="index.html">Research home</a>
  <a href="journal.html">Field journal</a>
  <a href="paper.pdf">Paper</a>
  <a href="minimax-confidence-protocol.html">MiniMax protocol</a>
</nav>

::: {.notice}
**Living research · preliminary · not peer reviewed**

This page separates what the data already support from what is still being
tested. Detailed methods live in the protocols and paper.
:::

::: {.answer}
## The short answer

**Difficulty is a useful starting point. Billing and timing metadata may make
that estimate better. The words in a model's reasoning trace did not.**

A fresh, prospectively registered MiniMax study is now testing whether the
metadata result holds up. A separate idea—launching backup models when the
trace looks troubled—failed its no-spend gate and was stopped.
:::

## The problem in one minute

Suppose a model answers a hard question. We want a number such as:

> There is a 72% chance this answer is correct.

A difficulty-response curve supplies the first estimate: easier tasks should
receive higher confidence than harder ones. But two equally hard calls can
unfold very differently. One may finish cleanly; another may consume its whole
token budget, repeat itself, or backtrack for minutes.

This project asks whether those call-level signals improve the probability of
correctness **for this particular answer**.

::: {.summary-grid}
::: {.summary-card .supported}
### Supported — the baseline

Task difficulty gives a useful prior probability of success.
:::

::: {.summary-card .exploratory}
### Exploratory — metadata

Token use and elapsed time predicted mistakes in old MiniMax calls. Fresh
validation is under way.
:::

::: {.summary-card .not-supported}
### Not supported — trace words

The frozen dictionary of hedging, repetition, backtracking, and give-up
language did not produce a reliable confidence score.
:::

::: {.summary-card .not-supported}
### Not supported — automatic fan-out

The frozen warning policy launched backup models on almost every call, so its
paid experiment was cancelled before spending.
:::

::: {.summary-card .censored}
### Censored — existing GLM calls

The 14 historical GLM-5 calls span three unpinned providers and contain only
five silent errors. They cannot identify a confidence replication.
:::

::: {.summary-card .not-supported}
### Not supported — GLM-5.2 frontier scout

A new ten-call, provider-pinned scout produced four correct completions, no
silent errors, and six loud failures. It did not locate a confidence cohort.
:::

::: {.summary-card .not-supported}
### Not supported — GLM-5.2 256K reliability

The paired SiliconFlow follow-up eliminated token-cap truncation but still
produced four loud failures, exceeding its registered ceiling of two.
:::

::: {.summary-card .supported}
### Supported — GLM streaming transport

A registered one-call smoke carried the previously failing instance through a
complete SiliconFlow stream and retained 29,671 timed events.
:::
:::

## What exactly counts as failure?

The study keeps three outcomes separate:

1. **Correct completion.** The model finishes and the answer passes the task's
   mechanical checker.
2. **Silent error.** The model finishes normally, but the answer is wrong.
3. **Loud failure.** The call truncates, refuses, times out, fails to parse, or
   returns an API error.

The confidence question compares correct completions with silent errors. Loud
failures are operationally important, but they are modelled separately because
they already announce themselves.

The primary score is the **Brier score**, which measures the squared error of a
stated probability. A useful confidence model must improve probability
calibration, not merely put failures near the top of a ranking. Repeated calls
from the same generated puzzle are always kept in the same evaluation fold.

## Finding 1: metadata looked promising in old calls

The retrospective MiniMax cohort contains **145 calls on 30 generated
instances**:

::: {.number-grid}
::: {.number-card}
<strong>61</strong>

correct completions
:::
::: {.number-card}
<strong>24</strong>

silent errors
:::
::: {.number-card}
<strong>60</strong>

loud failures
:::
:::

The selected metadata model reached **AUROC 0.852** and improved Brier score by
**36.9%** over the difficulty curve alone. Its instance-bootstrap 95% interval
for that improvement was 11.5% to 57.6%.

In plain language: silently wrong completions used about **54,700 billed
tokens**, compared with **36,100** for correct completions, and took about
**756 seconds**, compared with **524 seconds**. Their effective billed token
rates were almost identical. MiniMax did not appear to generate more slowly
when it was wrong; it simply continued for longer.

The trace-only model was much weaker: **AUROC 0.671** and **7.4% Brier skill**,
with an uncertainty interval that crossed zero. The earlier trace-ranking
result did not transfer into a dependable probability of correctness.

![Four retrospective confidence models. Metadata and the combined model clear the exploratory thresholds; trace features alone do not.](figs/confidence-minimax-ablation.svg)

::: {.interpretation}
### What this result does—and does not—say

It says metadata is worth a fresh test. It does **not** yet show that the score
will work on new calls. The old calls were used to choose the model, so this
finding remains **Exploratory**.
:::

## Study 1: the fresh MiniMax test is running

The prospective test was frozen before collecting its evaluation calls:

- one model: `or/minimax-m2.5`;
- one route: `openrouter/Parasail`;
- a fixed 65,536-token cap and prompt version;
- a metadata-only confidence model selected in advance;
- one final analysis, with no peeking and retuning;
- stop after at least 60 correct and 60 silently wrong completions, 600 calls,
  or USD 40—whichever comes first.

The result will count as supported only if Brier skill remains at least 10%,
its instance-bootstrap 95% interval excludes zero, and AUROC remains at least
0.75. If it fails, the negative result is the result.

[Read the frozen MiniMax protocol](minimax-confidence-protocol.html) ·
[Download the exploratory result JSON](data/confidence-minimax.json) ·
[Download the compact study table](data/minimax-confidence-v1.jsonl.gz)

## GLM replication audit: the old calls are not enough

The released database contains **14 calls on `z-ai/glm-5`**: nine correct
completions and five silent errors. That is useful reconnaissance, but not a
replication of the MiniMax confidence result.

Three problems prevent a calibrated comparison:

1. The cohort has five silent errors, below the registered minimum of 20.
2. Calls were served unpinned across Phala, SiliconFlow, and Z.ai routes.
3. Correct and wrong calls occupy different difficulty cells; no tested level
   contains both outcomes, so difficulty and metadata effects are confounded.

The audit is therefore **Censored**, not negative. It says the available data
cannot answer the question; it does not say GLM lacks a confidence signal. No
new calls were made and new spend was USD 0.

[Download the GLM cohort audit](data/glm-existing-data-audit.json)

### Modern GLM-5.2 scout: loud failures came first

A protocol frozen before spending tested `z-ai/glm-5.2` through StreamLake
only at five difficulties from 4.2 to 6.6. The ten-call scout cost USD
0.281850 and produced four correct completions, no silently wrong completed
answers, and six loud failures: four token-cap truncations, one malformed
19-bit answer, and one malformed API response.

The registered cohort-discovery gate failed. The planned thirty-call focus
batch was therefore stopped before launch. This result is **Not supported**
for the narrow claim that the scout located a GLM-5.2 confidence frontier. It
does not show that GLM-5.2 lacks confidence signals; it shows that under the
frozen 32,768-token high-reasoning condition, operational failures appeared
before a silent-error cohort.

[Read the frozen scout and result](glm-5.2-frontier-pilot.html) ·
[Download the result JSON](data/glm-5.2-frontier-scout-v1.json) ·
[Download the compact calls](data/glm-5.2-frontier-scout-v1/calls.jsonl.gz)

A 262,144-token reliability follow-up on the same ten instances ran through
SiliconFlow without fallback or retry. It cost USD 0.662540 and produced three
correct completions, three silent errors, and four loud failures: one malformed
19-bit answer and three undecodable JSON response bodies. No call reached the
new token cap.

The reliability gate allowed at most two loud failures, so the result is **Not
supported**. Compared with the 32K scout, truncations fell from four to zero,
but API failures rose from one to three. Because provider and cap changed
together, this cannot identify a cap-only effect. The six completed calls are
too few for a confidence model, and no focus batch is authorized.

[Read the completed 256K follow-up](glm-5.2-frontier-256k-siliconflow.html) ·
[Download the result JSON](data/glm-5.2-frontier-256k-siliconflow-v1.json) ·
[Download the compact calls](data/glm-5.2-frontier-256k-siliconflow-v1/calls.jsonl.gz)

### Streaming transport smoke: the long response completed

The next registered step changed the transport, not the task or model
condition. One previously failing difficulty-5.4 instance was sent to the same
pinned SiliconFlow route with SSE, a 262,144-token allowance, no client read
deadline, no fallback, and no retry.

The stream completed normally after **460.111 seconds** with HTTP 200 and
terminal reason `stop`. The collector retained **29,671 timed events**, the
generation ID, 29,630 native reasoning tokens, and the final answer. No SSE
event was rejected. OpenRouter's server-side generation record independently
confirmed SiliconFlow, streaming, normal completion, and a cost of
**USD 0.12242427**.

The answer was parseable but wrong. That is a silent error, not a transport
failure. The registered transport smoke therefore **passed**, while the answer
does not add a confidence claim. One successful call also does not erase the
four loud failures in the completed ten-call study or estimate a new transport
failure rate.

[Read the completed streaming smoke](glm-5.2-streaming-smoke.html) ·
[Download the result JSON](data/glm-5.2-streaming-smoke-v1.json) ·
[Download the timed stream events](data/glm-5.2-streaming-smoke-v1/stream-events.jsonl.gz)

## Study 2: the trace-triggered backup idea failed

The control idea was simple:

1. Start with a trace-visible primary model.
2. Watch for persistent backtracking, hedging, repetition, or give-up language.
3. If risk stays high, pause external side effects and launch challenger models.
4. Accept only an answer that passes an external verifier; cancel the rest.

This differs from a conventional model council. A council launches several
models by default and combines completed answers. The proposed controller was
supposed to launch backups only when needed.

Before making any paid calls, the frozen trigger was replayed over every
historical call with a visible reasoning trace.

::: {.number-grid .negative-result}
::: {.number-card}
<strong>84 / 89</strong>

calls launched backups
:::
::: {.number-card}
<strong>50 / 50</strong>

failures triggered
:::
::: {.number-card}
<strong>34 / 39</strong>

correct calls also triggered
:::
::: {.number-card}
<strong>USD 0</strong>

new API spend
:::
:::

The policy caught every failure, but only because it escalated **94.4% of all
calls**. Its false-hedge rate on correct completions was **87.2%**, far above
the registered 40% ceiling. A simple timer matched to the same launch rate also
caught every failure.

Changing the replay observation size did not rescue the policy. Coarser chunks
reduced false alarms, but also lost failures; every tested setting failed the
gate.

![Failure recall stays high as replay chunks grow, but false hedges never fall below the registered ceiling.](figs/speculative-replay-sensitivity.svg)

The historical traces lack timestamped chunks, so the promised 15-second
warning-time test is **Censored**. That missing clock does not change the
decision: the false-alarm gate already failed. The live branch was stopped and
the threshold was not retuned.

[Read the frozen design and outcome](speculative-council-protocol.html) ·
[Download the replay result](data/speculative-replay.json) ·
[Download per-call replay decisions](data/speculative-replay-predictions.jsonl)

## What to take away today

::: {.claim-list}
::: {.claim .supported}
### Supported

Difficulty-response curves provide a useful baseline probability. The revised
collector also carried and recorded one long, provider-pinned GLM stream.
:::

::: {.claim .exploratory}
### Exploratory

Completion length and elapsed time may improve per-answer confidence for
MiniMax. The prospective test is still running.
:::

::: {.claim .not-supported}
### Not supported

The frozen trace dictionary is not a strong calibrated confidence model, and
the frozen trace trigger is not a selective backup policy. The GLM-5.2 scout
also failed to locate a silent-error frontier under its frozen call condition.
:::

::: {.claim .censored}
### Censored

End-to-end billed tokens per second is not generation throughput. Queueing,
retries, and transport are mixed into the denominator; streamed timing is
needed to measure actual output rate. The existing GLM-5 pilot is also too
small and route-confounded to serve as a confidence replication.
:::
:::

## The open record

This is intentionally a living research page rather than a polished preprint.
The [field journal](journal.html) preserves the sequence of questions, mistakes,
protocol freezes, and negative results. The [paper](paper.pdf) contains the
broader difficulty-curve work. A conventional preprint will wait for at least
one prospectively validated result.

The programme connects generated evaluation and dynamic testing
([GSM-Symbolic](https://arxiv.org/abs/2410.05229),
[Dynamic Evaluation](https://proceedings.mlr.press/v235/zhu24m.html)) with
difficulty-aware routing ([IRT-Router](https://aclanthology.org/2025.acl-long.761/),
[RouteLLM](https://arxiv.org/abs/2406.18665)) and answer agreement
([Self-Consistency](https://arxiv.org/abs/2203.11171)). Its narrower question
is whether signals produced during one model call help us trust that call.

Code is MIT licensed. Research text and released study data are CC BY 4.0,
subject to provider terms.
