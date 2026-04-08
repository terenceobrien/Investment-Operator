from __future__ import annotations

import asyncio
import io
import sys
import uuid
from pathlib import Path
from typing import Optional

import pandas as pd
from fastapi import FastAPI, HTTPException, Query, UploadFile, File, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware

# Make sure src/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.cache import cache
from api.models import (
    MarketStateOut, DeltaOut, PortfolioOut, NarrativeOut
)

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

app = FastAPI(title="Market Intelligence API", version="1.0.0")

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


# ── Market State ──────────────────────────────────────────────────────────────

@app.get("/api/market/state", response_model=MarketStateOut)
@cache("market_state")
async def get_market_state(horizon: str = Query("1D")):
    if horizon not in HORIZONS:
        raise HTTPException(400, f"Invalid horizon. Choose from {list(HORIZONS.keys())}")
    state = await asyncio.to_thread(build_market_state, horizon=horizon)
    state = await asyncio.to_thread(score_market_state, state)
    await asyncio.to_thread(save_snapshot, state, SNAPSHOT_DIR)
    return MarketStateOut(**state.to_dict())


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


# ── Prices ────────────────────────────────────────────────────────────────────

@app.get("/api/prices/heatmap")
@cache("prices")
async def get_heatmap(horizon: str = Query("1D")):
    import yfinance as yf
    import numpy as np
    from datetime import datetime

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