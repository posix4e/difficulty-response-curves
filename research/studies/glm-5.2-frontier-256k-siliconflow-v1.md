# GLM-5.2 256K reliability follow-up v1

**Status: Registered; blocked pending credential rotation.** Frozen before the
first call.

## Question

Do the same ten satisfiable 3-SAT instances produce fewer loud failures when
GLM-5.2 receives a 262,144-token completion allowance through SiliconFlow?

This is a reliability follow-up, not a confidence-model test. StreamLake's
endpoint is limited to 128,000 completion tokens, so serving 256K requires a
provider change. Any difference from the 32,768-token scout is therefore the
joint effect of cap and provider and cannot be attributed to the cap alone.

## Frozen conditions

- Model: `z-ai/glm-5.2` through OpenRouter.
- Provider: SiliconFlow only; fallback disabled.
- Instances: exactly the ten scout instances generated from seed 2026071201.
- Difficulties: 4.2, 4.8, 5.4, 6.0, and 6.6; two instances per level.
- Prompt version: 1.
- Completion cap: 262,144 tokens.
- Temperature: 0.6.
- Reasoning effort: high, with returned reasoning retained separately.
- Outcomes: correct completion, silently wrong completion, or loud failure.
- Calls: ten, without automatic retries.
- Dollar spend ceiling: none. Provider-reported spend remains recorded.

The OpenRouter credential exposed during the preceding scout must be rotated
before collection. The run must stop on a provider mismatch or the ten-call
cap.

## Readout

Report outcomes and spend for all ten calls, plus paired outcome transitions
from the 32K scout. The follow-up clears the reliability gate only if no more
than two calls fail loudly. Confidence analysis remains unavailable unless the
completed calls also contain at least two correct and two silently wrong
answers. No focus batch is implied by either condition.
