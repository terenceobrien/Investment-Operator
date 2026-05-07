"""
Runtime safety controls for narrative generation.

Defaults are intentionally conservative so an unconfigured deploy does not
silently spend LLM tokens.
"""
from __future__ import annotations

import os

NARRATIVE_MODES = {"mock", "cache", "live"}


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def get_narrative_mode() -> str:
    mode = os.getenv("NARRATIVE_MODE", "live").strip().lower()
    if mode not in NARRATIVE_MODES:
        raise RuntimeError(
            f"Invalid NARRATIVE_MODE={mode!r}. Expected one of: "
            f"{', '.join(sorted(NARRATIVE_MODES))}."
        )
    return mode


def llm_calls_allowed() -> bool:
    return _env_bool("ALLOW_LLM_CALLS", default=True)


def assert_llm_calls_allowed(context: str = "") -> None:
    if llm_calls_allowed():
        return
    suffix = f" Blocked: {context}" if context else ""
    raise RuntimeError(
        "LLM calls are disabled by ALLOW_LLM_CALLS=false."
        f"{suffix}"
    )


def assert_live_mode(context: str = "") -> None:
    mode = get_narrative_mode()
    if mode == "live":
        return
    suffix = f" Blocked: {context}" if context else ""
    raise RuntimeError(
        f"Narrative generation is disabled in NARRATIVE_MODE={mode}."
        f"{suffix}"
    )
