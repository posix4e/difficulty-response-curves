"""Phase 1: trace-delivery audit. One frontier-ish SAT prompt per
(model, door) candidate; records delivered-share, where the reasoning
text lives (content <think> tags vs a reasoning field), price, and
latency. Extends the traces.json availability picture for fleet choice.

Spend-gated: run only after the Phase 0 gate passes. ~$0.30-0.80 per
probe call, ~20 probes => under the $15 Phase 1 cap with room to re-probe.

Usage: ../.venv/bin/python probe_traces.py [--dry]   (from analysis/)
Writes analysis/probe_traces.json.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from drc import config
from drc.tasks import sat

OR_KEY = re.search(r"sk-or-[A-Za-z0-9_-]+", (Path.home() / "src" / ".env-or").read_text()).group(0)
TR_KEY = config.load_key()

# (label, gateway, wire model, provider pin or None, max_tokens)
CANDIDATES = [
    # cheap traced rung candidates
    ("qwen3-235b@or-auto", "or", "qwen/qwen3-235b-a22b-thinking-2507", None, 32768),
    ("qwen3-coder@or", "or", "qwen/qwen3-coder-plus", None, 32768),
    ("glm-5@or-auto", "or", "z-ai/glm-5", None, 32768),
    ("kimi-k2-think@or", "or", "moonshotai/kimi-k2-thinking", None, 32768),
    ("r1-0528@or-auto", "or", "deepseek/deepseek-r1-0528", None, 32768),
    ("r1-0528@or-nebius", "or", "deepseek/deepseek-r1-0528", "nebius", 32768),
    ("minimax@or-parasail", "or", "minimax/minimax-m2.5", "parasail", 32768),
    # TR front door post-fix: does thinking flow now?
    ("haiku@tr-chat", "tr", "anthropic/claude-haiku-4.5", None, 16384),
    ("r1@tr-chat", "tr", "deepseek/deepseek-r1-0528", None, 32768),
    ("qwen@tr-chat", "tr", "qwen/qwen3-235b-a22b-thinking-2507", None, 32768),
    # premium closers (blind rung allowed, but check anyway)
    ("gpt-5.5@or", "or", "openai/gpt-5.5", None, 32768),
    ("fable-5@tr-chat", "tr", "anthropic/claude-fable-5", None, 32768),
]


def probe_prompt() -> str:
    inst = sat.gen_instance(n_vars=20, alpha=4.3, master_seed=20260709,
                            set_name="probe", level_idx=0, index=0)
    return sat.render_prompt(inst)


def call(gateway: str, model: str, pin: str | None, max_tokens: int, prompt: str) -> dict:
    if gateway == "or":
        url, key = "https://openrouter.ai/api/v1/chat/completions", OR_KEY
    else:
        url, key = "https://api.trustedrouter.com/v1/chat/completions", TR_KEY
    body: dict = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "max_completion_tokens": max_tokens,
    }
    if pin:
        body["provider"] = {"only": [pin], "allow_fallbacks": False}
    t0 = time.time()
    r = httpx.post(url, headers={"Authorization": f"Bearer {key}"}, json=body, timeout=900)
    d = r.json()
    lat = time.time() - t0
    if "choices" not in d:
        return {"error": str(d.get("error", d))[:200], "latency_s": round(lat, 1)}
    msg = d["choices"][0].get("message") or {}
    content = msg.get("content") or ""
    reasoning = msg.get("reasoning") or msg.get("reasoning_content") or ""
    u = d.get("usage") or {}
    out_tok = u.get("completion_tokens") or 0
    visible = len(content) + len(reasoning)
    return {
        "provider": d.get("provider") or (d.get("trustedrouter") or {}).get("routing", {}).get("selected_endpoint"),
        "latency_s": round(lat, 1),
        "out_tokens": out_tok,
        "content_chars": len(content),
        "reasoning_field_chars": len(reasoning),
        "think_tags_in_content": "<think>" in content,
        "delivered_share": round(visible / max(out_tok * 3.7, 1), 3),
        "finish": d["choices"][0].get("finish_reason"),
        "answer_line": "ANSWER" in (content + reasoning),
    }


def main() -> None:
    dry = "--dry" in sys.argv
    prompt = probe_prompt()
    out = {}
    for label, gw, model, pin, mt in CANDIDATES:
        if dry:
            print("would probe:", label)
            continue
        try:
            out[label] = call(gw, model, pin, mt, prompt)
        except Exception as e:
            out[label] = {"error": f"{type(e).__name__}: {e}"[:200]}
        print(label, json.dumps(out[label])[:220])
    if not dry:
        Path(__file__).with_name("probe_traces.json").write_text(json.dumps(out, indent=2))
        print("wrote analysis/probe_traces.json")


if __name__ == "__main__":
    main()
