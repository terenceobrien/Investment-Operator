"""Configuration names/defaults for research source providers."""
from __future__ import annotations

import os
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[4]
REPO_ROOT = BACKEND_ROOT.parent


def _load_env_files() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(REPO_ROOT / ".env")
        load_dotenv(REPO_ROOT / ".env.local")
        load_dotenv(BACKEND_ROOT / ".env", override=True)
        return
    except Exception:
        pass

    for path in (REPO_ROOT / ".env", REPO_ROOT / ".env.local", BACKEND_ROOT / ".env"):
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            clean = line.strip()
            if not clean or clean.startswith("#") or "=" not in clean:
                continue
            key, value = clean.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and (path == BACKEND_ROOT / ".env" or key not in os.environ):
                os.environ[key] = value


_load_env_files()


FMP_API_KEY_ENV = "FMP_API_KEY"
FINNHUB_API_KEY_ENV = "FINNHUB_API_KEY"
NEWS_API_KEY_ENV = "NEWS_API_KEY"


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


DEFAULT_NEWS_LOOKBACK_DAYS = _int_env("RESEARCH_CONTEXT_NEWS_LOOKBACK_DAYS", 90)
DEFAULT_MAX_NEWS_ITEMS = _int_env("RESEARCH_CONTEXT_MAX_NEWS_ITEMS", 10)
DEFAULT_MAX_TRANSCRIPTS = _int_env("RESEARCH_CONTEXT_MAX_TRANSCRIPTS", 1)
