"""Immutable schemas for fundamental-data provider output."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class FilingExtract(BaseModel):
    """A single SEC filing with extracted text and metadata."""

    model_config = ConfigDict(frozen=True)

    filing_type: str
    filing_date: date
    period_of_report: date | None
    accession_number: str
    primary_document_url: str
    extracted_text: str | None
    text_was_truncated: bool = False
    extraction_method: str = "unknown"


class AnnualRevenueRecord(BaseModel):
    """One fiscal year's annual revenue."""

    model_config = ConfigDict(frozen=True)

    fiscal_year_end: date
    revenue: float


class CompanyFacts(BaseModel):
    """Structured XBRL financial facts from SEC."""

    model_config = ConfigDict(frozen=True)

    revenue_ttm: float | None
    gross_profit_ttm: float | None
    operating_income_ttm: float | None
    net_income_ttm: float | None

    total_assets: float | None
    total_debt: float | None
    cash_and_equivalents: float | None
    stockholders_equity: float | None

    operating_cash_flow_ttm: float | None
    free_cash_flow_ttm: float | None
    capex_ttm: float | None
    depreciation_amortization_ttm: float | None
    ebitda_ttm: float | None

    most_recent_fiscal_year_end: date | None
    most_recent_quarter_end: date | None

    annual_revenue_history: list[AnnualRevenueRecord] = Field(default_factory=list)
    revenue_yoy_growth: float | None = None
    revenue_3yr_cagr: float | None = None

    gross_margin: float | None = None
    operating_margin: float | None = None
    net_margin: float | None = None


class EarningsRecord(BaseModel):
    """One historical earnings event."""

    model_config = ConfigDict(frozen=True)

    report_date: date
    period_end: date | None
    eps_actual: float | None
    eps_estimate: float | None
    surprise_pct: float | None


class FundamentalDataBundle(BaseModel):
    """Complete data bundle for one ticker."""

    model_config = ConfigDict(frozen=True)

    ticker: str
    as_of: datetime
    is_etf: bool = False

    cik: str | None
    company_name: str | None
    most_recent_10k: FilingExtract | None
    most_recent_10q: FilingExtract | None
    recent_8ks: list[FilingExtract] = Field(default_factory=list)
    company_facts: CompanyFacts | None

    current_price: float | None
    market_cap: float | None
    trailing_pe: float | None
    forward_pe: float | None
    price_to_sales: float | None
    enterprise_value: float | None
    ev_to_ebitda: float | None

    analyst_count_buy: int | None
    analyst_count_hold: int | None
    analyst_count_sell: int | None
    mean_price_target: float | None
    sector: str | None = None
    industry: str | None = None

    earnings_history: list[EarningsRecord] = Field(default_factory=list)

    sec_fetch_success: bool
    yahoo_fetch_success: bool
    fetch_errors: list[str] = Field(default_factory=list)
    fetch_duration_ms: int | None


class TechnicalContext(BaseModel):
    """Derived technical context from daily OHLCV history."""

    model_config = ConfigDict(frozen=True)

    sma_50: float | None
    sma_200: float | None
    price_vs_sma_50: float | None
    price_vs_sma_200: float | None
    high_20d: float | None
    low_20d: float | None
    high_52w: float | None
    low_52w: float | None
    atr_14: float | None
    atr_pct: float | None
    trend_regime: str | None


class MarketDataBundle(BaseModel):
    """Price-history and technical-analysis bundle for one ticker."""

    model_config = ConfigDict(frozen=True)

    ticker: str
    as_of: datetime
    current_price: float | None
    history_start: date | None
    history_end: date | None
    bars_count: int
    technicals: TechnicalContext | None

    fetch_success: bool
    fetch_errors: list[str] = Field(default_factory=list)
