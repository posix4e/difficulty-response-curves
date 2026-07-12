# GLM-5.2 256K reliability follow-up v1

**Status: Not supported — reliability gate not met.** Frozen before the first
call; completed on 12 July 2026.

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

The registered draft requested credential rotation before collection. The
user explicitly waived that operational condition and authorized reuse of the
existing credential. This did not change any model, provider, prompt, task,
token, or scoring condition. The run remained required to stop on a provider
mismatch or the ten-call cap.

## Readout

Report outcomes and spend for all ten calls, plus paired outcome transitions
from the 32K scout. The follow-up clears the reliability gate only if no more
than two calls fail loudly. Confidence analysis remains unavailable unless the
completed calls also contain at least two correct and two silently wrong
answers. No focus batch is implied by either condition.

## Result

All ten calls ran through SiliconFlow without fallback or automatic retry and
stopped at the call cap. Provider-reported spend was USD 0.662540.

| Difficulty | Correct | Silent error | Loud failure |
|---:|---:|---:|---:|
| 4.2 | 1 | 0 | 1 |
| 4.8 | 0 | 1 | 1 |
| 5.4 | 0 | 0 | 2 |
| 6.0 | 1 | 1 | 0 |
| 6.6 | 1 | 1 | 0 |

The four loud failures were one 19-bit answer where 20 bits were required and
three malformed JSON responses from the API path. No call reached the
262,144-token cap; the longest completed response used 65,967 completion
tokens. The reliability gate required no more than two loud failures and
therefore failed.

During collection, the scorer was found to reject contiguous bit strings even
when exactly 20 bits were present. A tested mechanical re-score changed two
such calls from parse failures to correct completions. The genuine 19-bit
answer and all API failures remained loud.

Compared with the 32K StreamLake scout, loud failures fell from six to four and
truncations fell from four to zero, while API failures rose from one to three.
Because provider and token cap changed together, these paired differences
cannot be attributed to the cap alone.

The six completed calls contain three correct and three silently wrong
answers, including mixed outcomes at difficulties 6.0 and 6.6. That is useful
reconnaissance but far too small for a confidence model. No focus batch is
authorized by this result.
