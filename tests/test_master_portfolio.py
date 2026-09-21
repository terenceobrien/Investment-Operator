"""Offline accounting tests: synthetic inputs with independently known balances."""
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

# An installed package also owns the name 'scripts'; import the local CLI by path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_master_portfolio import (
    Issues, build_ledger, calculate_returns, load_prices, normalize_transactions,
)


def transaction(day, action, ticker="", quantity="0", amount="0", price="", fees="", description=""):
    return {"Run Date": day, "Action": action, "Symbol": ticker,
            "Quantity": quantity, "Amount ($)": amount, "Price ($)": price,
            "Commission ($)": fees, "Description": description}


def run_fixture(tmp_path, transactions, dates, closes, **settings):
    tx_path, price_path = tmp_path / "transactions.csv", tmp_path / "prices.csv"
    pd.DataFrame(transactions).fillna("").to_csv(tx_path, index=False)
    rows = []
    for ticker, prices in closes.items():
        for day, close in zip(dates, prices):
            if close is not None:
                rows.append({"Date": day, "Ticker": ticker, "Close": close, "Adj Close": close / 2})
    pd.DataFrame(rows).to_csv(price_path, index=False)
    return build_ledger(tx_path, price_path, **settings)


def test_cash_core_fees_fractional_exit_and_external_flow(tmp_path):
    dates = ["2026-01-05", "2026-01-06", "2026-01-07"]
    tx = [
        transaction(dates[0], "Electronic Funds Transfer Received (Cash)", amount="100"),
        transaction(dates[0], "YOU BOUGHT A", "A", "0.1", "-1.01", "10", ".01"),
        transaction(dates[0], "YOU BOUGHT A", "A", "0.2", "-2", "10"),
        transaction(dates[1], "DIVIDEND RECEIVED", "A", amount="1"),
        transaction(dates[1], "DIVIDEND RECEIVED", "SPAXX", amount="2"),
        transaction(dates[1], "REINVESTMENT", "SPAXX", "2", "-2", "1"),
        transaction(dates[1], "INTEREST EARNED", amount=".10"),
        transaction(dates[1], "FEE CHARGED", amount="-.20"),
        transaction(dates[1], "Electronic Funds Transfer Received (Cash)", amount="50"),
        transaction(dates[1], "JOURNALED AUTO-JOURNAL", "A", "-0.3"),
        transaction(dates[1], "JOURNALED AUTO-JOURNAL", "A", "0.3"),
        transaction(dates[2], "YOU SOLD A", "A", "-0.3", "3.59", "12", ".01"),
        transaction(dates[2], "Electronic Funds Transfer Paid (Cash)", amount="-20"),
    ]
    m, issues, normalized, positions = run_fixture(tmp_path, tx, dates, {"A": [10, 11, 12]})
    assert m.QTY_A.tolist() == [.3, .3, 0]
    assert "QTY_SPAXX" not in m
    assert m.Cash.tolist() == pytest.approx([96.99, 149.89, 133.48])
    assert m.Total_NAV.tolist() == pytest.approx([99.99, 153.19, 133.48])
    assert m.External_Flow.tolist() == [100, 50, -20]
    assert m.Fees.tolist() == [-.01, -.2, -.01]
    assert m.Buy_Cash_Flow.iloc[0] == -3
    assert m.Sell_Cash_Flow.iloc[-1] == 3.6
    assert m.Core_Bookkeeping_Adjustment.sum() == 2
    assert np.isnan(m.Daily_Return.iloc[0])
    r1, r2 = (153.19 - 50) / 99.99 - 1, (133.48 + 20) / 153.19 - 1
    assert m.Daily_Return.iloc[1:].tolist() == pytest.approx([r1, r2])
    assert m.Cumulative_Return.iloc[-1] == pytest.approx((1+r1)*(1+r2)-1)
    assert normalized.Confident.all()
    assert positions.empty
    assert not m.NAV_Potentially_Incomplete_Flag.any()


def test_observed_option_entry_and_late_posted_expiration(tmp_path):
    dates = ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08", "2026-01-09"]
    option = "-ABC260107C10"
    tx = [
        transaction(dates[0], "Electronic Funds Transfer Received", amount="1000"),
        transaction(dates[1], "YOU BOUGHT OPENING TRANSACTION", option, "1", "-100.65", "1", ".65", "CALL (ABC) (100 SHS)"),
        transaction(dates[3], "EXPIRED as of 2026-01-07", option, "-1"),
        transaction(dates[4], "INTEREST EARNED", amount="1"),
    ]
    m, issues, normalized, positions = run_fixture(tmp_path, tx, dates, {"ABC": [10]*5})
    assert m[f"QTY_{option}"].tolist() == [0, 1, 0, 0, 0]
    assert not m.Option_Pricing_Incomplete_Flag.any()
    assert m.Options_Market_Value.iloc[1] == 100
    assert m.Total_NAV.iloc[1] == 999.35  # Only the commission reduces entry NAV.
    assert m.Option_Realized_Cash_Flow.iloc[2] == -100.65
    assert m.Option_Net_Cash_Flow.sum() == -100.65
    assert np.isnan(m.Daily_Return.iloc[0])
    assert m.Daily_Return.iloc[1:].notna().all()
    assert m.Daily_Return.iloc[3] == 0
    assert m.Cumulative_Return.notna().all()
    assert m[f"QTY_{option}"].iloc[-1] == 0


def test_same_day_option_round_trip_is_fully_priced(tmp_path):
    dates = ["2026-01-05", "2026-01-06"]
    option = "-ABC260106C10"
    tx = [transaction(dates[0], "Electronic Funds Transfer Received", amount="1000"),
          transaction(dates[1], "YOU BOUGHT OPENING TRANSACTION", option, "1", "-100.65", "1", ".65", "(100 SHS)"),
          transaction(dates[1], "YOU SOLD CLOSING TRANSACTION", option, "-1", "119.35", "1.20", ".65", "(100 SHS)")]
    m, _, _, _ = run_fixture(tmp_path, tx, dates, {"ABC": [10, 10]})
    assert not m.Option_Pricing_Incomplete_Flag.any()
    assert m.Options_Market_Value.eq(0).all()
    assert m.Total_NAV.iloc[-1] == 1018.70
    assert m.Daily_Return.iloc[-1] == pytest.approx(.0187)
    assert m.Option_Realized_Cash_Flow.sum() == 18.7


def test_missing_held_price_invalidates_nav_without_filling(tmp_path):
    dates = ["2026-01-05", "2026-01-06", "2026-01-07"]
    tx = [transaction(dates[0], "Electronic Funds Transfer Received", amount="100"),
          transaction(dates[0], "YOU BOUGHT", "A", "1", "-10", "10"),
          transaction(dates[2], "INTEREST EARNED", amount="1")]
    m, issues, _, _ = run_fixture(tmp_path, tx, dates, {"A": [10, None, 12], "B": [1, 1, 1]})
    assert m.Missing_Security_Price_Flag.tolist() == [False, True, False]
    assert np.isnan(m.Securities_Market_Value.iloc[1])
    assert np.isnan(m.Total_NAV.iloc[1])
    assert m.Cumulative_Return.iloc[1:].isna().all()
    assert len(issues[issues.Issue == "missing_price_while_held"]) == 1


def test_ambiguous_transfer_is_not_external_and_blocks_returns(tmp_path):
    dates = ["2026-01-05", "2026-01-06"]
    tx = [transaction(dates[0], "Electronic Funds Transfer Received", amount="100"),
          transaction(dates[1], "TRANSFER ADJUSTMENT", amount="50")]
    m, issues, normalized, _ = run_fixture(tmp_path, tx, dates, {"A": [10, 10]})
    assert m.Cash.iloc[-1] == 150
    assert m.External_Flow.iloc[-1] == 0
    assert normalized.Category.iloc[-1] == "other"
    assert m.Ledger_Reconciliation_Incomplete_Flag.iloc[-1]
    assert np.isnan(m.Daily_Return.iloc[-1])
    assert "unexplained_cash_activity" in issues.Issue.tolist()


def test_nontrading_cash_maps_forward_and_missing_session_is_flagged(tmp_path):
    dates = ["2026-01-05", "2026-01-07"]
    tx = [transaction("2026-01-04", "Electronic Funds Transfer Received", amount="100"),
          transaction(dates[-1], "INTEREST EARNED", amount="1")]
    m, issues, _, _ = run_fixture(tmp_path, tx, dates, {"A": [10, 11]})
    assert m.Cash.tolist() == [100, 101]
    assert "transaction_mapped_to_next_price_date" in issues.Issue.tolist()
    assert "missing_trading_date" in issues.Issue.tolist()
    assert np.isnan(m.Daily_Return.iloc[-1])


def test_bad_number_is_rejected():
    raw = pd.DataFrame([transaction("2026-01-05", "YOU BOUGHT", "A", "not-a-number", "-10")])
    with pytest.raises(ValueError, match="invalid number"):
        normalize_transactions(raw, Issues())


def test_duplicate_price_is_rejected(tmp_path):
    path = tmp_path / "prices.csv"
    row = {"Date": "2026-01-05", "Ticker": "A", "Close": 10, "Adj Close": 10}
    pd.DataFrame([row, row]).to_csv(path, index=False)
    with pytest.raises(ValueError, match="exactly one row"):
        load_prices(path, Issues())


def test_zero_previous_nav_does_not_generate_infinite_return():
    m = pd.DataFrame({"Total_NAV": [0., 100., 101.], "External_Flow": [0., 100., 0.], "Return_Eligible_Flag": [True]*3})
    result = calculate_returns(m)
    assert result.Daily_Return.iloc[:2].isna().all()
    assert result.Daily_Return.iloc[2] == pytest.approx(.01)
    assert result.Cumulative_Return.isna().all()


def test_unbalanced_journal_requires_review(tmp_path):
    dates = ["2026-01-05", "2026-01-06"]
    tx = [transaction(dates[0], "Electronic Funds Transfer Received", amount="100"),
          transaction(dates[0], "YOU BOUGHT", "A", "1", "-10", "10"),
          transaction(dates[1], "JOURNALED AUTO-JOURNAL", "A", "-1")]
    m, issues, _, _ = run_fixture(tmp_path, tx, dates, {"A": [10, 11]})
    assert m.QTY_A.iloc[-1] == 1
    assert "unbalanced_auto_journal" in issues.Issue.tolist()
    assert m.Ledger_Reconciliation_Incomplete_Flag.iloc[-1]
    assert np.isnan(m.Daily_Return.iloc[-1])


def test_open_expired_contract_is_not_silently_assumed_worthless(tmp_path):
    dates = ["2026-01-05", "2026-01-06", "2026-01-07"]
    option = "-ABC260106C10"
    tx = [transaction(dates[0], "Electronic Funds Transfer Received", amount="1000"),
          transaction(dates[1], "YOU BOUGHT OPENING TRANSACTION", option, "1", "-100", "1", description="(100 SHS)"),
          transaction(dates[2], "INTEREST EARNED", amount="1")]
    m, issues, _, _ = run_fixture(tmp_path, tx, dates, {"ABC": [10]*3})
    assert m[f"QTY_{option}"].iloc[-1] == 1
    assert m.Options_Market_Value.iloc[-1] == 0  # Intrinsic mark, not an assumed close.
    assert m.Ledger_Reconciliation_Incomplete_Flag.iloc[-1]
    assert "unresolved_expired_option" in issues.Issue.tolist()
