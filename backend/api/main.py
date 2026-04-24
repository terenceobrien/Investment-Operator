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
from fastapi import FastAPI, HTTPException, Query, UploadFile, File, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware

# Make sure src/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.cache import cache
from api.models import (
    MarketStateOut, DeltaOut, PortfolioOut, NarrativeOut
)
from api.strategy_router import strategy_router

from src.state.market_state import (
    build_market_state, save_snapshot, HORIZONS
)
from src.state.scoring import score_market_state
from src.state.delta import find_previous_snapshot, diff_states, diff_to_bullets
from src.data.macro import fetch_regime_signals
from src.data.market import fetch_market_moves
from src.data.portfolio import load_portfolio_csv
from src.brief.portfolio import compute_portfolio_snapshot, add_regime_aware_flags
from src.brief.what_matters import generate_what_matters_today, heuristic_what_matters
from src.narrative.bundle import build_narrative_bundle, top_n_by_channel
from src.narrative.synth import synthesize_narrative_state, load_latest_narrative_snapshot, save_narrative_snapshot

logger = logging.getLogger("api.main")

app = FastAPI(title="Market Intelligence API", version="1.0.0")
app.include_router(strategy_router)

@app.on_event("startup")
async def startup_prewarm():
    """Build today's regime snapshot in background at startup, then schedule daily trend scan."""
    import asyncio

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
    """Return seconds until the next 6:30 PM US/Eastern wall-clock time."""
    import zoneinfo
    eastern = zoneinfo.ZoneInfo("America/New_York")
    now_et = datetime.now(tz=eastern)
    target = now_et.replace(hour=18, minute=30, second=0, microsecond=0)
    if now_et >= target:
        target += timedelta(days=1)
    return (target - now_et).total_seconds()


async def _run_daily_trend_scan() -> None:
    """Load latest narrative snapshot and run trend scan. Logs all outcomes."""
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
    """Background loop: fire _run_daily_trend_scan every day at 6:30 PM Eastern."""
    while True:
        wait = _seconds_until_next_630pm_eastern()
        logger.info("Next daily trend scan in %.0fs (%.1f hours)", wait, wait / 3600)
        await asyncio.sleep(wait)
        await _run_daily_trend_scan()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://ai-financial-operator.vercel.app",
        "https://ai-financial-operator-*.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SNAPSHOT_DIR = "data/snapshots"

# In-memory job store for long-running narrative synthesis
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
@cache("regime_state")           # long cache — regime doesn't change intraday
async def get_regime_state(
    horizon: str = Query("default", enum=["default", "swing", "investor"]),
    refresh: bool = Query(False),
):
    """
    Returns the current daily regime state.
    Computed once at close — stable throughout the day.
    If today's snapshot exists on disk, loads it (fast).
    If not, computes it fresh (slow — ~30s on first call).
    """
    return await _resolve_regime_state(horizon=horizon, refresh=refresh)
 
 
# ── Intraday tape endpoint (live, 5min refresh) ───────────────────────────────
 
@app.get("/api/market/tape")
@cache("intraday_tape")          # short cache — updates every 5 min
async def get_intraday_tape():
    """
    Returns live intraday tape metrics.
    Updates every 5 minutes during market hours.
    Never modifies the regime score.
    """
    return await _resolve_intraday_tape()
 
 
# ── Combined endpoint (for the main dashboard) ────────────────────────────────
 
@app.get("/api/market/dashboard")
@cache("dashboard")
async def get_dashboard(
    horizon: str = Query("default", enum=["default", "swing", "investor"]),
):
    """
    Returns both regime state and intraday tape in one call.
    Use this for the main market state page.
    """
    regime = await _resolve_regime_state(horizon=horizon, refresh=False)
    tape = await _resolve_intraday_tape()

    return {
        "regime": regime,
        "tape": tape,
        "asof_utc": datetime.now(timezone.utc).isoformat(),
        "stale": bool(regime.get("stale")) or bool(tape.get("stale")),
    }
 
 
# ── Historical regime snapshots ───────────────────────────────────────────────
 
@app.get("/api/market/regime/history")
async def get_regime_history(days: int = Query(30, ge=1, le=252)):
    """
    Returns the last N days of regime snapshots for trend analysis.
    """
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
 
 
# ── Cache TTL additions for cache.py ─────────────────────────────────────────
# Add these entries to your TTL_SECONDS dict in api/cache.py:
#
#   "regime_state":  3600 * 6,   # 6 hours — regime stable all day
#   "intraday_tape": 300,        # 5 minutes — live tape

# ── Add this to backend/api/main.py ──────────────────────────────────────────
# Place alongside your other endpoints

@app.get("/api/market/analogues")
@cache("market_state")
async def get_historical_analogues(top_n: int = Query(15, ge=5, le=30)):
    from src.state.regime_state import RegimeState, build_regime_state
    from src.analysis.analogues import get_historical_analogues as _get_analogues

    today = date.today().isoformat()

    # Use regime state (new system) not old market_state
    regime = RegimeState.load_snapshot(today)
    if not regime:
        regime = await asyncio.to_thread(build_regime_state, save=True)

    # Score delta from prior snapshot
    score_delta = regime.score_delta  # already computed in build_regime_state

    result = await asyncio.to_thread(
        _get_analogues,
        environment=regime.environment or "Mixed / Neutral",
        score_total=regime.score_total or 50.0,
        vix_level=regime.vix_level,
        sectors_green=regime.layer_breadth,  # use breadth layer as proxy
        score_delta=score_delta,
        confidence=regime.confidence,
        top_n=top_n,
    )

    result["current_state"] = {
        "score_total":    regime.score_total,
        "confidence":     regime.confidence,
        "environment":    regime.environment,
        "vix_level":      regime.vix_level,
        "layer_agreement": regime.layer_agreement,
        "score_delta":    regime.score_delta,
        "asof_utc":       regime.asof_utc,
    }

    return result
    
@app.get("/api/market/delta", response_model=DeltaOut)
@cache("market_state")
async def get_market_delta(horizon: str = Query("1D")):
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
async def get_macro():
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
    tickers: str = Query("SPY,QQQ,IWM,DIA,TLT,HYG,GLD,USO,BTC-USD")
):
    ticker_list = [t.strip() for t in tickers.split(",")]
    df = await asyncio.to_thread(fetch_market_moves, ticker_list)
    return df.to_dict(orient="records") if df is not None else []


@app.get("/api/brief/summary")
@cache("brief_summary")
async def get_brief_summary():
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
            model="gpt-4o-mini",
        )
        return {"summary": text}
    except Exception as e:
        signals = await asyncio.to_thread(fetch_regime_signals)
        moves_df = await asyncio.to_thread(fetch_market_moves, ["SPY","QQQ","IWM"])
        text = heuristic_what_matters(signals, moves_df, [])
        return {"summary": text, "fallback": True}


@app.get("/api/market/context")
@cache("state_context")
async def get_market_context():
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
async def get_heatmap(horizon: str = Query("1D")):
    import yfinance as yf
    import numpy as np

    SECTORS = {
        "XLB":"Materials","XLE":"Energy","XLF":"Financials",
        "XLI":"Industrials","XLK":"Technology","XLP":"Staples",
        "XLU":"Utilities","XLV":"Health Care","XLY":"Discretionary",
        "XLC":"Comm Services","XLRE":"Real Estate",
    }
    CROSS = {
        "SPY":"S&P 500","QQQ":"Nasdaq 100","IWM":"Russell 2000",
        "TLT":"20Y+ Treas","HYG":"High Yield","GLD":"Gold",
        "USO":"Oil","BTC-USD":"Bitcoin",
    }

    def _ret(series: pd.Series, h) -> float | None:
        s = series.dropna()
        if h == "YTD":
            ytd = s[s.index >= pd.Timestamp(datetime.now().year, 1, 1)]
            if ytd.empty: return None
            return float((ytd.iloc[-1] / ytd.iloc[0] - 1) * 100)
        n = int(h)
        if len(s) <= n: return None
        return float((s.iloc[-1] / s.iloc[-(n+1)] - 1) * 100)

    from src.state.market_state import HORIZONS as H
    h = H.get(horizon, 1)

    all_tickers = list(SECTORS.keys()) + list(CROSS.keys())
    data = await asyncio.to_thread(
        yf.download, all_tickers, period="2y",
        auto_adjust=True, progress=False, threads=True
    )
    closes = data.xs("Close", axis=1, level=0) if isinstance(data.columns, pd.MultiIndex) else data[["Close"]]

    sector_rets = {t: _ret(closes[t], h) for t in SECTORS if t in closes}
    cross_rets  = {t: _ret(closes[t], h) for t in CROSS  if t in closes}

    return {
        "sectors": [{"ticker": t, "name": SECTORS[t], "return": sector_rets.get(t)} for t in SECTORS],
        "cross":   [{"ticker": t, "name": CROSS[t],   "return": cross_rets.get(t)}  for t in CROSS],
        "horizon": horizon,
    }


@app.get("/api/prices/chart")
@cache("prices")
async def get_chart(
    ticker: str = Query("SPY"),
    tf: str = Query("1D")
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
async def analyze_portfolio(file: UploadFile = File(...)):
    contents = await file.read()
    try:
        df = load_portfolio_csv(io.BytesIO(contents))
    except Exception as e:
        raise HTTPException(400, f"Could not parse CSV: {e}")

    snap = await asyncio.to_thread(compute_portfolio_snapshot, df)

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
    )


# ── Narrative ─────────────────────────────────────────────────────────────────

@app.post("/api/narrative/synthesize")
async def trigger_narrative(
    background_tasks: BackgroundTasks,
    news_category: str = Query("general"),
    earnings_days: int = Query(7),
    tickers: str = Query("SPY,QQQ,IWM,AAPL,MSFT,NVDA,TSLA"),
    lookback_hours: int = Query(36),
):
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

            asof = bundle.asof_utc if hasattr(bundle, "asof_utc") else ""
            prior_date, prior = load_latest_narrative_snapshot(SNAPSHOT_DIR, asof[:10])

            result = await asyncio.to_thread(
                synthesize_narrative_state,
                bundle.to_dict(),
                market_state_summary=market_summary,
                market_moves=moves,
                prior_state=prior,
                lookback_hours=lookback_hours,
                model="gpt-4o",
            )
            save_narrative_snapshot(result, SNAPSHOT_DIR, asof[:10])
            _jobs[job_id] = {"status": "done", "result": result}
        except Exception as e:
            _jobs[job_id] = {"status": "error", "error": str(e)}

    background_tasks.add_task(_run)
    return {"job_id": job_id, "status": "running"}


@app.get("/api/narrative/status/{job_id}")
async def narrative_status(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@app.get("/api/narrative/latest")
async def get_latest_narrative():
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    _, snap = load_latest_narrative_snapshot(SNAPSHOT_DIR, today)
    if snap is None:
        raise HTTPException(404, "No narrative snapshot found")
    return snap


@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/api/market/conditional")
async def get_conditional():
    state = await asyncio.to_thread(build_market_state)
    state = await asyncio.to_thread(score_market_state, state)
    from src.analysis.conditional_probability import get_conditional_stats
    result = get_conditional_stats(
        environment=state.environment,
        score_total=state.score_total,
        vix_level=state.vix_level,
        sectors_green=state.sectors_green,
        confidence=state.confidence,
    )
    return result

# ── Add this to backend/api/main.py ──────────────────────────────────────────
# Place alongside your other endpoints

# ── Trends endpoints ──────────────────────────────────────────────────────────

TRENDS_OUTPUT_DIR = "data/narrative/trends"


@app.get("/api/narrative/trends/scan")
async def trends_scan(
    snapshot_date: Optional[str] = Query(None, description="YYYY-MM-DD; defaults to today"),
    skip_static: bool = Query(False),
    skip_dynamic: bool = Query(False),
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
async def trends_live():
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
async def trends_history(days_back: int = Query(30, ge=1, le=365)):
    from src.narrative.trends import build_trend_history_df
    df = await asyncio.to_thread(build_trend_history_df, TRENDS_OUTPUT_DIR)
    if df.empty:
        return {"records": [], "n_rows": 0}
    subset = df.tail(days_back)
    subset = subset.copy()
    subset["date"] = subset["date"].astype(str)
    return {"records": subset.to_dict(orient="records"), "n_rows": len(subset)}


@app.post("/api/narrative/trends/backtest")
async def trends_backtest(body: dict):
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
async def get_historical_narrative(date_str: str):
    """
    Generate a retrospective market narrative for a historical date
    using only quantitative market structure data.
    Results are cached in memory after first generation.
    """
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
