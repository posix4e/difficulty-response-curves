#set document(title: "Can a Model Tell When It Is Wrong?", author: "Alex Newman")
#set page(
  paper: "a4",
  margin: (x: 25mm, y: 23mm),
  numbering: "1",
  header: context if counter(page).get().first() > 1 [
    #set text(size: 8pt, fill: rgb("#66736e"))
    Can a Model Tell When It Is Wrong? #h(1fr) Preliminary research report
  ],
)
#set text(font: "New Computer Modern", size: 10pt, lang: "en")
#set par(justify: true, leading: 0.62em)
#set heading(numbering: "1.")
#show heading.where(level: 1): it => block(
  above: 1.25em,
  below: 0.65em,
)[#set text(size: 15pt, weight: "bold", fill: rgb("#163f33")); #it]
#show heading.where(level: 2): it => block(
  above: 1em,
  below: 0.45em,
)[#set text(size: 11.5pt, weight: "bold"); #it]
#show link: set text(fill: rgb("#176b51"))
#show figure.caption: set text(size: 8.5pt)

#let C = json("../analysis/confidence-minimax.json")
#let S = json("../analysis/speculative-replay.json")
#let G = json("../analysis/glm-existing-data-audit.json")
#let P = json("../analysis/glm-5.2-frontier-scout-v1.json")
#let F = json("../analysis/glm-5.2-frontier-256k-siliconflow-v1.json")
#let H = json("../analysis/glm-5.2-streaming-smoke-v1.json")
#let counts = C.at("cohort").at("counts")
#let metadata = C.at("metrics").at("metadata")
#let trace = C.at("metrics").at("trace")
#let replay = S.at("results")
#let trigger = replay.at("trace_trigger")
#let n(value, digits: 3) = str(calc.round(value, digits: digits))
#let pct(value, digits: 1) = str(calc.round(value * 100, digits: digits)) + "%"

#align(center)[
  #text(size: 25pt, weight: "bold", fill: rgb("#123e31"))[
    Can a Model Tell When It Is Wrong?
  ]
  #v(0.6em)
  #text(size: 12.5pt, fill: rgb("#52615b"))[
    Confidence signals at the MiniMax frontier
  ]
  #v(1.1em)
  Alex Newman #h(1.2em) 13 July 2026
]

#v(1.2em)
#block(
  fill: rgb("#fbf3df"),
  stroke: (left: 3pt + rgb("#9a6500")),
  inset: 10pt,
  radius: 3pt,
)[
  *Status: preliminary and not peer reviewed.* Existing calls support an
  exploratory finding. A fresh, prospectively registered validation is still
  collecting data. The trace-triggered backup experiment failed its no-spend
  gate and was stopped.
]

= Abstract

A difficulty-response curve estimates how likely a model is to solve a task
at a given difficulty. We ask whether information produced during one call -
reasoning text, token counts, latency, or serving metadata - improves the
probability of correctness for that particular answer. In 145 retrospective
MiniMax-M2.5 calls, a frozen metadata model reached AUROC
#n(metadata.at("auc")) and Brier skill #pct(metadata.at("brier_skill_vs_curve"))
relative to the curve prior. A trace-only model reached AUROC
#n(trace.at("auc")) and #pct(trace.at("brier_skill_vs_curve")) Brier skill;
its clustered interval crossed zero. A second frozen hypothesis used trace
markers to launch backup models. It caught every historical failure but also
triggered on #pct(trigger.at("correct_false_hedge_rate")) of correct calls,
making it an always-on council in practice. That branch stopped with no new
spend. The metadata result is now undergoing a single prospective evaluation.

= The question

For an answer to a hard problem, we want a calibrated statement such as
"there is a 72% chance this answer is correct." Difficulty provides the first
estimate. Two equally difficult calls can still look different: one may finish
quickly, while another consumes its token budget and backtracks for minutes.
The research question is whether those differences should change confidence.

The measurement instrument borrows the logic of item response theory
@birnbaum1968. Fresh satisfiable 3-SAT instances provide a scalar difficulty
axis through their clause-to-variable ratio, and full assignments are checked
as certificates. Random SAT is known to exhibit strong difficulty variation
near its transition region @mitchell1992hard. The curve is a prior, not a claim
about a reasoning mechanism.

== Three outcomes

The study keeps mutually exclusive outcomes:

+ *Correct completion:* a normal completion with a verified certificate.
+ *Silent error:* a normal completion with a parseable but wrong certificate.
+ *Loud failure:* truncation, refusal, parse failure, timeout, provider
  mismatch, malformed response, or API error.

Confidence is evaluated only on correct completions versus silent errors. Loud
failures are reported separately because they already announce themselves.
The primary endpoint is Brier skill relative to the curve prior. AUROC and log
loss are secondary views. Repeated samples of one generated instance are kept
together during evaluation.

= Retrospective result

The exploratory cohort contains #counts.at("all_calls") calls on
#counts.at("instances_completed") instances: #counts.at("correct_completed")
correct completions, #counts.at("silently_wrong_completed") silent errors, and
#counts.at("loud_failure") loud failures.

#figure(
  image("../analysis/confidence-minimax-ablation.svg", width: 83%),
  caption: [Retrospective comparison. Dashed lines are the frozen exploratory
  spend-gate thresholds.],
)

#block(breakable: false)[#table(
  columns: (1.25fr, 1fr, 1fr, 1fr),
  inset: 6pt,
  stroke: 0.45pt + rgb("#d5d8d2"),
  table.header([*Model*], [*Brier*], [*Skill vs curve*], [*AUROC*]),
  [Curve prior], [#n(C.at("metrics").at("curve").at("brier"))], [0],
    [#n(C.at("metrics").at("curve").at("auc"))],
  [Metadata], [#n(metadata.at("brier"))], [#pct(metadata.at("brier_skill_vs_curve"))],
    [#n(metadata.at("auc"))],
  [Trace], [#n(trace.at("brier"))], [#pct(trace.at("brier_skill_vs_curve"))],
    [#n(trace.at("auc"))],
  [Combined], [#n(C.at("metrics").at("combined").at("brier"))],
    [#pct(C.at("metrics").at("combined").at("brier_skill_vs_curve"))],
    [#n(C.at("metrics").at("combined").at("auc"))],
)]

The metadata model's 95% clustered interval for Brier skill was
[#pct(metadata.at("brier_skill_ci95").at(0)),
#pct(metadata.at("brier_skill_ci95").at(1))]. Silently wrong completions used
about 54,700 billed tokens, versus 36,100 for correct completions, and took
about 756 seconds, versus 524 seconds. Effective billed tokens per second was
nearly unchanged. The simplest interpretation is not that MiniMax generated
more slowly when wrong; it continued for longer.

This finding is *Exploratory*. The same calls selected the model class, so they
cannot establish prospective validity.

= GLM replication audit

The released database contains #G.at("counts").at("calls") calls on
`z-ai/glm-5`: #G.at("counts").at("correct_completed") correct completions and
#G.at("counts").at("silently_wrong_completed") silent errors. Those calls do
not form an eligible confidence cohort. Five silent errors are below the
registered minimum of 20; calls were unpinned across three provider routes;
and correct and wrong outcomes occupy different difficulty cells. Difficulty,
route, and metadata effects cannot be separated.

This audit is *Censored*, not a negative model result. It made no new calls and
spent USD 0. A paid GLM replication would first need an explicit model
checkpoint, one provider pin, a frontier-local sampling design, and a separate
budget decision.

== Modern GLM-5.2 scout

We then froze and ran a ten-call frontier scout on `z-ai/glm-5.2`, pinned to
StreamLake. It spent USD #n(P.at("spend").at("actual_usd"), digits: 6) and
returned #P.at("counts").at("correct_completed") correct completions, no
silent errors, and #P.at("counts").at("loud_failure") loud failures. Four
calls exhausted the 32,768-token cap, one returned 19 assignment bits instead
of 20, and one ended in a malformed API response.

The registered cohort-discovery gate failed, so the planned thirty-call focus
batch was not run. This is *Not supported* for the narrow claim that the scout
located a GLM-5.2 confidence frontier. It is not evidence that GLM-5.2 lacks a
confidence signal: loud reliability failures dominated before a silent-error
cohort appeared under this call condition.

A 262,144-token SiliconFlow follow-up then ran on the same instances. It spent
USD #n(F.at("spend").at("actual_usd"), digits: 6) and produced three correct
completions, three silent errors, and four loud failures. No call reached its
token cap; the loud failures were one 19-bit answer and three undecodable JSON
response bodies.
The reliability gate allowed at most two loud failures and therefore failed.
Provider and cap changed together, so the paired difference is not a cap-only
effect. Six completed answers are too few for a confidence model.

A separately registered one-call transport smoke then repeated a previously
failing instance over SSE. It completed on SiliconFlow in
#n(H.at("transport").at("latency_ms") / 1000, digits: 3) seconds with terminal
reason `stop`, no fallback, and no retry. The collector retained
#H.at("transport").at("stream_events") timed events and rejected none. The
answer was silently wrong, but the registered transport endpoint passed. This
single success verifies the collector path; it does not revise the ten-call
reliability result or establish a confidence signal.

= A negative control result

We separately asked whether trace deterioration could trigger selective
backup calls. The intended controller would begin with one primary model,
pause external side effects after persistent risk, launch challengers, and
accept only a verifier-approved answer. This resembles a hedged request
@dean2013tail, but with reasoning markers rather than a fixed timer.

The policy was frozen before replay. Among #replay.at("counts").at("eligible")
historical traces it launched on #replay.at("counts").at("triggered") calls.
It caught all #replay.at("counts").at("failures") failures, including every
silent error, but also launched on 34 of 39 correct calls. A fixed timer matched
to the same launch rate also caught every failure.

#figure(
  image("../analysis/speculative-replay-sensitivity.svg", width: 78%),
  caption: [Proxy chunk-size sensitivity. No setting reached the registered
  false-hedge ceiling while retaining the target recall.],
)

Historical traces lacked timestamped chunks, so the 15-second warning-time
endpoint is *Censored*. The false-alarm condition already failed. The paid
comparison was therefore not run, the threshold was not retuned, and new spend
was USD 0. This result is *Not supported*.

= Prospective validation

The frozen MiniMax protocol fixes one model, one provider route, a 65,536-token
cap, three difficulty levels around the measured frontier, and the metadata
coefficients selected retrospectively. Collection stops at 60 correct and 60
silently wrong completions, 600 calls, or USD 40 - whichever comes first.
There is one efficacy analysis.

The primary claim passes only if:

+ Brier skill is at least 10%;
+ its instance-bootstrap 95% interval excludes zero; and
+ AUROC remains at least 0.75.

If it fails, the negative result is published and the branch stops. If it
passes, a separately capped USD 10 streaming smoke may measure time to first
token, inter-chunk gaps, and observed output rate. End-to-end billed tokens per
second is not called generation throughput because it mixes queueing,
transport, retries, and provider overhead.

= What the work supports today

#block(breakable: false)[#table(
  columns: (auto, 1fr),
  inset: 7pt,
  stroke: 0.45pt + rgb("#d5d8d2"),
  [*Supported*], [Difficulty-response curves provide a useful baseline probability.],
  [*Exploratory*], [Token use and elapsed time may improve confidence for MiniMax.],
  [*Not supported*], [The frozen trace dictionary is not a strong calibrated score,
    and its frozen trigger is not a selective backup policy.],
  [*Prospective*], [The metadata score is being evaluated once on fresh calls.],
  [*Censored*], [Warning time and true generation throughput need streamed timing.],
  [*Censored - GLM*], [The existing GLM pilot is too small and route-confounded
    to identify a confidence result.],
  [*Not supported - GLM-5.2*], [The pinned scout found no silent errors; six of
    ten calls failed loudly. The 256K follow-up still had four loud failures
    and did not clear its reliability gate.],
  [*Supported - GLM transport*], [One registered SSE smoke completed normally
    and retained 29,671 timed events without fallback or retry.],
)]

The result is deliberately narrow: one model, one provider route, one task
family, and a frontier-local difficulty window. It does not establish a
general confidence mechanism, and it does not justify using hidden reasoning
text as a universal safety signal. Generated evaluation and model routing
remain broader adjacent areas; see
#link("https://arxiv.org/abs/2410.05229")[GSM-Symbolic],
#link("https://proceedings.mlr.press/v235/zhu24m.html")[Dynamic Evaluation],
#link("https://aclanthology.org/2025.acl-long.761/")[IRT-Router], and
#link("https://arxiv.org/abs/2406.18665")[RouteLLM].

= Reproducibility and next step

Version 2 of the released code has one workflow: plan, collect under hard
provider and registered stopping constraints, inspect outcome counts without efficacy
metrics, perform the frozen analysis once, and export compact metadata plus a
separately checksummed trace artifact. Historical routing and speculative
controller code is not part of the runtime.

The frozen data, coefficients, protocols, negative replay, paper source, and
field journal remain public at
#link("https://github.com/posix4e/difficulty-response-curves")[the project repository].
The next scientific event is the single prospective read after a registered
stopping condition is reached.

#heading(numbering: none)[References]
#bibliography("refs.yml", style: "ieee", title: none)
