from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from src.research.options_backtest import (
    BacktestConfig,
    get_trade_details,
    normalize_options_data,
    run_backtest,
    select_spread,
)


SIGNAL_DATE = date(2026, 1, 2)
ENTRY_DATE = date(2026, 1, 5)
EXPIRATION = date(2026, 2, 16)


def _ticker(expiration: date, strike: float) -> str:
    return f"O:SPY{expiration:%y%m%d}P{int(round(strike * 1000)):08d}"


def _row(
    row_date: date,
    expiration: date,
    strike: float,
    option_close: float,
    *,
    underlying: float = 100.0,
    hedge_trigger_active: bool = False,
    hedge_stage: int = 0,
) -> dict:
    dte = (expiration - row_date).days
    return {
        "date": row_date,
        "option_ticker": _ticker(expiration, strike),
        "expiration": expiration,
        "strike": strike,
        "option_type": "put",
        "dte": dte,
        "underlying_close": underlying,
        "moneyness": strike / underlying,
        "option_open": option_close,
        "option_high": option_close,
        "option_low": option_close,
        "option_close": option_close,
        "option_volume": 10,
        "hedge_trigger_active": hedge_trigger_active,
        "hedge_stage": hedge_stage,
        "hedge_stage_label": "Stage 0 - Normal"
        if hedge_stage == 0
        else "Stage 2 - Confirmed Hedge Trigger",
        "bhr_active": hedge_trigger_active,
        "credit_stress": False,
        "vol_stress": hedge_trigger_active,
        "data_quality_ok": True,
    }


def _chain_rows(
    row_date: date,
    expiration: date,
    *,
    short_close: float,
    long_close: float,
    underlying: float = 100.0,
    hedge_trigger_active: bool = False,
) -> list[dict]:
    return [
        _row(row_date, expiration, 87.5, long_close, underlying=underlying, hedge_trigger_active=hedge_trigger_active),
        _row(row_date, expiration, 90.0, long_close + 0.25, underlying=underlying, hedge_trigger_active=hedge_trigger_active),
        _row(row_date, expiration, 92.5, short_close, underlying=underlying, hedge_trigger_active=hedge_trigger_active),
        _row(row_date, expiration, 95.0, short_close + 0.50, underlying=underlying, hedge_trigger_active=hedge_trigger_active),
    ]


def _selected_leg_rows(
    row_date: date,
    expiration: date,
    *,
    short_close: float,
    long_close: float,
    underlying: float = 100.0,
    hedge_trigger_active: bool = False,
) -> list[dict]:
    return [
        _row(row_date, expiration, 87.5, long_close, underlying=underlying, hedge_trigger_active=hedge_trigger_active),
        _row(row_date, expiration, 92.5, short_close, underlying=underlying, hedge_trigger_active=hedge_trigger_active),
    ]


def _dataset(
    *,
    path: list[tuple[date, float, float, bool]] | None = None,
    signal_hedge: bool = False,
    expiration: date = EXPIRATION,
) -> pd.DataFrame:
    rows = _chain_rows(
        SIGNAL_DATE,
        expiration,
        short_close=1.40,
        long_close=0.40,
        hedge_trigger_active=signal_hedge,
    )
    if path is None:
        path = [
            (ENTRY_DATE, 1.50, 0.50, False),
            (SIGNAL_DATE + timedelta(days=4), 1.20, 0.40, False),
            (expiration, 0.00, 0.00, False),
        ]
    for row_date, short_close, long_close, hedge in path:
        rows.extend(
            _selected_leg_rows(
                row_date,
                expiration,
                short_close=short_close,
                long_close=long_close,
                hedge_trigger_active=hedge,
            )
        )
    return pd.DataFrame(rows)


def _config(**updates) -> BacktestConfig:
    params = {
        "target_dte": 45,
        "dte_tolerance": 0,
        "short_put_otm_pct": 0.075,
        "spread_width_mode": "pct_spy",
        "spread_width_pct": 0.05,
        "profit_target_pct": 0.50,
        "exit_dte": -1,
        "stop_loss_multiple": None,
        "risk_per_trade_pct": 0.01,
        "slippage_per_leg": 0.0,
        "max_concurrent_positions": 1,
    }
    params.update(updates)
    return BacktestConfig(**params)


def test_selects_spread_by_closest_dte_and_moneyness() -> None:
    later_expiration = EXPIRATION + timedelta(days=5)
    raw = pd.DataFrame(
        _chain_rows(SIGNAL_DATE, later_expiration, short_close=1.80, long_close=0.60)
        + _chain_rows(SIGNAL_DATE, EXPIRATION, short_close=1.40, long_close=0.40)
    )
    data = normalize_options_data(raw)

    selection = select_spread(data, SIGNAL_DATE, _config(dte_tolerance=10))

    assert selection is not None
    assert selection.expiration == EXPIRATION
    assert selection.short_strike == 92.5
    assert selection.long_strike == 87.5
    assert selection.short_moneyness_signal == pytest.approx(0.925)


def test_no_lookahead_entry_uses_next_available_option_close() -> None:
    raw = _dataset(
        path=[
            (ENTRY_DATE, 3.00, 1.00, False),
            (EXPIRATION, 0.00, 0.00, False),
        ]
    )

    result = run_backtest(raw, _config(), strategy="always_sell")
    trade = result.trades.iloc[0]

    assert trade["entry_signal_date"] == SIGNAL_DATE
    assert trade["entry_date"] == ENTRY_DATE
    assert trade["entry_credit"] == pytest.approx(2.00)


def test_benign_only_rejects_trigger_active_entry_signal() -> None:
    result = run_backtest(_dataset(signal_hedge=True), _config(), strategy="benign_entries")

    assert result.trades.empty


def test_strategy_c_exits_next_session_after_trigger_turns_on() -> None:
    trigger_signal = SIGNAL_DATE + timedelta(days=4)
    trigger_exit = SIGNAL_DATE + timedelta(days=5)
    raw = _dataset(
        path=[
            (ENTRY_DATE, 1.50, 0.50, False),
            (trigger_signal, 1.70, 0.50, True),
            (trigger_exit, 1.80, 0.50, True),
            (EXPIRATION, 0.00, 0.00, False),
        ]
    )

    result = run_backtest(raw, _config(), strategy="benign_trigger_exit")
    trade = result.trades.iloc[0]

    assert trade["exit_reason"] == "trigger_exit"
    assert trade["exit_signal_date"] == trigger_signal
    assert trade["exit_date"] == trigger_exit
    assert trade["exit_debit"] == pytest.approx(1.30)


def test_profit_target_exits_on_next_available_session() -> None:
    profit_signal = SIGNAL_DATE + timedelta(days=4)
    profit_exit = SIGNAL_DATE + timedelta(days=5)
    raw = _dataset(
        path=[
            (ENTRY_DATE, 1.50, 0.50, False),
            (profit_signal, 0.90, 0.45, False),
            (profit_exit, 0.70, 0.40, False),
            (EXPIRATION, 0.00, 0.00, False),
        ]
    )

    result = run_backtest(raw, _config(), strategy="always_sell")
    trade = result.trades.iloc[0]

    assert trade["exit_reason"] == "profit_target"
    assert trade["exit_signal_date"] == profit_signal
    assert trade["exit_date"] == profit_exit
    assert trade["exit_debit"] == pytest.approx(0.30)


def test_dte_exit_works() -> None:
    dte_signal = date(2026, 2, 2)
    dte_exit = date(2026, 2, 3)
    raw = _dataset(
        path=[
            (ENTRY_DATE, 1.50, 0.50, False),
            (dte_signal, 1.20, 0.50, False),
            (dte_exit, 1.10, 0.45, False),
            (EXPIRATION, 0.00, 0.00, False),
        ]
    )

    result = run_backtest(raw, _config(exit_dte=14), strategy="always_sell")
    trade = result.trades.iloc[0]

    assert trade["exit_reason"] == "dte_exit"
    assert trade["exit_signal_date"] == dte_signal
    assert trade["exit_date"] == dte_exit


def test_expiration_intrinsic_settlement_when_option_price_absent() -> None:
    raw = _dataset(
        path=[
            (ENTRY_DATE, 1.50, 0.50, False),
            (SIGNAL_DATE + timedelta(days=4), 1.60, 0.50, False),
        ]
    )
    raw.loc[raw["date"].eq(SIGNAL_DATE + timedelta(days=4)), "underlying_close"] = 80.0

    result = run_backtest(raw, _config(profit_target_pct=0.99), strategy="always_sell")
    trade = result.trades.iloc[0]

    assert trade["exit_reason"] == "expiration"
    assert trade["exit_date"] == EXPIRATION
    assert trade["exit_debit"] == pytest.approx(5.00)


def test_max_loss_and_contract_sizing_are_correct() -> None:
    result = run_backtest(_dataset(), _config(), strategy="always_sell")
    trade = result.trades.iloc[0]

    assert trade["entry_credit"] == pytest.approx(1.00)
    assert trade["spread_width"] == pytest.approx(5.00)
    assert trade["contracts"] == 2
    assert trade["max_loss"] == pytest.approx(800.00)


def test_slippage_reduces_entry_credit_and_pnl() -> None:
    raw = _dataset(
        path=[
            (ENTRY_DATE, 1.50, 0.50, False),
            (EXPIRATION, 0.50, 0.00, False),
        ]
    )

    no_slip = run_backtest(raw, _config(profit_target_pct=0.99), strategy="always_sell").trades.iloc[0]
    slipped = run_backtest(
        raw,
        _config(profit_target_pct=0.99, slippage_per_leg=0.02),
        strategy="always_sell",
    ).trades.iloc[0]

    assert no_slip["entry_credit"] == pytest.approx(1.00)
    assert slipped["entry_credit"] == pytest.approx(0.96)
    assert slipped["exit_debit"] == pytest.approx(0.54)
    assert slipped["pnl_dollars"] < no_slip["pnl_dollars"]


def test_counterfactual_pnl_for_trigger_exit() -> None:
    trigger_signal = SIGNAL_DATE + timedelta(days=4)
    trigger_exit = SIGNAL_DATE + timedelta(days=5)
    profit_signal = SIGNAL_DATE + timedelta(days=6)
    profit_exit = SIGNAL_DATE + timedelta(days=7)
    raw = _dataset(
        path=[
            (ENTRY_DATE, 1.50, 0.50, False),
            (trigger_signal, 1.70, 0.50, True),
            (trigger_exit, 1.80, 0.50, True),
            (profit_signal, 0.90, 0.45, False),
            (profit_exit, 0.70, 0.40, False),
            (EXPIRATION, 0.00, 0.00, False),
        ]
    )

    result = run_backtest(raw, _config(), strategy="benign_trigger_exit")
    trade = result.trades.iloc[0]

    assert trade["exit_reason"] == "trigger_exit"
    assert trade["counterfactual_exit_date"] == profit_exit
    assert trade["counterfactual_exit_reason"] == "profit_target"
    assert trade["trigger_value_added"] == pytest.approx(
        trade["pnl_dollars"] - trade["counterfactual_pnl"]
    )
    assert trade["trigger_value_added"] < 0


def test_overlapping_position_constraint_is_respected() -> None:
    second_signal = SIGNAL_DATE + timedelta(days=7)
    second_expiration = second_signal + timedelta(days=45)
    rows = _dataset(
        path=[
            (ENTRY_DATE, 1.50, 0.50, False),
            (EXPIRATION, 0.00, 0.00, False),
        ]
    ).to_dict("records")
    rows.extend(
        _chain_rows(second_signal, second_expiration, short_close=1.40, long_close=0.40)
    )
    rows.extend(
        _selected_leg_rows(second_signal + timedelta(days=3), second_expiration, short_close=1.50, long_close=0.50)
    )
    rows.extend(
        _selected_leg_rows(second_expiration, second_expiration, short_close=0.00, long_close=0.00)
    )
    raw = pd.DataFrame(rows)

    one_at_a_time = run_backtest(
        raw,
        _config(max_concurrent_positions=1, profit_target_pct=0.99),
        strategy="always_sell",
    )
    two_at_a_time = run_backtest(
        raw,
        _config(max_concurrent_positions=2, profit_target_pct=0.99),
        strategy="always_sell",
    )

    assert len(one_at_a_time.trades) == 1
    assert len(two_at_a_time.trades) == 2


def test_missing_post_signal_option_prices_skip_trade_gracefully() -> None:
    raw = pd.DataFrame(_chain_rows(SIGNAL_DATE, EXPIRATION, short_close=1.40, long_close=0.40))

    result = run_backtest(raw, _config(), strategy="always_sell")

    assert result.trades.empty


def test_future_hedge_state_is_not_used_for_entry_filter() -> None:
    raw = _dataset(
        path=[
            (ENTRY_DATE, 1.50, 0.50, True),
            (SIGNAL_DATE + timedelta(days=4), 1.20, 0.50, True),
            (EXPIRATION, 0.00, 0.00, False),
        ],
        signal_hedge=False,
    )

    result = run_backtest(raw, _config(), strategy="benign_entries")
    trade = result.trades.iloc[0]

    assert len(result.trades) == 1
    assert trade["entry_signal_date"] == SIGNAL_DATE
    assert trade["entry_date"] == ENTRY_DATE
    assert bool(trade["hedge_trigger_at_entry"]) is False


def test_trade_details_returns_spread_and_helix_path() -> None:
    raw = _dataset()
    data = normalize_options_data(raw)
    result = run_backtest(data, _config(), strategy="always_sell")

    details = get_trade_details(data, result.trades, result.trades.iloc[0]["trade_id"])

    assert not details.empty
    assert {"spread_value", "bhr_active", "credit_stress", "vol_stress", "hedge_trigger_active"}.issubset(
        details.columns
    )
