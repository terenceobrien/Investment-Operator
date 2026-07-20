from __future__ import annotations

from src.agent_system.schemas.trade_outcome import TradeOutcome
from scripts import update_trade_prices


def test_recompute_cached_metrics_does_not_refresh_current_unrealized_pnl(
    monkeypatch,
) -> None:
    outcome = TradeOutcome(
        trade_id="trade-1",
        cycle_id="8b1dcfdb-1dd2-4ccf-8afa-be2ab2dae01e",
        cycle_date="2026-06-25",
        underlying="TEST",
        direction="long",
        instrument_type="stock",
        instrument_description="TEST common stock",
        proposed_size_pct=0.02,
        final_size_pct=0.02,
        decision="execute",
        status="open",
        entry_date="2026-06-25",
        entry_underlying_price=100.0,
        current_unrealized_pnl_pct=0.42,
    )
    monkeypatch.setattr(update_trade_prices, "load_price_points", lambda _trade_id: [])

    updated = update_trade_prices._recompute_cached_metrics(
        outcome,
        asof="2026-07-03",
        underlying_price=125.0,
        instrument_price=None,
    )

    assert updated.current_underlying_price == 125.0
    assert updated.current_unrealized_pnl_pct == 0.42
