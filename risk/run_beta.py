"""
End-to-end: Fidelity positions CSV -> portfolio beta.

    python run_beta.py <path_to_fidelity_positions.csv>

Chains:
  1. fidelity_ingest.load_fidelity_positions  -> weights + cash fraction
  2. yfinance download of holdings + SPY       -> prices
  3. portfolio_beta.portfolio_beta             -> invested-sleeve beta
  4. scale by invested_fraction                -> whole-book beta

Fail-loud on symbols that don't return usable price history, so a broker
ticker that doesn't match yfinance (share classes, delisted names) surfaces
instead of silently shrinking your estimation window.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime

import pandas as pd
import yfinance as yf

from fidelity_ingest import load_fidelity_positions, print_ingest_report
from portfolio_beta import prices_to_returns, portfolio_beta
from excel_export import export_beta_workbook

MARKET = "SPY"
LOOKBACK = 252
HALFLIFE = 75.0
PRIOR_MEAN = 1.0


def fetch_prices(tickers: list[str], market: str = MARKET, period: str = "2y") -> pd.DataFrame:
    symbols = tickers + [market]
    raw = yf.download(symbols, period=period, auto_adjust=True, progress=False)
    if raw.empty:
        raise ValueError("yfinance returned no data — check connectivity and symbols.")
    prices = raw["Close"] if "Close" in raw.columns.get_level_values(0) else raw
    # single-symbol edge case returns a Series/flat frame; normalize to wide
    if isinstance(prices, pd.Series):
        prices = prices.to_frame()

    # fail-loud on any symbol that came back entirely empty
    all_nan = [c for c in symbols if c not in prices.columns or prices[c].isna().all()]
    if all_nan:
        raise ValueError(
            f"No price history for: {all_nan}. "
            "Check the ticker mapping (share classes like BRK.B -> BRK-B, "
            "delisted names, or symbols yfinance doesn't cover)."
        )
    return prices[symbols]


def main(csv_path: str) -> None:
    # 1. ingest
    res = load_fidelity_positions(csv_path)
    print_ingest_report(res)
    print("\n" + "=" * 52 + "\n")

    weights = dict(res.weights)

    # SPY (the benchmark) may also be held as a position. The beta engine
    # rejects the market ticker in the weights, so pull it out — but don't
    # just delete it (that would redistribute its weight and overstate the
    # other names). Instead hold its weight aside and add it back as a known
    # beta = 1.0 contribution, which is what SPY's beta is by definition.
    spy_weight = weights.pop(MARKET, 0.0)
    if spy_weight > 0:
        print(f"Note: {MARKET} held as a position ({spy_weight:.2%} of sleeve) — "
              f"treated as a beta=1.0 contribution, not redistributed.\n")

    tickers = list(weights.keys())

    # 2. prices
    prices = fetch_prices(tickers)

    # 3. returns + beta on the non-SPY holdings
    #    Renormalize the non-SPY weights to sum to 1.0 for the engine, then
    #    rescale the resulting beta back to its true share of the sleeve.
    non_spy_share = 1.0 - spy_weight
    engine_weights = {t: w / non_spy_share for t, w in weights.items()}

    rets = prices_to_returns(prices, lookback=LOOKBACK, method="log")
    beta = portfolio_beta(
        rets, engine_weights, market_col=MARKET, halflife=HALFLIFE, prior_mean=PRIOR_MEAN
    )

    # invested-sleeve beta (SHRUNK) = non-SPY names (rescaled) + SPY's 1.0 slice
    sleeve_beta = non_spy_share * beta.portfolio_beta + spy_weight * 1.0

    # Same aggregate but using RAW (un-shrunk) betas, for comparison. SPY still
    # enters as exactly 1.0 (its beta vs itself is 1 by definition, raw or not).
    pt = beta.per_ticker
    raw_engine_beta = float((pt["weight"] * pt["raw_beta"]).sum())
    sleeve_beta_raw = non_spy_share * raw_engine_beta + spy_weight * 1.0

    # 4. scale for cash drag (both versions)
    book_beta = res.invested_fraction * sleeve_beta
    book_beta_raw = res.invested_fraction * sleeve_beta_raw

    print(f"Estimation window:       {beta.n_obs} periods (lookback={LOOKBACK})")
    print(f"EWMA halflife:           {HALFLIFE} days")
    print(f"Shrinkage prior:         {beta.prior_mean:.2f}\n")
    print(f"{'':<24}{'RAW':>10}{'SHRUNK':>10}{'delta':>10}")
    print(f"{'Invested-sleeve beta:':<24}{sleeve_beta_raw:>10.3f}{sleeve_beta:>10.3f}"
          f"{sleeve_beta - sleeve_beta_raw:>+10.3f}")
    print(f"{'Whole-book beta:':<24}{book_beta_raw:>10.3f}{book_beta:>10.3f}"
          f"{book_beta - book_beta_raw:>+10.3f}")
    print(f"{'':<24}{'':<20}(incl. {res.cash_fraction:.1%} cash)\n")

    # per-ticker: show raw beta, shrunk beta, the shrinkage delta, and both
    # contribution columns (rescaled back to true sleeve share for honesty)
    disp = beta.per_ticker.copy()
    disp["beta_delta"] = disp["shrunk_beta"] - disp["raw_beta"]
    disp["contrib_raw"] = disp["weight"] * disp["raw_beta"] * non_spy_share
    disp["contrib_shrunk"] = disp["contribution"] * non_spy_share
    disp = disp[
        ["ticker", "weight", "raw_beta", "shrunk_beta", "beta_delta",
         "raw_beta_var", "contrib_raw", "contrib_shrunk"]
    ]
    with pd.option_context("display.float_format", lambda x: f"{x:.4f}"):
        print(disp.to_string(index=False))

    # ----- Excel export (same folder as the input CSV) -----
    out_dir = os.path.dirname(os.path.abspath(csv_path))
    out_path = os.path.join(
        out_dir, f"beta_report_{datetime.now():%Y-%m-%d}.xlsx"
    )
    export_beta_workbook(
        out_path,
        ingest=res,
        beta=beta,
        beta_summary={
            "market": MARKET,
            "lookback": LOOKBACK,
            "spy_position_weight": spy_weight,
            "non_spy_share": non_spy_share,
            "sleeve_beta_raw": sleeve_beta_raw,
            "sleeve_beta_shrunk": sleeve_beta,
            "whole_book_beta_raw": book_beta_raw,
            "whole_book_beta_shrunk": book_beta,
        },
        per_ticker=disp,
    )
    print(f"\nExcel report written to: {out_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python run_beta.py <path_to_fidelity_positions.csv>")
        sys.exit(1)
    main(sys.argv[1])
