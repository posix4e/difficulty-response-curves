"""Round 3, Phase 0: per-model trained trace judges, one-shot gate.

Round 2's judge was one feature at a Youden threshold; it lost a live race
to a coin. This trains a small per-model combo (<=3 features, L2 logistic)
on the EXPLORATORY corpus (every SAT trace outside the percall set) and
evaluates ONCE on the frozen confirmatory percall set.

Stopping-rule discipline, pre-registered 2026-07-08 (the round-2 lesson):
  - default run: feature-subset selection + metrics via instance-grouped
    cross-validation on the TRAINING corpus only; percall is never read.
  - `--gate` run: the single confirmatory evaluation. Gate = stratified
    pairwise AUC >= 0.75 on >= 2 of 3 models AND recall >= 0.5 at
    FPR <= 0.25, with the threshold FROZEN from training data.
The gate is called once. There is no second look.

Writes analysis/percall-judge.json (train CV always; test block only on
--gate).
"""

from __future__ import annotations

import itertools
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from drc import config
from drc.runner.store import Store
from drc.stats.tracefeat import extra_features, features

from percall import MODELS, pair_auc, stratified_pairs  # noqa: E402  (same dir)

SEED = 20260708
MAX_COMBO = 3
FEATS = ["rep_tail", "bt_tail", "hedge_tail", "rep_full", "bt_full", "wait_tail", "tok",
         "hedge_ans", "giveup_full", "flip", "qmark_tail", "rep_tail_k4", "wait_full",
         "bt_last10", "neg_tail", "len_ratio"]


def load_split(store: Store, model_ids: tuple[str, ...], split: str) -> list[dict]:
    cmp = "!=" if split == "train" else "="
    q = f"""SELECT c.model_id, i.instance_id, i.set_name, ROUND(i.level_value,2),
                   c.pass, c.completion_tokens, c.response_text
            FROM calls c JOIN instances i USING(instance_id)
            WHERE c.model_id IN ({','.join('?' * len(model_ids))})
              AND i.family='sat'
              AND c.outcome IN ('pass','fail_wrong')
              AND LENGTH(c.response_text) > 2000
              AND i.set_name {cmp} 'percall'"""
    out = []
    for m, iid, s, lv, p, tok, txt in store.conn.execute(q, model_ids):
        f = features(txt, tok)
        f.update(extra_features(txt, tok))
        f.update({"iid": (m, iid), "level": (m, s, lv), "pass": bool(p)})
        out.append(f)
    return out


def xy(calls: list[dict], feats: list[str], mu=None, sd=None):
    X = np.array([[c[f] for f in feats] for c in calls], dtype=float)
    y = np.array([0.0 if c["pass"] else 1.0 for c in calls])
    if mu is None:
        mu, sd = X.mean(axis=0), X.std(axis=0) + 1e-9
    return (X - mu) / sd, y, mu, sd


def fit_logistic(X: np.ndarray, y: np.ndarray, l2: float = 1.0, iters: int = 500) -> np.ndarray:
    """Deterministic batch gradient descent; returns weights incl. bias."""
    Xb = np.hstack([X, np.ones((len(X), 1))])
    w = np.zeros(Xb.shape[1])
    for _ in range(iters):
        p = 1.0 / (1.0 + np.exp(-Xb @ w))
        grad = Xb.T @ (p - y) / len(y) + l2 * np.r_[w[:-1], 0.0] / len(y)
        w -= 0.5 * grad
    return w


def score_calls(calls: list[dict], feats: list[str], w, mu, sd) -> None:
    X, _, _, _ = xy(calls, feats, mu, sd)
    Xb = np.hstack([X, np.ones((len(X), 1))])
    s = Xb @ w
    for c, v in zip(calls, s):
        c["judge"] = float(v)


def grouped_folds(calls: list[dict], k: int = 5) -> list[list[dict]]:
    iids = sorted({c["iid"] for c in calls}, key=str)
    rng = random.Random(SEED)
    rng.shuffle(iids)
    buckets = [set(iids[i::k]) for i in range(k)]
    return [[c for c in calls if c["iid"] in b] for b in buckets]


def cv_auc(calls: list[dict], feats: list[str]) -> float:
    folds = grouped_folds(calls)
    scored: list[dict] = []
    for i, fold in enumerate(folds):
        train = [c for j, f in enumerate(folds) if j != i for c in f]
        if sum(1 for c in train if not c["pass"]) < 3 or not fold:
            continue
        Xtr, ytr, mu, sd = xy(train, feats)
        w = fit_logistic(Xtr, ytr)
        fold = [dict(c) for c in fold]
        score_calls(fold, feats, w, mu, sd)
        scored += fold
    pairs = stratified_pairs(scored)
    return pair_auc(pairs, "judge") if pairs else float("nan")


def threshold_for_fpr(calls: list[dict], max_fpr: float = 0.25) -> float:
    """Smallest score threshold whose training FPR is <= max_fpr."""
    passes = sorted((c["judge"] for c in calls if c["pass"]))
    idx = int(np.ceil(len(passes) * (1 - max_fpr))) - 1
    idx = min(max(idx, 0), len(passes) - 1)
    return float(np.nextafter(passes[idx], np.inf))


def recall_fpr(calls: list[dict], th: float) -> tuple[float, float]:
    wrong = [c for c in calls if not c["pass"]]
    right = [c for c in calls if c["pass"]]
    rec = sum(1 for c in wrong if c["judge"] >= th) / max(len(wrong), 1)
    fpr = sum(1 for c in right if c["judge"] >= th) / max(len(right), 1)
    return rec, fpr


def main() -> None:
    gate = "--gate" in sys.argv
    store = Store(config.DATA_DIR / "drc.sqlite")
    report: dict = {
        "preregistered": "AUC >= 0.75 on >= 2 of 3 models AND recall >= 0.5 at FPR <= 0.25; "
                         "threshold frozen on training data; gate evaluated ONCE (--gate)",
        "seed": SEED,
        "models": {},
    }
    for name, ids in MODELS.items():
        train = load_split(store, ids, "train")
        n_wrong = sum(1 for c in train if not c["pass"])
        entry: dict = {"n_train": len(train), "n_train_wrong": n_wrong}
        if n_wrong < 8:
            entry["skipped"] = "under 8 training wrongs - too thin to train honestly"
            report["models"][name] = entry
            print(name, entry)
            continue
        best: tuple[float, tuple] = (-1.0, ())
        for r in range(1, MAX_COMBO + 1):
            for combo in itertools.combinations(FEATS, r):
                a = cv_auc(train, list(combo))
                if a == a and a > best[0]:
                    best = (a, combo)
        feats = list(best[1])
        Xtr, ytr, mu, sd = xy(train, feats)
        w = fit_logistic(Xtr, ytr)
        train_scored = [dict(c) for c in train]
        score_calls(train_scored, feats, w, mu, sd)
        th = threshold_for_fpr(train_scored)
        tr_rec, tr_fpr = recall_fpr(train_scored, th)
        entry.update({
            "features": feats,
            "cv_auc_train": round(best[0], 3),
            "threshold": round(th, 4),
            "train_recall_at_threshold": round(tr_rec, 3),
            "train_fpr_at_threshold": round(tr_fpr, 3),
            "weights": [round(float(v), 4) for v in w],
        })
        if gate:
            test = load_split(store, ids, "test")
            score_calls(test, feats, w, mu, sd)
            pairs = stratified_pairs(test)
            rec, fpr = recall_fpr(test, th)
            auc = pair_auc(pairs, "judge") if pairs else float("nan")
            entry["confirmatory"] = {
                "n_test": len(test),
                "n_pairs": len(pairs),
                "auc": round(auc, 3),
                "recall_at_frozen_threshold": round(rec, 3),
                "fpr_at_frozen_threshold": round(fpr, 3),
                "clears_gate": bool(pairs) and auc >= 0.75 and rec >= 0.5 and fpr <= 0.25,
            }
        report["models"][name] = entry
        print(name, json.dumps(entry, indent=1)[:600])
    if gate:
        clears = sum(1 for e in report["models"].values()
                     if e.get("confirmatory", {}).get("clears_gate"))
        report["gate"] = {"models_clearing": clears, "pass": clears >= 2}
        print("GATE:", report["gate"])
    out = Path(__file__).with_name("percall-judge.json")
    out.write_text(json.dumps(report, indent=2))
    print(f"wrote {out.name}")


if __name__ == "__main__":
    main()
