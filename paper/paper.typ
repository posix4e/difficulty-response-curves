// Difficulty–Response Curves: A Form Guide for Reasoning Models
// Build: sh paper/build.sh   (copies analysis/numbers.json here, compiles, lints)

#let N = json("numbers.json")
#let A = N.at("abstract", default: (:))
#let val(dict, key, d: 2, suffix: "") = {
  let v = dict.at(key, default: none)
  if v == none { text(fill: red)[⟨pending⟩] } else { str(calc.round(float(v), digits: d)) + suffix }
}

#set page(paper: "a4", margin: (x: 2.4cm, y: 2.6cm), numbering: "1")
#set text(font: "New Computer Modern", size: 10pt, lang: "en", region: "GB")
#set par(justify: true, leading: 0.62em)
#set heading(numbering: "1.1")
#show heading: it => block(above: 1.2em, below: 0.7em, text(weight: "bold", it))
#show figure.caption: it => text(size: 8.5pt, it)
#set figure(gap: 0.6em)

#align(center)[
  #text(size: 15.5pt, weight: "bold")[Difficulty–Response Curves:\ A Form Guide for Reasoning Models]
  #v(0.6em)
  #text(size: 10.5pt)[alex newman]\
  #text(size: 9pt, fill: rgb("#444444"))[posix4e\@gmail.com · code, data and generators: #link("https://github.com/posix4e/difficulty-response-curves")[github.com/posix4e/difficulty-response-curves]]\
  #text(size: 9.5pt, style: "italic", fill: rgb("#8a6d00"))[Working notes — a living document reporting what we have learnt so far. Measurements are ongoing; corrections are published in place and kept in the text as part of the findings. Last updated 12 July 2026.]
]
#v(1em)

#block(inset: (x: 1.6em), text(size: 9.2pt)[
  *Abstract.* A leaderboard gives every AI model one number, and one number
  cannot tell you the thing you actually need to know before you rely on a
  model: as problems get gradually harder, where does its success rate
  collapse, and how suddenly? We measure exactly that. We generate logic
  puzzles with a *difficulty dial* — random 3-SAT, where turning the dial
  adds constraints to a puzzle whose answer we can check mechanically — and
  test eight reasoning models many times at each of fifteen dial settings.
  Plotting pass rate against difficulty gives each model an S-shaped
  *difficulty–response curve*, which two numbers summarise: the *frontier*
  $x_50$ (the difficulty at which the model succeeds half the time) and the
  *sharpness* $a$ (how abruptly success collapses past it). Psychometricians
  have fitted exactly these curves to humans for seventy years under the
  name item response theory; we point the same instrument at machines and
  ask whether the readings can be trusted. They can. First, re-measuring on
  freshly generated puzzles reproduces the numbers (split-half reliability
  $r = #val(A, "X_reliability_r")$ across models; the two models re-tested
  in full repeated to within 0.02 and 0.12 dial units) — more than most
  benchmark scores can say. Second, the frontier is mist, not a wall: at the
  frontier, #val(A, "Y_within_pct", d: 0) per cent of outcome variance is
  luck of the draw on the *same* puzzle rather than differences between
  puzzles, so retrying a failed problem there genuinely helps. Third, a
  model's spending of reasoning tokens peaks within
  #val(A, "Z_offset_units") dial units of its frontier, so the cliff can be
  located from billing metadata alone — no internal access needed. Fourth, a
  simple binary search finds the frontier with
  #val(A, "W_efficiency", d: 1)#sym.times fewer tests than a full sweep.
  Generators, raw data, fitting code, and a tool to measure your own model
  are released. No mechanism, no grand theory of mind. An instrument.
])
#v(0.8em)

= Introduction

Suppose you are about to trust a language model with real work, and the work
arrives at varying levels of difficulty. The question that matters is not
"how smart is it" — leaderboards answer that with a single score, and single
scores hide everything useful. The question is: *as the work gets harder,
where does this model stop coping, and does it fail gently or fall off a
cliff?* Everyone who has used a reasoning model has watched it glide through
medium problems and then collapse two ticks later. The pattern is well
photographed in the research literature on reasoning "collapse". What nobody
hands you is the measuring device: for this model, on this kind of problem,
where the cliff sits, how wide the crumbling ledge is, and whether the
reading would hold if you measured again tomorrow.

This paper builds that device. The recipe has four steps and no magic.
*One:* generate puzzles by computer, with a knob that controls difficulty —
our main family is random 3-SAT, a classic logic puzzle where the solver
must find a true/false setting for twenty variables that satisfies a list of
constraints, and turning the knob simply adds more constraints. Because the
puzzles are generated fresh, the model cannot have memorised them, and
because a proposed solution can be checked mechanically, grading involves no
judgement calls. *Two:* test a model repeatedly at each of fifteen knob
settings, from easy to hopeless. *Three:* plot the fraction it solves
against the knob. The result is always an S-shape: near-certain success on
the left, near-certain failure on the right, a slope between. *Four:* fit
that S-shape and read off two numbers — the *frontier* $x_50$, the knob
setting where success crosses fifty-fifty, and the *sharpness* $a$, how
steep the fall is. Psychometricians have fitted exactly these curves to
human test-takers since the 1950s, under the name item response theory; the
mathematics arrives ready-made, and this paper's only job is to show that it
transfers to machines and to report what it finds.

Why "a form guide"? At the races, the pamphlet in every punter's hand never
says whether a horse is *good* — a meaningless question — but what distance
it runs, on what ground, and whether it fades in the final straight. That is
the shape of answer a model deserves: a datasheet of measured, repeatable
numbers about where it runs out of legs (@tbl-form is literally that table).
The Hong Kong Observatory does not explain the typhoon either. It hoists a
numbered signal, and everybody knows what T8 means.

We make four claims. Each is registered here with the manner of its death
printed beside it — the result that would have falsified it — because an
instrument you cannot break is not an instrument.

/ C1, reliability: measure a model twice — fresh puzzles, fresh attempts —
  and you get the same frontier and sharpness back. Dies if the error bars
  are so fat that the model rankings reshuffle between Tuesday and Thursday.
/ C2, the misty frontier: at the frontier, when a model fails a puzzle, is
  that because the puzzle was secretly harder, or because the model is
  simply a coin-flip there — the *same* puzzle passing on one attempt and
  failing on the next? We measure the split. Cannot lose, only cannot lie:
  if it is mostly the puzzles, then the "frontier" is just a sorting of hard
  problems from easy ones, and we say so in exactly those words.
/ C3, the effort marker: models spend the most reasoning tokens — visible in
  any API bill — on problems near their own frontier, so token counts alone
  can locate the cliff without any internal access. Dies if the spending
  peak is missing or wanders about uncorrelated with the frontier across
  models.
/ C4, fast estimation: you should not need thousands of tests to find a
  frontier; a binary search — try a middling difficulty, jump harder on
  success and easier on failure — recovers it at a fraction of the cost of
  testing every level uniformly. Pure engineering. We state the ratio and do
  not dress it up in a dinner jacket.

= The instrument

== Task families

*Random 3-SAT, satisfiable only, certificate required.* The primary family is
random 3-SAT at fixed $n = 20$ variables, with the clause-to-variable ratio
$alpha$ swept across fifteen levels from 2.0 to 5.6; an instance at level
$alpha$ has $m = "round"(alpha n)$ distinct clauses of three distinct
variables with independent random polarities. Theorists gift-wrapped this
difficulty axis decades ago @mitchell1992hard @cheeseman1991really. We add
one design decision: every instance is rejection-sampled at generation time
to be *satisfiable*, and the model must output a complete assignment, which
we check directly against the clauses. A pass is a verified certificate. This
kills the guessing floor — a random assignment satisfies all $m$ clauses with
probability $(7\/8)^m$, under half a per cent at the easiest level — so the
response curve needs no third guessing parameter, and verification needs no
trust in anything. The cost of the decision is stated plainly: conditioned on
satisfiability, high-$alpha$ instances are not typical of random 3-SAT; the
knob measures the constrainedness of solvable instances, which is what an
instrument for *reasoning up to a frontier* wants anyway.

*DAG arithmetic, the second opinion.* Random arithmetic circuits over small
integers: leaves in $[-9, 9]$, operations from ${+, -, times}$, each new node
consuming the immediately previous node plus one earlier node, so dependency
depth equals the op count by construction. Any intermediate exceeding
$|v| > 999$ is locally resampled: per-step arithmetic stays small, and
difficulty comes from length and structure, not from multiplying big
numbers. The knob is the op count across ten levels from 2 to 42. Pass is
exact integer match.

*Contamination.* Every instance is freshly generated from named seed streams;
retest sets are disjoint by construction. A fixed canary string rides in
every prompt as a tripwire for future training runs.

== The curve

Higher $x$ means harder. We fit

$ P(x) = (1 - lambda) dot sigma(a(b - x)), quad sigma(z) = 1/(1+e^(-z)), $

a two-parameter logistic with an upper lapse $lambda in [0, 0.15]$ and the
floor fixed at zero (the certificate design bought us that). The lapse
matters: models drop the odd easy instance to format slips and carelessness,
and a curve forced through a 100 per cent ceiling buys that slack by biasing
the frontier. The reported frontier is $x_50 = b - "logit"(0.5\/(1-lambda))\/a$,
the level where the *fitted* pass rate crosses one half.

Point estimates are penalised maximum likelihood on per-instance binomial
counts: a mild Normal prior on $log a$ keeps the slope finite when the data
are step-like, and a gentle Beta prior shrinks the lapse toward small values.
Every confidence interval in this paper is a stratified cluster bootstrap
over *instances* (an instance carries all its samples; levels are design
points and are never resampled), 2#h(0pt)000 replicates, percentile
intervals. With heterogeneous instances this likelihood is deliberately the
*population-averaged* curve: $a$ is a marginal slope, flatter than any
single instance's, and that is the right object for a form guide.
Goodness of fit is a level-wise Pearson $chi^2$ calibrated by parametric
bootstrap under beta-binomial instance effects matched to the observed
frontier ICC, because the plain binomial reference over-rejects under
clustering.

= Protocol

*Models.* Six core models across four families and two within-family scale
pairs, plus two budget-contingent extras, all served through one
OpenAI-compatible gateway (TrustedRouter) with the provider pinned per model
and the serving endpoint recorded on every call. Models that do not reason
unless asked were excluded by construction — the roster is models that
reason by default. Exact model strings, providers, prices, and decoding
settings are in @settings.

*Sampling.* No temperature is sent (several closed reasoning models reject
the parameter; the rest use their provider defaults); "reseeding" throughout
means independent resampling, since providers ignore seeds. A
temperature-sensitivity study on two open models is in the appendix.
Truncation is scored as failure and disclosed per model; any cell with more
than five per cent truncation flags its fit as cap-contaminated. Parse
failures score as failures too — format compliance is part of the task — with
rates disclosed and an exclusion sensitivity in the appendix.

*Budget honesty.* The textbook protocol (fifteen levels, fifty instances,
sixteen samples everywhere, every model, both families, plus a retest) does
not fit the stated \$300 ceiling once real reasoning-token burn is priced in
— the pilot priced it at roughly \$530. We publish what we ran instead of
pretending otherwise: a pilot to measure per-model token burn; then a
two-pass primary sweep — a cheap backbone of $k$ = 2–4 samples across all
fifteen levels, refit, then a top-up concentrated at the levels nearest the
provisional frontier, which is where claim C2 actually needs the sampling
depth. Two models on the original roster (Qwen3-235B-Thinking, GLM-5) were
dropped to keep six models measurable; Claude Haiku 4.5 was promoted into
the core in their place.

*Provider honesty.* The binding constraint was not price but *serving
throughput*: several open-weight models are served to one API key at a
fraction of a call per minute, whichever provider hosts them. Truncation
artefacts appeared twice and were discarded, not scored; differential
probes later traced *both* to a single gateway bug — the router silently
drops the `max_completion_tokens` parameter in translation to several
upstreams, whose reply length then falls to their own defaults (4#h(0pt)096
tokens on two of them). The same request phrased as `max_tokens` delivers
30#h(0pt)000 tokens from the very provider the artefact had framed. The
client now sends both spellings, and the post-fix re-measurement appears
under C4. Provider pins were switched when a lane stalled; every call
records the endpoint that actually served it, and per-model curves use
single-provider data only. One drift was caught outright: the same pinned
endpoint read gpt-oss-20b's frontier at 4.63 in the afternoon and
$3.58 plus.minus 0.10$ the same evening — the served artefact changed under
its label, both readings are reported, and the fact that a \$0.36 adaptive
probe catches this is an argument for running one before trusting any
datasheet, including ours. Two consequences are
flagged wherever they bite: DeepSeek-R1's design is reduced (132 scored
calls; its sole provider served ~3 calls per hour for most of a day), and
the gpt-oss pair's frontier depth reached $k$ = 12–16 rather than a uniform
16. The retest ran in full on the two models whose providers permitted it
(Haiku, o4-mini); the split-half tier of C1 covers every model for free.
Every call's cost in microdollars lands in a ledger enforced by the runner:
a call is admitted only if spend plus an in-flight reserve stays under its
stage cap. The ledger closed at
\$#N.at("provenance", default: (:)).at("spend_usd", default: "⟨pending⟩"),
plus roughly \$12 of discarded provider-artifact calls, all under the \$300
ceiling.

= Findings

== The curves

@fig1 shows the primary family. Points are per-level pass rates; lines are
the fitted curves; ticks mark each fitted frontier. The datasheet numbers —
the form guide proper — are in @fig2 and @tbl-form.

Three entries deserve a steward's note. MiniMax-M2.5 passed *everything* on
the standard grid and was re-run on an extended one reaching $alpha = 7.2$;
it spends twenty-odd thousand completion tokens per instance and simply
does not fall over where the others do — the cheap open models in this
field out-lasted the closed ones, and it is not close. The gpt-oss pair
provides the within-family scale contrast the design wanted, with the two
curves separated cleanly in frontier and slope. And o4-mini is the only
runner that *declines* at the frontier: past its $x_50$ it increasingly
answers with "I'm not able to solve this by hand" — a capitulation, scored
as failure and counted in its disclosed refusal rate, and an interesting
temperament note for a form guide.

#figure(image("figs/fig1_curves.svg", width: 100%), caption: [
  Difficulty–response curves, random 3-SAT ($n=20$, satisfiable-only,
  certificate-checked). Point size scales with samples per level; vertical
  ticks mark fitted frontiers $x_50$.
]) <fig1>

#figure(image("figs/fig2_formguide.svg", width: 100%), caption: [
  The form guide. Left: frontier $x_50$ with 95% cluster-bootstrap intervals;
  filled markers are the main run, open markers the retest on fresh
  instances. Right: sharpness $a$. Models sorted by frontier.
]) <fig2>

#let is-num(v) = type(v) == int or type(v) == float
#let fitted-models = N.at("models", default: (:)).pairs().filter(p =>
  is-num(p.at(1).at("sat", default: (:)).at("x50", default: none)))
#let r2(v) = if is-num(v) { str(calc.round(float(v), digits: 2)) } else { "—" }
#let ci(s, key) = {
  let c = s.at(key, default: none)
  if c == none { "" } else { " [" + r2(c.at(0)) + ", " + r2(c.at(1)) + "]" }
}
#figure(
  table(
    columns: 7,
    align: (left, center, center, center, center, center, center),
    stroke: 0.4pt + rgb("#cccccc"),
    inset: 4.5pt,
    table.header([*model*], [*$x_50$ [95% CI]*], [*$a$ [95% CI]*], [*lapse*],
      [*GOF $p$*], [*parse-fail*], [*truncated*]),
    ..fitted-models
      .sorted(key: p => p.at(1).sat.x50)
      .map(p => {
        let s = p.at(1).sat
        let rates = s.at("rates", default: (:))
        (
          [#p.at(1).label],
          [#r2(s.x50)#ci(s, "x50_ci")],
          [#r2(s.a)#ci(s, "a_ci")],
          [#r2(s.at("lapse", default: none))],
          [#r2(s.at("gof_p_mc", default: none))],
          [#r2(rates.at("parse", default: none))],
          [#r2(rates.at("trunc", default: none))],
        )
      })
      .flatten()
  ),
  caption: [The datasheet. Frontier and sharpness with cluster-bootstrap
    intervals; lapse; Monte-Carlo-calibrated goodness of fit; disclosed
    parse-failure and truncation rates (fractions of scored calls).],
) <tbl-form>

== C1: the measurement holds (or does not)

Reliability is reported at three tiers, cheapest first. Split-half: refit on
a parity split of instances, correlate across models, Spearman–Brown
corrected — this tier costs nothing and covers every model. Test–retest:
fresh instances, fresh samples, per-model
$z = |x_50^((2)) - x_50^((1))| \/ sqrt("SE"_1^2 + "SE"_2^2)$ — this tier ran
in full on the two models whose providers would serve it (Haiku 4.5 and
o4-mini) and is disclosed as such rather than quietly padded. o4-mini
retested at $x_50 = 3.26$ against a first reading of $3.28$; Haiku at
$3.52$ against $3.40$. The abstract's cross-model $r$ is computed over the
split-half tier, wide interval and all.

== C2: mist, not a wall

At the frontier level, with sixteen samples on every instance, the outcome
variance splits by an unbiased moment decomposition into a within-instance
part ($E[p(1-p)]$: the same instance passing on one draw, failing the next)
and a between-instance part ($"Var"(p)$: some instances being genuinely
harder). @fig3 shows the split per model. The within share is what makes
pass\@k a rational purchase near the frontier; the between share is what a
difficulty knob is supposed to produce, and does, away from it.

#figure(image("figs/fig3_variance.svg", width: 100%), caption: [
  Variance decomposition at the frontier level (the level nearest each
  model's $x_50$ with $k = 16$). Solid: within-instance share, with 95%
  bootstrap interval; faint: between-instance share.
]) <fig3>

== C3: effort betrays the frontier

Mean log completion tokens per level, all scored calls, peak located by a
windowed quadratic, offset $Delta = "peak" - x_50$ from the joint bootstrap
(the same instance resample drives both the curve refit and the token peak,
so frontier uncertainty propagates into the offset interval). @fig4 shows
the effort curves. One honest wrinkle: the peaks sit systematically *past*
the frontier — median $|Delta|$ of
#val(N.at("claims", default: (:)).at("C3", default: (:)), "median_abs_offset")
difficulty units, on the hard side — models grind hardest at levels they
have already mostly stopped solving, and the sag beyond the peak is where
several of them start declining or thrashing rather than reasoning. The
marker works — the peak exists, it tracks the frontier model-by-model, and
it is computable from token counts alone, no logprobs, no trace access —
but it reads a step behind the cliff, not on it, and anyone using it as a
gauge should calibrate that lag on a task family they can verify.

#figure(image("figs/fig4_effort.svg", width: 100%), caption: [
  The effort marker. Mean log completion tokens per level; triangles mark
  fitted effort peaks; base ticks mark each model's $x_50$. Inset: adaptive
  vs uniform sample cost at matched confidence width (C4).
]) <fig4>

== C4: haggling for the frontier

#let AH = json("adaptive-haiku.json")
#let AO = json("adaptive-o4.json")
The adaptive procedure brackets by bisection on the level grid (four fresh
instances per probe), then batches samples at the level nearest the current
frontier estimate — for a logistic curve, information about $b$ is maximised
where the pass rate is near one half, so the greedy rule is also the optimal
one — refitting with a pooled slope prior until the frontier's standard
error crosses the target. Its sample cost is compared against level-balanced
subsamples of the real uniform sweep at matched confidence width, per model,
plus two live reruns as a reality check. Live, against Haiku 4.5, the
procedure spent #AH.at("calls_used", default: "⟨n⟩") calls
(\$#val(AH, "spent_usd")) to estimate
$x_50 = #val(AH, "x50") plus.minus #val(AH, "se_b")$ against the
980-call sweep's $3.40$; against o4-mini, at a stricter stopping rule,
#AO.at("calls_used", default: "⟨n⟩") calls (\$#val(AO, "spent_usd")) gave
$#val(AO, "x50") plus.minus #val(AO, "se_b")$ against the sweep's $3.28$ —
the same answer at a seventh of the sample cost. The ratio is the finding;
it gets no dinner jacket.

The procedure also served as the budget instrument for two late entries too
expensive to sweep, and then as the auditor for the whole card. GPT-5.5
(single run, 48 calls, \$14.52, default reasoning) ran off the end of the
track: it passed everything up to the hardest generatable difficulty at
this puzzle size ($alpha = 7.2$), so its frontier is right-censored — read
"$> 7.2$", above every model in @fig1. Claude Fable 5's first run returned
no frontier at all — 20 of 44 calls failed on plumbing — which triggered
the differential probing that diagnosed the gateway's
`max_completion_tokens` bug (see Protocol). Re-measured fairly, Fable
fitted $x_50 = 6.34 plus.minus 0.21$, and a fresh-instance replicate
reproduced it to the hundredth ($6.33 plus.minus 0.20$) — and *both
readings were wrong*, because both runs sat on the standard grid, so the
estimate was an extrapolation pressed against the track's edge. A direct
head-to-head on the extended grid's hardest instances falsified it: Fable
went 10/10 at $alpha = 7.2$ (42/45 overall, versus GPT-5.5's 29/29 on
identical instances — no meaningful separation at these sample sizes).
Corrected verdict: Fable is right-censored like GPT-5.5, joint top of the
card at $n = 20$ — and a perfectly replicating fit can still be wrong about
the region beyond its data. Precision is not truth; that is what
verification runs are for. Separating the two champions required a bigger
track: head-to-head on identical $n = 50$ instances near threshold, at 32k
and then 64k thinking-token budgets (the second symmetrically via a second
gateway), GPT-5.5 scored 13/21 with no truncations — its $n = 50$ frontier
finally lands on-track around $alpha approx 4.6$–$5.0$ — while Fable
converted 11 of 40 attempts, because about half its calls exhausted even
the 64k budget mid-thought (on completed calls it was marginally the more
accurate, 11/16). By this paper's pre-registered scoring the verdict is a
GPT-5.5 win, and the mechanism is worth naming: at scale, the frontier
acquires a price axis, and a model that will not stop thinking pays for it
in truncations. The cleanest demonstration was accidental: fixing the
gateway's parameter bug made token limits *enforced* on routes that had
ignored them, silently re-running MiniMax's measurement with one variable
changed. Uncapped, its frontier is 6.58 — top of the sweep card; capped at
32#h(0pt)768 tokens it collapses to $approx 3.6$ (56 of 108 calls died at
the token wall mid-thought); at $n = 50$ even 64k was not enough (0/17).
A follow-up search for its $n = 50$ frontier came back in two
instalments. Through a ten-minute read window nothing shipped: at
$alpha = 3.9$ every response outlived the socket (eight retries,
103 minutes) and the search starved. Through a thirty-minute window,
on the same pinned provider, answers arrived — averaging 1,791 seconds
and 49k thinking tokens each — and the model converted 3 of 12 at
$alpha$ 3.0–3.6, the easiest end of the track. Its $n = 50$ frontier
therefore sits at or below $alpha approx 3$, and reaching it at all
costs half an hour of silence per question: the delivery constraint
binds before the capability one.
Three measured points now span the spectrum: GPT-5.5 budget-*efficient*,
MiniMax budget-*elastic* — its frontier moves three dial units with the
cap — and Fable budget-*insatiable*. A frontier is not one number but a
curve against the thinking budget, and a datasheet should state the budget
it was measured at. Finally, post-fix adaptive probes
re-checked every sweep frontier: o4-mini $3.28 arrow.r 3.20$, Haiku
$3.40 arrow.r 3.14$, gpt-oss-120b $4.24 arrow.r 4.41$, DeepSeek-R1
$3.78 arrow.r 3.77$ — four agreements — and gpt-oss-20b
$4.63 arrow.r 3.58$, the provider drift reported in Protocol. An instrument
reads the model *and* the pipe; a procedure cheap enough to run twice a day
is what makes the difference detectable at all.

The card also earns a living. We wired the fitted curves into a
difficulty-aware router (cheapest capable model first, retry into the
mist, escalate past the frontier) and put it before 25 never-seen
instances spanning the grid, live, with real money. Always-cheap
(gpt-oss-20b) solved 12 of 25; always-premium (o4-mini) solved 9 of 25
at nineteen times the price per solve; the router solved *24 of 25* for
\$4.45 by spending on exactly the puzzles the card said the cheap horse
would lose. An accidental duplicate of the run re-measured the two
single-model arms at 10/25 and 6/25 on the same instances — the
within-instance mist of Claim 2, photographed in the wild.

== The second opinion has a second opinion

The DAG-arithmetic check family produced its own surprise: the two models
measured to completion sailed through every level of the planned grid — 480
of 480 passes up to 42-operation chains — and the grid had to be extended
twice to find their arithmetic frontiers. o4-mini's arithmetic curve breaks
past roughly a hundred operations; Haiku's held to 99 per cent at *two
hundred and forty* operations and finally fell to 27 per cent somewhere in
the 340–960 band. Meanwhile both models' SAT frontiers sit near $alpha
approx 3.3$, and MiniMax — the SAT champion of @fig1 — needed an extended
SAT grid of its own. The lesson is printed on the packet: a frontier is a
property of a model *and* a task family, and no single number will be
telling you where a model runs out of legs. That is why the datasheet has
rows.

== Round 2: the trace does not route itself <round2>

#let PC = json("percall.json")
#let R2 = json("routing2.json")

The router above had a luxury real deployments lack: SAT answers are
checkable, so every escalation decision was refereed for free. Round 2
spent a fresh \$70 asking whether the model's own reasoning trace can
stand in for that referee — with hypotheses pre-registered before the
purpose-built data existed (primary: hedging density in the trace tail;
secondary: backtrack density; gate: within-difficulty pairwise AUC
$>= 0.65$ on two of three traced models), a second task family with
hidden unit tests (program synthesis from examples — the dial took three
designs, because rule *transcription* is flat out to forty rules and
conditional rules produce ambiguity rather than difficulty), and a live
four-arm race in which ground truth never touched a routing decision.

The offline verdict is one model of three, and a methods lesson. The
signal is *model-specific*: MiniMax backtracks and rambles when it is
silently wrong (AUC #PC.models.at("minimax/minimax-m2.5").auc.bt_tail.point
on #PC.models.at("minimax/minimax-m2.5").n_pairs pairs; token count alone
reaches #PC.models.at("minimax/minimax-m2.5").auc.tok.point) while its
hedging is noise; DeepSeek-R1 hedges, faintly
(#PC.models.at("deepseek/deepseek-r1-0528").auc.hedge_tail.point on
#PC.models.at("deepseek/deepseek-r1-0528").n_pairs pairs — under the bar)
while its backtracking is noise; Qwen gives nothing away at all — every
feature within noise of 0.5 on
#PC.models.at("qwen/qwen3-235b-a22b-thinking-2507").n_pairs pairs. There
is no universal tell — a trace judge is one more per-model calibration,
with a date on it. The lesson: mid-batch, the table briefly read two of
three over the bar and we called the gate passed, funding the live arm;
the completed set walked R1 back under the line. Our pre-registration
fixed the hypotheses and the bar but not the stopping rule, and
sequential peeking did what it always does. Both the call and the
walk-back are in the devlog.

Then the live race priced that signal. Four arms per family — always-cheap,
always-premium, the trace-judged router (threshold fixed offline), and a
random-escalation control rate-matched to the judge's realized escalation
rate. The judged router missed the pre-registered bar on both families and
*lost to the random control on both*
(SAT: #R2.live_eval_v2.results.sat.judged_router.solved vs
#R2.live_eval_v2.results.sat.random_escalate.solved of 20; synthesis:
#R2.live_eval_v2.results.synth.judged_router.solved vs
#R2.live_eval_v2.results.synth.random_escalate.solved, at
\$#R2.live_eval_v2.results.synth.judged_router.cost_per_solved_usd per
solve against the control's
\$#R2.live_eval_v2.results.synth.random_escalate.cost_per_solved_usd).
The autopsy is clean: the judge's escalations were precise — on SAT every
one converted — but it fired far too rarely (live recall $approx 0.21$),
and at the closer's own frontier it fired on the closer too, buying
retries that converted nothing. A threshold sweep over the confirmatory
traces shows no tuning rescues it: at these AUCs the judge trades solves
for dollars along a Pareto line and never dominates a strong closer
(GPT-5.5 went 20/20 on the SAT grid, making that family's bar
unreachable outright). One flaw is ours to report: the SAT control's
small-sample RNG realized 35 per cent escalation against the judge's 15,
flattering it there — but on synthesis the rates matched within five
points and the control still won. The conclusion survives its footnotes:
the certificate is not an implementation detail of the router. It *is*
the router.

#let PJ = json("percall-judge.json")

The rematch answered the obvious objection the same morning, for free.
A *trained* judge — per-model combos over sixteen trace features,
selection and a recall-oriented threshold locked on the exploratory
corpus, and a pre-registration that this time carried a stopping rule
(one look at the frozen confirmatory set, ever) — cleared the gate on
zero of three models. R1's cross-validated 0.81 collapsed to
#PJ.models.at("deepseek/deepseek-r1-0528").confirmatory.auc on the
frozen set — the combo had learnt the corpus, not the model; Qwen's
perfect-looking CV was noise on eleven training wrongs (flagged as
overfit-smell in writing before the gate ran); MiniMax posted a
genuinely excellent
#PJ.models.at("minimax/minimax-m2.5").confirmatory.auc at
#PJ.models.at("minimax/minimax-m2.5").confirmatory.recall_at_frozen_threshold
recall and still clipped the false-alarm bar. One talkative model
cannot crew a fleet. No live dollar was spent on round 3.

#let CN = json("percall-consistency.json")

Round 4 tried the one signal our own findings predict: the mist. If
near-frontier answers are coin flips (Claim 2), two samples should
disagree exactly where an answer cannot be trusted. Pre-registered with
the hazard named in advance — satisfiable SAT admits many correct
assignments — and evaluated once on the frozen k=6 corpus: recall is a
perfect 1.000 on all three models (every silent wrong disagreed with its
partners) and P(correct given exact agreement) is also a perfect 1.000
(agreement never once shipped a wrong answer). A flawless certificate —
that fires on
#(100 - calc.round(CN.models.at("minimax/minimax-m2.5").escalation_rate * 100))
to
#(100 - calc.round(CN.models.at("deepseek/deepseek-r1-0528").escalation_rate * 100))
per cent of calls, because correct answers pick *different* satisfying
assignments: false alarms run 76–94 per cent and the router degenerates
to escalate-everything. Gate failed zero-of-three on the arm the hazard
named; no live money moved. Three rounds, three pre-registered
negatives, three different reasons — under-firing, corpus-learning, and
answer multiplicity. On task families with unique answers the same
arithmetic could land differently; round 5 spent the door open.

#let CG = json("consistency-gate.json")
#let R3 = json("routing3.json").live_consistency

On program synthesis the answer is unique — two extracted programs
either compute the same function on eight seeded probe inputs or they do
not — so multiplicity cannot tax the agreement signal. A fresh 120-call
gate corpus (pre-registered before it existed, stopping rule included)
produced the campaign's first gate pass on its one look: recall
#CG.recall, false alarm #CG.fpr, AUC #CG.auc_reported. The live
four-arm race then ran with the control finally rate-matched by exact
quota. Three results, in order. The certificate still has never lied:
all shipped-on-agreement answers were correct, live. The signal's
marginal value is causally clean at last: against a control that
escalated the *same number* of instances by coin flip, the consistency
router solved #R3.results.consistency_router.solved to the control's
#R3.results.quota_random.solved — six solves attributable to *where*
disagreement pointed, not to spend. And the economics, spin-free: the
router tied always-premium's solve rate
(#R3.results.always_premium.solved) but paid
\$#R3.results.consistency_router.cost_per_solved_usd per solve to
premium's \$#R3.results.always_premium.cost_per_solved_usd on a
deliberately frontier-heavy mix (20 of 25 instances past the cheap
rung), so the pre-registered stretch bar — beat premium outright — was
missed while the primary control bar was cleared. Four rounds of *no*
bought one conditioned *yes*: where answers are unique, two cheap
samples grade each other, and the certificate can sometimes be minted
from agreement.

== Next registered control: a council that races <speculative-council>

The result above waits for two completed cheap answers. A conventional
model council goes further: launch several models, then rank, vote, or fuse
their completed outputs. LLM-Blender ranks and fuses candidates
@jiang2023blender; Mixture-of-Agents passes one layer's reports into the next
@wang2024moa. Both spend parallel work to buy a stronger combined answer.
That is sensible when answer quality is the only objective. It is a poor
default when one good, checkable answer is enough and tail latency matters.

The next protocol therefore turns the trace from a retrospective score into
a control signal. Begin with one trace-visible GLM primary. Over a rolling
window, count the same small family of backtracking, hedging, give-up, and
repetition markers already audited above. A single nervous word does nothing;
persistent risk pauses external side effects, checkpoints the reproducible
task state, and launches a fast Grok lane plus an OpenAI lane. The first
candidate that passes the task's external certificate wins. Only then does
the controller request cancellation of unfinished calls. If nobody verifies,
the completed reports may enter a council judge as an exception path.

#figure(
  image("figs/speculative-council.svg", width: 100%),
  caption: [Prospective architecture. The council is a fallback after a
  verifier-gated speculative race, not the default fan-out.],
)

The systems ancestor is the hedged request: issue a secondary copy when a
primary request looks slow, accept the first result, and cancel the replicas
@dean2013tail. Our proposed experiment changes the trigger, not the principle.
It asks whether deterioration in the primary's unfolding reasoning launches
the hedge earlier and more selectively than a fixed timer. Four frozen arms
make the question identifiable: GLM only, always-on council, a matched-rate
fixed-delay hedge, and the trace-triggered hedge. Correctness is a gate;
among non-inferior arms the endpoints are p95 time and billed cost per verified
success.

This is a protocol, not a result. Version 0 first replays timestamped traces
without new calls. It must show early warning on failures, at least fifteen
seconds of median warning time, and an acceptable false-hedge rate before a
separately budgeted live comparison. The released `drc hedge` command already
enforces the important negative space: no shared writable checkout, no winner
without an external verifier unless the operator explicitly selects an unsafe
mode, worst-case model authorisation below the cap before launch, and separate
records for cancellation requested, transport closure, and provider-reported
usage. Closing a stream is not evidence that billing stopped.

= Positioning

Item response theory and adaptive testing are the toolbox, borrowed with
thanks and zero pretence of invention @birnbaum1968 @lord1980 @vanderlinden2010.
The collapse literature — the Illusion-of-Thinking exchange and the
SAT-hardness evaluations @shojaee2025illusion @mitchell1992hard — photographed
the typhoon; we hoist numbered signals. The benchmark-reliability
complaints are the motivation, and they have been shouting into the wind for
years, poor souls. The one methodological addition worth naming: certificate
scoring on satisfiable-only instances, which buys a two-parameter curve an
honest zero floor.

= What we do not claim

No mechanism. No physics vocabulary — nobody's water is freezing, nothing is
critical, there is no order parameter hiding in section five. No entropy
tea-leaves, and no claim yet that a live trace policy gives useful early
warning. Whether trace contents can grade *individual answers* stopped being
future work when we checked (@round2: real signal, cannot route); whether a
persistent trace trigger beats a matched-rate timer is now registered and
checkable; whether any of this connects to a mechanism is somebody else's
paper. The restraint is the brand.

= Limitations

Two task families, one gateway, six-to-eight models: the instrument is
demonstrated, not exhausted. Satisfiable-only conditioning makes high-$alpha$
instances atypical of random 3-SAT, as stated. The marginal slope $a$
compresses instance heterogeneity into one number by design. Effort in
tokens is a proxy paid for at the provider's meter, and providers that hide
or bill thinking differently will move it. And a \$300 experiment measures
what a \$300 experiment measures; the generators and the runner are released
precisely so that anyone with a bigger ledger can stretch every axis.

#v(0.5em)
#line(length: 30%, stroke: 0.5pt + rgb("#999999"))
#text(size: 8.8pt)[
  *Reproducibility.* Generators, raw per-call records (tokens, cost,
  provider endpoint, full response text), fitting code, and the exact
  configs that produced every figure are at
  #link("https://github.com/posix4e/difficulty-response-curves")[github.com/posix4e/difficulty-response-curves].
  `analysis/run_analysis.py` regenerates every number; the abstract reads
  them from `numbers.json` at compile time. Git revision:
  #raw(str(N.at("provenance", default: (:)).at("git_sha", default: "pending")).slice(0, calc.min(8, str(N.at("provenance", default: (:)).at("git_sha", default: "pending")).len()))).
]

#pagebreak()
#heading(numbering: none)[Appendix]

== Model and decoding settings <settings>

#include "settings_table.typ"

== Traces: delivery by model and route <traces>

#let TR = json("traces.json")
Measured from this project's own calls: of the reasoning text each call was
billed for, the share that arrived (chars received over billed tokens
$times$ 3.7). Below 2 per cent means the thinking was withheld and only the
final answer (plus the count) came back.

#table(
  columns: (auto, auto, auto, auto),
  align: (left, left, right, right),
  stroke: 0.4pt + rgb("#cccccc"),
  inset: 4.5pt,
  table.header([*model*], [*route*], [*billed tok/call*], [*delivered*]),
  ..TR.at("availability", default: ())
    .sorted(key: r => -r.delivered_share)
    .map(r => (
      raw(r.model.split("/").last()),
      [#r.route],
      [#str(r.avg_billed_tokens)],
      [#str(calc.round(r.delivered_share * 100, digits: 0))%],
    ))
    .flatten()
)

== Bibliography

#bibliography("refs.yml", style: "ieee", title: none)
