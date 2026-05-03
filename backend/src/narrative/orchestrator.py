"""
orchestrator.py — Single entry point for running the full narrative
synthesis pipeline for a given ticker.

Used by:
  - The /api/narrative/latest endpoint (when the cache is cold)
  - The precompute_spy_narrative.py script (scheduled cache warm-up)

Keeps the multi-step pipeline (bundle → market state → price context →
synthesis) in one place so we don't drift between callers.
"""
from __future__ import annotations

import asyncio
import logging
import traceback
from typing import Any, Dict, List

from src.narrative.config import (
    FINAL_SYNTHESIS_MODEL,
    PREPROCESSING_MODEL,
)

logger = logging.getLogger("narrative.orchestrator")

SNAPSHOT_DIR = "data/snapshots"

# Default watchlist when generating SPY's narrative — broad-market ETFs +
# duration/credit proxies provide enough cross-asset signal for the
# price_context module to compute relationship signals.
SPY_WATCH_TICKERS: List[str] = ["SPY", "QQQ", "IWM", "TLT", "HYG"]


def _shape_regime_for_synth(r: Dict[str, Any]) -> Dict[str, Any]:
    """
    Project a RegimeState dict into the shape we hand to the LLM.

    Reasoning for the reshape (vs. passing RegimeState.to_dict() verbatim):
      - The dataclass exposes parallel arrays (`layer_monetary` + `layer_signals.monetary`
        + `layer_statuses.monetary`) that read awkwardly. Nesting under
        `layers.<name>.{score,status,signals}` is far cleaner for LLM grounding
        and for human inspection of synth_input_*.json.
      - We drop verbose diagnostics (layer_data_quality, raw asof_utc) the LLM
        does not need.
    """
    layer_signals = r.get("layer_signals") or {}
    layer_statuses = r.get("layer_statuses") or {}
    return {
        "asof_date": r.get("asof_date"),
        "horizon": r.get("horizon"),
        "score_total": r.get("score_total"),
        "score_delta": r.get("score_delta"),
        "environment": r.get("environment"),
        "environment_drivers": r.get("environment_drivers", []),
        "confidence": r.get("confidence"),
        "layer_agreement": r.get("layer_agreement"),
        "layers": {
            name: {
                "score": r.get(f"layer_{name}"),
                "status": layer_statuses.get(name),
                "signals": layer_signals.get(name, []),
            }
            for name in ("monetary", "credit", "volatility", "breadth", "positioning")
        },
        "key_inputs": {
            k: r.get(k) for k in (
                "vix_level", "vix_term_slope", "hy_spread_level",
                "net_liquidity_z", "pct_above_200d", "new_highs_minus_lows_z",
            )
        },
    }


async def run_narrative_for_ticker(ticker: str) -> Dict[str, Any]:
    """
    Run the full narrative synthesis pipeline for a ticker. Returns the
    synthesis output dict (NarrativeStateV1 + _meta with information_ledgers).

    Async — uses asyncio.to_thread for blocking yfinance / synthesis calls.
    """
    # Imports are local to avoid heavy side effects at module load time
    from datetime import date as date_cls
    from src.narrative.bundle import build_narrative_bundle
    from src.narrative.synth import (
        synthesize_narrative_state,
        load_latest_narrative_snapshot,
        save_narrative_snapshot,
        extract_tickers_from_items,
    )
    from src.state.regime_state import RegimeState, build_regime_state
    from src.data.market import fetch_market_moves
    from src.data.price_context import build_multi_timeframe_price_context

    ticker_u = ticker.upper().strip()
    watch = list(SPY_WATCH_TICKERS) if ticker_u == "SPY" else [ticker_u]

    logger.info(
        "Narrative pipeline starting — ticker=%s, watch=%s, "
        "final_model=%s, preprocess_model=%s",
        ticker_u, watch, FINAL_SYNTHESIS_MODEL, PREPROCESSING_MODEL,
    )

    # ── 1. Bundle ──
    bundle = await asyncio.to_thread(
        build_narrative_bundle,
        watch_tickers=watch,
        news_category="general",
        news_limit=80,
        ticker_news_limit=20,
        earnings_days_ahead=7,
    )

    # ── 2. Regime state (five-layer scoring) ──
    # Reuse today's saved regime snapshot (computed once at close) when present
    # — building it from scratch is heavy. Fall back to a fresh build only if
    # the snapshot is missing.
    today_str = date_cls.today().isoformat()
    regime = await asyncio.to_thread(RegimeState.load_snapshot, today_str)
    if regime is None:
        logger.info("No regime snapshot for %s — building one now", today_str)
        regime = await asyncio.to_thread(build_regime_state, save=True)
    regime_summary = _shape_regime_for_synth(regime.to_dict())

    # ── 3. Market moves ──
    moves_df = await asyncio.to_thread(fetch_market_moves, watch)
    moves = moves_df.to_dict(orient="records") if moves_df is not None else []

    # ── 4. Multi-timeframe price context (with derived single-name tickers) ──
    price_context = None
    try:
        bundle_items = bundle.to_dict().get("items") or []
        derived = extract_tickers_from_items(bundle_items, max_tickers=20)
        seen = set(watch)
        combined_watch = list(watch) + [t for t in derived if t not in seen]
        price_context = await build_multi_timeframe_price_context(
            watch_tickers=combined_watch,
        )
        if price_context.get("errors"):
            logger.warning("price_context errors: %s", price_context["errors"])
    except Exception as exc:
        logger.warning(
            "price_context build failed (continuing without): %s\n%s",
            exc, traceback.format_exc(),
        )

    # ── 5. Prior snapshot ──
    asof = bundle.asof_utc if hasattr(bundle, "asof_utc") else ""
    _, prior = load_latest_narrative_snapshot(SNAPSHOT_DIR, asof[:10])

    # ── 6. Synthesize (final synthesis model) ──
    logger.info("Calling synthesize_narrative_state with model=%s", FINAL_SYNTHESIS_MODEL)
    result = await asyncio.to_thread(
        synthesize_narrative_state,
        bundle.to_dict(),
        market_state_summary=regime_summary,
        market_moves=moves,
        prior_state=prior,
        lookback_hours=36,
        model=FINAL_SYNTHESIS_MODEL,
        price_context=price_context,
    )

    # Also write the legacy snapshot so trends/historical analysis still work
    save_narrative_snapshot(result, SNAPSHOT_DIR, asof[:10])
    return result


def run_narrative_for_ticker_sync(ticker: str) -> Dict[str, Any]:
    """Synchronous wrapper for CLI scripts (do not call from async contexts)."""
    return asyncio.run(run_narrative_for_ticker(ticker))
