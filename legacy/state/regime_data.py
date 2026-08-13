"""
src/state/regime_data.py

Fetches all raw inputs needed for the five-layer regime scoring system.
Runs ONCE at market close — not intraday.

Returns a RegimeInputs dataclass with every field the scoring system needs.
Missing data is None — the scoring system handles this gracefully.
"""
from __future__ import annotations

import os
import requests
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import Optional
import numpy as np
import pandas as pd


# ── Output dataclass ──────────────────────────────────────────────────────────

@dataclass
class RegimeInputs:
    asof_date: str = ""

    # Layer 1 — Monetary
    net_liquidity:      Optional[float] = None   # WALCL - TGA - RRP (billions)
    net_liquidity_z:    Optional[float] = None   # z-score vs 1yr
    nfci:               Optional[float] = None   # Chicago Fed NFCI
    nfci_inverted:      Optional[float] = None   # -NFCI z-score
    m2_growth_yoy:      Optional[float] = None   # M2 YoY %
    fci_z:              Optional[float] = None   # FCI z-score inverted

    # Layer 2 — Credit
    hy_spread_level:    Optional[float] = None   # bps
    hy_spread_z:        Optional[float] = None
    hy_spread_chg_4w:   Optional[float] = None   # bps
    ig_spread_level:    Optional[float] = None   # bps
    ig_spread_z:        Optional[float] = None
    hyg_tlt_ratio_z:    Optional[float] = None

    # Layer 3 — Volatility
    vix_level:          Optional[float] = None
    vix_z_20d:          Optional[float] = None
    vix_term_slope:     Optional[float] = None   # VIX3M - VIX
    vvix_level:         Optional[float] = None
    vvix_z:             Optional[float] = None
    put_call_ratio:     Optional[float] = None   # generic/SPY-proxy put-call, not Cboe equity PCR
    skew_index:         Optional[float] = None

    # Layer 4 — Breadth
    pct_above_200d:         Optional[float] = None
    avg_dist_from_200d:     Optional[float] = None   # avg % distance of 11 sector ETFs from their 200d MA
    sectors_green:           Optional[int]   = None
    rsp_vs_spy_z:           Optional[float] = None
    adl_slope:              Optional[float] = None

    # Layer 5 — Positioning
    dealer_gamma_z:       Optional[float] = None
    put_call_5d_ma:       Optional[float] = None
    aaii_bull_minus_bear: Optional[float] = None
    cot_net_large_spec_z: Optional[float] = None
    equity_etf_flow_z:    Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_last(series: pd.Series) -> Optional[float]:
    try:
        v = series.dropna().iloc[-1]
        return float(v) if np.isfinite(float(v)) else None
    except Exception:
        return None


def _z_score(series: pd.Series, window: int = 252) -> Optional[float]:
    try:
        s = series.dropna()
        if len(s) < 20:
            return None
        rolling = s.rolling(window, min_periods=20)
        mu = rolling.mean().iloc[-1]
        sd = rolling.std().iloc[-1]
        if sd == 0 or not np.isfinite(sd):
            return None
        return float((s.iloc[-1] - mu) / sd)
    except Exception:
        return None


def _pct_change_yoy(series: pd.Series) -> Optional[float]:
    try:
        s = series.dropna()
        if len(s) < 252:
            return None
        latest = s.iloc[-1]
        year_ago = s.iloc[-252]
        if year_ago == 0:
            return None
        return float((latest / year_ago - 1) * 100)
    except Exception:
        return None


# ── FRED fetcher ──────────────────────────────────────────────────────────────

def _fred(
    series_id: str,
    periods: int = 520,
    asof_date: Optional[str] = None,
) -> pd.Series:
    """Fetch a FRED series. Returns empty Series on failure.

    If asof_date is provided, truncate the series to that date inclusive before
    taking the trailing observation window.
    """
    try:
        def _lazy_fred():
            from fredapi import Fred
            api_key = os.environ.get("FRED_API_KEY", "")
            return Fred(api_key=api_key)

        fred = _lazy_fred()
        data = fred.get_series(series_id)
        if data is None or data.empty:
            return pd.Series(dtype=float)
        data = data.dropna()
        if asof_date is not None:
            data = data[data.index <= pd.Timestamp(asof_date)]
        return data.tail(periods)
    except Exception as e:
        print(f"FRED fetch failed for {series_id}: {e}")
        return pd.Series(dtype=float)


# ── yfinance fetcher ──────────────────────────────────────────────────────────

def _yf_close(
    ticker: str,
    period: str = "2y",
    asof_date: Optional[str] = None,
) -> pd.Series:
    """Fetch closing prices via yfinance.

    If asof_date is provided, fetch a wider historical window and truncate to
    that date inclusive.
    """
    try:
        import yfinance as yf
        if asof_date is not None:
            asof_ts = pd.Timestamp(asof_date)
            start = (asof_ts - pd.Timedelta(days=365 * 3)).strftime("%Y-%m-%d")
            # yfinance treats end as exclusive, so add one calendar day and
            # still explicitly trim below to keep the fetch point-in-time.
            end = (asof_ts + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
            data = yf.download(
                ticker,
                start=start,
                end=end,
                progress=False,
                auto_adjust=True,
                threads=False,
            )
        else:
            data = yf.download(ticker, period=period, progress=False,
                               auto_adjust=True, threads=False)
        if data is None or data.empty:
            return pd.Series(dtype=float)
        closes = data["Close"].squeeze().dropna()
        if asof_date is not None:
            asof_ts = pd.Timestamp(asof_date)
            if getattr(closes.index, "tz", None) is not None:
                asof_ts = asof_ts.tz_localize(closes.index.tz)
            closes = closes[closes.index <= asof_ts]
        return closes
    except Exception as e:
        print(f"yfinance fetch failed for {ticker}: {e}")
        return pd.Series(dtype=float)


# ── Layer 1: Monetary ─────────────────────────────────────────────────────────

def _fetch_monetary(
    inputs: RegimeInputs,
    asof_date: Optional[str] = None,
) -> None:
    print("  Fetching monetary & liquidity data...")

    # Net liquidity = Fed balance sheet - TGA - RRP
    walcl = _fred("WALCL", asof_date=asof_date)      # Fed balance sheet (millions)
    tga   = _fred("WTREGEN", asof_date=asof_date)    # Treasury General Account (millions)
    rrp   = _fred("RRPONTSYD", asof_date=asof_date)  # Overnight reverse repo (billions)

    if not walcl.empty and not tga.empty and not rrp.empty:
        try:
            walcl_b = walcl / 1000  # millions -> billions
            tga_b = tga / 1000  # millions -> billions
            # Align to weekly frequency
            combined = pd.concat([walcl_b, tga_b, rrp], axis=1).ffill().dropna()
            combined.columns = ["walcl", "tga", "rrp"]
            print(combined.tail(3))          # <- add this
            print("walcl_b last:", walcl_b.iloc[-1], walcl_b.index[-1])
            print("tga_b last:", tga_b.iloc[-1], tga_b.index[-1])
            print("rrp last:", rrp.iloc[-1], rrp.index[-1])
            net_liq = combined["walcl"] - combined["tga"] - combined["rrp"]
            inputs.net_liquidity = _safe_last(net_liq)
            z = _z_score(net_liq, window=52)
            inputs.net_liquidity_z = z
            print(f"    net_liquidity=${inputs.net_liquidity:.0f}B  z={z}")
        except Exception as e:
            print(f"    net_liquidity calc failed: {e}")

    # NFCI — Chicago Fed National Financial Conditions Index
    nfci = _fred("NFCI", asof_date=asof_date)
    if not nfci.empty:
        inputs.nfci = _safe_last(nfci)
        # Inverted z-score: negative NFCI (easy) = positive score
        z = _z_score(nfci)
        inputs.nfci_inverted = -z if z is not None else None
        print(f"    nfci={inputs.nfci}  inverted_z={inputs.nfci_inverted}")

    # M2 growth YoY
    m2 = _fred("M2SL", asof_date=asof_date)
    if not m2.empty:
        try:
            s = m2.dropna()
            if len(s) >= 13:
                inputs.m2_growth_yoy = round(float((s.iloc[-1] / s.iloc[-13] - 1) * 100), 2)
                print(f"    m2_growth_yoy={inputs.m2_growth_yoy:.1f}%")
        except Exception:
            pass


# ── Layer 2: Credit ───────────────────────────────────────────────────────────

def _fetch_credit(
    inputs: RegimeInputs,
    asof_date: Optional[str] = None,
) -> None:
    print("  Fetching credit & stress data...")

    # HY spreads (BAMLH0A0HYM2 = ICE BofA HY OAS in %)
    hy = _fred("BAMLH0A0HYM2", asof_date=asof_date)
    if not hy.empty:
        hy_bps = hy * 100  # convert % to bps
        inputs.hy_spread_level = _safe_last(hy_bps)
        inputs.hy_spread_z = _z_score(hy_bps, window=504)  # 2yr

        # 4-week change
        try:
            s = hy_bps.dropna()
            if len(s) >= 20:
                inputs.hy_spread_chg_4w = float(s.iloc[-1] - s.iloc[-20])
        except Exception:
            pass
        print(f"    hy_spread={inputs.hy_spread_level}bps  z={inputs.hy_spread_z}  chg4w={inputs.hy_spread_chg_4w}")

    # IG spreads (BAMLC0A0CM = ICE BofA IG OAS in %)
    ig = _fred("BAMLC0A0CM", asof_date=asof_date)
    if not ig.empty:
        ig_bps = ig * 100
        inputs.ig_spread_level = _safe_last(ig_bps)
        inputs.ig_spread_z = _z_score(ig_bps, window=504)
        print(f"    ig_spread={inputs.ig_spread_level}bps  z={inputs.ig_spread_z}")

    # HYG/TLT ratio z-score via yfinance
    hyg = _yf_close("HYG", asof_date=asof_date)
    tlt = _yf_close("TLT", asof_date=asof_date)
    if not hyg.empty and not tlt.empty:
        try:
            ratio = (hyg / tlt).dropna()
            inputs.hyg_tlt_ratio_z = _z_score(ratio, window=252)
            print(f"    hyg_tlt_ratio_z={inputs.hyg_tlt_ratio_z}")
        except Exception:
            pass


# ── Layer 3: Volatility ───────────────────────────────────────────────────────

def _fetch_volatility(
    inputs: RegimeInputs,
    asof_date: Optional[str] = None,
) -> None:
    print("  Fetching volatility structure data...")

    vix   = _yf_close("^VIX",  period="1y", asof_date=asof_date)
    vix3m = _yf_close("^VIX3M", period="1y", asof_date=asof_date)
    vvix  = _yf_close("^VVIX", period="1y", asof_date=asof_date)
    skew  = _yf_close("^SKEW", period="1y", asof_date=asof_date)

    if not vix.empty:
        inputs.vix_level = _safe_last(vix)
        inputs.vix_z_20d = _z_score(vix, window=20)
        print(f"    vix={inputs.vix_level}  z={inputs.vix_z_20d}")

    if not vix.empty and not vix3m.empty:
        try:
            aligned = pd.concat([vix, vix3m], axis=1).dropna()
            aligned.columns = ["vix", "vix3m"]
            slope = aligned["vix3m"] - aligned["vix"]
            inputs.vix_term_slope = _safe_last(slope)
            print(f"    vix_term_slope={inputs.vix_term_slope} (VIX3M-VIX)")
        except Exception:
            pass

    if not vvix.empty:
        inputs.vvix_level = _safe_last(vvix)
        inputs.vvix_z = _z_score(vvix, window=252)
        print(f"    vvix={inputs.vvix_level}  z={inputs.vvix_z}")

    if not skew.empty:
        inputs.skew_index = _safe_last(skew)
        print(f"    skew={inputs.skew_index}")


# ── Layer 4: Breadth ──────────────────────────────────────────────────────────

def _fetch_breadth(
    inputs: RegimeInputs,
    sectors_green: Optional[int] = None,
    asof_date: Optional[str] = None,
) -> None:
    print("  Fetching breadth & participation data...")

    if sectors_green is None and asof_date is not None:
        try:
            sector_etfs = ["XLK", "XLF", "XLV", "XLY", "XLP",
                           "XLE", "XLI", "XLB", "XLU", "XLRE", "XLC"]
            green_count = 0
            for etf in sector_etfs:
                closes = _yf_close(etf, asof_date=asof_date)
                if len(closes) >= 2 and closes.iloc[-1] > closes.iloc[-2]:
                    green_count += 1
            sectors_green = green_count
            print(f"    sectors_green (historical)={sectors_green}/11")
        except Exception as e:
            print(f"    sectors_green historical compute failed: {e}")

    inputs.sectors_green = sectors_green

    # RSP vs SPY ratio z-score
    rsp = _yf_close("RSP", asof_date=asof_date)
    spy = _yf_close("SPY", asof_date=asof_date)
    if not rsp.empty and not spy.empty:
        try:
            ratio = (rsp / spy).dropna()
            inputs.rsp_vs_spy_z = _z_score(ratio, window=252)
            print(f"    rsp_vs_spy_z={inputs.rsp_vs_spy_z}")
        except Exception:
            pass

    # Continuous breadth proxy: average % distance from 200d MA across 11 sector ETFs.
    # Replaces the older binary "above/below 200d" indicator which had only 12
    # possible values. Positive = average sector is above its 200d MA.
    try:
        sector_etfs = ["XLK", "XLF", "XLV", "XLY", "XLP",
                        "XLE", "XLI", "XLB", "XLU", "XLRE", "XLC"]
        distances_pct = []
        above_count = 0

        for etf in sector_etfs:
            closes = _yf_close(etf, period="2y", asof_date=asof_date)
            if closes.empty or len(closes) < 200:
                continue
            ma200 = closes.rolling(200).mean().iloc[-1]
            if pd.isna(ma200) or ma200 == 0:
                continue
            current = closes.iloc[-1]
            distance_pct = (current - ma200) / ma200 * 100
            distances_pct.append(float(distance_pct))
            if current > ma200:
                above_count += 1

        if distances_pct:
            inputs.avg_dist_from_200d = round(sum(distances_pct) / len(distances_pct), 2)
            inputs.pct_above_200d = round(above_count / len(distances_pct) * 100, 1)
            print(
                f"    avg_dist_from_200d={inputs.avg_dist_from_200d}%  "
                f"pct_above_200d={inputs.pct_above_200d}%"
            )
    except Exception as e:
        print(f"    breadth distance compute failed: {e}")

    # Sector-level advance/decline line approximation.
    # True ADL uses individual stocks. This coarser proxy captures whether
    # participation is broadening or narrowing across the 11 sector ETFs.
    try:
        sector_etfs = ["XLK", "XLF", "XLV", "XLY", "XLP",
                        "XLE", "XLI", "XLB", "XLU", "XLRE", "XLC"]

        daily_changes = {}
        for etf in sector_etfs:
            closes = _yf_close(etf, period="2y", asof_date=asof_date)
            if closes.empty or len(closes) < 30:
                continue
            daily_changes[etf] = closes.pct_change()

        if len(daily_changes) >= 6:
            returns_df = pd.DataFrame(daily_changes).dropna(how="all")
            ad_per_day = (returns_df > 0).sum(axis=1) - (returns_df < 0).sum(axis=1)
            adl = ad_per_day.cumsum()

            if len(adl) >= 20:
                recent = adl.tail(20).values
                x = np.arange(len(recent))
                slope, _ = np.polyfit(x, recent, 1)
                inputs.adl_slope = float(slope)
                print(f"    adl_slope (sector-level, 20d)={inputs.adl_slope:+.3f}")
    except Exception as e:
        print(f"    adl_slope compute failed: {e}")


# ── Layer 5: Positioning ──────────────────────────────────────────────────────

def _fetch_cboe_pcr(asof_date: Optional[str] = None) -> Optional[float]:
    """
    Compute a generic SPY-options put/call proxy via yfinance.
    Uses the 3 nearest-dated expirations for liquid volume.
    CBOE's CDN (cdn.cboe.com) enforces Cloudflare and blocks programmatic access;
    SPY options data from yfinance is a proxy, not Cboe's official equity PCR.
    Returns the current-session put/call ratio, or None on failure.
    """
    if asof_date is not None:
        print(
            "    cboe_pcr: skipped for historical backfill "
            "(option chains are point-in-time only)"
        )
        return None

    try:
        import yfinance as yf
        spy = yf.Ticker("SPY")
        expirations = spy.options
        if not expirations:
            print("    cboe_pcr: no SPY options expirations available")
            return None

        total_put_vol  = 0.0
        total_call_vol = 0.0
        used = 0
        for exp in expirations[:3]:
            try:
                chain = spy.option_chain(exp)
                total_call_vol += float(chain.calls["volume"].fillna(0).sum())
                total_put_vol  += float(chain.puts["volume"].fillna(0).sum())
                used += 1
            except Exception:
                continue

        if total_call_vol == 0 or used == 0:
            print("    cboe_pcr: zero call volume or no valid chains")
            return None

        result = total_put_vol / total_call_vol
        print(f"    spy_options_put_call_proxy={result:.3f} ({used} expirations)")
        return result
    except Exception as e:
        print(f"    cboe_pcr: failed — {e}")
        return None


def _fetch_cftc_cot(asof_date: Optional[str] = None) -> Optional[float]:
    """
    Fetch CFTC Commitment of Traders — large speculator net position in S&P 500 futures.
    Source: CFTC public reporting Socrata API, dataset jun7-fc8e (legacy COT).
    Contract: E-MINI S&P 500 (cftc_contract_market_code = 13874A).
    Returns z-score vs 2-year rolling window, or None on failure.
    Updates weekly (released every Friday for prior Tuesday data).
    """
    try:
        url = "https://publicreporting.cftc.gov/resource/jun7-fc8e.json"
        where = "cftc_contract_market_code='13874A'"
        if asof_date is not None:
            where += f" AND report_date_as_yyyy_mm_dd <= '{asof_date}'"
        params = {
            "$where": where,
            "$order": "report_date_as_yyyy_mm_dd DESC",
            "$limit": "120",
        }
        resp = requests.get(url, params=params, timeout=20)
        resp.raise_for_status()

        records = resp.json()
        if not isinstance(records, list) or not records:
            print(f"    cftc_cot: unexpected response ({type(records).__name__}, len={len(records) if isinstance(records, list) else '?'})")
            return None

        rows = []
        for rec in records:
            try:
                date_str  = rec.get("report_date_as_yyyy_mm_dd")
                long_pos  = rec.get("noncomm_positions_long_all")
                short_pos = rec.get("noncomm_positions_short_all")
                if not date_str or long_pos is None or short_pos is None:
                    continue
                date = pd.to_datetime(date_str, utc=True)
                net  = float(long_pos) - float(short_pos)
                rows.append({"date": date, "net": net})
            except Exception:
                continue

        if len(rows) < 20:
            print(f"    cftc_cot: too few valid rows ({len(rows)})")
            return None

        df_cot = (
            pd.DataFrame(rows)
            .sort_values("date")
            .reset_index(drop=True)
        )
        net_series = df_cot.set_index("date")["net"]

        # z-score vs ~2-year rolling window (weekly COT: 104 observations ≈ 2 years)
        z = _z_score(net_series, window=104)
        if z is None:
            print("    cftc_cot: z-score computation failed (insufficient history)")
            return None

        print(f"    cftc_cot_large_spec_z={z:.3f} (COT data, weekly)")
        return z
    except Exception as e:
        print(f"    cftc_cot: failed — {e}")
        return None


def _fetch_positioning(
    inputs: RegimeInputs,
    asof_date: Optional[str] = None,
) -> None:
    print("  Fetching positioning & sentiment data...")

    # Put/call ratio proxy from SPY options via yfinance; official Cboe equity/total/index
    # series are intentionally treated as separate inputs by the forecast audit.
    cboe_pcr = _fetch_cboe_pcr(asof_date=asof_date)
    if cboe_pcr is not None:
        inputs.put_call_ratio = cboe_pcr
        inputs.put_call_5d_ma = cboe_pcr
    else:
        print("    cboe_pcr: failed or unavailable for historical date")

    # COT large speculator positioning from CFTC
    cot_z = _fetch_cftc_cot(asof_date=asof_date)
    if cot_z is not None:
        inputs.cot_net_large_spec_z = cot_z
    else:
        print("    cftc_cot: failed — skipping")

    # AAII sentiment (weekly, point-in-time correct via local XLS lookup)
    try:
        from src.state.sentiment_data import get_aaii_asof

        aaii_value = get_aaii_asof(asof_date=asof_date)
        if aaii_value is not None:
            inputs.aaii_bull_minus_bear = aaii_value
            print(f"    aaii_bull_minus_bear={aaii_value:+.1f}pp")
        else:
            print("    aaii_bull_minus_bear: no reading available on or before asof")
    except Exception as e:
        print(f"    aaii_bull_minus_bear: failed — {e}")

    print("    dealer_gamma: requires SpotGamma API — skipping")

    populated = sum(
        1
        for v in [
            inputs.put_call_ratio,
            inputs.cot_net_large_spec_z,
            inputs.aaii_bull_minus_bear,
        ]
        if v is not None
    )
    print(f"    Positioning inputs populated: {populated}/3")


# ── Main fetch function ───────────────────────────────────────────────────────

def fetch_regime_inputs(
    sectors_green: Optional[int] = None,
    asof_date: Optional[str] = None,
) -> RegimeInputs:
    """
    Fetch all regime inputs from FRED and yfinance.
    Call this ONCE at market close.

    Args:
        sectors_green: Pass from your existing market_state build
        asof_date: Override date string (defaults to today)

    Returns:
        RegimeInputs with all available data populated
    """
    inputs = RegimeInputs(
        asof_date=asof_date or datetime.utcnow().strftime("%Y-%m-%d")
    )

    print(f"\nFetching regime inputs for {inputs.asof_date}...")

    try:
        _fetch_monetary(inputs, asof_date=asof_date)
    except Exception as e:
        print(f"  Monetary fetch error: {e}")

    try:
        _fetch_credit(inputs, asof_date=asof_date)
    except Exception as e:
        print(f"  Credit fetch error: {e}")

    try:
        _fetch_volatility(inputs, asof_date=asof_date)
    except Exception as e:
        print(f"  Volatility fetch error: {e}")

    try:
        _fetch_breadth(inputs, sectors_green=sectors_green, asof_date=asof_date)
    except Exception as e:
        print(f"  Breadth fetch error: {e}")

    try:
        _fetch_positioning(inputs, asof_date=asof_date)
    except Exception as e:
        print(f"  Positioning fetch error: {e}")

    print(f"Done. Fields populated: {sum(1 for v in asdict(inputs).values() if v is not None)}/{len(asdict(inputs))}")
    return inputs
