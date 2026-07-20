"""
End-to-end: Fidelity positions CSV -> ETF-proxy factor exposures.

    python run_factors.py <path_to_fidelity_positions.csv>

Chains:
  1. fidelity_ingest.load_fidelity_positions   -> weights + cash fraction
  2. yfinance download of holdings + factor ETFs
  3. factor_model.build_factor_returns          -> orthogonalized factor matrix
  4. factor_model.estimate_factor_loadings      -> per-name + portfolio exposures
  5. scale portfolio exposures by invested_fraction for whole-book view

SPY appears both as a holding and as the market factor proxy. As a holding it
regresses out to ~[MKT=1, everything else ~0], which is correct and harmless.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime

import pandas as pd
import yfinance as yf

from fidelity_ingest import load_fidelity_positions, print_ingest_report
from factor_model import (
    build_factor_returns,
    estimate_factor_loadings,
    required_factor_tickers,
)
from factor_covariance import factor_risk
from stress_model import run_stress
from effective_breadth import effective_breadth
from excel_export import export_workbook

LOOKBACK = 252
DECISIONS_PER_YEAR = 4.0


def fetch_prices(tickers: list[str], period: str = "2y") -> pd.DataFrame:
    raw = yf.download(sorted(set(tickers)), period=period, auto_adjust=True, progress=False)
    if raw.empty:
        raise ValueError("yfinance returned no data — check connectivity and symbols.")
    prices = raw["Close"] if "Close" in raw.columns.get_level_values(0) else raw
    if isinstance(prices, pd.Series):
        prices = prices.to_frame()
    all_nan = [c for c in set(tickers) if c not in prices.columns or prices[c].isna().all()]
    if all_nan:
        raise ValueError(
            f"No price history for: {all_nan}. Check ticker mapping "
            "(share classes, delisted names, or symbols yfinance doesn't cover)."
        )
    return prices


def main(csv_path: str) -> None:
    # 1. ingest
    res = load_fidelity_positions(csv_path)
    print_ingest_report(res)
    print("\n" + "=" * 60 + "\n")

    weights = dict(res.weights)
    holding_tickers = list(weights.keys())
    factor_tickers = required_factor_tickers()

    # 2. prices for holdings + factor ETFs (single download)
    all_tickers = holding_tickers + factor_tickers
    prices = fetch_prices(all_tickers)

    # 3. factor returns (orthogonalized)
    factor_prices = prices[[t for t in factor_tickers if t in prices.columns]]
    factor_rets = build_factor_returns(factor_prices)
    factor_rets = factor_rets.iloc[-LOOKBACK:]  # trailing window

    # 4. holding returns over same window
    import numpy as np
    hold_px = prices[holding_tickers].sort_index()
    hold_rets = np.log(hold_px / hold_px.shift(1)).dropna(how="any")

    fr = estimate_factor_loadings(hold_rets, factor_rets, weights)

    # 5. report
    print(f"Estimation window:       {fr.n_obs} periods")
    print(f"Model fit (R^2):         mean {fr.r2_summary['mean']:.2f}  "
          f"min {fr.r2_summary['min']:.2f}  max {fr.r2_summary['max']:.2f}\n")

    print("PORTFOLIO FACTOR EXPOSURES (invested sleeve):")
    for fac in fr.factor_names:
        sleeve = fr.portfolio_exposures[fac]
        book = res.invested_fraction * sleeve
        print(f"  {fac:<8} sleeve {sleeve:+.3f}   whole-book {book:+.3f}")
    print()

    print(f"AI-factor exposure (sleeve): {fr.portfolio_exposures['AI']:+.3f}")
    print(f"  -> To neutralize, short {fr.ai_hedge_notional_frac:+.3f} units of the "
          f"AI spread (0.5 SOXX + 0.5 QQQ - RSP)")
    print(f"  -> As whole-book: {res.invested_fraction * fr.portfolio_exposures['AI']:+.3f}\n")

    with pd.option_context("display.float_format", lambda x: f"{x:.3f}"):
        print("PER-NAME FACTOR LOADINGS:")
        print(fr.per_ticker_loadings.to_string(index=False))

    # ----- factor covariance risk decomposition (raw sample + EWMA) -----
    print("\n" + "=" * 60 + "\n")
    print("FACTOR COVARIANCE RISK DECOMPOSITION\n")

    port_spec = sum(weights[t] ** 2 * fr.specific_var[t] for t in weights)

    risk_by_method = {}
    for method in ("sample", "ewma"):
        rr = factor_risk(
            factor_rets, fr.portfolio_exposures, fr.specific_var, weights, method=method
        )
        risk_by_method[method] = rr
        tag = "RAW (sample cov)" if method == "sample" else "EWMA (recent-weighted cov)"
        print(f"[{tag}]")
        print(f"  Total vol (annualized):   {rr.total_vol_annual:6.1%}")
        print(f"  Factor vol:               {rr.factor_vol_annual:6.1%}  "
              f"({rr.pct_factor:.0%} of variance)")
        print(f"  Specific vol:             {rr.specific_vol_annual:6.1%}  "
              f"({rr.pct_specific:.0%} of variance)")
        print("  Risk contribution by factor (% of total variance):")
        for _, row in rr.risk_contributions.iterrows():
            print(f"    {row['factor']:<8} exposure {row['exposure']:+.3f}   "
                  f"{row['pct_of_total_var']:+.1%}")
        print()

    # keep the sample covariance for the stress base
    rr_sample = risk_by_method["sample"]

    # ----- stress test (raw exposures, stressed covariance) -----
    print("=" * 60 + "\n")
    print("STRESS TEST (raw exposures, correlations converge in crash)\n")
    sr = run_stress(
        rr_sample.cov,
        fr.portfolio_exposures,
        port_spec,
        vol_scale=1.5,
        corr_floor=0.5,
        market_shock=-0.10,
    )
    print(f"  Scenario: {sr.shock_description}")
    print(f"  Base factor vol (annualized):     {sr.base_factor_vol_annual:6.1%}")
    print(f"  Stressed factor vol:              {sr.stressed_factor_vol_annual:6.1%}")
    print(f"  Stressed total vol:               {sr.stressed_total_vol_annual:6.1%}")
    print(f"  IMPLIED SLEEVE DRAWDOWN:          {sr.implied_drawdown:6.1%}")
    print(f"  IMPLIED WHOLE-BOOK DRAWDOWN:      "
          f"{res.invested_fraction * sr.implied_drawdown:6.1%}  "
          f"(incl. {res.cash_fraction:.0%} cash)\n")
    print("  Drawdown contribution by factor:")
    with pd.option_context("display.float_format", lambda x: f"{x:.4f}"):
        print(sr.factor_shock_contributions.to_string(index=False))

    # ----- effective breadth / independent bets -----
    print("\n" + "=" * 60 + "\n")
    print("PORTFOLIO BREADTH (independent bets)\n")
    corr = hold_rets.corr()
    br = effective_breadth(corr, decisions_per_year=DECISIONS_PER_YEAR)
    print(f"  Positions:                 {br.n_positions}")
    print(f"  Avg pairwise correlation:  {br.avg_pairwise_corr:.2f}")
    print(f"  Effective N (avg-corr):    {br.effective_n_avgcorr:.1f}")
    print(f"  Effective N (eigenvalue):  {br.effective_n_eigen:.1f}")
    print(f"  Concentration ratio:       {br.concentration_ratio:.1%}")
    print(f"  Top principal component:   {br.top_eigen_share:.1%}")
    print(f"  Decisions per year:        {br.decisions_per_year:.1f}")
    print(f"  Effective annual breadth:  {br.effective_breadth_annual:.1f}")
    print("  Implied IR by IC:")
    for ic, implied_ir in sorted(br.implied_ir_at_ic.items()):
        print(f"    IC={ic:.2f} -> IR={implied_ir:.2f}")

    # ----- Excel export (same folder as the input CSV) -----
    out_dir = os.path.dirname(os.path.abspath(csv_path))
    out_path = os.path.join(
        out_dir, f"risk_report_{datetime.now():%Y-%m-%d}.xlsx"
    )
    export_workbook(
        out_path,
        ingest=res,
        factor=fr,
        risk_by_method=risk_by_method,
        stress=sr,
        breadth=br,
    )
    print(f"\nExcel report written to: {out_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python run_factors.py <path_to_fidelity_positions.csv>")
        sys.exit(1)
    main(sys.argv[1])
