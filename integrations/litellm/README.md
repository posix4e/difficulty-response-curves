# Form-guide routing for LiteLLM

Route requests to the cheapest model that can actually do the work — where
"can do the work" is a **measured frontier**, not a price tier or a vibe.

Every rule in this router traces to a measured finding from the parent
project (see the paper):

| rule | finding behind it |
|---|---|
| rank rungs by frontier-on-your-task, not price | on our task family the premium models solved *half* as much as a cheap open model, at 17× the cost per solve |
| retry the same rung before escalating | near-frontier failures are coin-flips ("the mist"); retry ×3 beat every cascade we replayed |
| each rung carries its own `max_tokens` | budget-elastic models lose whole difficulty bands when capped (MiniMax: frontier 6.58 uncapped → 3.6 at 32k) |
| recalibrate on a schedule | the same pinned endpoint moved a model's frontier a full dial unit within twelve hours |
| send both `max_tokens` spellings | a gateway we used silently drops one of them and defaults to 4,096 |
| don't trust per-call token signals to grade an answer | we measured it: AUC ≈ 0.5. Use a verifier; the invoice locates frontiers, not correctness |

## Quickstart

```python
from drc_router import FormGuideRouter

def my_verifier(text: str) -> bool:
    # your domain's answer check (parse + validate). Without one, the
    # router still picks by frontier/cost but cannot retry-on-failure.
    return check_answer(text)

router = FormGuideRouter.from_config("formguide.json", verifier=my_verifier)
resp = router.completion(
    messages=[{"role": "user", "content": prompt}],
    difficulty=4.2,   # optional: your task's difficulty estimate
)
print(router.explain())  # the decision log: rungs tried, retries, tokens
```

`formguide.json` ships calibrated for our task family (random 3-SAT,
difficulty = clause/variable ratio). **For your task, recalibrate**: the
frontier scale is family-specific (that's finding F of the paper). Generate
fresh numbers with the parent repo's `drc adaptive` (≈ 20–120 calls per
model, cents to a few dollars):

```bash
python gen_formguide.py          # regenerate config from measured numbers
python recalibrate.py --cap-per-model 3.0   # re-probe live frontiers
```

## What this is not

Not a per-request difficulty classifier (bring your own `difficulty` if you
have one), not an answer grader (bring a verifier), and not immune to the
task-family caveat: a frontier measured on logic puzzles says nothing about
your summarisation workload. Calibrate on something shaped like your work.
