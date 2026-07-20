"""
ETF-proxy multi-factor risk model.

Decomposes each holding's returns onto a set of tradeable ETF factors, then
aggregates to portfolio-level factor exposures. This is the "poor man's Barra":
it captures most of the value of a commercial factor model using free, liquid
ETF proxies, and — unlike a single-factor beta — it separates market exposure
from AI-concentration, momentum, quality, value, size, and low-vol tilts.

Factor construction
-------------------
  Market            : SPY excess return (raw)
  AI-concentration  : 0.5*SOXX + 0.5*QQQ  minus  RSP   (long-short spread;
                      market-neutral by construction, so this isolates the
                      AI/semis-concentration premium vs equal-weight breadth)
  Momentum          : MTUM, orthogonalized vs [market, AI]
  Quality           : QUAL, orthogonalized vs [market, AI]
  Value             : IWD,  orthogonalized vs [market, AI]
  Size (small)      : IWM,  orthogonalized vs [market, AI]
  Low-volatility    : USMV, orthogonalized vs [market, AI]

Orthogonalization ordering is market -> AI -> styles. The AI spread is residual-
ized only lightly (it's already market-neutral); the style factors are resid-
ualized against BOTH market and AI so a name's AI loading isn't smeared into
its momentum/growth loading. This is what makes the AI-factor exposure a clean,
hedge-able number.

Per-name loadings come from OLS of holding excess returns on the factor matrix.
Portfolio factor exposure = weighted sum of per-name loadings.

Fail-loud: raises on missing factor data, insufficient overlap, or NaNs.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


# ETF proxies for each factor. Swap these if you prefer different vehicles.
FACTOR_ETFS = {
    "MKT": "SPY",
    "MOM": "MTUM",
    "QUAL": "QUAL",
    "VAL": "IWD",
    "SIZE": "IWM",
    "LOWVOL": "USMV",
}
# AI-concentration spread legs
AI_LONG = {"SOXX": 0.5, "QQQ": 0.5}
AI_SHORT = {"RSP": 1.0}

# All ETFs we need price history for (dedup)
def required_factor_tickers() -> list[str]:
    tks = set(FACTOR_ETFS.values()) | set(AI_LONG) | set(AI_SHORT)
    return sorted(tks)


@dataclass
class FactorResult:
    portfolio_exposures: dict[str, float]      # factor -> portfolio loading
    per_ticker_loadings: pd.DataFrame          # ticker + one column per factor + r2
    factor_names: list[str]
    ai_hedge_notional_frac: float              # SPY-equiv frac to neutralize AI factor
    r2_summary: dict[str, float]               # mean / min r2 across names
    n_obs: int
    specific_var: dict[str, float] = field(default_factory=dict)  # ticker -> residual var


def _residualize(target: np.ndarray, bases: np.ndarray) -> np.ndarray:
    """
    Return target with the linear span of `bases` (columns) projected out.
    bases: (T, k) matrix of factor columns to residualize against.
    Adds an intercept implicitly by demeaning.
    """
    if bases.ndim == 1:
        bases = bases.reshape(-1, 1)
    X = np.column_stack([np.ones(len(target)), bases])
    coef, *_ = np.linalg.lstsq(X, target, rcond=None)
    return target - X @ coef


def build_factor_returns(
    factor_prices: pd.DataFrame,
    rf_daily: float = 0.0,
) -> pd.DataFrame:
    """
    factor_prices: wide DataFrame of ETF prices (date index), must contain all
        of required_factor_tickers().
    rf_daily: per-period risk-free rate to subtract for excess returns. Default
        0.0 (fine for beta-style loadings; set to a real daily RF if you want
        true excess returns).

    Returns a DataFrame of factor RETURNS with columns:
        MKT, AI, MOM, QUAL, VAL, SIZE, LOWVOL
    orthogonalized per the module docstring.
    """
    need = required_factor_tickers()
    missing = [t for t in need if t not in factor_prices.columns]
    if missing:
        raise ValueError(f"factor_prices missing ETF columns: {missing}")

    px = factor_prices[need].sort_index()
    rets = np.log(px / px.shift(1)).dropna(how="any")
    if len(rets) < 60:
        raise ValueError(f"only {len(rets)} overlapping factor observations; need >= 60")

    # raw excess returns
    ex = rets - rf_daily

    # Market
    mkt = ex["SPY"].to_numpy()

    # AI-concentration spread: long semis/QQQ, short equal-weight
    ai_long = sum(w * ex[t].to_numpy() for t, w in AI_LONG.items())
    ai_short = sum(w * ex[t].to_numpy() for t, w in AI_SHORT.items())
    ai_raw = ai_long - ai_short
    # light residualization vs market (spread is already ~market-neutral, but
    # remove any residual market beta so MKT and AI don't overlap)
    ai = _residualize(ai_raw, mkt)

    # Style factors, residualized vs [market, AI]
    base = np.column_stack([mkt, ai])
    styles = {}
    for fac, etf in FACTOR_ETFS.items():
        if fac == "MKT":
            continue
        styles[fac] = _residualize(ex[etf].to_numpy(), base)

    out = pd.DataFrame(
        {"MKT": mkt, "AI": ai, **styles},
        index=rets.index,
    )
    return out


def estimate_factor_loadings(
    holding_returns: pd.DataFrame,
    factor_returns: pd.DataFrame,
    weights: dict[str, float],
) -> FactorResult:
    """
    holding_returns: wide DataFrame of per-holding returns (date index), one
        column per ticker in `weights`. Must align to factor_returns index.
    factor_returns: output of build_factor_returns.
    weights: {ticker: weight}, summing to 1.0 over the sleeve you're analyzing.

    Regresses each holding on the factor matrix (OLS with intercept) and
    aggregates loadings by weight.
    """
    tickers = list(weights.keys())
    missing = [t for t in tickers if t not in holding_returns.columns]
    if missing:
        raise ValueError(f"holding_returns missing tickers: {missing}")

    # align dates
    idx = factor_returns.index.intersection(holding_returns.index)
    if len(idx) < 60:
        raise ValueError(f"only {len(idx)} overlapping obs between holdings and factors; need >= 60")
    F = factor_returns.loc[idx]
    H = holding_returns.loc[idx, tickers]
    if F.isna().any().any() or H.isna().any().any():
        raise ValueError("NaNs in aligned holdings/factors window")

    factor_names = list(F.columns)
    Fmat = np.column_stack([np.ones(len(idx)), F.to_numpy()])  # intercept + factors

    rows = []
    specific_var: dict[str, float] = {}
    for t in tickers:
        y = H[t].to_numpy()
        coef, *_ = np.linalg.lstsq(Fmat, y, rcond=None)
        resid = y - Fmat @ coef
        ss_res = float(np.sum(resid**2))
        ss_tot = float(np.sum((y - y.mean()) ** 2))
        r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
        # specific (idiosyncratic) variance = residual variance, dof-adjusted
        dof = len(y) - Fmat.shape[1]
        specific_var[t] = ss_res / dof if dof > 0 else float("nan")
        loadings = dict(zip(factor_names, coef[1:]))  # drop intercept
        rows.append({"ticker": t, **loadings, "r2": r2, "specific_var": specific_var[t]})

    per_ticker = pd.DataFrame(rows)

    # portfolio-level exposures = weighted sum of loadings
    port = {}
    for fac in factor_names:
        port[fac] = float(sum(weights[t] * per_ticker.loc[per_ticker.ticker == t, fac].iloc[0]
                              for t in tickers))

    # AI hedge sizing: to neutralize portfolio AI loading with the AI spread
    # itself (unit exposure), you'd short `port['AI']` units of the spread.
    ai_hedge = port.get("AI", 0.0)

    r2_summary = {
        "mean": float(per_ticker["r2"].mean()),
        "min": float(per_ticker["r2"].min()),
        "max": float(per_ticker["r2"].max()),
    }

    per_ticker = per_ticker.sort_values("MKT", ascending=False).reset_index(drop=True)

    return FactorResult(
        portfolio_exposures=port,
        per_ticker_loadings=per_ticker,
        factor_names=factor_names,
        ai_hedge_notional_frac=ai_hedge,
        r2_summary=r2_summary,
        n_obs=len(idx),
        specific_var=specific_var,
    )