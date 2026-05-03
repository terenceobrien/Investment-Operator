"""
config.py — Centralized model/version/cache configuration for the narrative
pipeline.

Model rule:
    - FINAL_SYNTHESIS_MODEL is used ONLY for the final narrative synthesis call.
    - PREPROCESSING_MODEL is used for every other LLM task: classification,
      ticker extraction, summary compression, trend analysis, brief generation.

Override via environment variables in dev/prod without code changes.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Set

# ──────────────────────────────────────────────────────────────────────
# Model selection
# ──────────────────────────────────────────────────────────────────────
FINAL_SYNTHESIS_MODEL: str = os.getenv("NARRATIVE_FINAL_MODEL", "gpt-5.5")
PREPROCESSING_MODEL: str = os.getenv("NARRATIVE_PREPROCESS_MODEL", "gpt-4o-mini")

# ──────────────────────────────────────────────────────────────────────
# Versioning — bump when prompt or source config changes so caches roll
# ──────────────────────────────────────────────────────────────────────
PROMPT_VERSION: str = os.getenv("NARRATIVE_PROMPT_VERSION", "v2")
SOURCE_CONFIG_VERSION: str = os.getenv("NARRATIVE_SOURCE_CONFIG_VERSION", "v1")

# ──────────────────────────────────────────────────────────────────────
# Cache
# ──────────────────────────────────────────────────────────────────────
CACHE_DIR: Path = Path(os.getenv("NARRATIVE_CACHE_DIR", "data/narrative/cache"))

# ──────────────────────────────────────────────────────────────────────
# Supported subjects
# ──────────────────────────────────────────────────────────────────────
SUPPORTED_TICKERS: Set[str] = {"SPY"}


def is_supported_ticker(ticker: str) -> bool:
    return ticker.upper().strip() in SUPPORTED_TICKERS
