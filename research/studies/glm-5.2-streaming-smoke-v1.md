# GLM-5.2 streaming transport smoke v1

**Status: Frozen before collection.**

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
