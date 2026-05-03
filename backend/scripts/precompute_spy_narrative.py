"""
precompute_spy_narrative.py — Generate today's SPY narrative cache.

Intended schedule:
    Run before market open on trading days, e.g. 8:00 AM ET Mon–Fri.

Usage (from repo root):
    python backend/scripts/precompute_spy_narrative.py
    python backend/scripts/precompute_spy_narrative.py --ticker SPY --force
    python backend/scripts/precompute_spy_narrative.py --ignore-trading-day

Behavior:
    1. Skip if today is not a trading day (Mon–Fri unless --ignore-trading-day).
    2. Skip if today's cache exists (unless --force).
    3. Run the full narrative pipeline for the ticker via orchestrator.
    4. Save cache record with model + version metadata.

Exits non-zero on synthesis failure.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import date as date_cls
from pathlib import Path

# ── Path setup (must precede src.* imports) ──
_repo_root = Path(__file__).resolve().parents[2]
_backend_dir = _repo_root / "backend"
_backend_src_dir = _backend_dir / "src"
for _p in (_backend_src_dir, _backend_dir):
    _ps = str(_p)
    if _ps not in sys.path:
        sys.path.insert(0, _ps)

# ── Load .env before importing app modules ──
def _load_env_file(path: Path) -> None:
    import os
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip().strip("\"'")
            if k and k not in os.environ:
                os.environ[k] = v

try:
    from dotenv import load_dotenv
    load_dotenv(_repo_root / ".env")
    load_dotenv(_backend_dir / ".env")
except ImportError:
    _load_env_file(_repo_root / ".env")
    _load_env_file(_backend_dir / ".env")

# ── Application imports (after path + env setup) ──
from src.narrative.cache import (  # noqa: E402
    load_cache, save_cache, build_cache_record,
)
from src.narrative.config import (  # noqa: E402
    FINAL_SYNTHESIS_MODEL, PREPROCESSING_MODEL,
    PROMPT_VERSION, SOURCE_CONFIG_VERSION,
    is_supported_ticker,
)
from src.narrative.orchestrator import run_narrative_for_ticker  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("precompute_spy")


def is_trading_day(d: date_cls) -> bool:
    """
    Simple Mon-Fri check. Replace with a real trading-calendar helper
    (e.g. pandas_market_calendars) once one is wired in.
    """
    return d.weekday() < 5  # 0=Mon..4=Fri


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Precompute the daily narrative cache for a supported ticker.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--ticker", default="SPY", help="Ticker symbol")
    parser.add_argument("--force", action="store_true",
                        help="Regenerate even if today's cache already exists")
    parser.add_argument("--ignore-trading-day", action="store_true",
                        help="Run even on weekends/holidays")
    args = parser.parse_args()

    ticker = args.ticker.upper().strip()
    if not is_supported_ticker(ticker):
        logger.error(
            "Ticker %s is not in the supported set. Add it to "
            "SUPPORTED_TICKERS in narrative/config.py to enable.",
            ticker,
        )
        return 2

    today = date_cls.today()
    if not args.ignore_trading_day and not is_trading_day(today):
        logger.info(
            "Today (%s, weekday=%d) is not a trading day — skipping. "
            "Use --ignore-trading-day to override.",
            today.isoformat(), today.weekday(),
        )
        return 0

    today_str = today.isoformat()

    if not args.force and load_cache(ticker, today_str):
        logger.info(
            "Cache already exists for %s on %s — skipping. Use --force to regenerate.",
            ticker, today_str,
        )
        return 0

    logger.info("Generating narrative cache for %s on %s", ticker, today_str)
    logger.info("  Final synthesis model: %s", FINAL_SYNTHESIS_MODEL)
    logger.info("  Preprocessing model:   %s", PREPROCESSING_MODEL)
    logger.info("  Prompt version:        %s", PROMPT_VERSION)
    logger.info("  Source config version: %s", SOURCE_CONFIG_VERSION)

    try:
        result = asyncio.run(run_narrative_for_ticker(ticker))
    except Exception as exc:
        logger.error("Synthesis failed: %s", exc, exc_info=True)
        return 1

    record = build_cache_record(
        ticker, today_str, result,
        final_model=FINAL_SYNTHESIS_MODEL,
        preprocessing_model=PREPROCESSING_MODEL,
        prompt_version=PROMPT_VERSION,
        source_config_version=SOURCE_CONFIG_VERSION,
    )
    path = save_cache(ticker, today_str, record)
    logger.info("Saved cache → %s", path)

    md = record.get("metadata") or {}
    logger.info(
        "Cache metadata: source_count=%s, selected=%s, price_context=%s",
        md.get("source_count"),
        md.get("selected_count"),
        md.get("price_context_active"),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
