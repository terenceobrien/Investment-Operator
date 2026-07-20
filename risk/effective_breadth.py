"""
Effective breadth: how many INDEPENDENT bets are you actually making?

Grinold-Kahn's Fundamental Law says IR = IC * sqrt(BR), where BR is the number
of *independent* forecasts per year. Holding N correlated positions does NOT
give you breadth N — correlated bets are partially the same bet. This module
measures your effective (independent) breadth from the correlation structure,
so "low breadth" becomes a number you can watch rather than an assertion.

Three views, because they answer different questions:

  1. effective_n_avgcorr:  N / (1 + (N-1)*rho_bar)
     The classic diversification approximation using average pairwise
     correlation. Intuitive, but assumes uniform correlation.

  2. effective_n_eigen:  the "effective number of independent bets" from the
     eigenspectrum of the correlation matrix. Uses the entropy of the
     normalized eigenvalues: ENB = exp(H) where H = -sum(p_i ln p_i), p_i the
     eigenvalue shares. This is the rigorous version — it doesn't assume
     uniform correlation and it captures that a few dominant principal
     components (e.g. "the market", "the AI trade") eat most of your risk.

  3. effective_breadth_annual:  effective_n * decisions_per_year, the quantity
     that actually plugs into the Fundamental Law once you specify how often you
     form genuinely NEW, independent views.

Plus marginal_breadth(): the operational tool — does adding a proposed position
raise or lower effective breadth?

All measures are computed from a correlation matrix you pass in (typically the
holdings' return correlation over your estimation window).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class BreadthResult:
    n_positions: int
    avg_pairwise_corr: float
    effective_n_avgcorr: float          # N / (1 + (N-1)*rho_bar)
    effective_n_eigen: float            # entropy-based effective number of bets
    concentration_ratio: float          # effective_n_eigen / N  (1.0 = fully independent)
    top_eigen_share: float              # fraction of variance in the largest PC
    decisions_per_year: float
    effective_breadth_annual: float     # effective_n_eigen * decisions_per_year
    implied_ir_at_ic: dict              # {IC: implied IR} using Fundamental Law


def _correlation_from_returns(returns: pd.DataFrame) -> pd.DataFrame:
    if returns.isna().any().any():
        raise ValueError("NaNs in returns; align/clean before computing correlation")
    if returns.shape[1] < 2:
        raise ValueError("need >= 2 assets for a correlation structure")
    return returns.corr()


def _effective_n_eigen(corr: np.ndarray) -> tuple[float, float]:
    """
    Entropy-based effective number of independent bets from a correlation
    matrix. Returns (ENB, top_eigenvalue_share).

    Eigenvalues of an NxN correlation matrix sum to N. Normalize them to shares
    p_i = lambda_i / N (sum to 1), then ENB = exp(-sum p_i ln p_i). If all
    assets were independent, every eigenvalue = 1, shares = 1/N, ENB = N. If all
    perfectly correlated, one eigenvalue = N and ENB -> 1.
    """
    vals = np.linalg.eigvalsh(corr)
    vals = np.clip(vals, 1e-12, None)      # numerical floor
    p = vals / vals.sum()
    entropy = -np.sum(p * np.log(p))
    enb = float(np.exp(entropy))
    top_share = float(vals.max() / vals.sum())
    return enb, top_share


def effective_breadth(
    corr: pd.DataFrame,
    decisions_per_year: float = 4.0,
    ic_grid: tuple[float, ...] = (0.05, 0.10, 0.15),
) -> BreadthResult:
    """
    corr: correlation matrix of your holdings (or bets).
    decisions_per_year: how often you form GENUINELY NEW, independent views.
        Not your rebalance frequency — the frequency at which new information
        drives a fresh, independent forecast. Default 4 (quarterly), which is
        generous for a discretionary macro thesis.
    ic_grid: information-coefficient levels to show implied IR for.
    """
    C = corr.to_numpy()
    n = C.shape[0]
    if C.shape[0] != C.shape[1]:
        raise ValueError("correlation matrix must be square")

    # average pairwise correlation (off-diagonal mean)
    off = ~np.eye(n, dtype=bool)
    rho_bar = float(C[off].mean())

    # avg-corr effective N (guard the degenerate rho_bar = -1/(n-1))
    denom = 1 + (n - 1) * rho_bar
    eff_n_avg = n / denom if denom > 0 else float("inf")

    eff_n_eig, top_share = _effective_n_eigen(C)

    eff_breadth = eff_n_eig * decisions_per_year

    # Fundamental Law: IR = IC * sqrt(BR)
    implied_ir = {ic: ic * np.sqrt(eff_breadth) for ic in ic_grid}

    return BreadthResult(
        n_positions=n,
        avg_pairwise_corr=rho_bar,
        effective_n_avgcorr=eff_n_avg,
        effective_n_eigen=eff_n_eig,
        concentration_ratio=eff_n_eig / n,
        top_eigen_share=top_share,
        decisions_per_year=decisions_per_year,
        effective_breadth_annual=eff_breadth,
        implied_ir_at_ic=implied_ir,
    )


def marginal_breadth(
    returns_with_candidate: pd.DataFrame,
    current_tickers: list[str],
    candidate_ticker: str,
) -> dict:
    """
    Operational trade-screening tool: does adding `candidate_ticker` to the
    current book raise or lower effective independent breadth?

    returns_with_candidate: returns DataFrame that includes BOTH the current
        holdings and the candidate (so correlations are computed on the same
        window).
    Returns effective_n_eigen before and after adding the candidate, the delta,
    and the candidate's average correlation to the existing book.
    """
    missing = [t for t in current_tickers + [candidate_ticker]
               if t not in returns_with_candidate.columns]
    if missing:
        raise ValueError(f"returns missing columns: {missing}")

    before = _correlation_from_returns(returns_with_candidate[current_tickers])
    after = _correlation_from_returns(
        returns_with_candidate[current_tickers + [candidate_ticker]]
    )
    enb_before, _ = _effective_n_eigen(before.to_numpy())
    enb_after, _ = _effective_n_eigen(after.to_numpy())

    # candidate's average correlation to the existing book
    cand_corr = returns_with_candidate[current_tickers + [candidate_ticker]].corr()
    avg_corr_to_book = float(cand_corr[candidate_ticker].loc[current_tickers].mean())

    return {
        "candidate": candidate_ticker,
        "effective_n_before": enb_before,
        "effective_n_after": enb_after,
        "delta_effective_n": enb_after - enb_before,
        "avg_corr_to_book": avg_corr_to_book,
        # a "real" new bet adds close to +1.0; a redundant one adds near 0
        "breadth_efficiency": (enb_after - enb_before),  # of a theoretical +1
    }