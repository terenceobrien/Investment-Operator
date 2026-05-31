from __future__ import annotations

import asyncio
import io
import json
import logging
import sys
import uuid
from pathlib import Path
from typing import Optional
from datetime import date, datetime, timedelta, timezone

import pandas as pd
from fastapi import FastAPI, HTTPException, Query, UploadFile, File, BackgroundTasks, Depends
from fastapi.middleware.cors import CORSMiddleware

# Make sure src/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.auth import verify_clerk_token
from api.cache import cache
from api.models import (
    MarketStateOut, DeltaOut, PortfolioOut, NarrativeOut
)
from api.strategy_router import strategy_router
from api.agent_system_router import agent_system_router
from api.cycle_router import cycle_router
from screener.screener_router import router as screener_router

from src.state.market_state import (
    build_market_state, save_snapshot, HORIZONS
)
from src.state.scoring import score_market_state
from src.state.delta import find_previous_snapshot, diff_states, diff_to_bullets
from src.data.macro import fetch_regime_signals
from src.data.market import fetch_market_moves
from src.data.portfolio import load_portfolio_csv
from src.brief.portfolio import compute_portfolio_snapshot, add_regime_aware_flags
from src.portfolio.regime_overlay import analyze_portfolio_for_regime
from src.brief.what_matters import generate_what_matters_today, heuristic_what_matters
from src.narrative.bundle import build_narrative_bundle, top_n_by_channel
from src.narrative.synth import synthesize_narrative_state, load_latest_narrative_snapshot, save_narrative_snapshot
from src.narrative.cache import (
    load_cache as load_narrative_cache,
    save_cache as save_narrative_cache,
    load_latest_cache as load_latest_narrative_cache,
    build_cache_record,
)
from src.narrative.config import (
    FINAL_SYNTHESIS_MODEL, PREPROCESSING_MODEL,
    PROMPT_VERSION, SOURCE_CONFIG_VERSION,
)
from src.narrative.fixtures import load_narrative_fixture
from src.narrative.memory import save_memory_record
from src.narrative.orchestrator import run_narrative_for_ticker
from src.narrative.runtime_config import (
    assert_live_mode,
    assert_llm_calls_allowed,
    get_narrative_mode,
    llm_calls_allowed,
)
from src.narrative.ticker_profiles import (
    get_ticker_profile,
    is_supported_ticker,
    normalize_ticker,
    prompt_subject_profile,
    supported_ticker_label,
)

logger = logging.getLogger("api.main")

app = FastAPI(title="Market Intelligence API", version="1.0.0")
app.include_router(strategy_router)
app.include_router(agent_system_router)
app.include_router(cycle_router)
app.include_router(screener_router)

@app.on_event("startup")
async def startup_prewarm():
    async def _build():
        try:
            from src.state.regime_state import RegimeState, build_regime_state
            today = date.today().isoformat()
            existing = RegimeState.load_snapshot(today)
            if not existing:
                print("Prewarming regime state...")
                await asyncio.to_thread(build_regime_state, save=True)
                print("Regime state ready.")
        except Exception as e:
            print(f"Prewarm failed: {e}")

    asyncio.create_task(_build())
    asyncio.create_task(_schedule_daily_trend_scan())


def _seconds_until_next_630pm_eastern() -> float:
    import zoneinfo
    eastern = zoneinfo.ZoneInfo("America/New_York")
    now_et = datetime.now(tz=eastern)
    target = now_et.replace(hour=18, minute=30, second=0, microsecond=0)
    if now_et >= target:
        target += timedelta(days=1)
    return (target - now_et).total_seconds()


async def _run_daily_trend_scan() -> None:
    import time as _time
    from src.narrative.trends import run_trend_scan, save_scan_result
    t0 = _time.monotonic()
    today = date.today().isoformat()
    logger.info("Daily trend scan starting (date=%s)", today)
    try:
        _, snapshot = load_latest_narrative_snapshot(SNAPSHOT_DIR, today)
        result = await asyncio.to_thread(
            run_trend_scan,
            snapshot=snapshot,
            snapshot_date=today,
        )
        await asyncio.to_thread(save_scan_result, result, TRENDS_OUTPUT_DIR)
        elapsed = _time.monotonic() - t0
        logger.info(
            "Daily trend scan complete in %.1fs — static=%d dynamic=%d aligned=%d diverging=%d",
            elapsed,
            len(result.static_signals),
            len(result.dynamic_signals),
            len(result.aligned_signals()),
            len(result.diverging_signals()),
        )
    except Exception as exc:
        logger.error("Daily trend scan failed: %s", exc, exc_info=False)


async def _schedule_daily_trend_scan() -> None:
    while True:
        wait = _seconds_until_next_630pm_eastern()
        logger.info("Next daily trend scan in %.0fs (%.1f hours)", wait, wait / 3600)
        await asyncio.sleep(wait)
        await _run_daily_trend_scan()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://www.helixintel.io",
        "https://ai-financial-operator.vercel.app",
        "https://ai-financial-operator-*.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SNAPSHOT_DIR = "data/snapshots"
TRENDS_OUTPUT_DIR = "data/narrative/trends"

_jobs: dict[str, dict] = {}
_regime_build_tasks: dict[str, asyncio.Task] = {}


def _queue_regime_build(horizon: str = "default") -> None:
    existing = _regime_build_tasks.get(horizon)
    if existing and not existing.done():
        return

    async def _build() -> None:
        try:
            from src.state.regime_state import build_regime_state
            await asyncio.to_thread(build_regime_state, horizon=horizon, save=True)
        except Exception as e:
            print(f"Background regime build failed: {e}")

    _regime_build_tasks[horizon] = asyncio.create_task(_build())


def _has_usable_tape(tape) -> bool:
    return (
        getattr(tape, "spy_last", None) is not None
        or bool(getattr(tape, "cross_asset_now", {}))
        or getattr(tape, "sectors_green_now", None) is not None
    )


async def _resolve_regime_state(
    horizon: str = "default",
    refresh: bool = False,
) -> dict:
    from src.state.regime_state import RegimeState, build_regime_state

    today = date.today().isoformat()

    if refresh:
        state = await asyncio.to_thread(build_regime_state, horizon=horizon, save=True)
        return state.to_dict()

    snapshot = RegimeState.load_snapshot(today)
    if snapshot:
        return snapshot.to_dict()

    latest = RegimeState.load_latest_snapshot()
    if latest:
        _queue_regime_build(horizon)
        payload = latest.to_dict()
        payload["stale"] = latest.asof_date != today
        return payload

    _queue_regime_build(horizon)
    return {
        "asof_date": today,
        "asof_utc": datetime.now(timezone.utc).isoformat(),
        "horizon": horizon,
        "environment": "Warming / Pending Snapshot",
        "score_total": None,
        "confidence": None,
        "layer_monetary": None,
        "layer_credit": None,
        "layer_volatility": None,
        "layer_breadth": None,
        "layer_positioning": None,
        "stale": True,
    }


async def _resolve_intraday_tape() -> dict:
    from src.state.regime_state import RegimeState, IntradayTape, build_intraday_tape

    today = date.today().isoformat()
    regime = RegimeState.load_snapshot(today) or RegimeState.load_latest_snapshot()

    tape = await asyncio.to_thread(build_intraday_tape, regime_state=regime)
    if _has_usable_tape(tape):
        try:
            tape.save_snapshot()
        except Exception as e:
            print(f"Could not save tape snapshot: {e}")
        return tape.to_dict()

    fallback = IntradayTape.load_latest_snapshot()
    if fallback:
        payload = fallback.to_dict()
        payload["stale"] = True
        return payload

    return tape.to_dict()


# ── Market State ──────────────────────────────────────────────────────────────

@app.get("/api/market/regime")
@cache("regime_state")
async def get_regime_state(
    horizon: str = Query("default", enum=["default", "swing", "investor"]),
    refresh: bool = Query(False),
    user: dict = Depends(verify_clerk_token),
):
    return await _resolve_regime_state(horizon=horizon, refresh=refresh)


@app.get("/api/market/tape")
@cache("intraday_tape")
async def get_intraday_tape(user: dict = Depends(verify_clerk_token)):
    return await _resolve_intraday_tape()


@app.get("/api/market/dashboard")
@cache("dashboard")
async def get_dashboard(
    horizon: str = Query("default", enum=["default", "swing", "investor"]),
    user: dict = Depends(verify_clerk_token),
):
    regime = await _resolve_regime_state(horizon=horizon, refresh=False)
    tape = await _resolve_intraday_tape()
    return {
        "regime": regime,
        "tape": tape,
        "asof_utc": datetime.now(timezone.utc).isoformat(),
        "stale": bool(regime.get("stale")) or bool(tape.get("stale")),
    }


@app.get("/api/market/regime/history")
async def get_regime_history(
    days: int = Query(30, ge=1, le=252),
    user: dict = Depends(verify_clerk_token),
):
    from src.state.regime_state import RegimeState
    from pathlib import Path

    snapshot_dir = Path("data/snapshots")
    snapshots = []

    for i in range(days):
        d = (date.today() - timedelta(days=i)).isoformat()
        snap = RegimeState.load_snapshot(d)
        if snap:
            snapshots.append({
                "date": snap.asof_date,
                "score_total": snap.score_total,
                "environment": snap.environment,
                "layer_monetary":    snap.layer_monetary,
                "layer_credit":      snap.layer_credit,
                "layer_volatility":  snap.layer_volatility,
                "layer_breadth":     snap.layer_breadth,
                "layer_positioning": snap.layer_positioning,
                "layer_agreement":   snap.layer_agreement,
                "confidence":        snap.confidence,
            })

    return {"snapshots": snapshots, "n": len(snapshots)}


@app.get("/api/market/analogues")
@cache("market_state")
async def get_historical_analogues(
    top_n: int = Query(15, ge=5, le=30),
    user: dict = Depends(verify_clerk_token),
):
    from src.state.regime_state import RegimeState, build_regime_state
    from src.analysis.analogues import get_historical_analogues as _get_analogues

    today = date.today().isoformat()
    regime = RegimeState.load_snapshot(today)
    if not regime:
        regime = await asyncio.to_thread(build_regime_state, save=True)

    score_delta = regime.score_delta

    try:
        result = await asyncio.to_thread(
            _get_analogues,
            environment=regime.environment or "Mixed / Neutral",
            score_total=regime.score_total or 50.0,
            vix_level=regime.vix_level,
            sectors_green=regime.sectors_green,
            score_delta=score_delta,
            confidence=regime.confidence,
            top_n=top_n,
        )
    except FileNotFoundError as exc:
        logger.error("Historical analogue data missing: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Historical analogue research data is not available on this backend.",
        )
    except Exception as exc:
        logger.error("Historical analogue lookup failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Historical analogue lookup failed.",
        )

    result["current_state"] = {
        "score_total":       regime.score_total,
        "confidence":        regime.confidence,
        "environment":       regime.environment,
        "vix_level":         regime.vix_level,
        "sectors_green":     regime.sectors_green,
        "layer_agreement":   regime.layer_agreement,
        "layer_monetary":    regime.layer_monetary,
        "layer_credit":      regime.layer_credit,
        "layer_volatility":  regime.layer_volatility,
        "layer_breadth":     regime.layer_breadth,
        "layer_positioning": regime.layer_positioning,
        "score_delta":       score_delta,
        "asof_utc":          regime.asof_utc,
    }

    return result


@app.get("/api/analogues/rolling-composite")
@cache("market_state")
async def get_rolling_composite_analogues(
    asof_date: Optional[str] = Query(None),
    lookback_days: int = Query(30, ge=1, le=252),
    half_life: int = Query(30, ge=1, le=252),
    top_n_per_lookup: int = Query(15, ge=1, le=50),
    pool_top_n: int = Query(50, ge=1, le=200),
    exclude_recent_days: int = Query(60, ge=0, le=365),
    user: dict = Depends(verify_clerk_token),
):
    from src.analysis.rolling_composite import get_rolling_composite

    try:
        return await asyncio.to_thread(
            get_rolling_composite,
            asof_date=asof_date,
            lookback_days=lookback_days,
            half_life=half_life,
            top_n_per_lookup=top_n_per_lookup,
            pool_top_n=pool_top_n,
            exclude_recent_days=exclude_recent_days,
        )
    except FileNotFoundError as exc:
        logger.error("Rolling composite analogue data missing: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Historical analogue research data is not available on this backend.",
        )
    except Exception as exc:
        logger.error("Rolling composite analogue lookup failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Rolling composite analogue lookup failed.",
        )


@app.get("/api/market/delta", response_model=DeltaOut)
@cache("market_state")
async def get_market_delta(
    horizon: str = Query("1D"),
    user: dict = Depends(verify_clerk_token),
):
    state = await asyncio.to_thread(build_market_state, horizon=horizon)
    state = await asyncio.to_thread(score_market_state, state)
    session_date = state.market_session_date
    prev_date, prev_state = await asyncio.to_thread(
        find_previous_snapshot, SNAPSHOT_DIR, session_date
    )
    if prev_state is None:
        raise HTTPException(404, "No prior snapshot found")
    d = diff_states(state, prev_state)
    d["bullets"] = diff_to_bullets(d)
    return DeltaOut(**d)


# ── Brief ─────────────────────────────────────────────────────────────────────

@app.get("/api/brief/macro")
@cache("macro")
async def get_macro(user: dict = Depends(verify_clerk_token)):
    signals = await asyncio.to_thread(fetch_regime_signals)
    return {
        k: {
            "name": v.name,
            "latest": v.latest,
            "mom": v.mom,
            "yoy": v.yoy,
            "trend": v.trend,
            "components": v.components,
            "history": v.history_12m.tolist(),
            "history_index": [str(d) for d in v.history_12m.index],
        }
        for k, v in signals.items()
    }


@app.get("/api/brief/moves")
@cache("brief_moves")
async def get_market_moves(
    tickers: str = Query("SPY,QQQ,IWM,DIA,TLT,HYG,GLD,USO,BTC-USD"),
    user: dict = Depends(verify_clerk_token),
):
    ticker_list = [t.strip() for t in tickers.split(",")]
    df = await asyncio.to_thread(fetch_market_moves, ticker_list)
    return df.to_dict(orient="records") if df is not None else []


@app.get("/api/brief/summary")
@cache("brief_summary")
async def get_brief_summary(user: dict = Depends(verify_clerk_token)):
    try:
        signals = await asyncio.to_thread(fetch_regime_signals)
        moves_df = await asyncio.to_thread(
            fetch_market_moves,
            ["SPY", "QQQ", "IWM", "DIA", "TLT", "HYG", "GLD", "USO", "BTC-USD"]
        )
        text = await asyncio.to_thread(
            generate_what_matters_today,
            macro_signals=signals,
            market_moves_df=moves_df,
            portfolio_flags=[],
            model=PREPROCESSING_MODEL,
        )
        return {"summary": text}
    except Exception as e:
        signals = await asyncio.to_thread(fetch_regime_signals)
        moves_df = await asyncio.to_thread(fetch_market_moves, ["SPY","QQQ","IWM"])
        text = heuristic_what_matters(signals, moves_df, [])
        return {"summary": text, "fallback": True}


@app.get("/api/market/context")
@cache("state_context")
async def get_market_context(user: dict = Depends(verify_clerk_token)):
    heatmap = await get_heatmap(horizon="1D")
    movers = await get_market_moves(
        tickers="SPY,QQQ,IWM,DIA,TLT,HYG,GLD,USO,BTC-USD"
    )
    return {
        "sectors": heatmap.get("sectors", []),
        "movers": movers,
        "asof_utc": datetime.now(timezone.utc).isoformat(),
    }


# ── Prices ────────────────────────────────────────────────────────────────────

@app.get("/api/prices/heatmap")
@cache("prices")
async def get_heatmap(
    horizon: str = Query("1D"),
    user: dict = Depends(verify_clerk_token),
):
    from src.data.price_context import build_price_context
    price_ctx = await build_price_context(
        horizon=horizon,
        include_secondary_horizons=False,
    )
    # Return shape is unchanged from prior implementation so the frontend
    # markets page continues to work. "last" is additive — existing reads
    # of "return" are unaffected.
    return {
        "sectors": price_ctx["sectors"],
        "cross":   price_ctx["cross_asset"],
        "horizon": horizon,
    }


@app.get("/api/prices/chart")
@cache("prices")
async def get_chart(
    ticker: str = Query("SPY"),
    tf: str = Query("1D"),
    user: dict = Depends(verify_clerk_token),
):
    import yfinance as yf

    TF_MAP = {
        "1D": ("1d",  "5m"),
        "5D": ("5d",  "15m"),
        "1M": ("1mo", "1h"),
        "3M": ("3mo", "1d"),
        "YTD":("1y",  "1d"),
    }
    period, interval = TF_MAP.get(tf, ("1mo", "1d"))
    df = await asyncio.to_thread(
        yf.download, ticker, period=period,
        interval=interval, auto_adjust=False, progress=False
    )
    if df.empty:
        raise HTTPException(404, "No data returned")

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.reset_index()
    date_col = "Datetime" if "Datetime" in df.columns else "Date"
    df = df.rename(columns={date_col: "time"})
    df["time"] = pd.to_datetime(df["time"]).dt.strftime("%Y-%m-%dT%H:%M:%S")

    return {
        "ticker": ticker,
        "tf": tf,
        "ohlcv": df[["time","Open","High","Low","Close","Volume"]].dropna().to_dict(orient="records")
    }


# ── Portfolio ─────────────────────────────────────────────────────────────────

@app.post("/api/portfolio/analyze", response_model=PortfolioOut)
async def analyze_portfolio(
    file: UploadFile = File(...),
    user: dict = Depends(verify_clerk_token),
):
    contents = await file.read()
    try:
        df = load_portfolio_csv(io.BytesIO(contents))
    except Exception as e:
        raise HTTPException(400, f"Could not parse CSV: {e}")

    snap = await asyncio.to_thread(compute_portfolio_snapshot, df)
    overlay = await asyncio.to_thread(analyze_portfolio_for_regime, df)

    try:
        from src.data.macro import fetch_regime_signals as _frs
        macro = await asyncio.to_thread(_frs)
    except Exception:
        macro = None

    snap["flags"] = add_regime_aware_flags(
        base_flags=snap["flags"],
        macro_signals=macro,
        summary=snap["summary"],
        theme_exposure=snap["theme_exposure"],
        top_positions=snap["top_positions"],
    )

    return PortfolioOut(
        summary=snap["summary"],
        top_positions=snap["top_positions"].to_dict(orient="records"),
        theme_exposure=snap["theme_exposure"].to_dict(orient="records"),
        flags=snap["flags"],
        regime_overlay=overlay,
    )


# ── Narrative ─────────────────────────────────────────────────────────────────

@app.post("/api/narrative/synthesize")
async def trigger_narrative(
    background_tasks: BackgroundTasks,
    news_category: str = Query("general"),
    earnings_days: int = Query(7),
    tickers: str = Query("SPY,QQQ,IWM,AAPL,MSFT,NVDA,TSLA"),
    lookback_hours: int = Query(36),
    user: dict = Depends(verify_clerk_token),
):
    try:
        assert_live_mode("manual narrative synthesis")
        assert_llm_calls_allowed("manual narrative synthesis")
    except RuntimeError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"status": "running"}

    async def _run():
        try:
            watch = [t.strip().upper() for t in tickers.split(",")]
            bundle = await asyncio.to_thread(
                build_narrative_bundle,
                watch_tickers=watch,
                news_category=news_category,
                news_limit=80,
                ticker_news_limit=20,
                earnings_days_ahead=earnings_days,
            )

            state_obj = await asyncio.to_thread(build_market_state)
            state_obj = await asyncio.to_thread(score_market_state, state_obj)
            from src.state.market_state import summarize_state
            market_summary = summarize_state(state_obj)

            moves_df = await asyncio.to_thread(fetch_market_moves, watch)
            moves = moves_df.to_dict(orient="records") if moves_df is not None else []

            # Build price context (sector/cross-asset/relationship returns) so the
            # LLM can compare narrative/fundamentals against actual market behavior.
            # Failure here is non-fatal — synthesis runs with price_context=None.
            # Derive single-name tickers from bundle items so company-specific
            # price evidence (e.g. LLY, MRK, GOOGL) appears in price_ledger.
            price_context = None
            try:
                from src.data.price_context import build_multi_timeframe_price_context
                from src.narrative.synth import extract_tickers_from_items
                _bundle_items = bundle.to_dict().get("items") or []
                _derived = extract_tickers_from_items(_bundle_items, max_tickers=20)
                _seen_w: set[str] = set(watch)
                _combined_watch = list(watch) + [t for t in _derived if t not in _seen_w]
                price_context = await build_multi_timeframe_price_context(
                    watch_tickers=_combined_watch,
                )
                _pc_errors = (price_context or {}).get("errors") or []
                if _pc_errors:
                    logger.warning(
                        "price_context returned with %d error(s) "
                        "(watch=%s): %s",
                        len(_pc_errors), _combined_watch[:5], _pc_errors,
                    )
                else:
                    logger.info(
                        "price_context OK — %d cross_asset, %d sectors, "
                        "%d single_names, %d relationships, horizons=%s",
                        len((price_context or {}).get("cross_asset") or []),
                        len((price_context or {}).get("sectors") or []),
                        len((price_context or {}).get("single_names") or []),
                        len((price_context or {}).get("relationships") or []),
                        (price_context or {}).get("horizons"),
                    )
            except Exception as _pc_err:
                import traceback as _tb
                logger.warning(
                    "price_context build raised an exception "
                    "(continuing without — watch=%s): %s\n%s",
                    watch,
                    _pc_err,
                    _tb.format_exc(),
                )

            asof = bundle.asof_utc if hasattr(bundle, "asof_utc") else ""
            prior_date, prior = load_latest_narrative_snapshot(SNAPSHOT_DIR, asof[:10])

            result = await asyncio.to_thread(
                synthesize_narrative_state,
                bundle.to_dict(),
                market_state_summary=market_summary,
                market_moves=moves,
                prior_state=prior,
                lookback_hours=lookback_hours,
                model=FINAL_SYNTHESIS_MODEL,
                price_context=price_context,
            )
            save_narrative_snapshot(result, SNAPSHOT_DIR, asof[:10])
            _jobs[job_id] = {"status": "done", "result": result}
        except Exception as e:
            _jobs[job_id] = {"status": "error", "error": str(e)}

    background_tasks.add_task(_run)
    return {"job_id": job_id, "status": "running"}


@app.get("/api/narrative/status/{job_id}")
async def narrative_status(
    job_id: str,
    user: dict = Depends(verify_clerk_token),
):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


# In-memory tracking of in-flight cache generation per ticker.
# Cleared once the background task finishes (success or failure).
_cache_generating: dict[str, dict] = {}

# Hard ceiling on a single generation. yfinance + bundle + price context +
# GPT-5.5 synthesis typically finishes well under 2 min on warm caches; 240s
# leaves headroom without letting a stuck call sit forever.
NARRATIVE_GENERATION_TIMEOUT_SEC: int = 240


def _with_result_alias(record: dict, *, mode: str, is_mock: bool) -> dict:
    out = dict(record)
    output = out.get("output")
    if output is not None:
        out["result"] = output
    out["narrative_mode"] = mode
    out["is_mock"] = is_mock
    return out


@app.get("/api/narrative/latest")
async def get_latest_narrative(
    ticker: str = Query("SPY"),
    user: dict = Depends(verify_clerk_token),
):
    """
    User-facing read endpoint for the Narrative page.

    Behavior per ticker:
      - Supported subjects: S&P 500 and Nasdaq-100 constituents use the same
        cache/mock/live flow.
      - Unsupported subjects: return status=unsupported and never generate.
    """
    ticker_u = normalize_ticker(ticker)
    mode = get_narrative_mode()
    profile = get_ticker_profile(ticker_u)
    subject = prompt_subject_profile(profile) if profile else None

    if not is_supported_ticker(ticker_u):
        return {
            "status": "unsupported",
            "ticker": ticker_u,
            "cache_hit": False,
            "is_mock": False,
            "narrative_mode": mode,
            "message": (
                f"Ticker-specific Helix reads are currently enabled for {supported_ticker_label()}."
            ),
        }

    if mode == "mock":
        fixture = load_narrative_fixture(ticker_u)
        fixture["status"] = "ready"
        fixture["ticker"] = ticker_u
        if subject:
            fixture["subject"] = subject
            fixture["subject_type"] = subject.get("subject_type")
        fixture["cache_hit"] = False
        fixture["narrative_mode"] = "mock"
        fixture["is_mock"] = True
        return _with_result_alias(fixture, mode="mock", is_mock=True)

    today = date.today().isoformat()

    if mode == "cache":
        cached = load_narrative_cache(ticker_u, today) or load_latest_narrative_cache(ticker_u)
        if cached:
            cached["cache_hit"] = True
            cached["status"] = "ready"
            if subject:
                cached["subject"] = subject
                cached["subject_type"] = subject.get("subject_type")
            save_memory_record(cached)
            return _with_result_alias(cached, mode="cache", is_mock=False)
        return {
            "status": "cache_miss",
            "ticker": ticker_u,
            "subject": subject,
            "cache_hit": False,
            "is_mock": False,
            "narrative_mode": "cache",
            "message": "No cached narrative read is available for this ticker/date in cache-only mode.",
        }

    # 1. Cache hit — serve immediately
    cached = load_narrative_cache(ticker_u, today)
    if cached:
        cached["cache_hit"] = True
        cached["status"] = "ready"
        if subject:
            cached["subject"] = subject
            cached["subject_type"] = subject.get("subject_type")
        save_memory_record(cached)
        return _with_result_alias(cached, mode="live", is_mock=False)

    # 2. Cache miss — check in-flight generation
    pending = _cache_generating.get(ticker_u)
    if pending and not pending.get("done"):
        return {
            "status": "generating",
            "cache_hit": False,
            "ticker": ticker_u,
            "subject": subject,
            "is_mock": False,
            "narrative_mode": "live",
            "started_at": pending.get("started_at"),
            "last_cached_result": load_latest_narrative_cache(ticker_u),
        }

    # 3. Last attempt errored? Surface that with a stale fallback if available
    last_error = pending.get("error") if (pending and pending.get("done")) else None

    if not llm_calls_allowed():
        stale = load_latest_narrative_cache(ticker_u)
        if stale:
            stale["status"] = "ready"
            stale["cache_hit"] = True
            stale["stale_cache"] = True
            stale["generation_blocked"] = True
            stale["message"] = "Showing latest cached narrative read because live generation is blocked."
            if subject:
                stale["subject"] = subject
                stale["subject_type"] = subject.get("subject_type")
            save_memory_record(stale)
            return _with_result_alias(stale, mode="live", is_mock=False)
        return {
            "status": "llm_blocked",
            "ticker": ticker_u,
            "subject": subject,
            "cache_hit": False,
            "is_mock": False,
            "narrative_mode": "live",
            "message": "Live narrative generation is blocked because LLM calls are disabled.",
            "last_cached_result": load_latest_narrative_cache(ticker_u),
            "last_error": last_error,
        }

    # 4. Kick off a fresh generation
    assert_llm_calls_allowed("narrative live generation")
    started_at = datetime.now(timezone.utc).isoformat()
    _cache_generating[ticker_u] = {"done": False, "started_at": started_at}

    async def _generate(t: str, day: str) -> None:
        # Wrap the whole pipeline in a hard timeout. Any error path (including
        # timeout) marks the entry done in `finally` so subsequent requests
        # can re-trigger generation instead of hanging on a stuck pending flag.
        error_str: Optional[str] = None
        try:
            result = await asyncio.wait_for(
                run_narrative_for_ticker(t),
                timeout=NARRATIVE_GENERATION_TIMEOUT_SEC,
            )
            record = build_cache_record(
                t, day, result,
                final_model=FINAL_SYNTHESIS_MODEL,
                preprocessing_model=PREPROCESSING_MODEL,
                prompt_version=PROMPT_VERSION,
                source_config_version=SOURCE_CONFIG_VERSION,
                narrative_mode="live",
            )
            save_narrative_cache(t, day, record)
            save_memory_record(record)
            logger.info("Narrative cache populated for %s on %s", t, day)
        except asyncio.TimeoutError:
            error_str = f"timeout after {NARRATIVE_GENERATION_TIMEOUT_SEC}s"
            logger.error(
                "%s narrative generation timed out after %ds",
                t, NARRATIVE_GENERATION_TIMEOUT_SEC,
            )
        except Exception as exc:
            import traceback as _tb
            error_str = str(exc)
            logger.error(
                "Narrative cache generation failed for %s: %s\n%s",
                t, exc, _tb.format_exc(),
            )
        finally:
            entry: dict = {"done": True, "started_at": started_at}
            if error_str:
                entry["error"] = error_str
            _cache_generating[t] = entry

    asyncio.create_task(_generate(ticker_u, today))

    return {
        "status": "generating",
        "cache_hit": False,
        "ticker": ticker_u,
        "subject": subject,
        "is_mock": False,
        "narrative_mode": "live",
        "started_at": started_at,
        "last_cached_result": load_latest_narrative_cache(ticker_u),
        "last_error": last_error,
    }


# Internal/dev: manual synthesis snapshot (kept for trends + historical paths
# that still load from data/snapshots). Not used by the user-facing UI anymore.
@app.get("/api/narrative/snapshot")
async def get_latest_narrative_snapshot(user: dict = Depends(verify_clerk_token)):
    today = datetime.now().strftime("%Y-%m-%d")
    _, snap = load_latest_narrative_snapshot(SNAPSHOT_DIR, today)
    if snap is None:
        raise HTTPException(404, "No narrative snapshot found")
    return snap


# ── Trends ────────────────────────────────────────────────────────────────────

@app.get("/api/narrative/trends/scan")
async def trends_scan(
    snapshot_date: Optional[str] = Query(None, description="YYYY-MM-DD; defaults to today"),
    skip_static: bool = Query(False),
    skip_dynamic: bool = Query(False),
    user: dict = Depends(verify_clerk_token),
):
    from src.narrative.trends import run_trend_scan, save_scan_result
    today = snapshot_date or datetime.now().strftime("%Y-%m-%d")
    _, snapshot = load_latest_narrative_snapshot(SNAPSHOT_DIR, today)

    result = await asyncio.to_thread(
        run_trend_scan,
        snapshot=snapshot,
        snapshot_date=today,
        skip_static=skip_static,
        skip_dynamic=skip_dynamic,
    )
    await asyncio.to_thread(save_scan_result, result, TRENDS_OUTPUT_DIR)
    return result.to_dict()


@app.get("/api/narrative/trends/live")
async def trends_live(user: dict = Depends(verify_clerk_token)):
    from pathlib import Path
    scan_dir = Path(TRENDS_OUTPUT_DIR)
    if not scan_dir.exists():
        raise HTTPException(404, "no scan available")
    files = sorted(scan_dir.glob("trends_*.json"))
    if not files:
        raise HTTPException(404, "no scan available")
    try:
        return json.loads(files[-1].read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(500, f"Failed to read scan: {exc}")


@app.get("/api/narrative/trends/history")
async def trends_history(
    days_back: int = Query(30, ge=1, le=365),
    user: dict = Depends(verify_clerk_token),
):
    from src.narrative.trends import build_trend_history_df
    df = await asyncio.to_thread(build_trend_history_df, TRENDS_OUTPUT_DIR)
    if df.empty:
        return {"records": [], "n_rows": 0}
    subset = df.tail(days_back)
    subset = subset.copy()
    subset["date"] = subset["date"].astype(str)
    return {"records": subset.to_dict(orient="records"), "n_rows": len(subset)}


@app.post("/api/narrative/trends/backtest")
async def trends_backtest(
    body: dict,
    user: dict = Depends(verify_clerk_token),
):
    import time as _time
    from src.narrative.trends_history import run_historical_backtest
    from pathlib import Path

    synthetic = bool(body.get("synthetic", True))
    start = body.get("start")
    end = body.get("end")

    t0 = _time.monotonic()
    result = await asyncio.to_thread(
        run_historical_backtest,
        use_synthetic=synthetic,
        start=start,
        end=end,
    )
    elapsed = _time.monotonic() - t0
    if elapsed > 60:
        logger.warning("trends_backtest took %.1fs (>60s threshold)", elapsed)

    out_dir = Path(TRENDS_OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = "synthetic" if synthetic else (start[:4] if start else "custom")

    history_chart = str(out_dir / f"trends_history_{suffix}.png")
    sq_chart = str(out_dir / f"signal_quality_{suffix}.png")

    await asyncio.to_thread(result.plot, history_chart)
    from src.narrative.trends_history import plot_signal_quality
    await asyncio.to_thread(plot_signal_quality, result.term_results, sq_chart)

    return {
        "results": result.to_dataframe().to_dict(orient="records"),
        "charts": {
            "history": history_chart,
            "signal_quality": sq_chart,
        },
    }


@app.get("/api/narrative/historical/{date_str}")
async def get_historical_narrative(
    date_str: str,
    user: dict = Depends(verify_clerk_token),
):
    import re
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        raise HTTPException(400, "Date must be in YYYY-MM-DD format")

    try:
        from src.analysis.historical_narrative import generate_historical_narrative
        result = await asyncio.to_thread(generate_historical_narrative, date_str)
        return result
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(500, f"Failed to generate narrative: {e}")


@app.get("/api/market/conditional")
async def get_conditional(user: dict = Depends(verify_clerk_token)):
    # Conditional probabilities query the historical analogues database, which
    # was scored with the new five-layer regime system. Today's conditions must
    # come from the same system or the comparison is apples-to-oranges.
    from src.state.regime_state import RegimeState, build_regime_state
    from src.analysis.conditional_probability import get_conditional_stats

    today = date.today().isoformat()
    regime = RegimeState.load_snapshot(today)
    if not regime:
        regime = await asyncio.to_thread(build_regime_state, save=True)

    result = get_conditional_stats(
        environment=regime.environment,
        score_total=regime.score_total,
        vix_level=regime.vix_level,
        sectors_green=regime.sectors_green,
        score_delta=regime.score_delta,
        confidence=regime.confidence,
    )
    return result


@app.get("/api/debug/price-context")
async def debug_price_context(
    tickers: str = Query("SPY,QQQ,IWM,TLT,HYG,LLY,NVDA,META"),
):
    """
    Probe build_multi_timeframe_price_context and return the full result.
    Useful for confirming yfinance data is flowing and that per-asset
    multi-horizon returns + trend_context are populated.

    Not auth-guarded — hit directly from a browser or curl.
    """
    import time as _time
    from src.data.price_context import build_multi_timeframe_price_context

    watch = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    t0 = _time.monotonic()
    result = await build_multi_timeframe_price_context(watch_tickers=watch)
    elapsed_ms = round((_time.monotonic() - t0) * 1000)

    return {
        "ok":                  not bool(result.get("errors")),
        "elapsed_ms":          elapsed_ms,
        "asof_utc":            result.get("asof_utc"),
        "format":              result.get("format"),
        "horizons":            result.get("horizons"),
        "cross_asset_count":   len(result.get("cross_asset") or []),
        "sectors_count":       len(result.get("sectors") or []),
        "single_names_count":  len(result.get("single_names") or []),
        "relationships_count": len(result.get("relationships") or []),
        "errors":              result.get("errors") or [],
        # Full data for inspection
        "cross_asset":   result.get("cross_asset"),
        "sectors":       result.get("sectors"),
        "single_names":  result.get("single_names"),
        "relationships": result.get("relationships"),
    }


@app.get("/health")
async def health():
    return {"status": "ok"}
