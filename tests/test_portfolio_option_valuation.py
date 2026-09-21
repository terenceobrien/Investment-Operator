"""Offline numerical, causal and accounting checks for modeled option marks."""
import math

import numpy as np
import pandas as pd
import pytest

from test_master_portfolio import run_fixture, transaction
from portfolio_option_valuation import black_scholes_price, parse_option_contract, solve_implied_volatility


def test_bsm_known_prices_parity_and_edges():
    call = black_scholes_price(100, 100, 1, .05, .2, "call")
    put = black_scholes_price(100, 100, 1, .05, .2, "put")
    assert call == pytest.approx(10.4505835722)
    assert put == pytest.approx(5.5735260223)
    c = black_scholes_price(100, 100, 1, .05, .2, "C", .02)
    p = black_scholes_price(100, 100, 1, .05, .2, "P", .02)
    assert c-p == pytest.approx(100*math.exp(-.02)-100*math.exp(-.05))
    assert c < call
    assert black_scholes_price(110, 100, 0, .04, 0, "C") == 10
    assert black_scholes_price(90, 100, -1, .04, 0, "P") == 10
    assert black_scholes_price(100, 100, 1, .05, 0, "C") == pytest.approx(100-100*math.exp(-.05))
    assert black_scholes_price(0, 100, 1, .05, .2, "P") == pytest.approx(100*math.exp(-.05))
    with pytest.raises(ValueError):
        black_scholes_price(100, 0, 1, .05, .2, "C")


@pytest.mark.parametrize("kind", ["C", "P"])
def test_iv_round_trip(kind):
    observed = black_scholes_price(100, 100, .4, .04, .42, kind, .01)
    assert solve_implied_volatility(observed, 100, 100, .4, .04, kind, .01) == pytest.approx(.42)


@pytest.mark.parametrize("premium,spot,t", [(1, 150, .2), (150, 100, .2), (3, 100, 0), (3, np.nan, .2)])
def test_impossible_iv_warns_instead_of_raising(premium, spot, t):
    with pytest.warns(RuntimeWarning, match="Entry IV unavailable"):
        assert np.isnan(solve_implied_volatility(premium, spot, 100, t, .04, "C"))


def test_fidelity_contract_parser_literal_strike_and_description_fallback():
    contract = parse_option_contract(" -BABA260807C120", "CALL (BABA) ALIBABA AUG 07 26 $120 (100 SHS)")
    assert contract["Option_ID"] == "BABA_2026-08-07_C_120"
    assert contract["Strike"] == 120
    assert contract["Contract_Multiplier"] == 100
    assert parse_option_contract("-XYZ260807P12.5")["Strike"] == 12.5
    fallback = parse_option_contract("-MALFORMED", "PUT (XYZ) COMPANY AUG 07 26 $12.5 (50 SHS)")
    assert fallback["Option_ID"] == "XYZ_2026-08-07_P_12.5"
    assert fallback["Contract_Multiplier"] == 50
    assert parse_option_contract("-BAD")["Parse_Error"]


def test_constant_iv_path_and_no_exit_lookahead(tmp_path):
    dates = ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08", "2026-01-09"]
    symbol = "-ABC260220C100"
    iv = .35
    expiry = pd.Timestamp("2026-02-20")
    t = (expiry-pd.Timestamp(dates[1])).days/365
    premium = black_scholes_price(100, 100, t, .04, iv, "C")
    tx = [transaction(dates[0], "Electronic Funds Transfer Received", amount="1000"),
          transaction(dates[1], "YOU BOUGHT OPENING TRANSACTION", symbol, "1", str(round(-premium*100-.65, 2)), str(premium), ".65", "(100 SHS)"),
          transaction(dates[-1], "YOU SOLD CLOSING TRANSACTION", symbol, "-1", "599.35", "6", ".65", "(100 SHS)")]
    m, issues, _, _, daily, lots = run_fixture(tmp_path, tx, dates, {"ABC": [99, 100, 101, 102, 103]}, include_option_details=True)
    assert lots.Entry_IV.iloc[0] == pytest.approx(iv)
    assert daily.Valuation_Method.tolist() == ["actual_transaction", "black_scholes_constant_iv", "black_scholes_constant_iv", "actual_transaction"]
    expected = black_scholes_price(101, 100, (expiry-pd.Timestamp(dates[2])).days/365, .04, iv, "C")
    assert daily.Price_Used.iloc[1] == pytest.approx(expected)
    assert daily.Option_Market_Value.iloc[0] == pytest.approx(premium*100)
    assert m.Total_NAV.iloc[1] == pytest.approx(999.35, abs=.005)
    assert daily.Contracts.iloc[-1] == 0 and daily.Option_Market_Value.iloc[-1] == 0
    assert m.Total_NAV.notna().all() and m.Cumulative_Return.notna().all()
    tx[-1]["Price ($)"], tx[-1]["Amount ($)"] = "16", "1599.35"
    _, _, _, _, changed, changed_lots = run_fixture(tmp_path, tx, dates, {"ABC": [99, 100, 101, 102, 103]}, include_option_details=True)
    pd.testing.assert_frame_equal(daily.iloc[:-1], changed.iloc[:-1])
    assert changed.Price_Used.iloc[-1] == 16
    assert changed_lots.Realized_Option_PnL.iloc[0] - lots.Realized_Option_PnL.iloc[0] == pytest.approx(1000)


@pytest.mark.parametrize("symbol,underlying", [("-ABC260220C100", "UNRELATED"), ("-BAD", "ABC")])
def test_missing_contract_or_spot_carries_actual_and_preserves_nav(tmp_path, symbol, underlying):
    dates = ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"]
    tx = [transaction(dates[0], "Electronic Funds Transfer Received", amount="1000"),
          transaction(dates[1], "YOU BOUGHT OPENING TRANSACTION", symbol, "1", "-200", "2"),
          transaction(dates[-1], "YOU SOLD CLOSING TRANSACTION", symbol, "-1", "300", "3")]
    m, issues, _, _, daily, lots = run_fixture(tmp_path, tx, dates, {underlying: [100]*4}, include_option_details=True)
    assert daily.Valuation_Method.tolist() == ["actual_transaction", "carry_last_actual_price", "actual_transaction"]
    assert daily.Price_Used.tolist() == [2, 2, 3]
    assert m.Options_Market_Value.tolist() == [0, 200, 200, 0]
    assert m.Total_NAV.notna().all() and m.Cumulative_Return.notna().all()
    assert np.isnan(lots.Entry_IV.iloc[0])


def test_multiple_lots_partial_close_and_constant_iv_per_lot(tmp_path):
    dates = ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08", "2026-01-09", "2026-01-12"]
    symbol = "-ABC260220C100"
    tx = [transaction(dates[0], "Electronic Funds Transfer Received", amount="5000"),
          transaction(dates[1], "YOU BOUGHT OPENING TRANSACTION", symbol, "2", "-600", "3"),
          transaction(dates[2], "YOU BOUGHT OPENING TRANSACTION", symbol, "1", "-500", "5"),
          transaction(dates[3], "YOU SOLD CLOSING TRANSACTION", symbol, "-1", "600", "6"),
          transaction(dates[-1], "YOU SOLD CLOSING TRANSACTION", symbol, "-2", "1400", "7")]
    m, issues, _, _, daily, lots = run_fixture(tmp_path, tx, dates, {"ABC": [100]*6}, include_option_details=True)
    assert daily.Contracts.tolist() == [2, 3, 2, 2, 0]
    assert daily.Option_Market_Value.iloc[1] == 1500  # Actual quote overrides all open lots.
    assert daily.Option_Market_Value.iloc[2] == 1200  # Partial close quote overrides model.
    assert lots.Entry_IV.notna().all() and lots.Entry_IV.nunique() == 2
    t = (pd.Timestamp("2026-02-20")-pd.Timestamp(dates[4])).days/365
    expected = sum(black_scholes_price(100, 100, t, .04, iv, "C")*100 for iv in lots.Entry_IV)
    assert daily.Option_Market_Value.iloc[3] == pytest.approx(expected)
    assert np.isnan(daily.Entry_IV.iloc[3])  # No invented single IV for distinct lots.
    assert lots.Realized_Option_PnL.tolist() == pytest.approx([700, 200])
    assert m.Option_Realized_Cash_Flow.sum() == 900
    assert m.Total_NAV.notna().all()


def test_short_put_is_signed_liability_and_closes_at_actual_cash(tmp_path):
    dates = ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"]
    symbol = "-ABC260220P100"
    tx = [transaction(dates[0], "Electronic Funds Transfer Received", amount="1000"),
          transaction(dates[1], "YOU SOLD OPENING TRANSACTION", symbol, "-1", "299.35", "3", ".65"),
          transaction(dates[-1], "YOU BOUGHT CLOSING TRANSACTION", symbol, "1", "-100.65", "1", ".65")]
    m, issues, _, _, daily, lots = run_fixture(tmp_path, tx, dates, {"ABC": [100, 100, 101, 102]}, include_option_details=True)
    assert daily.Contracts.tolist() == [-1, -1, 0]
    assert daily.Option_Market_Value.iloc[0] == -300
    assert daily.Option_Market_Value.iloc[1] < 0
    assert m.Total_NAV.iloc[1] == pytest.approx(999.35)
    assert m.Total_NAV.iloc[-1] == pytest.approx(1198.70)
    assert m.Cumulative_Return.notna().all()
    assert lots.Realized_Option_PnL.iloc[0] == pytest.approx(198.7)


def test_explicit_exercise_uses_actual_share_and_cash_legs(tmp_path):
    dates = ["2026-01-05", "2026-01-06", "2026-01-07"]
    symbol = "-ABC260220C100"
    tx = [transaction(dates[0], "Electronic Funds Transfer Received", amount="20000"),
          transaction(dates[1], "YOU BOUGHT OPENING TRANSACTION", symbol, "1", "-1000", "10"),
          transaction(dates[-1], "EXERCISED", symbol, "-1", "0", "100"),
          transaction(dates[-1], "EXERCISED", "ABC", "100", "-10000", "100")]
    m, issues, _, _, daily, lots = run_fixture(tmp_path, tx, dates, {"ABC": [105, 105, 110]}, include_option_details=True)
    assert daily.Valuation_Method.iloc[-1] == "exercise_or_assignment"
    assert daily.Option_Market_Value.iloc[-1] == 0
    assert m.QTY_ABC.iloc[-1] == 100
    assert m.Cash.iloc[-1] == 9000
    assert m.Total_NAV.iloc[-1] == 20000
    assert not m.Ledger_Reconciliation_Incomplete_Flag.any()


def test_derived_premium_and_nonstandard_multiplier(tmp_path):
    dates = ["2026-01-05", "2026-01-06", "2026-01-07"]
    symbol = "-ABC260220C100"
    tx = [transaction(dates[0], "Electronic Funds Transfer Received", amount="1000"),
          transaction(dates[1], "YOU BOUGHT OPENING TRANSACTION", symbol, "2", "-300.65", "", ".65", "(50 SHS)"),
          transaction(dates[-1], "YOU SOLD CLOSING TRANSACTION", symbol, "-2", "400", "4", description="(50 SHS)")]
    m, issues, _, _, daily, lots = run_fixture(tmp_path, tx, dates, {"ABC": [100]*3}, include_option_details=True)
    assert daily.Price_Used.iloc[0] == 3
    assert daily.Contract_Multiplier.eq(50).all()
    assert m.Options_Market_Value.iloc[1] == 300
    assert m.Total_NAV.iloc[1] == 999.35
    assert lots.Entry_Price_Source.iloc[0] == "derived_from_net_cash_and_fees"


def test_fallback_uses_latest_partial_close_price_without_refitting_iv(tmp_path):
    dates = ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08", "2026-01-09"]
    symbol = "-ABC260220C100"
    tx = [transaction(dates[0], "Electronic Funds Transfer Received", amount="2000"),
          transaction(dates[1], "YOU BOUGHT OPENING TRANSACTION", symbol, "2", "-400", "2"),
          transaction(dates[2], "YOU SOLD CLOSING TRANSACTION", symbol, "-1", "300", "3"),
          transaction(dates[-1], "YOU SOLD CLOSING TRANSACTION", symbol, "-1", "500", "5")]
    _, _, _, _, daily, lots = run_fixture(tmp_path, tx, dates, {"OTHER": [100]*5}, include_option_details=True)
    assert daily.Price_Used.tolist() == [2, 3, 3, 5]
    assert daily.Valuation_Method.iloc[2] == "carry_last_actual_price"
    assert daily.Option_Market_Value.iloc[2] == 300
    assert lots.Entry_IV.isna().all()


def test_overlapping_contracts_keep_distinct_ids_and_mixed_methods(tmp_path):
    dates = ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"]
    call, put = "-ABC260220C100", "-XYZ260320P90"
    tx = [transaction(dates[0], "Electronic Funds Transfer Received", amount="2000"),
          transaction(dates[1], "YOU BOUGHT OPENING TRANSACTION", call, "1", "-300", "3"),
          transaction(dates[1], "YOU BOUGHT OPENING TRANSACTION", put, "1", "-200", "2"),
          transaction(dates[-1], "YOU SOLD CLOSING TRANSACTION", call, "-1", "400", "4"),
          transaction(dates[-1], "YOU SOLD CLOSING TRANSACTION", put, "-1", "300", "3")]
    m, _, _, _, daily, lots = run_fixture(tmp_path, tx, dates, {"ABC": [100]*4}, include_option_details=True)
    assert daily.Option_ID.nunique() == 2
    assert m.Option_Valuation_Method.iloc[2] == "mixed"
    assert m.Option_MV_Estimated_Flag.iloc[2]
    assert m.Total_NAV.notna().all()
    assert not daily.duplicated(["Date", "Option_ID"]).any()


def test_mixed_iv_lots_and_missing_daily_spot_use_fallback(tmp_path):
    dates = ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08", "2026-01-09", "2026-01-12"]
    symbol = "-ABC260220C100"
    tx = [transaction(dates[0], "Electronic Funds Transfer Received", amount="3000"),
          transaction(dates[1], "YOU BOUGHT OPENING TRANSACTION", symbol, "1", "-300", "3"),
          transaction(dates[2], "YOU BOUGHT OPENING TRANSACTION", symbol, "1", "-200", "2"),
          transaction(dates[-1], "YOU SOLD CLOSING TRANSACTION", symbol, "-2", "800", "4")]
    m, _, _, _, daily, lots = run_fixture(tmp_path, tx, dates, {"ABC": [100, 100, None, 101, None, 102], "OTHER": [1]*6}, include_option_details=True)
    assert pd.notna(lots.Entry_IV.iloc[0]) and pd.isna(lots.Entry_IV.iloc[1])
    assert daily.Valuation_Method.iloc[2] == "mixed"
    assert set(daily.Valuation_Methods.iloc[2].split(';')) == {"black_scholes_constant_iv", "carry_last_actual_price"}
    t = (pd.Timestamp("2026-02-20")-pd.Timestamp(dates[3])).days/365
    expected = black_scholes_price(101, 100, t, .04, lots.Entry_IV.iloc[0], "C")*100+200
    assert daily.Option_Market_Value.iloc[2] == pytest.approx(expected)
    assert daily.Valuation_Method.iloc[3] == "carry_last_actual_price"
    assert daily.Option_Market_Value.iloc[3] == 400
    assert m.Total_NAV.notna().all()
