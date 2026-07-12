---
title: "MiniMax Confidence at the Frontier: Protocol v1"
author: "Alex Newman"
date: "12 July 2026"
lang: en-GB
---

> **Frozen prospective protocol.** Existing data are exploratory for this
> confidence question. This protocol must be publicly committed before any new
> API calls are admitted to the prospective stage.

## Research question

For completed MiniMax-M2.5 answers near its native SAT frontier, do trace or
serving features improve a calibrated estimate of correctness beyond the
difficulty-response curve?

## Cohort and outcomes

- Model: `or/minimax-m2.5`.
- Required endpoint: `openrouter/Parasail`; calls served elsewhere are protocol
  deviations and excluded from the primary analysis.
- Task: satisfiable-only random 3-SAT, `n=20`, certificate checked.
- Difficulty: the three configured levels centred on the native frontier.
- Maximum completion tokens: 65,536; provider defaults otherwise unchanged;
  no temperature is sent.
- Prompt and task versions are fixed at batch launch and recorded per call.

Outcomes are mutually exclusive:

1. **Correct completed:** mechanically verified and not truncated.
2. **Silently wrong completed:** completed normally, parsed, and failed the
   certificate.
3. **Loud failure:** truncation, parse failure, refusal, timeout, transport/API
   error, or malformed response.

The confidence analysis uses outcomes 1 and 2. Loud failures receive a
separate descriptive and predictive analysis and are never silently dropped.

## Frozen model comparisons

The response is `P(correct)`.

1. **Curve prior:** cross-fitted two-parameter difficulty-response curve with
   lapse; the held-out instance is not used to fit its own prior.
2. **Metadata:** curve logit plus log completion tokens, reported reasoning
   tokens when present, fraction of the 65,536-token cap used, log end-to-end
   latency, log effective billed tokens/second, attempt count, and finish-reason
   indicators.
3. **Trace:** curve logit plus the existing fixed trace dictionary:
   backtracking, waiting, hedging, repetition, give-up markers, answer flips,
   negative markers, and full/tail/last-10% positions normalised by trace
   length.
4. **Combined:** the union of metadata and trace features.

Cost is reported but is not a predictor because it is a price-weighted
transform of token counts. No embeddings, language-model judges, new lexical
features, or post-gate threshold search are allowed in v1.

Models are L2-regularised logistic regressions. Feature scaling, missing-value
indicators, and coefficients are learned within training folds only. Folds are
grouped by generated instance and stratified by difficulty where feasible.

## Retrospective gate

Existing calls are used only to choose among the four frozen model classes and
to decide whether new spend is warranted. The gate passes if all are true:

- at least 20 silently wrong completed calls are available;
- the best non-curve model has grouped out-of-fold AUROC at least 0.75;
- its Brier skill relative to the curve prior is at least 0.10.

If the gate fails, publish the result and stop with USD 0 new spend.

## Prospective batch and one-look analysis

Before batch launch, fit the selected model to all eligible retrospective calls
and freeze its feature order, scaling, missing-value handling, coefficients,
and decision thresholds in a checksummed JSON file.

Generate fresh instances at the three frontier levels, with 20 instances per
level and up to 10 samples per instance. Stop without inspecting effect metrics
when any condition is reached:

- at least 60 correct and 60 silently wrong completed calls;
- 600 admitted calls;
- USD 40 recorded or reserved spend.

Twelve fixed-seed sentinel calls, split before and after the batch and excluded
from efficacy metrics, check endpoint continuity and gross provider drift.
Endpoint mismatch pauses admission and is reported as a protocol deviation.

The frozen model receives one evaluation on the prospective set. The primary
claim passes if:

- Brier skill relative to the prospectively evaluated curve prior is at least
  0.10;
- the 95% instance-cluster bootstrap interval for Brier skill excludes zero;
- AUROC is at least 0.75.

Secondary outputs are log loss, calibration intercept and slope, reliability
diagram, AUROC, precision-recall curve, and accuracy/cost across coverage
levels. All protocol deviations and loud failures are reported.

## Streaming feasibility gate

At most USD 10 remains reserved. It is used only if the prospective primary
claim passes. Streaming instrumentation must capture at least 95% of expected
events on a no-effect-look smoke batch before any streaming hypothesis is
tested. Recorded observables are time to first token, time to first reasoning
and answer chunks, per-channel chunk times and sizes, inter-chunk gap
quantiles, and observed output rate between first and last chunks.

End-to-end billed tokens divided by request latency is named
`effective_billed_tokens_per_second`; it is never labelled generation speed.

## Reproducibility and reporting

- The source database, compact study table, result JSON, fold assignments,
  frozen model, figures, manifest, code commit, and spend ledger are released.
- Instance identifiers are hashed in the compact table. Raw traces are a
  separate checksummed artifact.
- A result is labelled `Exploratory`, `Prospective`, `Supported`,
  `Not supported`, or `Censored`.
- Code uses MIT; research text and released study data use CC BY 4.0 subject to
  provider terms.
