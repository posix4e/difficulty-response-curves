"""Config loading: models, grids, stages, API key."""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "configs"
DATA_DIR = REPO_ROOT / "data"
DEFAULT_KEY_PATHS = (
    os.environ.get("TRUSTEDROUTER_KEY_FILE", ""),
    str(Path.home() / "src" / ".env-tr"),
)


@dataclass(frozen=True)
class ModelCfg:
    model_id: str  # config key; also the recorded model_id in the store
    tier: str
    core: bool
    api_path: str  # "openai" | "anthropic"
    price_in: float  # $/1M prompt tokens
    price_out: float  # $/1M completion tokens
    max_completion_tokens: int
    thinking_budget: int = 0
    provider_only: tuple[str, ...] = ()
    base_url: str = ""  # non-default gateway (e.g. OpenRouter); "" = TrustedRouter
    key_env: str = ""  # env var or ~/src/.env-* name for that gateway's key
    api_model: str = ""  # wire-format model slug if different from model_id

    def pricetable_microdollars(self, prompt_tokens: int, completion_tokens: int) -> int:
        # price is $/1M => microdollars/token == price; +10% safety margin
        raw = prompt_tokens * self.price_in + completion_tokens * self.price_out
        return int(round(raw * 1.10))


def load_key() -> str:
    """Accepts a bare key, or a shell-style env file containing one."""
    candidates = [os.environ.get("TRUSTEDROUTER_API_KEY", "")]
    for p in DEFAULT_KEY_PATHS:
        if p and Path(p).is_file():
            candidates.append(Path(p).read_text())
    for text in candidates:
        m = re.search(r"sk-tr-[A-Za-z0-9_-]+", text)
        if m:
            return m.group(0)
        if text.strip() and "\n" not in text.strip() and "=" not in text:
            return text.strip()
    raise RuntimeError(
        "no API key: set TRUSTEDROUTER_API_KEY, TRUSTEDROUTER_KEY_FILE, or create ~/src/.env-tr"
    )


def load_models(path: Path | None = None) -> dict[str, ModelCfg]:
    raw = tomllib.loads((path or CONFIG_DIR / "models.toml").read_text())
    out: dict[str, ModelCfg] = {}
    for model_id, m in raw["models"].items():
        out[model_id] = ModelCfg(
            model_id=model_id,
            tier=m["tier"],
            core=m["core"],
            api_path=m["api_path"],
            price_in=m["price_in"],
            price_out=m["price_out"],
            max_completion_tokens=m["max_completion_tokens"],
            thinking_budget=m.get("thinking_budget", 0),
            provider_only=tuple(m.get("provider_only", [])),
            base_url=m.get("base_url", ""),
            key_env=m.get("key_env", ""),
            api_model=m.get("api_model", ""),
        )
    return out


@dataclass(frozen=True)
class GridCfg:
    name: str
    family: str
    levels: tuple[float, ...]
    n_vars: int = 0  # SAT only


def load_grids(path: Path | None = None) -> dict[str, GridCfg]:
    raw = tomllib.loads((path or CONFIG_DIR / "grids.toml").read_text())
    return {
        name: GridCfg(
            name=name,
            family=g["family"],
            levels=tuple(float(x) for x in g["levels"]),
            n_vars=g.get("n_vars", 0),
        )
        for name, g in raw["grids"].items()
    }


@dataclass
class StageCfg:
    name: str
    grid: str
    set_name: str
    models: list[str]  # explicit model ids
    n_instances: int
    k: int
    cap_usd: float
    focus_k: int = 0  # ADDITIONAL samples at focus levels (0 = no focus topup)
    focus_width: int = 2  # +/- levels around center for the focus topup
    focus_from: str = ""  # path to focus.json mapping model -> center level_idx
    c2_k: int = 0  # ADDITIONAL samples at the single center level
    window_width: int = -1  # restrict backbone k to center +/- this (-1 = all levels)
    temperature: float | None = None
    master_seed: int = 20260704


def load_stages(models: dict[str, ModelCfg], path: Path | None = None) -> dict[str, StageCfg]:
    raw = tomllib.loads((path or CONFIG_DIR / "stages.toml").read_text())
    out: dict[str, StageCfg] = {}
    for name, s in raw["stages"].items():
        sel = s["models"]
        if sel == "all":
            ids = list(models)
        elif sel == "core":
            ids = [m for m, c in models.items() if c.core]
        elif isinstance(sel, str) and sel.startswith("tier:"):
            ids = [m for m, c in models.items() if c.tier == sel[5:]]
        else:
            ids = list(sel)
        out[name] = StageCfg(
            name=name,
            grid=s["grid"],
            set_name=s["set_name"],
            models=ids,
            n_instances=s["n_instances"],
            k=s["k"],
            cap_usd=s["cap_usd"],
            focus_k=s.get("focus_k", 0),
            focus_width=s.get("focus_width", 2),
            focus_from=s.get("focus_from", ""),
            c2_k=s.get("c2_k", 0),
            window_width=s.get("window_width", -1),
            temperature=s.get("temperature"),
            master_seed=s.get("master_seed", 20260704),
        )
    return out


GLOBAL_CAP_USD = 300.0
# ~$12 of provider-artifact calls (baseten/novita truncations, mixed-provider
# purges) were deleted from the ledger but cost real money; stops are lowered
# by a safety margin so true spend stays under the $300 promise.
# purged-artifact spend measured at ~$12; stops sit that far under the
# original 290/295 so true spend stays within the $300 promise
SOFT_STOP_USD = 278.0
HARD_REFUSE_USD = 283.0
