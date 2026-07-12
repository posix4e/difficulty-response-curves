# GLM-5.2 frontier pilot v1

**Status: Exploratory protocol.** Frozen before the first GLM-5.2 call.

## Question

Can a small, provider-pinned pilot locate a region where GLM-5.2 produces both
correct and silently wrong completed answers on the existing satisfiable 3-SAT
instrument? This pilot locates a cohort; it does not test a confidence model.

## Fixed call conditions

- Model: `z-ai/glm-5.2` through OpenRouter.
- Provider: StreamLake only; fallback disabled.
- Prompt version: 1.
- Variables: 20.
- Completion cap: 32,768 tokens.
- Temperature: 0.6.
- Reasoning effort: high, returned reasoning retained separately.
- Correctness: mechanical verification of the final 20-bit assignment.
- Outcomes: correct completion, silently wrong completion, or loud failure.

## Two-stage design

1. **Scout:** two fresh instances at each difficulty 4.2, 4.8, 5.4, 6.0,
   and 6.6; ten calls total.
2. **Focus:** after reporting the scout outcomes, choose three levels centered
   on the observed transition and run ten fresh instances per level; thirty
   calls total. If the scout has no transition, shift the focus range in the
   direction indicated by the outcomes and document that choice before calls.

The scout has a $0.75 hard cap. The complete pilot has a $3.00 hard cap and a
40-call cap. Provider mismatch stops collection immediately. No confidence
coefficients are fit until the pilot is complete.

## Readout

The pilot succeeds only as cohort discovery if at least two difficulty levels
contain both correct and silently wrong completed calls, with at least eight of
each label overall. Otherwise the result is `Frontier not located`, and a
confidence experiment remains unauthorized.

Reasoning text, completion/reasoning tokens, elapsed time, finish reason, and
provider-reported cost are retained for later feature specification. This
exploratory pilot cannot establish that any of them predict correctness.
