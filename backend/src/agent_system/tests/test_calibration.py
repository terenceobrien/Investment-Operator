"""Tests for sector/industry calibration distribution builder."""
from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest

from src.agent_system.data.types import CompanyFacts, FundamentalDataBundle
from src.agent_system.evals.run_calibration import (
    METRICS,
    build_distributions,
    compute_percentiles,
    derive_metric_values,
    load_calibration_bounds,
    normalize_sector,
    run_harness,
)


def _facts(
    *,
    revenue_ttm: float | None = 100.0,
    free_cash_flow_ttm: float | None = 10.0,
    operating_cash_flow_ttm: float | None = 20.0,
    total_debt: float | None = 30.0,
    total_assets: float | None = 100.0,
    ebitda_ttm: float | None = 10.0,
    operating_margin: float | None = 0.20,
    net_margin: float | None = 0.10,
    gross_margin: float | None = 0.40,
    revenue_yoy_growth: float | None = 0.05,
    revenue_3yr_cagr: float | None = 0.04,
) -> CompanyFacts:
    return CompanyFacts(
        revenue_ttm=revenue_ttm,
        gross_profit_ttm=None,
        operating_income_ttm=None,
        net_income_ttm=None,
        total_assets=total_assets,
        total_debt=total_debt,
        cash_and_equivalents=40.0,
        stockholders_equity=None,
        operating_cash_flow_ttm=operating_cash_flow_ttm,
        free_cash_flow_ttm=free_cash_flow_ttm,
        capex_ttm=None,
        depreciation_amortization_ttm=None,
        ebitda_ttm=ebitda_ttm,
        most_recent_fiscal_year_end=None,
        most_recent_quarter_end=None,
        annual_revenue_history=[],
        revenue_yoy_growth=revenue_yoy_growth,
        revenue_3yr_cagr=revenue_3yr_cagr,
        gross_margin=gross_margin,
        operating_margin=operating_margin,
        net_margin=net_margin,
    )


def _bundle(**facts_kwargs) -> FundamentalDataBundle:
    return FundamentalDataBundle(
        ticker="TST",
        as_of=datetime.now(timezone.utc),
        is_etf=False,
        cik="0000000001",
        company_name="Test Corp",
        most_recent_10k=None,
        most_recent_10q=None,
        recent_8ks=[],
        company_facts=_facts(**facts_kwargs),
        current_price=None,
        market_cap=None,
        trailing_pe=None,
        forward_pe=None,
        price_to_sales=None,
        enterprise_value=None,
        ev_to_ebitda=None,
        analyst_count_buy=None,
        analyst_count_hold=None,
        analyst_count_sell=None,
        mean_price_target=None,
        sector="Information Technology",
        industry="Software - Application",
        earnings_history=[],
        sec_fetch_success=True,
        yahoo_fetch_success=True,
        fetch_errors=[],
        fetch_duration_ms=0,
    )


def _row(
    *,
    sector: str = "Information Technology",
    industry: str | None = "Software - Application",
    metric: str,
    value: float | None,
    dropped: bool = False,
) -> dict:
    metrics = {name: {"value": None, "dropped": False} for name in METRICS}
    metrics[metric] = {"value": value, "dropped": dropped}
    return {
        "ticker": "TST",
        "sector": sector,
        "industry": industry,
        "metrics": metrics,
        "fetch_success": True,
    }


def test_plausibility_trimming_drops_and_counts_out_of_bounds_values():
    rows = [
        _row(metric="operating_margin", value=0.10),
        _row(metric="operating_margin", value=0.20),
        _row(metric="operating_margin", value=None, dropped=True),
    ]

    buckets = build_distributions(rows, min_sector_n=2, min_all_n=2)
    summary = buckets["sector"]["Information Technology"]["operating_margin"]

    assert summary["n"] == 2
    assert summary["dropped"] == 1
    assert summary["p50"] == pytest.approx(0.15)


def test_debt_to_ebitda_excludes_negative_ebitda_names():
    bounds = load_calibration_bounds()

    metrics = derive_metric_values(
        _bundle(ebitda_ttm=-10.0, total_debt=50.0),
        bounds,
    )

    assert metrics["debt_to_ebitda"]["value"] is None
    assert metrics["debt_to_ebitda"]["dropped"] is True


def test_cash_runway_only_includes_negative_ocf_names():
    bounds = load_calibration_bounds()

    positive = derive_metric_values(
        _bundle(operating_cash_flow_ttm=20.0),
        bounds,
    )
    burning = derive_metric_values(
        _bundle(operating_cash_flow_ttm=-40.0),
        bounds,
    )

    assert positive["cash_runway_quarters"] == {"value": None, "dropped": False}
    assert burning["cash_runway_quarters"]["value"] == pytest.approx(4.0)
    assert burning["cash_runway_quarters"]["dropped"] is False


def test_percentile_computation_linear_interpolation():
    percentiles = compute_percentiles([1, 2, 3, 4, 5])

    assert percentiles["p10"] == pytest.approx(1.4)
    assert percentiles["p25"] == pytest.approx(2.0)
    assert percentiles["p50"] == pytest.approx(3.0)
    assert percentiles["p75"] == pytest.approx(4.0)
    assert percentiles["p90"] == pytest.approx(4.6)


def test_normalize_sector_maps_yahoo_labels_to_gics_names():
    assert normalize_sector("Technology") == "Information Technology"
    assert normalize_sector("Financial Services") == "Financials"
    assert normalize_sector("Consumer Cyclical") == "Consumer Discretionary"
    assert normalize_sector("Health Care") == "Health Care"
    assert normalize_sector(None) is None


def test_industry_with_too_few_valid_names_is_not_emitted():
    rows = [
        _row(metric="debt_to_assets", value=0.20 + idx * 0.001)
        for idx in range(29)
    ]

    buckets = build_distributions(
        rows,
        min_sector_n=20,
        min_industry_n=30,
        min_all_n=20,
    )

    assert "debt_to_assets" in buckets["sector"]["Information Technology"]
    assert buckets["industry"] == {}


def test_bucket_metric_with_n_below_minimum_is_omitted():
    rows = [
        _row(metric="debt_to_assets", value=0.20 + idx * 0.001)
        for idx in range(19)
    ]

    buckets = build_distributions(
        rows,
        min_sector_n=20,
        min_industry_n=30,
        min_all_n=20,
    )

    assert buckets["sector"]["Information Technology"] == {}
    assert "debt_to_assets" not in buckets["ALL"]


@pytest.mark.skipif(
    os.getenv("INTEGRATION_TESTS") != "1",
    reason="Set INTEGRATION_TESTS=1 to run provider integration tests.",
)
def test_integration_calibration_limit_30_writes_asset(tmp_path):
    output_path = tmp_path / "sector_distributions.json"

    asset = run_harness(output_path=output_path, limit=30)

    assert output_path.exists()
    assert "ALL" in asset["buckets"]
    assert asset["universe_size"] == 30
    assert asset["buckets"]["sector"]
