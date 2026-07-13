# GLM-5.2 streaming transport smoke v1

**Status: Supported - transport smoke passed.** Frozen before collection and
completed on 13 July 2026.

## Question

Can the revised collector complete one real, provider-pinned GLM-5.2 request
through SSE without losing the response envelope or imposing a client read
deadline?

This is a transport smoke, not a confidence analysis and not a retry of the
earlier outcome. It reuses one instance whose buffered 256K call ended with an
undecodable JSON body so the wire path is tested where it previously failed.

## Frozen conditions

- Model: `z-ai/glm-5.2` through OpenRouter.
- Provider: SiliconFlow only; fallback disabled.
- Instance ID: `5d09e54e272a57891e26f579`.
- Difficulty: 5.4; generator seed 2026271201; 20 variables.
- Prompt version: 1, unchanged from the previous call.
- Completion allowance: 262,144 tokens.
- Temperature: 0.6.
- Reasoning effort: high.
- Transport: SSE with chunk timing retained.
- Client read timeout: none; connection and write timeouts remain 30 seconds.
- Calls: exactly one.
- Automatic retries: none.
- Dollar ceiling: none. Provider-reported spend is recorded.

## Readout

Report the outcome, provider, finish reason, HTTP status, generation ID
presence, elapsed time, first-token timing, reasoning and completion tokens,
stream-event count, rejected-event count, partial-output retention if an error
occurs, and cost.

The smoke passes only if the pinned provider returns a decodable stream ending
in `stop` or `completed`, the call is durably recorded with its chunk events,
and no fallback or retry occurs. A model answer may still be correct or
silently wrong; answer correctness is reported but is not the transport pass
criterion.

## Result

The single call completed through SiliconFlow with HTTP 200 and terminal
reason `stop`. It used no fallback and no retry. The OpenRouter generation
record independently confirmed that the request was streamed, was not
cancelled, and resolved to `z-ai/glm-5.2-20260616` on SiliconFlow.

The stream ran for 460.111 seconds. Its first reasoning event arrived after
1.282 seconds; the answer channel began after 459.548 seconds. The collector
stored 29,671 events: 29,629 reasoning events and 42 answer events. No SSE
event was rejected, and the 35-character generation ID was retained.

The final stream usage reported 773 native prompt tokens, 29,672 native
completion tokens, and 29,630 native reasoning tokens. OpenRouter's generation
record separately reported 335 normalised prompt tokens and 12,887 normalised
completion tokens. Both records agree on a cost of USD 0.12242427 at the
precision exposed by the generation endpoint.

The returned SAT assignment was parseable but wrong, so the answer outcome is
a silent error. That does not fail this transport smoke: the registered
endpoint was whether a normal, pinned stream reached a terminal event and was
stored without fallback or retry. The transport endpoint therefore passed.

This one successful paired smoke does not estimate a transport failure rate,
erase the four loud failures in the completed ten-call study, or establish a
GLM confidence result. It shows that the revised harness can carry and record
one long GLM stream on the exact instance whose buffered request previously
ended in an undecodable response body.
