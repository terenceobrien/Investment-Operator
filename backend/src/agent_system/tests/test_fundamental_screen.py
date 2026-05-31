"""Tests for deterministic fundamental-health screening."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.agent_system.data.types import CompanyFacts, FundamentalDataBundle
from src.agent_system.orchestration.stub_agents import (
    make_stub_regime_state,
    make_stub_thematic_map,
)
from src.agent_system.rules.fundamental_screen import (
    screen_candidate,
    screen_to_minimal_fundamental_analysis,
)
from src.agent_system.schemas.common import ConvictionRating
from src.agent_system.schemas.fundamental_screen import Archetype, ScreenVerdict

_DEFAULT_FACTS = object()
_DERIVE_EBITDA = object()


def _facts(
    *,
    revenue_ttm: float | None = 100.0,
    operating_income_ttm: float | None = 20.0,
    net_income_ttm: float | None = 10.0,
    total_assets: float | None = 100.0,
    total_debt: float | None = 10.0,
    cash_and_equivalents: float | None = 20.0,
    stockholders_equity: float | None = 50.0,
    operating_cash_flow_ttm: float | None = 12.0,
    free_cash_flow_ttm: float | None = 10.0,
    depreciation_amortization_ttm: float | None = 0.0,
    ebitda_ttm: float | None | object = _DERIVE_EBITDA,
    revenue_yoy_growth: float | None = 0.08,
    revenue_3yr_cagr: float | None = None,
) -> CompanyFacts:
    if ebitda_ttm is _DERIVE_EBITDA:
        resolved_ebitda = (
            operating_income_ttm + depreciation_amortization_ttm
            if operating_income_ttm is not None
            and depreciation_amortization_ttm is not None
            else None
        )
    else:
        resolved_ebitda = ebitda_ttm
    return CompanyFacts(
        revenue_ttm=revenue_ttm,
        gross_profit_ttm=None,
        operating_income_ttm=operating_income_ttm,
        net_income_ttm=net_income_ttm,
        total_assets=total_assets,
        total_debt=total_debt,
        cash_and_equivalents=cash_and_equivalents,
        stockholders_equity=stockholders_equity,
        operating_cash_flow_ttm=operating_cash_flow_ttm,
        free_cash_flow_ttm=free_cash_flow_ttm,
        capex_ttm=None,
        depreciation_amortization_ttm=depreciation_amortization_ttm,
        ebitda_ttm=resolved_ebitda,
        most_recent_fiscal_year_end=None,
        most_recent_quarter_end=None,
        revenue_yoy_growth=revenue_yoy_growth,
        revenue_3yr_cagr=revenue_3yr_cagr,
        gross_margin=None,
        operating_margin=None,
        net_margin=None,
    )


def _bundle(
    *,
    ticker: str = "TST",
    is_etf: bool = False,
    company_facts: CompanyFacts | None | object = _DEFAULT_FACTS,
    current_price: float | None = None,
    mean_price_target: float | None = None,
    analyst_count_buy: int | None = None,
    analyst_count_hold: int | None = None,
    analyst_count_sell: int | None = None,
) -> FundamentalDataBundle:
    return FundamentalDataBundle(
        ticker=ticker,
        as_of=datetime.now(timezone.utc),
        is_etf=is_etf,
        cik=None if is_etf else "0000000001",
        company_name="Test Corp",
        most_recent_10k=None,
        most_recent_10q=None,
        recent_8ks=[],
        company_facts=_facts() if company_facts is _DEFAULT_FACTS else company_facts,
        current_price=current_price,
        market_cap=None,
        trailing_pe=None,
        forward_pe=None,
        price_to_sales=None,
        enterprise_value=None,
        ev_to_ebitda=None,
        analyst_count_buy=analyst_count_buy,
        analyst_count_hold=analyst_count_hold,
        analyst_count_sell=analyst_count_sell,
        mean_price_target=mean_price_target,
        earnings_history=[],
        sec_fetch_success=not is_etf,
        yahoo_fetch_success=current_price is not None,
        fetch_errors=[],
        fetch_duration_ms=0,
    )


def _bridge_candidate():
    regime = make_stub_regime_state()
    return make_stub_thematic_map(regime).candidates[0]


def test_distressed_negative_equity_eliminates():
    result = screen_candidate(
        _bundle(company_facts=_facts(stockholders_equity=-5.0))
    )

    assert result.archetype == Archetype.DISTRESSED
    assert result.verdict == ScreenVerdict.ELIMINATE
    assert "negative stockholders' equity" in result.reason


def test_distressed_high_debt_to_ebitda_eliminates():
    result = screen_candidate(
        _bundle(company_facts=_facts(operating_income_ttm=100.0, total_debt=700.0))
    )

    assert result.archetype == Archetype.DISTRESSED
    assert result.verdict == ScreenVerdict.ELIMINATE
    assert result.metrics_used["debt_to_ebitda"] == pytest.approx(7.0)
    assert result.metrics_used["leverage_measure_used"] == "ebitda"


def test_distressed_negative_ocf_cash_below_debt_eliminates():
    result = screen_candidate(
        _bundle(
            company_facts=_facts(
                operating_income_ttm=-10.0,
                operating_cash_flow_ttm=-100.0,
                free_cash_flow_ttm=-110.0,
                cash_and_equivalents=10.0,
                total_debt=100.0,
            )
        )
    )

    assert result.archetype == Archetype.DISTRESSED
    assert result.verdict == ScreenVerdict.ELIMINATE
    assert "negative operating cash flow" in result.reason


def test_growth_unprofitable_fast_growth_low_debt_long_runway_passes():
    result = screen_candidate(
        _bundle(
            company_facts=_facts(
                net_income_ttm=-10.0,
                free_cash_flow_ttm=-10.0,
                operating_cash_flow_ttm=-40.0,
                cash_and_equivalents=100.0,
                total_debt=10.0,
                total_assets=100.0,
                revenue_3yr_cagr=0.30,
            )
        )
    )

    assert result.archetype == Archetype.GROWTH
    assert result.verdict == ScreenVerdict.PASS
    assert result.metrics_used["cash_runway_quarters"] == pytest.approx(10.0)
    assert result.data_quality_flag is False


def test_growth_short_runway_eliminates():
    result = screen_candidate(
        _bundle(
            company_facts=_facts(
                net_income_ttm=-10.0,
                free_cash_flow_ttm=-10.0,
                operating_cash_flow_ttm=-40.0,
                cash_and_equivalents=30.0,
                total_debt=10.0,
                total_assets=100.0,
                revenue_3yr_cagr=0.30,
            )
        )
    )

    assert result.archetype == Archetype.GROWTH
    assert result.verdict == ScreenVerdict.ELIMINATE
    assert "cash runway" in result.reason


def test_implausible_yoy_uses_plausible_cagr_and_flags_anomaly():
    result = screen_candidate(
        _bundle(
            company_facts=_facts(
                net_income_ttm=-10.0,
                free_cash_flow_ttm=-5.0,
                operating_cash_flow_ttm=20.0,
                total_debt=29.0,
                total_assets=100.0,
                revenue_yoy_growth=2.65,
                revenue_3yr_cagr=0.59,
            )
        )
    )

    assert result.archetype == Archetype.GROWTH
    assert result.verdict == ScreenVerdict.PASS
    assert result.data_quality_flag is True
    assert result.data_quality_detail is not None
    assert "265%" in result.data_quality_detail
    assert result.metrics_used["revenue_growth"] == pytest.approx(0.59)
    assert result.metrics_used["growth_measure_used"] == "revenue_3yr_cagr"


def test_implausible_yoy_without_cagr_falls_through_to_established():
    result = screen_candidate(
        _bundle(
            company_facts=_facts(
                net_income_ttm=-10.0,
                free_cash_flow_ttm=10.0,
                operating_cash_flow_ttm=12.0,
                revenue_yoy_growth=1.5,
                revenue_3yr_cagr=None,
            )
        )
    )

    assert result.archetype == Archetype.ESTABLISHED
    assert result.verdict == ScreenVerdict.PASS
    assert result.data_quality_flag is True
    assert result.metrics_used["revenue_growth"] is None
    assert result.metrics_used["growth_measure_used"] is None
    assert result.data_quality_detail is not None
    assert "150%" in result.data_quality_detail


def test_plausible_growth_measures_do_not_set_data_quality_flag():
    result = screen_candidate(
        _bundle(
            company_facts=_facts(
                net_income_ttm=-10.0,
                free_cash_flow_ttm=-10.0,
                operating_cash_flow_ttm=-40.0,
                cash_and_equivalents=100.0,
                total_debt=10.0,
                total_assets=100.0,
                revenue_yoy_growth=0.30,
                revenue_3yr_cagr=0.25,
            )
        )
    )

    assert result.archetype == Archetype.GROWTH
    assert result.verdict == ScreenVerdict.PASS
    assert result.data_quality_flag is False
    assert result.metrics_used["revenue_growth"] == pytest.approx(0.25)
    assert result.metrics_used["growth_measure_used"] == "revenue_3yr_cagr"


def test_data_quality_flag_never_changes_verdict():
    flagged = screen_candidate(
        _bundle(
            company_facts=_facts(
                net_income_ttm=10.0,
                free_cash_flow_ttm=10.0,
                operating_cash_flow_ttm=12.0,
                revenue_yoy_growth=1.5,
                revenue_3yr_cagr=None,
            )
        )
    )
    unflagged = screen_candidate(
        _bundle(
            company_facts=_facts(
                net_income_ttm=10.0,
                free_cash_flow_ttm=10.0,
                operating_cash_flow_ttm=12.0,
                revenue_yoy_growth=0.05,
                revenue_3yr_cagr=None,
            )
        )
    )

    assert flagged.data_quality_flag is True
    assert unflagged.data_quality_flag is False
    assert flagged.archetype == unflagged.archetype == Archetype.ESTABLISHED
    assert flagged.verdict == unflagged.verdict == ScreenVerdict.PASS


def test_decelerated_growth_reclassifies_to_established():
    result = screen_candidate(
        _bundle(
            company_facts=_facts(
                net_income_ttm=-10.0,
                free_cash_flow_ttm=-5.0,
                operating_cash_flow_ttm=20.0,
                total_debt=10.0,
                total_assets=100.0,
                revenue_3yr_cagr=0.12,
            )
        )
    )

    assert result.archetype == Archetype.ESTABLISHED
    assert result.verdict == ScreenVerdict.PASS


def test_established_profitable_low_leverage_passes():
    result = screen_candidate(
        _bundle(
            company_facts=_facts(
                net_income_ttm=100.0,
                free_cash_flow_ttm=100.0,
                operating_cash_flow_ttm=100.0,
                operating_income_ttm=100.0,
                total_debt=100.0,
            )
        )
    )

    assert result.archetype == Archetype.ESTABLISHED
    assert result.verdict == ScreenVerdict.PASS
    assert result.metrics_used["debt_to_ebitda"] == pytest.approx(1.0)
    assert "leverage 1.0x EBITDA" in result.reason


def test_established_profitable_high_leverage_eliminates():
    result = screen_candidate(
        _bundle(
            company_facts=_facts(
                net_income_ttm=100.0,
                free_cash_flow_ttm=100.0,
                operating_cash_flow_ttm=100.0,
                operating_income_ttm=100.0,
                total_debt=500.0,
            )
        )
    )

    assert result.archetype == Archetype.ESTABLISHED
    assert result.verdict == ScreenVerdict.ELIMINATE
    assert result.metrics_used["debt_to_ebitda"] == pytest.approx(5.0)


def test_real_ebitda_prevents_false_positive_leverage_elimination():
    result = screen_candidate(
        _bundle(
            company_facts=_facts(
                revenue_ttm=15000.0,
                operating_income_ttm=3500.0,
                depreciation_amortization_ttm=1700.0,
                total_debt=19000.0,
                net_income_ttm=1200.0,
                free_cash_flow_ttm=900.0,
                operating_cash_flow_ttm=2600.0,
            )
        )
    )

    assert result.archetype == Archetype.ESTABLISHED
    assert result.verdict == ScreenVerdict.PASS
    assert result.metrics_used["ebitda_ttm"] == pytest.approx(5200.0)
    assert result.metrics_used["debt_to_ebitda"] == pytest.approx(19000.0 / 5200.0)
    assert result.metrics_used["leverage_measure_used"] == "ebitda"
    assert "leverage 3.7x EBITDA" in result.reason


def test_missing_da_fallback_uses_operating_income_proxy_and_records_note():
    result = screen_candidate(
        _bundle(
            company_facts=_facts(
                operating_income_ttm=100.0,
                depreciation_amortization_ttm=None,
                ebitda_ttm=None,
                total_debt=100.0,
            )
        )
    )

    assert result.verdict == ScreenVerdict.PASS
    assert result.metrics_used["leverage_measure_used"] == "operating_income_proxy"
    assert result.metrics_used["debt_to_ebitda"] == pytest.approx(1.0)
    assert "D&A unavailable" in result.reason
    assert result.notes is not None
    assert "EBITDA proxy used" in result.notes


def test_missing_ebitda_and_nonpositive_operating_income_leans_pass():
    result = screen_candidate(
        _bundle(
            company_facts=_facts(
                operating_income_ttm=None,
                depreciation_amortization_ttm=None,
                ebitda_ttm=None,
                total_debt=1000.0,
                net_income_ttm=10.0,
                free_cash_flow_ttm=10.0,
                operating_cash_flow_ttm=12.0,
            )
        )
    )

    assert result.verdict == ScreenVerdict.PASS
    assert result.metrics_used["debt_to_ebitda"] is None
    assert result.metrics_used["leverage_measure_used"] is None
    assert result.notes is not None
    assert "leverage check inconclusive" in result.notes


def test_established_unprofitable_slow_growth_eliminates():
    result = screen_candidate(
        _bundle(
            company_facts=_facts(
                net_income_ttm=-10.0,
                free_cash_flow_ttm=10.0,
                operating_cash_flow_ttm=10.0,
                operating_income_ttm=10.0,
                total_debt=0.0,
                revenue_yoy_growth=0.01,
            )
        )
    )

    assert result.archetype == Archetype.ESTABLISHED
    assert result.verdict == ScreenVerdict.ELIMINATE
    assert "unprofitable" in result.reason


def test_etf_bundle_passes_as_not_applicable():
    result = screen_candidate(_bundle(ticker="SPY", is_etf=True))

    assert result.verdict == ScreenVerdict.PASS
    assert result.archetype == Archetype.ESTABLISHED
    assert "not applicable" in result.reason


def test_insufficient_data_passes_for_manual_review():
    result = screen_candidate(_bundle(company_facts=None))

    assert result.verdict == ScreenVerdict.PASS
    assert result.data_was_sufficient is False
    assert "Insufficient financial data" in result.reason


def test_crowding_flag_with_high_buy_ratio_and_low_upside():
    result = screen_candidate(
        _bundle(
            current_price=100.0,
            mean_price_target=102.0,
            analyst_count_buy=8,
            analyst_count_hold=2,
            analyst_count_sell=0,
        )
    )

    assert result.verdict == ScreenVerdict.PASS
    assert result.crowding_flag is True
    assert result.metrics_used["buy_ratio"] == pytest.approx(0.8)
    assert result.metrics_used["upside_to_target"] == pytest.approx(0.02)


def test_crowding_flag_false_when_upside_is_large():
    result = screen_candidate(
        _bundle(
            current_price=100.0,
            mean_price_target=125.0,
            analyst_count_buy=8,
            analyst_count_hold=2,
            analyst_count_sell=0,
        )
    )

    assert result.verdict == ScreenVerdict.PASS
    assert result.crowding_flag is False


def test_crowding_never_changes_verdict():
    crowded_args = {
        "current_price": 100.0,
        "mean_price_target": 102.0,
        "analyst_count_buy": 8,
        "analyst_count_hold": 2,
        "analyst_count_sell": 0,
    }
    passing = screen_candidate(_bundle(**crowded_args))
    eliminated = screen_candidate(
        _bundle(
            company_facts=_facts(stockholders_equity=-5.0),
            **crowded_args,
        )
    )

    assert passing.crowding_flag is True
    assert passing.verdict == ScreenVerdict.PASS
    assert eliminated.crowding_flag is True
    assert eliminated.verdict == ScreenVerdict.ELIMINATE


def test_screen_bridge_clean_pass_maps_to_moderate_fundamental_conviction():
    screen = screen_candidate(_bundle())
    fundamental = screen_to_minimal_fundamental_analysis(
        _bridge_candidate(),
        screen,
    )

    assert fundamental.conviction.rating == ConvictionRating.MODERATE
    assert "screen passed cleanly" in fundamental.conviction.justification
    assert "Bounded at MODERATE" in fundamental.conviction.justification


def test_screen_bridge_crowding_flag_maps_to_weak_fundamental_conviction():
    screen = screen_candidate(
        _bundle(
            current_price=100.0,
            mean_price_target=102.0,
            analyst_count_buy=8,
            analyst_count_hold=2,
            analyst_count_sell=0,
        )
    )
    fundamental = screen_to_minimal_fundamental_analysis(
        _bridge_candidate(),
        screen,
    )

    assert screen.crowding_flag is True
    assert fundamental.conviction.rating == ConvictionRating.WEAK
    assert "crowding flag" in fundamental.conviction.justification


def test_screen_bridge_data_quality_flag_maps_to_weak_fundamental_conviction():
    screen = screen_candidate(
        _bundle(
            company_facts=_facts(
                net_income_ttm=10.0,
                free_cash_flow_ttm=10.0,
                operating_cash_flow_ttm=12.0,
                revenue_yoy_growth=1.5,
                revenue_3yr_cagr=None,
            )
        )
    )
    fundamental = screen_to_minimal_fundamental_analysis(
        _bridge_candidate(),
        screen,
    )

    assert screen.data_quality_flag is True
    assert fundamental.conviction.rating == ConvictionRating.WEAK
    assert "data_quality flag set" in fundamental.conviction.justification


def test_screen_bridge_insufficient_data_maps_to_weak_fundamental_conviction():
    screen = screen_candidate(_bundle(company_facts=None))
    fundamental = screen_to_minimal_fundamental_analysis(
        _bridge_candidate(),
        screen,
    )

    assert screen.data_was_sufficient is False
    assert fundamental.conviction.rating == ConvictionRating.WEAK
    assert "data was insufficient" in fundamental.conviction.justification


def test_screen_bridge_multiple_flags_stays_weak():
    screen = screen_candidate(
        _bundle(
            company_facts=_facts(
                net_income_ttm=10.0,
                free_cash_flow_ttm=10.0,
                operating_cash_flow_ttm=12.0,
                revenue_yoy_growth=1.5,
                revenue_3yr_cagr=None,
            ),
            current_price=100.0,
            mean_price_target=102.0,
            analyst_count_buy=8,
            analyst_count_hold=2,
            analyst_count_sell=0,
        )
    )
    fundamental = screen_to_minimal_fundamental_analysis(
        _bridge_candidate(),
        screen,
    )

    assert screen.crowding_flag is True
    assert screen.data_quality_flag is True
    assert fundamental.conviction.rating == ConvictionRating.WEAK
