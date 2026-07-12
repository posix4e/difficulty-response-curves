"""Budget enforcement. The ledger (sum of cost_microdollars over every
attempt, successes and failures alike) lives in SQLite; this class adds
admission control with an in-flight reserve so concurrent calls cannot
overshoot a cap between ledger updates.

Layers: per-stage cap < global soft stop ($290) < hard refusal ($295)
< the user's $300 ceiling. The reserve prices every in-flight call at
the model's running p95 cost.
"""

from __future__ import annotations

import math
import threading

from ..config import GLOBAL_CAP_USD, HARD_REFUSE_USD, SOFT_STOP_USD
from .store import Store

USD = 1_000_000  # microdollars


class BudgetExceeded(RuntimeError):
    pass


class BudgetGuard:
    def __init__(self, store: Store, stage_caps_usd: dict[str, float] | None = None):
        self.store = store
        self.stage_caps = {k: int(v * USD) for k, v in (stage_caps_usd or {}).items()}
        self._lock = threading.Lock()
        self._inflight: dict[str, int] = {}  # call token -> reserved micro
        self._observed: dict[str, list[int]] = {}  # model -> recent costs
        self._seeded_models: set[str] = set()
        self._counter = 0

    # -- cost estimation ------------------------------------------------------

    def note_cost(self, model_id: str, micro: int) -> None:
        with self._lock:
            hist = self._observed.setdefault(model_id, [])
            hist.append(micro)
            if len(hist) > 500:
                del hist[: len(hist) - 500]

    def p95_estimate(self, model_id: str, fallback_micro: int) -> int:
        if model_id not in self._seeded_models:
            persisted = self.store.recent_model_costs(model_id)
            with self._lock:
                if model_id not in self._seeded_models:
                    self._observed.setdefault(model_id, []).extend(persisted)
                    self._seeded_models.add(model_id)
        hist = self._observed.get(model_id, [])
        if len(hist) < 5:
            return fallback_micro
        index = max(0, math.ceil(len(hist) * 0.95) - 1)
        return sorted(hist)[index]

    # -- admission control ------------------------------------------------------

    def admit(self, stage: str, model_id: str, est_micro: int) -> str:
        """Reserve budget for one call. Returns a token to release later.
        Raises BudgetExceeded when any cap would be crossed."""
        spent_total = self.store.spent_microdollars()
        spent_stage = self.store.spent_microdollars(stage)
        with self._lock:
            reserve = sum(self._inflight.values())
            if spent_total + reserve + est_micro > HARD_REFUSE_USD * USD:
                raise BudgetExceeded(
                    f"hard refusal: spent={spent_total/USD:.2f} + reserve would cross ${HARD_REFUSE_USD}"
                )
            if spent_total + reserve + est_micro > SOFT_STOP_USD * USD:
                raise BudgetExceeded(
                    f"soft stop: spent={spent_total/USD:.2f} near global cap ${GLOBAL_CAP_USD}"
                )
            cap = self.stage_caps.get(stage)
            if cap is not None and spent_stage + reserve + est_micro > cap:
                raise BudgetExceeded(
                    f"stage '{stage}' cap ${cap/USD:.2f} reached (spent ${spent_stage/USD:.2f})"
                )
            self._counter += 1
            token = f"{model_id}:{self._counter}"
            self._inflight[token] = est_micro
            return token

    def release(self, token: str) -> None:
        with self._lock:
            self._inflight.pop(token, None)

    def summary(self, stage: str | None = None) -> dict:
        global_spent = self.store.spent_microdollars()
        stage_spent = self.store.spent_microdollars(stage) if stage else None
        with self._lock:
            reserve = sum(self._inflight.values())
        return {
            # Keep the legacy key for callers that consume the global ledger.
            "spent_usd": global_spent / USD,
            "global_spent_usd": global_spent / USD,
            "stage_spent_usd": stage_spent / USD if stage_spent is not None else None,
            "inflight_reserved_usd": reserve / USD,
            "global_cap_usd": GLOBAL_CAP_USD,
            "soft_stop_usd": SOFT_STOP_USD,
        }
