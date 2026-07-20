"""
Shrinkage + EWMA portfolio beta.

Design choices (all deliberate — see rationale inline):
  - EWMA covariance (half-life configurable) instead of rolling-window OLS,
    so beta adapts to regime without discrete jumps when outliers age out.
  - Vasicek shrinkage of each stock beta toward a prior (default 1.0 or a
    supplied cross-sectional/sector mean), weighted by the inverse variance
    of the raw estimate. Noisy, short-history names get pulled harder.
  - Portfolio beta = sum(w_i * beta_shrunk_i). Weights are your NAV fractions.

Fail-loud: raises on misaligned data, insufficient history, NaN leakage,
or weights that don't reconcile. Nothing is silently coerced.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


# ----------------------------------------------------------------------------
# EWMA moments
# ----------------------------------------------------------------------------
def _ewma_weights(n: int, halflife: float) -> np.ndarray:
    """Newest-last EWMA weights that sum to 1. index 0 = oldest obs."""
    if halflife <= 0:
        raise ValueError(f"halflife must be > 0, got {halflife}")
    lam = 0.5 ** (1.0 / halflife)  # decay per step
    ages = np.arange(n - 1, -1, -1)  # oldest has largest age
    w = lam ** ages
    return w / w.sum()


def ewma_beta_and_var(
    stock_ret: np.ndarray,
    mkt_ret: np.ndarray,
    halflife: float,
) -> tuple[float, float]:
    """
    EWMA beta of one asset vs the market, plus the sampling variance of that
    beta estimate (needed for Vasicek shrinkage).

    beta = Cov_ewma(stock, mkt) / Var_ewma(mkt)
    Var(beta) approx = resid_var_ewma / (effective_N * Var_ewma(mkt))
    """
    if stock_ret.shape != mkt_ret.shape:
        raise ValueError("stock and market return arrays must be same shape")
    n = stock_ret.shape[0]
    if n < 2:
        raise ValueError(f"need >= 2 observations, got {n}")
    if np.isnan(stock_ret).any() or np.isnan(mkt_ret).any():
        raise ValueError("NaNs in return arrays — clean/align before calling")

    w = _ewma_weights(n, halflife)

    m_s = np.dot(w, stock_ret)
    m_m = np.dot(w, mkt_ret)
    ds = stock_ret - m_s
    dm = mkt_ret - m_m

    cov = np.dot(w, ds * dm)
    var_m = np.dot(w, dm * dm)
    if var_m <= 0:
        raise ValueError("market EWMA variance is non-positive — degenerate data")

    beta = cov / var_m

    # residual variance of the EWMA regression, for the beta's sampling var
    resid = ds - beta * dm
    resid_var = np.dot(w, resid * resid)

    # effective sample size of an EWMA scheme (Kish): 1 / sum(w^2)
    eff_n = 1.0 / np.dot(w, w)
    beta_var = resid_var / (eff_n * var_m)

    return float(beta), float(beta_var)


# ----------------------------------------------------------------------------
# Vasicek shrinkage
# ----------------------------------------------------------------------------
def vasicek_shrink(
    raw_beta: float,
    raw_beta_var: float,
    prior_mean: float,
    prior_var: float,
) -> float:
    """
    Precision-weighted blend of the raw estimate and the prior.

      w_prior  = (1/prior_var)                          (precision of prior)
      w_sample = (1/raw_beta_var)                       (precision of estimate)
      beta_hat = (w_prior*prior_mean + w_sample*raw_beta) / (w_prior + w_sample)

    Noisy estimates (large raw_beta_var) are pulled toward the prior; precise
    ones barely move. This is the principled version of the crude 0.67/0.33
    Blume rule.
    """
    if raw_beta_var <= 0 or prior_var <= 0:
        raise ValueError("variances must be strictly positive")
    p_prior = 1.0 / prior_var
    p_sample = 1.0 / raw_beta_var
    return (p_prior * prior_mean + p_sample * raw_beta) / (p_prior + p_sample)


# ----------------------------------------------------------------------------
# Portfolio-level assembly
# ----------------------------------------------------------------------------
@dataclass
class BetaResult:
    portfolio_beta: float
    per_ticker: pd.DataFrame  # ticker, weight, raw_beta, raw_beta_var, shrunk_beta, contribution
    prior_mean: float
    prior_var: float
    halflife: float
    n_obs: int


def portfolio_beta(
    returns: pd.DataFrame,
    weights: dict[str, float],
    market_col: str = "SPY",
    halflife: float = 75.0,
    prior_mean: float | None = None,
    prior_var: float = 0.25**2,
    weight_tol: float = 1e-6,
) -> BetaResult:
    """
    returns:  DataFrame of *periodic returns* (not prices), one column per
              ticker plus the market column. Index = dates, already aligned
              and NaN-free over the estimation window you pass in.
    weights:  {ticker: NAV_fraction}. Must be a subset of returns.columns and
              exclude the market column.
    prior_mean: shrinkage target. None -> use the (equal-weight) cross-sectional
              mean of raw betas, which self-centers the book. Use 1.0 for the
              classic "toward market" prior, or pass a sector mean externally.
    prior_var: dispersion of the prior. Smaller -> stronger pull to prior_mean.
              0.25^2 says "betas are typically within +/-0.5 of the prior."
    """
    if market_col not in returns.columns:
        raise ValueError(f"market_col '{market_col}' not in returns columns")

    tickers = list(weights.keys())
    missing = [t for t in tickers if t not in returns.columns]
    if missing:
        raise ValueError(f"tickers missing from returns: {missing}")
    if market_col in tickers:
        raise ValueError(f"market_col '{market_col}' must not be a holding")

    w_sum = sum(weights.values())
    if abs(w_sum - 1.0) > weight_tol:
        # fail loud — do not silently renormalize; a book that doesn't sum to 1
        # usually means missing cash or a data drop you want to know about.
        raise ValueError(
            f"weights sum to {w_sum:.6f}, not 1.0 within tol {weight_tol}. "
            "Add a cash line or fix the position set explicitly."
        )

    sub = returns[tickers + [market_col]]
    if sub.isna().any().any():
        bad = sub.columns[sub.isna().any()].tolist()
        raise ValueError(f"NaNs present in columns {bad} over the window")
    n_obs = len(sub)

    mkt = sub[market_col].to_numpy()

    raw_betas: dict[str, float] = {}
    raw_vars: dict[str, float] = {}
    for t in tickers:
        b, bv = ewma_beta_and_var(sub[t].to_numpy(), mkt, halflife)
        raw_betas[t] = b
        raw_vars[t] = bv

    if prior_mean is None:
        prior_mean = float(np.mean(list(raw_betas.values())))

    rows = []
    port_beta = 0.0
    for t in tickers:
        shrunk = vasicek_shrink(raw_betas[t], raw_vars[t], prior_mean, prior_var)
        contrib = weights[t] * shrunk
        port_beta += contrib
        rows.append(
            {
                "ticker": t,
                "weight": weights[t],
                "raw_beta": raw_betas[t],
                "raw_beta_var": raw_vars[t],
                "shrunk_beta": shrunk,
                "contribution": contrib,
            }
        )

    per_ticker = (
        pd.DataFrame(rows).sort_values("contribution", ascending=False).reset_index(drop=True)
    )

    return BetaResult(
        portfolio_beta=port_beta,
        per_ticker=per_ticker,
        prior_mean=prior_mean,
        prior_var=prior_var,
        halflife=halflife,
        n_obs=n_obs,
    )


# ----------------------------------------------------------------------------
# Convenience: prices -> aligned returns window
# ----------------------------------------------------------------------------
def prices_to_returns(
    prices: pd.DataFrame,
    lookback: int | None = None,
    method: str = "log",
) -> pd.DataFrame:
    """
    prices: wide DataFrame, date index, one column per ticker (+ market).
    Drops any date with a missing value across the retained columns (inner
    alignment). Returns the last `lookback` rows if given.

    'log' returns compose additively and are the right choice for EWMA
    covariance; 'simple' if you specifically want arithmetic.
    """
    if method not in {"log", "simple"}:
        raise ValueError("method must be 'log' or 'simple'")
    prices = prices.sort_index()
    if method == "log":
        rets = np.log(prices / prices.shift(1))
    else:
        rets = prices.pct_change()
    rets = rets.dropna(how="any")
    if lookback is not None:
        if lookback < 2:
            raise ValueError("lookback must be >= 2")
        rets = rets.iloc[-lookback:]
    if len(rets) < 2:
        raise ValueError("not enough overlapping history after alignment")
    return rets


# ----------------------------------------------------------------------------
# Example
# ----------------------------------------------------------------------------
if __name__ == "__main__":
    rng = np.random.default_rng(7)
    dates = pd.bdate_range("2024-01-01", periods=400)
    mkt = rng.normal(0.0004, 0.009, len(dates))

    true_betas = {"RSP": 0.95, "XLF": 1.10, "SCHD": 0.80, "SOXX": 1.55, "LLY": 0.70}
    cols = {"SPY": mkt}
    for t, b in true_betas.items():
        cols[t] = b * mkt + rng.normal(0, 0.011, len(dates))
    prices = pd.DataFrame(
        {t: 100 * np.exp(np.cumsum(r)) for t, r in cols.items()}, index=dates
    )

    rets = prices_to_returns(prices, lookback=252, method="log")

    weights = {"RSP": 0.30, "XLF": 0.15, "SCHD": 0.25, "SOXX": 0.10, "LLY": 0.20}
    res = portfolio_beta(rets, weights, market_col="SPY", halflife=75.0, prior_mean=1.0)

    print(f"Portfolio beta: {res.portfolio_beta:.3f}")
    print(f"Prior mean {res.prior_mean:.2f} | halflife {res.halflife} | n={res.n_obs}\n")
    with pd.option_context("display.float_format", lambda x: f"{x:.4f}"):
        print(res.per_ticker.to_string(index=False))