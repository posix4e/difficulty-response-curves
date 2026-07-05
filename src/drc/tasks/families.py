"""Dispatch by family name, so the runner and CLI stay family-agnostic."""

from __future__ import annotations

from typing import Any, Callable

from . import code, dag, sat, synth
from .base import Instance


def render_prompt(inst: Instance) -> str:
    return _mod(inst.family).render_prompt(inst)


def score(inst: Instance, text: str) -> str:
    return _mod(inst.family).score(inst, text)


def generator(family: str) -> Callable[..., Instance]:
    return _mod(family).gen_instance


def _mod(family: str) -> Any:
    if family == "sat":
        return sat
    if family == "dag":
        return dag
    if family == "code":
        return code
    if family == "synth":
        return synth
    raise ValueError(f"unknown family: {family}")
