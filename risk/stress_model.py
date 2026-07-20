"""
Stress module: conservative drawdown estimation.

Central risk estimates (shrunk betas, sample/EWMA covariance) answer "what's my
risk in a normal market." They deliberately do NOT answer "what happens in a
crash," because two things change in a crash that central estimates smooth away:

  1. Volatilities spike.
  2. Correlations converge toward 1 — diversification and internal hedges
     (e.g. your defensive names offsetting the AI names) weaken exactly when
     you need them, because cross-sectional dispersion collapses.

This module takes RAW (unshrunk) factor exposures and applies a stressed
covariance matrix (vols scaled up, correlations pushed toward a floor) to
produce a conservative portfolio vol and an implied drawdown under a defined
shock. This is intentionally more pessimistic than the central estimate.

Fail-loud on shape/PSD issues.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class StressResult:
    vol_scale: float
    corr_floor: float
    stressed_cov: pd.DataFrame
    base_factor_vol_annual: float       # central, for comparison
    stressed_factor_vol_annual: float
    stressed_total_vol_annual: float
    implied_drawdown: float             # loss under the defined shock (fraction)
    shock_description: str
    factor_shock_contributions: pd.DataFrame


def stress_covariance(
    cov: pd.DataFrame,
    vol_scale: float = 1.5,
    corr_floor: float = 0.5,
) -> pd.DataFrame:
    """
    Produce a stressed covariance matrix from a base one.
      - scale all volatilities by vol_scale
      - push all pairwise correlations UP toward corr_floor (never lower them):
            corr_stressed = max(corr, corr_floor) for off-diagonal, sign-preserved
    Correlations already above the floor keep their (higher) value.
    """
    F = cov.to_numpy()
    d = np.sqrt(np.diag(F))
    corr = F / np.outer(d, d)

    # sign-preserving correlation floor on off-diagonals
    off = ~np.eye(len(F), dtype=bool)
    signs = np.sign(corr)
    stressed_corr = corr.copy()
    mag = np.abs(corr)
    bumped = np.maximum(mag, corr_floor)
    stressed_corr[off] = (signs * bumped)[off]
    np.fill_diagonal(stressed_corr, 1.0)

    # scaled vols
    d_stressed = d * vol_scale
    F_stressed = stressed_corr * np.outer(d_stressed, d_stressed)
    # PSD repair: clip negative eigenvalues (correlation flooring can break PSD)
    vals, vecs = np.linalg.eigh(F_stressed)
    if (vals < 0).any():
        vals = np.clip(vals, 1e-12, None)
        F_stressed = vecs @ np.diag(vals) @ vecs.T

    return pd.DataFrame(F_stressed, index=cov.index, columns=cov.columns)


def run_stress(
    cov: pd.DataFrame,
    raw_exposures: dict[str, float],
    specific_var: float,
    vol_scale: float = 1.5,
    corr_floor: float = 0.5,
    market_shock: float = -0.10,
    periods_per_year: int = 252,
) -> StressResult:
    """
    cov: base factor covariance (periodic) — use the SAMPLE matrix as the base.
    raw_exposures: {factor: portfolio loading} using RAW (unshrunk) loadings.
    specific_var: portfolio specific variance (periodic) — kept but NOT scaled by
        correlation (idiosyncratic risk doesn't converge), only by vol_scale^2.
    market_shock: the MKT factor move to price the drawdown against (e.g. -0.10).
        Other factors are shocked by their stressed-beta relationship to market.
    """
    factors = list(cov.index)
    if "MKT" not in factors:
        raise ValueError("cov must include an 'MKT' factor to anchor the shock")

    F_stress = stress_covariance(cov, vol_scale, corr_floor)
    w_f = np.array([raw_exposures[f] for f in factors])

    # stressed factor variance
    Fs = F_stress.to_numpy()
    stressed_factor_var = float(w_f @ Fs @ w_f)
    # specific risk scales with vol but not correlation
    stressed_specific_var = specific_var * (vol_scale**2)
    stressed_total_var = stressed_factor_var + stressed_specific_var

    ann = np.sqrt(periods_per_year)

    # base (unstressed) factor vol for comparison
    base_factor_var = float(w_f @ cov.to_numpy() @ w_f)

    # implied drawdown under the market shock:
    # price each factor's expected co-move with a market_shock using the
    # stressed covariance (conditional expectation E[f_j | MKT = shock]).
    mkt_idx = factors.index("MKT")
    mkt_var = Fs[mkt_idx, mkt_idx]
    # conditional factor moves given the market shock (linear-normal)
    cond_factor_moves = Fs[:, mkt_idx] / mkt_var * market_shock
    # portfolio return = sum(exposure_j * factor_move_j)
    port_move = float(w_f @ cond_factor_moves)

    # per-factor contribution to the shocked move
    contrib = w_f * cond_factor_moves
    contrib_df = pd.DataFrame(
        {
            "factor": factors,
            "raw_exposure": w_f,
            "cond_factor_move": cond_factor_moves,
            "contribution_to_drawdown": contrib,
        }
    ).sort_values("contribution_to_drawdown", key=abs, ascending=False).reset_index(drop=True)

    shock_desc = (
        f"MKT {market_shock:+.0%} shock, vols x{vol_scale}, corr floored at {corr_floor}"
    )

    return StressResult(
        vol_scale=vol_scale,
        corr_floor=corr_floor,
        stressed_cov=F_stress,
        base_factor_vol_annual=float(np.sqrt(base_factor_var) * ann),
        stressed_factor_vol_annual=float(np.sqrt(stressed_factor_var) * ann),
        stressed_total_vol_annual=float(np.sqrt(stressed_total_var) * ann),
        implied_drawdown=port_move,
        shock_description=shock_desc,
        factor_shock_contributions=contrib_df,
    )