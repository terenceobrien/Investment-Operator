r"""
Factor covariance matrix, portfolio factor risk, and risk decomposition.

This is the piece that correctly handles factor double-counting. Rather than
forcing the style factors to be independent (which introduces arbitrary
order-dependence), we leave them correlated and model their covariance
explicitly. Portfolio factor variance is then w_f' F w_f, where F carries the
correlations, so overlapping exposures (e.g. value & size) are not
double-booked in the risk number.

Total portfolio variance follows the Barra decomposition:

    Var(portfolio) = w_f' F w_f  +  sum_i (weight_i^2 * specific_var_i)
                     \___________/    \____________________________/
                      factor risk           specific (idiosyncratic) risk

Both a raw sample covariance and an EWMA (recent-weighted) covariance are
produced, so the raw and shrinkage/EWMA-adjusted paths sit side by side.

Fail-loud on shape mismatches, non-PSD matrices, or NaNs.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class FactorRiskResult:
    method: str                          # 'sample' or 'ewma'
    cov: pd.DataFrame                    # F, factor covariance (periodic)
    corr: pd.DataFrame                  # factor correlation
    factor_var: float                   # w_f' F w_f  (periodic)
    specific_var: float                 # sum w_i^2 spec_var_i (periodic)
    total_var: float                    # factor_var + specific_var
    factor_vol_annual: float            # sqrt(factor_var) * sqrt(252)
    specific_vol_annual: float
    total_vol_annual: float
    risk_contributions: pd.DataFrame    # per-factor contribution to variance & %
    pct_factor: float                   # factor_var / total_var
    pct_specific: float                 # specific_var / total_var


def _ewma_cov(returns: np.ndarray, halflife: float) -> np.ndarray:
    """
    EWMA covariance matrix of a (T, k) return array. Newest obs weighted most.
    Weights sum to 1; covariance is about the EWMA mean.
    """
    T, k = returns.shape
    if halflife <= 0:
        raise ValueError("halflife must be > 0")
    lam = 0.5 ** (1.0 / halflife)
    ages = np.arange(T - 1, -1, -1)
    w = lam ** ages
    w = w / w.sum()

    mean = w @ returns                        # (k,)
    dev = returns - mean                      # (T, k)
    # weighted covariance: sum_t w_t * dev_t dev_t'
    cov = (dev * w[:, None]).T @ dev
    # small ridge for numerical PSD safety
    cov += np.eye(k) * 1e-12
    return cov


def factor_risk(
    factor_returns: pd.DataFrame,
    exposures: dict[str, float],
    specific_var_by_name: dict[str, float],
    weights: dict[str, float],
    method: str = "sample",
    halflife: float = 90.0,
    periods_per_year: int = 252,
) -> FactorRiskResult:
    """
    factor_returns: (T, k) DataFrame of factor return series (from build_factor_returns).
    exposures: {factor: portfolio loading} — the w_f vector (weighted per-name loadings).
    specific_var_by_name: {ticker: residual variance} from each holding's factor regression.
    weights: {ticker: weight} for the specific-risk aggregation.
    method: 'sample' (equal-weight) or 'ewma' (recent-weighted).
    """
    factors = list(factor_returns.columns)
    missing = [f for f in factors if f not in exposures]
    if missing:
        raise ValueError(f"exposures missing factors: {missing}")

    R = factor_returns.to_numpy()
    if np.isnan(R).any():
        raise ValueError("NaNs in factor_returns")

    if method == "sample":
        F = np.cov(R, rowvar=False, bias=False)
    elif method == "ewma":
        F = _ewma_cov(R, halflife)
    else:
        raise ValueError("method must be 'sample' or 'ewma'")

    F = np.atleast_2d(F)
    cov_df = pd.DataFrame(F, index=factors, columns=factors)

    # correlation for display
    d = np.sqrt(np.diag(F))
    corr = F / np.outer(d, d)
    corr_df = pd.DataFrame(corr, index=factors, columns=factors)

    # factor exposure vector in factor order
    w_f = np.array([exposures[f] for f in factors])

    # factor variance: w_f' F w_f
    factor_var = float(w_f @ F @ w_f)
    if factor_var < 0:
        raise ValueError(f"negative factor variance ({factor_var}); covariance not PSD")

    # specific variance: sum w_i^2 * spec_var_i
    specific_var = 0.0
    for t, wt in weights.items():
        sv = specific_var_by_name.get(t)
        if sv is None:
            raise ValueError(f"missing specific variance for {t}")
        specific_var += (wt**2) * sv

    total_var = factor_var + specific_var

    # risk contributions: each factor's contribution to factor variance via
    # the marginal-contribution decomposition. RC_j = w_f_j * (F w_f)_j
    Fwf = F @ w_f
    rc = w_f * Fwf                       # sums to factor_var
    rc_df = pd.DataFrame(
        {
            "factor": factors,
            "exposure": w_f,
            "risk_contribution": rc,
            "pct_of_factor_var": rc / factor_var if factor_var > 0 else np.nan,
            "pct_of_total_var": rc / total_var if total_var > 0 else np.nan,
        }
    ).sort_values("risk_contribution", ascending=False, key=abs).reset_index(drop=True)

    ann = np.sqrt(periods_per_year)
    return FactorRiskResult(
        method=method,
        cov=cov_df,
        corr=corr_df,
        factor_var=factor_var,
        specific_var=specific_var,
        total_var=total_var,
        factor_vol_annual=float(np.sqrt(factor_var) * ann),
        specific_vol_annual=float(np.sqrt(specific_var) * ann),
        total_vol_annual=float(np.sqrt(total_var) * ann),
        risk_contributions=rc_df,
        pct_factor=factor_var / total_var if total_var > 0 else float("nan"),
        pct_specific=specific_var / total_var if total_var > 0 else float("nan"),
    )