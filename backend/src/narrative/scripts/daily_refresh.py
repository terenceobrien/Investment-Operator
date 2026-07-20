"""Daily narrative refresh CLI for scheduled Railway runs."""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
import traceback
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from src.narrative.bundle import build_narrative_bundle
from src.narrative.config import FINAL_SYNTHESIS_MODEL
from src.narrative.orchestrator import _shape_regime_for_synth
from src.narrative.runtime_config import assert_live_mode, assert_llm_calls_allowed
from src.narrative.schema import (
    DominantNarrative,
    ExecutiveBullets,
    ExecutiveSnapshot,
    MarketTone,
    NarrativeStateV1,
    PriceSummary,
    Signals,
)
from src.narrative.synth import (
    extract_tickers_from_items,
    load_latest_narrative_snapshot,
    save_narrative_snapshot,
    synthesize_narrative_state,
)
from src.narrative.ticker_profiles import (
    get_ticker_profile,
    normalize_ticker,
    prompt_subject_profile,
    watch_tickers_for_profile,
)
from src.data.market import fetch_market_moves


SNAPSHOT_DIR = Path("data/snapshots")
DEFAULT_SUBJECTS = ("SPY", "QQQ")
logger = logging.getLogger("narrative.daily_refresh")


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("\"'")
            if key and key not in os.environ:
                os.environ[key] = value


def _load_env() -> None:
    backend_dir = Path(__file__).resolve().parents[3]
    repo_root = Path(__file__).resolve().parents[4]
    try:
        from dotenv import load_dotenv

        load_dotenv(repo_root / ".env")
        load_dotenv(backend_dir / ".env")
    except ImportError:
        _load_env_file(repo_root / ".env")
        _load_env_file(backend_dir / ".env")


def _setup_logging() -> None:
    level_name = os.getenv("NARRATIVE_REFRESH_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level_name, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        stream=sys.stdout,
    )


def _stub_mode_reason() -> str | None:
    try:
        assert_live_mode("daily narrative refresh")
        assert_llm_calls_allowed("daily narrative refresh")
    except RuntimeError as exc:
        return str(exc)
    return None


def _subject_profile(subject_key: str) -> Dict[str, Any]:
    normalized = normalize_ticker(subject_key)
    profile = get_ticker_profile(normalized)
    if profile is None:
        raise ValueError(f"Unsupported daily narrative subject: {normalized}")
    return profile


def _build_stub_snapshot(
    *,
    subject_key: str,
    subject: Dict[str, Any],
    reason: str,
    asof_utc: str,
) -> Dict[str, Any]:
    state = NarrativeStateV1(
        asof_utc=asof_utc,
        dominant_narratives=[
            DominantNarrative(
                title=f"{subject_key} stub narrative refresh",
                stance="unclear",
                confidence=1,
                why_now="This is a stub for testing; live narrative synthesis was disabled.",
                takeaways=[
                    "REALITY: this is a stub for testing.",
                    "STORY: this is a stub for testing.",
                    "PRICE: this is a stub for testing.",
                    "GAP: no real gap was computed.",
                ],
                tickers=[subject_key],
                what_would_change=["Enable live narrative synthesis and rerun the refresh."],
                risks_to_watch=["Do not consume this stub as a production narrative read."],
            )
        ],
        one_paragraph_summary=(
            f"This is a stub for testing for {subject_key}. Live narrative "
            "synthesis did not run, so no production investment signal should "
            "be inferred from this snapshot."
        ),
        raw_takeaways=[
            "UNCLEAR: this is a stub for testing.",
            "FALSIFIER: enable live LLM calls and regenerate the snapshot.",
        ],
        counter_narratives=["This snapshot contains no real counter-narrative analysis."],
        unknowns=["UNKNOWN: live synthesis was disabled for this scheduled refresh."],
        market_tone=MarketTone(
            risk_appetite="unclear",
            fragility="unclear",
            positioning_guess="unclear",
            tone_notes="Stub snapshot for testing; no live tone was computed.",
        ),
        signals=Signals(
            headline_intensity=0,
            earnings_intensity=0,
            macro_intensity=0,
            social_intensity=0,
        ),
        executive_snapshot=ExecutiveSnapshot(
            regime_tone="Stub - not production",
            primary_gap="Stub for testing; no real gap computed.",
            primary_archetype="Stub",
            price_confirmation="Not enough price evidence",
            confidence=0,
            executive_bullets=ExecutiveBullets(
                reality="Stub for testing.",
                story="Stub for testing.",
                price="Stub for testing.",
            ),
        ),
        inefficiency_map=[],
        price_summary=PriceSummary(
            cross_asset="Stub for testing; price evidence unavailable.",
            sector="Stub for testing; price evidence unavailable.",
            timeframe="Stub for testing; price evidence unavailable.",
            relationship="Stub for testing; price evidence unavailable.",
        ),
    ).model_dump()
    state["_meta"] = {
        "is_stub": True,
        "stub_reason": reason,
        "subject": subject,
        "total_items_in_bundle": 0,
        "items_selected_for_llm": 0,
        "lookback_hours": 36,
        "prior_snapshot_found": False,
        "ledger_counts": {},
        "role_counts": {},
        "information_ledgers": {},
    }
    return state


def _build_regime_summary() -> Dict[str, Any]:
    try:
        from src.state.regime_state import RegimeState, build_regime_state

        today_str = date.today().isoformat()
        regime = RegimeState.load_snapshot(today_str)
        if regime is None:
            logger.info("No regime snapshot for %s; building regime state", today_str)
            regime = build_regime_state(save=True)
        return _shape_regime_for_synth(regime.to_dict())
    except Exception as exc:
        logger.warning("Regime summary unavailable; continuing without it: %s", exc)
        return {}


def _build_market_moves(watch_tickers: List[str]) -> List[Dict[str, Any]]:
    try:
        moves_df = fetch_market_moves(watch_tickers)
        return moves_df.to_dict(orient="records") if moves_df is not None else []
    except Exception as exc:
        logger.warning("Market moves unavailable; continuing without them: %s", exc)
        return []


def _openai_client_for_refresh() -> Any:
    from openai import OpenAI

    timeout_sec = float(os.getenv("NARRATIVE_REFRESH_OPENAI_TIMEOUT_SEC", "240"))
    return OpenAI(timeout=timeout_sec)


async def _build_price_context(
    *,
    bundle_items: List[Dict[str, Any]],
    watch_tickers: List[str],
    subject: Dict[str, Any],
) -> Dict[str, Any] | None:
    try:
        from src.data.price_context import build_multi_timeframe_price_context

        derived = extract_tickers_from_items(bundle_items, max_tickers=20)
        seen = set(watch_tickers)
        combined_watch = list(watch_tickers) + [t for t in derived if t not in seen]
        price_context = await build_multi_timeframe_price_context(
            watch_tickers=combined_watch,
            subject_profile=subject,
        )
        errors = (price_context or {}).get("errors") or []
        if errors:
            logger.warning("price_context returned %d error(s): %s", len(errors), errors)
        return price_context
    except Exception as exc:
        logger.warning(
            "price_context build failed; continuing without it: %s\n%s",
            exc,
            traceback.format_exc(),
        )
        return None


def _snapshot_stats(state: Dict[str, Any]) -> Dict[str, Any]:
    meta = state.get("_meta") or {}
    return {
        "items": meta.get("total_items_in_bundle", 0),
        "selected": meta.get("items_selected_for_llm", 0),
        "ledger_counts": meta.get("ledger_counts") or {},
        "is_stub": bool(meta.get("is_stub")),
    }


async def _refresh_subject(
    *,
    subject_key: str,
    target_date: str,
    stub_reason: str | None,
) -> Path:
    normalized = normalize_ticker(subject_key)
    profile = _subject_profile(normalized)
    subject = prompt_subject_profile(profile)
    watch_tickers = watch_tickers_for_profile(profile)
    started = time.perf_counter()
    asof_utc = datetime.now(timezone.utc).isoformat()

    logger.info(
        "Starting narrative refresh subject=%s watch=%s target_date=%s",
        normalized,
        ",".join(watch_tickers),
        target_date,
    )

    if stub_reason is not None:
        state = _build_stub_snapshot(
            subject_key=normalized,
            subject=subject,
            reason=stub_reason,
            asof_utc=asof_utc,
        )
        path = save_narrative_snapshot(
            state,
            SNAPSHOT_DIR,
            target_date,
            subject_key=normalized,
        )
        elapsed = time.perf_counter() - started
        logger.info(
            "Finished stub refresh subject=%s elapsed=%.2fs path=%s reason=%s",
            normalized,
            elapsed,
            path,
            stub_reason,
        )
        return path

    bundle = await asyncio.to_thread(
        build_narrative_bundle,
        watch_tickers=watch_tickers,
        news_category="general",
        news_limit=80,
        ticker_news_limit=20,
        earnings_days_ahead=7,
    )
    bundle_dict = bundle.to_dict()
    bundle_items = bundle_dict.get("items") or []
    asof = bundle.asof_utc if hasattr(bundle, "asof_utc") else asof_utc
    prior_date, prior = load_latest_narrative_snapshot(
        SNAPSHOT_DIR,
        target_date,
        subject_key=normalized,
    )
    logger.info(
        "Built bundle subject=%s items=%d prior_snapshot=%s",
        normalized,
        len(bundle_items),
        prior_date or "none",
    )

    regime_summary = await asyncio.to_thread(_build_regime_summary)
    market_moves = await asyncio.to_thread(_build_market_moves, watch_tickers)
    price_context = await _build_price_context(
        bundle_items=bundle_items,
        watch_tickers=watch_tickers,
        subject=subject,
    )

    state = await asyncio.to_thread(
        synthesize_narrative_state,
        bundle_dict,
        market_state_summary=regime_summary,
        market_moves=market_moves,
        prior_state=prior,
        lookback_hours=36,
        model=FINAL_SYNTHESIS_MODEL,
        client=_openai_client_for_refresh(),
        price_context=price_context,
        subject=subject,
    )
    path = save_narrative_snapshot(
        state,
        SNAPSHOT_DIR,
        target_date,
        subject_key=normalized,
    )
    elapsed = time.perf_counter() - started
    stats = _snapshot_stats(state)
    logger.info(
        "Finished narrative refresh subject=%s elapsed=%.2fs path=%s "
        "items=%s selected=%s ledgers=%s asof=%s",
        normalized,
        elapsed,
        path,
        stats["items"],
        stats["selected"],
        stats["ledger_counts"],
        asof,
    )
    return path


async def run_daily_refresh() -> int:
    _load_env()
    _setup_logging()
    target_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    stub_reason = _stub_mode_reason()
    if stub_reason is not None:
        logger.warning("Daily narrative refresh running in stub mode: %s", stub_reason)

    successes: list[str] = []
    failures: dict[str, str] = {}
    overall_started = time.perf_counter()

    for subject_key in DEFAULT_SUBJECTS:
        try:
            path = await _refresh_subject(
                subject_key=subject_key,
                target_date=target_date,
                stub_reason=stub_reason,
            )
            successes.append(f"{subject_key}:{path}")
        except Exception as exc:
            failures[subject_key] = f"{type(exc).__name__}: {exc}"
            logger.error(
                "Narrative refresh failed subject=%s: %s\n%s",
                subject_key,
                exc,
                traceback.format_exc(),
            )

    elapsed = time.perf_counter() - overall_started
    logger.info(
        "Daily narrative refresh complete elapsed=%.2fs successes=%d failures=%d",
        elapsed,
        len(successes),
        len(failures),
    )
    if successes:
        logger.info("Successful snapshots: %s", successes)
    if failures:
        logger.error("Failed subjects: %s", failures)
        return 1
    return 0


def main() -> int:
    return asyncio.run(run_daily_refresh())


if __name__ == "__main__":
    raise SystemExit(main())
