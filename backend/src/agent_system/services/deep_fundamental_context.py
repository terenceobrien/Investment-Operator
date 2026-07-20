"""Build deterministic context packs for deep fundamental underwriting."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable

import pandas as pd
import yfinance as yf

from src.agent_system.schemas.deep_fundamental import (
    BasicScreenResult,
    DataConfidence,
    FinancialPeriodSnapshot,
    FinancialPeriodType,
    FinancialSnapshot,
    FinancialTrendSnapshot,
    FundamentalContextPack,
    PeerRelativeSnapshot,
    PriceSnapshot,
    QuarterlyFinancialTrendPack,
    ValuationSnapshot,
)


def build_fundamental_context_pack(
    ticker: str,
    peer_tickers: list[str] | None = None,
    basic_screen_result: BasicScreenResult | None = None,
) -> FundamentalContextPack:
    """Build a best-effort deterministic context pack from yfinance data."""

    clean_ticker = ticker.upper().strip()
    as_of_date = date.today()
    missing_fields: list[str] = []
    source_notes: list[str] = ["Financial context sourced from yfinance."]
    data_freshness_notes: list[str] = []

    yf_ticker = None
    info: dict[str, Any] = {}
    try:
        yf_ticker = yf.Ticker(clean_ticker)
        raw_info = yf_ticker.info
        info = raw_info if isinstance(raw_info, dict) else {}
        if not info:
            missing_fields.append("info")
            source_notes.append("yfinance info returned no data.")
    except Exception as exc:
        missing_fields.append("info")
        source_notes.append(f"yfinance info fetch failed: {exc}")

    financials = _fetch_statement(yf_ticker, "financials", missing_fields, source_notes)
    cashflow = _fetch_statement(yf_ticker, "cashflow", missing_fields, source_notes)
    balance_sheet = _fetch_statement(
        yf_ticker, "balance_sheet", missing_fields, source_notes
    )
    quarterly_financials = _fetch_first_statement(
        yf_ticker,
        ["quarterly_financials", "quarterly_income_stmt"],
        missing_fields,
        source_notes,
    )
    quarterly_cashflow = _fetch_first_statement(
        yf_ticker,
        ["quarterly_cashflow"],
        missing_fields,
        source_notes,
    )
    quarterly_balance_sheet = _fetch_first_statement(
        yf_ticker,
        ["quarterly_balance_sheet"],
        missing_fields,
        source_notes,
    )

    price_snapshot = _build_price_snapshot(
        clean_ticker,
        yf_ticker,
        info,
        missing_fields,
        source_notes,
    )
    quarterly_financial_trend = _build_quarterly_financial_trend_pack(
        quarterly_financials=quarterly_financials,
        quarterly_cashflow=quarterly_cashflow,
        quarterly_balance_sheet=quarterly_balance_sheet,
        annual_financials=financials,
        annual_cashflow=cashflow,
        annual_balance_sheet=balance_sheet,
        as_of_date=as_of_date,
        price_snapshot=price_snapshot,
        missing_fields=missing_fields,
    )
    financial_trend = _build_financial_trend_snapshot(
        info=info,
        financials=financials,
        cashflow=cashflow,
        balance_sheet=balance_sheet,
        quarterly_financial_trend=quarterly_financial_trend,
        missing_fields=missing_fields,
    )
    valuation_snapshot = _build_valuation_snapshot(info, missing_fields)
    peer_relative_snapshot = _build_peer_relative_snapshot(
        clean_ticker,
        peer_tickers,
        info,
        price_snapshot,
        valuation_snapshot,
        missing_fields,
    )

    data_confidence = _determine_context_confidence(
        financial_trend=financial_trend,
        quarterly_financial_trend=quarterly_financial_trend,
        price_snapshot=price_snapshot,
        valuation_snapshot=valuation_snapshot,
        peer_relative_snapshot=peer_relative_snapshot,
    )
    if (
        quarterly_financial_trend is not None
        and quarterly_financial_trend.financial_context_stale
    ):
        data_confidence = (
            DataConfidence.LOW
            if data_confidence == DataConfidence.MEDIUM
            else DataConfidence.MEDIUM
            if data_confidence == DataConfidence.HIGH
            else data_confidence
        )
    if quarterly_financial_trend is not None:
        data_freshness_notes.extend(quarterly_financial_trend.staleness_warnings)
        if quarterly_financial_trend.latest_period_end_date is not None:
            data_freshness_notes.append(
                "Latest financial period end date: "
                f"{quarterly_financial_trend.latest_period_end_date.isoformat()}."
            )
        if quarterly_financial_trend.latest_filing_date is not None:
            data_freshness_notes.append(
                "Latest financial filing/report date: "
                f"{quarterly_financial_trend.latest_filing_date.isoformat()}."
            )
        if quarterly_financial_trend.latest_quarter is not None:
            source_notes.append(
                "Financial trend is derived from quarterly financial statements "
                f"through period ending "
                f"{quarterly_financial_trend.latest_quarter.period_end_date}."
            )
        else:
            source_notes.append(
                "Quarterly financials unavailable; financial trend is derived "
                "from last full fiscal year and may be stale."
            )

    return FundamentalContextPack(
        ticker=clean_ticker,
        as_of_date=as_of_date,
        financial_trend=financial_trend,
        quarterly_financial_trend=quarterly_financial_trend,
        price_snapshot=price_snapshot,
        valuation_snapshot=valuation_snapshot,
        peer_relative_snapshot=peer_relative_snapshot,
        basic_screen_result=basic_screen_result,
        data_confidence=data_confidence,
        missing_fields=_dedupe_preserve_order(missing_fields),
        source_notes=_dedupe_preserve_order(source_notes),
        data_freshness_notes=_dedupe_preserve_order(data_freshness_notes),
    )


def _fetch_statement(
    yf_ticker: Any,
    attribute: str,
    missing_fields: list[str],
    source_notes: list[str],
) -> pd.DataFrame | None:
    if yf_ticker is None:
        missing_fields.append(attribute)
        return None

    try:
        statement = getattr(yf_ticker, attribute)
    except Exception as exc:
        missing_fields.append(attribute)
        source_notes.append(f"yfinance {attribute} fetch failed: {exc}")
        return None

    if not isinstance(statement, pd.DataFrame) or statement.empty:
        missing_fields.append(attribute)
        source_notes.append(f"yfinance {attribute} returned no rows.")
        return None
    return statement


def _fetch_first_statement(
    yf_ticker: Any,
    attributes: list[str],
    missing_fields: list[str],
    source_notes: list[str],
) -> pd.DataFrame | None:
    for attribute in attributes:
        before_missing = len(missing_fields)
        before_notes = len(source_notes)
        statement = _fetch_statement(yf_ticker, attribute, missing_fields, source_notes)
        if statement is not None:
            return statement
        del missing_fields[before_missing:]
        del source_notes[before_notes:]

    missing_fields.append(attributes[0])
    source_notes.append(f"yfinance {attributes[0]} returned no usable rows.")
    return None


def _build_quarterly_financial_trend_pack(
    *,
    quarterly_financials: pd.DataFrame | None,
    quarterly_cashflow: pd.DataFrame | None,
    quarterly_balance_sheet: pd.DataFrame | None,
    annual_financials: pd.DataFrame | None,
    annual_cashflow: pd.DataFrame | None,
    annual_balance_sheet: pd.DataFrame | None,
    as_of_date: date,
    price_snapshot: PriceSnapshot | None,
    missing_fields: list[str],
) -> QuarterlyFinancialTrendPack:
    quarter_columns = _statement_columns_desc(
        quarterly_financials,
        quarterly_cashflow,
        quarterly_balance_sheet,
    )[:8]
    quarters: list[FinancialPeriodSnapshot] = []

    for index, column in enumerate(quarter_columns):
        snapshot = _build_financial_period_snapshot(
            period_type=FinancialPeriodType.QUARTER,
            fiscal_period=f"Q-{index}",
            period_end_date=_column_to_date(column),
            source="yfinance_quarterly",
            financials=quarterly_financials,
            cashflow=quarterly_cashflow,
            balance_sheet=quarterly_balance_sheet,
            column=column,
        )
        if _period_snapshot_has_data(snapshot):
            quarters.append(snapshot)

    for index, quarter in enumerate(quarters):
        prior_quarter = quarters[index + 1] if index + 1 < len(quarters) else None
        year_ago_quarter = quarters[index + 4] if index + 4 < len(quarters) else None
        quarter.revenue_growth_qoq = _safe_growth(
            quarter.revenue,
            prior_quarter.revenue if prior_quarter else None,
        )
        quarter.revenue_growth_yoy = _safe_growth(
            quarter.revenue,
            year_ago_quarter.revenue if year_ago_quarter else None,
        )

    latest_quarter = quarters[0] if quarters else None
    prior_quarter = quarters[1] if len(quarters) > 1 else None
    year_ago_quarter = quarters[4] if len(quarters) > 4 else None
    trailing_four = (
        _aggregate_periods(
            quarters[:4],
            period_type=FinancialPeriodType.LTM,
            fiscal_period="trailing_four_quarters",
            source="yfinance_quarterly",
        )
        if len(quarters) >= 4
        else None
    )
    prior_trailing_four = (
        _aggregate_periods(
            quarters[4:8],
            period_type=FinancialPeriodType.LTM,
            fiscal_period="prior_trailing_four_quarters",
            source="yfinance_quarterly",
        )
        if len(quarters) >= 8
        else None
    )

    if trailing_four and prior_trailing_four:
        trailing_four.revenue_growth_yoy = _safe_growth(
            trailing_four.revenue,
            prior_trailing_four.revenue,
        )

    annual_columns = _statement_columns_desc(
        annual_financials,
        annual_cashflow,
        annual_balance_sheet,
    )
    last_fiscal_year = (
        _build_financial_period_snapshot(
            period_type=FinancialPeriodType.FISCAL_YEAR,
            fiscal_period="last_fiscal_year",
            period_end_date=_column_to_date(annual_columns[0]),
            source="yfinance_annual",
            financials=annual_financials,
            cashflow=annual_cashflow,
            balance_sheet=annual_balance_sheet,
            column=annual_columns[0],
        )
        if annual_columns
        else None
    )
    prior_fiscal_year = (
        _build_financial_period_snapshot(
            period_type=FinancialPeriodType.FISCAL_YEAR,
            fiscal_period="prior_fiscal_year",
            period_end_date=_column_to_date(annual_columns[1]),
            source="yfinance_annual",
            financials=annual_financials,
            cashflow=annual_cashflow,
            balance_sheet=annual_balance_sheet,
            column=annual_columns[1],
        )
        if len(annual_columns) > 1
        else None
    )

    latest_period_end_date = latest_quarter.period_end_date if latest_quarter else None
    stale, staleness_warnings = assess_financial_data_freshness(
        latest_period_end_date,
        as_of_date,
        price_snapshot,
    )

    notes = _latest_quarter_vs_ltm_notes(latest_quarter, trailing_four)
    inflection_flags = _build_inflection_flags(
        latest_quarter=latest_quarter,
        prior_quarter=prior_quarter,
        trailing_four=trailing_four,
        stale=stale,
    )

    if not quarters:
        missing_fields.append("quarterly_financial_trend.latest_quarter")

    return QuarterlyFinancialTrendPack(
        latest_quarter=latest_quarter,
        prior_quarter=prior_quarter,
        year_ago_quarter=year_ago_quarter,
        trailing_four_quarters=trailing_four,
        trailing_eight_quarters=quarters,
        last_fiscal_year=last_fiscal_year if _period_snapshot_has_data(last_fiscal_year) else None,
        prior_fiscal_year=prior_fiscal_year if _period_snapshot_has_data(prior_fiscal_year) else None,
        revenue_trend_8q=_series_trend([quarter.revenue for quarter in quarters]),
        gross_margin_trend_8q=_series_trend([quarter.gross_margin for quarter in quarters]),
        operating_margin_trend_8q=_series_trend([quarter.operating_margin for quarter in quarters]),
        fcf_trend_8q=_series_trend([quarter.free_cash_flow_margin for quarter in quarters]),
        leverage_trend_8q=_inverse_series_trend(
            [quarter.net_debt_to_ebitda for quarter in quarters]
        ),
        latest_quarter_vs_ltm_notes=notes,
        inflection_flags=inflection_flags,
        staleness_warnings=staleness_warnings,
        latest_period_end_date=latest_period_end_date,
        latest_filing_date=None,
        financial_context_stale=stale,
    )


def assess_financial_data_freshness(
    latest_period_end_date: date | None,
    as_of_date: date,
    price_snapshot: PriceSnapshot | None = None,
) -> tuple[bool, list[str]]:
    warnings: list[str] = []
    stale = False

    if latest_period_end_date is None:
        return True, ["Could not determine latest financial period end date."]

    age_days = (as_of_date - latest_period_end_date).days
    if age_days > 120:
        stale = True
        warnings.append("Latest quarterly financial period is more than 120 days old.")
    if age_days > 180:
        stale = True
        warnings.append(
            "Financial context may be using annual/old quarterly data and is stale for current underwriting."
        )
    if stale and price_snapshot is not None:
        if (
            price_snapshot.return_1m is not None
            and abs(price_snapshot.return_1m) >= 0.20
        ) or (
            price_snapshot.return_3m is not None
            and abs(price_snapshot.return_3m) >= 0.40
        ):
            warnings.append(
                "Large recent price move may reflect information not captured in stale financial statements."
            )

    return stale, warnings


def _build_financial_trend_snapshot(
    *,
    info: dict[str, Any],
    financials: pd.DataFrame | None,
    cashflow: pd.DataFrame | None,
    balance_sheet: pd.DataFrame | None,
    quarterly_financial_trend: QuarterlyFinancialTrendPack | None,
    missing_fields: list[str],
) -> FinancialTrendSnapshot | None:
    if (
        quarterly_financial_trend is not None
        and quarterly_financial_trend.trailing_four_quarters is not None
    ):
        latest = _financial_snapshot_from_period(
            quarterly_financial_trend.trailing_four_quarters
        )
        prior_window = (
            _aggregate_periods(
                quarterly_financial_trend.trailing_eight_quarters[4:8],
                period_type=FinancialPeriodType.LTM,
                fiscal_period="prior_trailing_four_quarters",
                source="yfinance_quarterly",
            )
            if len(quarterly_financial_trend.trailing_eight_quarters) >= 8
            else None
        )
        prior_year = (
            _financial_snapshot_from_period(prior_window)
            if prior_window and _period_snapshot_has_data(prior_window)
            else _financial_snapshot_from_period(
                quarterly_financial_trend.prior_fiscal_year
            )
        )
        notes = [
            "financial_trend.latest is derived from trailing four quarters.",
        ]
        if prior_window and _period_snapshot_has_data(prior_window):
            notes.append(
                "financial_trend.prior_year is derived from the previous trailing four-quarter window."
            )
        else:
            notes.append(
                "financial_trend.prior_year uses prior fiscal year because previous trailing four-quarter window is unavailable."
            )
        notes.extend(quarterly_financial_trend.latest_quarter_vs_ltm_notes)
        notes.extend(quarterly_financial_trend.staleness_warnings)

        latest_quarter = quarterly_financial_trend.latest_quarter
        prior_quarter = quarterly_financial_trend.prior_quarter
        year_ago_quarter = quarterly_financial_trend.year_ago_quarter
        return FinancialTrendSnapshot(
            latest=latest,
            prior_year=prior_year,
            revenue_growth_direction=_revenue_growth_direction_from_quarterly(
                quarterly_financial_trend,
            ),
            margin_direction=_quarterly_metric_direction(
                latest_quarter,
                prior_quarter,
                year_ago_quarter,
                "operating_margin",
            ),
            fcf_direction=_quarterly_metric_direction(
                latest_quarter,
                prior_quarter,
                year_ago_quarter,
                "free_cash_flow_margin",
            ),
            leverage_direction=_inverse_quarterly_metric_direction(
                latest_quarter,
                prior_quarter,
                year_ago_quarter,
                "net_debt_to_ebitda",
            ),
            notes=_dedupe_preserve_order(notes),
        )

    latest = _build_financial_snapshot(
        info=info,
        financials=financials,
        cashflow=cashflow,
        balance_sheet=balance_sheet,
        column_offset=0,
    )
    prior_year = _build_financial_snapshot(
        info=info,
        financials=financials,
        cashflow=cashflow,
        balance_sheet=balance_sheet,
        column_offset=1,
    )

    notes: list[str] = []
    if latest is None:
        missing_fields.append("financial_trend.latest")
        notes.append("No usable latest financial statement data was available.")

    if prior_year is None:
        missing_fields.append("financial_trend.prior_year")
        notes.append("No usable prior-year financial statement data was available.")

    if latest is None and prior_year is None:
        return FinancialTrendSnapshot(notes=notes) if notes else None

    notes.append(
        "financial_trend.latest is derived from last fiscal year because quarterly data unavailable."
    )
    return FinancialTrendSnapshot(
        latest=latest,
        prior_year=prior_year,
        revenue_growth_direction=_direction(
            latest.revenue_growth_yoy if latest else None,
            prior_year.revenue_growth_yoy if prior_year else None,
        ),
        margin_direction=_direction(
            _first_metric(latest, ("operating_margin", "net_margin", "gross_margin")),
            _first_metric(prior_year, ("operating_margin", "net_margin", "gross_margin")),
        ),
        fcf_direction=_direction(
            _first_metric(latest, ("free_cash_flow_margin", "free_cash_flow")),
            _first_metric(prior_year, ("free_cash_flow_margin", "free_cash_flow")),
        ),
        leverage_direction=_inverse_direction(
            _first_metric(latest, ("net_debt_to_ebitda", "net_debt")),
            _first_metric(prior_year, ("net_debt_to_ebitda", "net_debt")),
        ),
        notes=notes,
    )


def _build_financial_snapshot(
    *,
    info: dict[str, Any],
    financials: pd.DataFrame | None,
    cashflow: pd.DataFrame | None,
    balance_sheet: pd.DataFrame | None,
    column_offset: int,
) -> FinancialSnapshot | None:
    use_info = column_offset == 0

    revenue = _coalesce(
        _get_statement_value(
            financials,
            ["Total Revenue", "Operating Revenue", "Revenue"],
            column_offset,
        ),
        _to_float(info.get("totalRevenue")) if use_info else None,
    )
    prior_revenue = _get_statement_value(
        financials,
        ["Total Revenue", "Operating Revenue", "Revenue"],
        column_offset + 1,
    )
    revenue_growth_yoy = _safe_margin(
        revenue - prior_revenue
        if revenue is not None and prior_revenue is not None
        else None,
        prior_revenue,
    )
    if revenue_growth_yoy is None and use_info:
        revenue_growth_yoy = _to_float(info.get("revenueGrowth"))

    gross_profit = _get_statement_value(financials, ["Gross Profit"], column_offset)
    operating_income = _get_statement_value(
        financials,
        ["Operating Income", "Operating Income Or Loss"],
        column_offset,
    )
    ebitda = _coalesce(
        _get_statement_value(
            financials,
            ["EBITDA", "Normalized EBITDA", "Ebitda"],
            column_offset,
        ),
        _to_float(info.get("ebitda")) if use_info else None,
    )
    net_income = _get_statement_value(
        financials,
        ["Net Income", "Net Income Common Stockholders"],
        column_offset,
    )

    free_cash_flow = _coalesce(
        _get_statement_value(cashflow, ["Free Cash Flow"], column_offset),
        _to_float(info.get("freeCashflow")) if use_info else None,
    )
    if free_cash_flow is None:
        operating_cash_flow = _get_statement_value(
            cashflow,
            ["Operating Cash Flow", "Total Cash From Operating Activities"],
            column_offset,
        )
        capex_for_fcf = _get_statement_value(
            cashflow,
            ["Capital Expenditure", "Capital Expenditures"],
            column_offset,
        )
        if operating_cash_flow is not None and capex_for_fcf is not None:
            free_cash_flow = operating_cash_flow + capex_for_fcf

    total_debt = _coalesce(
        _get_statement_value(
            balance_sheet,
            [
                "Total Debt",
                "Long Term Debt And Finance Lease Obligation",
                "Long Term Debt",
            ],
            column_offset,
        ),
        _to_float(info.get("totalDebt")) if use_info else None,
    )
    cash_and_equivalents = _coalesce(
        _get_statement_value(
            balance_sheet,
            [
                "Cash And Cash Equivalents",
                "Cash Cash Equivalents And Short Term Investments",
                "Cash Financial",
            ],
            column_offset,
        ),
        _to_float(info.get("totalCash")) if use_info else None,
    )
    net_debt = (
        total_debt - cash_and_equivalents
        if total_debt is not None and cash_and_equivalents is not None
        else None
    )

    capex = _get_statement_value(
        cashflow,
        ["Capital Expenditure", "Capital Expenditures", "Capital Expenditure Reported"],
        column_offset,
    )

    snapshot = FinancialSnapshot(
        revenue=revenue,
        revenue_growth_yoy=revenue_growth_yoy,
        gross_margin=_safe_margin(gross_profit, revenue),
        operating_margin=_safe_margin(operating_income, revenue),
        ebitda_margin=_safe_margin(ebitda, revenue),
        net_margin=_safe_margin(net_income, revenue),
        free_cash_flow=free_cash_flow,
        free_cash_flow_margin=_safe_margin(free_cash_flow, revenue),
        total_debt=total_debt,
        cash_and_equivalents=cash_and_equivalents,
        net_debt=net_debt,
        net_debt_to_ebitda=_safe_margin(net_debt, ebitda),
        capex=capex,
        capex_as_pct_revenue=_safe_margin(abs(capex), revenue)
        if capex is not None
        else None,
        return_on_invested_capital=None,
    )

    return snapshot if _snapshot_has_data(snapshot) else None


def _build_financial_period_snapshot(
    *,
    period_type: FinancialPeriodType,
    fiscal_period: str | None,
    period_end_date: date | None,
    source: str,
    financials: pd.DataFrame | None,
    cashflow: pd.DataFrame | None,
    balance_sheet: pd.DataFrame | None,
    column: Any,
) -> FinancialPeriodSnapshot:
    revenue = _get_statement_value_at_column(
        financials,
        ["Total Revenue", "Operating Revenue", "Revenue"],
        column,
    )
    gross_profit = _get_statement_value_at_column(
        financials,
        ["Gross Profit"],
        column,
    )
    operating_income = _get_statement_value_at_column(
        financials,
        ["Operating Income", "Operating Income Or Loss"],
        column,
    )
    ebitda = _get_statement_value_at_column(
        financials,
        ["EBITDA", "Normalized EBITDA", "Ebitda"],
        column,
    )
    net_income = _get_statement_value_at_column(
        financials,
        ["Net Income", "Net Income Common Stockholders"],
        column,
    )
    operating_cash_flow = _get_statement_value_at_column(
        cashflow,
        ["Operating Cash Flow", "Total Cash From Operating Activities"],
        column,
    )
    capex = _normalize_capex(
        _get_statement_value_at_column(
            cashflow,
            [
                "Capital Expenditure",
                "Capital Expenditures",
                "Capital Expenditure Reported",
            ],
            column,
        )
    )
    free_cash_flow = _compute_fcf(operating_cash_flow, capex)
    total_debt = _get_statement_value_at_column(
        balance_sheet,
        [
            "Total Debt",
            "Short Long Term Debt Total",
            "Long Term Debt And Finance Lease Obligation",
            "Long Term Debt",
            "Short Term Debt",
        ],
        column,
    )
    cash_and_equivalents = _get_statement_value_at_column(
        balance_sheet,
        [
            "Cash And Cash Equivalents",
            "Cash Cash Equivalents And Short Term Investments",
            "Cash Financial",
        ],
        column,
    )
    net_debt = (
        total_debt - cash_and_equivalents
        if total_debt is not None and cash_and_equivalents is not None
        else None
    )

    return FinancialPeriodSnapshot(
        period_type=period_type,
        fiscal_period=fiscal_period,
        period_end_date=period_end_date,
        filing_date=None,
        source=source,
        revenue=revenue,
        gross_profit=gross_profit,
        gross_margin=_safe_divide(gross_profit, revenue),
        operating_income=operating_income,
        operating_margin=_safe_divide(operating_income, revenue),
        ebitda=ebitda,
        ebitda_margin=_safe_divide(ebitda, revenue),
        net_income=net_income,
        net_margin=_safe_divide(net_income, revenue),
        operating_cash_flow=operating_cash_flow,
        free_cash_flow=free_cash_flow,
        free_cash_flow_margin=_safe_divide(free_cash_flow, revenue),
        capex=capex,
        capex_as_pct_revenue=_safe_divide(abs(capex), revenue)
        if capex is not None
        else None,
        total_debt=total_debt,
        cash_and_equivalents=cash_and_equivalents,
        net_debt=net_debt,
        net_debt_to_ebitda=_safe_divide(net_debt, ebitda),
        return_on_invested_capital=None,
    )


def _aggregate_periods(
    periods: list[FinancialPeriodSnapshot],
    *,
    period_type: FinancialPeriodType,
    fiscal_period: str,
    source: str,
) -> FinancialPeriodSnapshot | None:
    clean = [period for period in periods if _period_snapshot_has_data(period)]
    if not clean:
        return None

    revenue = _sum_or_none([period.revenue for period in clean])
    gross_profit = _sum_or_none([period.gross_profit for period in clean])
    operating_income = _sum_or_none([period.operating_income for period in clean])
    ebitda = _sum_or_none([period.ebitda for period in clean])
    net_income = _sum_or_none([period.net_income for period in clean])
    operating_cash_flow = _sum_or_none([period.operating_cash_flow for period in clean])
    free_cash_flow = _sum_or_none([period.free_cash_flow for period in clean])
    capex = _sum_or_none([period.capex for period in clean])
    latest_balance = clean[0]
    net_debt = latest_balance.net_debt

    return FinancialPeriodSnapshot(
        period_type=period_type,
        fiscal_period=fiscal_period,
        period_end_date=clean[0].period_end_date,
        filing_date=clean[0].filing_date,
        source=source,
        revenue=revenue,
        gross_profit=gross_profit,
        gross_margin=_safe_divide(gross_profit, revenue),
        operating_income=operating_income,
        operating_margin=_safe_divide(operating_income, revenue),
        ebitda=ebitda,
        ebitda_margin=_safe_divide(ebitda, revenue),
        net_income=net_income,
        net_margin=_safe_divide(net_income, revenue),
        operating_cash_flow=operating_cash_flow,
        free_cash_flow=free_cash_flow,
        free_cash_flow_margin=_safe_divide(free_cash_flow, revenue),
        capex=capex,
        capex_as_pct_revenue=_safe_divide(abs(capex), revenue)
        if capex is not None
        else None,
        total_debt=latest_balance.total_debt,
        cash_and_equivalents=latest_balance.cash_and_equivalents,
        net_debt=net_debt,
        net_debt_to_ebitda=_safe_divide(net_debt, ebitda),
        return_on_invested_capital=None,
    )


def _financial_snapshot_from_period(
    period: FinancialPeriodSnapshot | None,
) -> FinancialSnapshot | None:
    if period is None or not _period_snapshot_has_data(period):
        return None
    return FinancialSnapshot(
        revenue=period.revenue,
        revenue_growth_yoy=period.revenue_growth_yoy,
        gross_margin=period.gross_margin,
        operating_margin=period.operating_margin,
        ebitda_margin=period.ebitda_margin,
        net_margin=period.net_margin,
        free_cash_flow=period.free_cash_flow,
        free_cash_flow_margin=period.free_cash_flow_margin,
        total_debt=period.total_debt,
        cash_and_equivalents=period.cash_and_equivalents,
        net_debt=period.net_debt,
        net_debt_to_ebitda=period.net_debt_to_ebitda,
        capex=period.capex,
        capex_as_pct_revenue=period.capex_as_pct_revenue,
        return_on_invested_capital=period.return_on_invested_capital,
    )


def _latest_quarter_vs_ltm_notes(
    latest_quarter: FinancialPeriodSnapshot | None,
    trailing_four: FinancialPeriodSnapshot | None,
) -> list[str]:
    notes: list[str] = []
    if latest_quarter is None or trailing_four is None:
        return notes
    if (
        latest_quarter.revenue is not None
        and trailing_four.revenue is not None
        and trailing_four.revenue > 0
    ):
        annualized = latest_quarter.revenue * 4
        spread = (annualized - trailing_four.revenue) / trailing_four.revenue
        notes.append(
            f"Latest quarter annualized revenue is {spread:+.1%} versus trailing four-quarter revenue."
        )
    if (
        latest_quarter.gross_margin is not None
        and trailing_four.gross_margin is not None
    ):
        notes.append(
            "Latest quarter gross margin is "
            f"{latest_quarter.gross_margin:.1%} versus "
            f"{trailing_four.gross_margin:.1%} LTM."
        )
    if (
        latest_quarter.operating_margin is not None
        and trailing_four.operating_margin is not None
    ):
        notes.append(
            "Latest quarter operating margin is "
            f"{latest_quarter.operating_margin:.1%} versus "
            f"{trailing_four.operating_margin:.1%} LTM."
        )
    return notes


def _build_inflection_flags(
    *,
    latest_quarter: FinancialPeriodSnapshot | None,
    prior_quarter: FinancialPeriodSnapshot | None,
    trailing_four: FinancialPeriodSnapshot | None,
    stale: bool,
) -> list[str]:
    flags: list[str] = []
    if latest_quarter is None:
        return ["financial_data_stale"] if stale else flags

    if latest_quarter.revenue_growth_yoy is not None and latest_quarter.revenue_growth_yoy > 0:
        flags.append("latest_quarter_revenue_accelerating_yoy")
    if _metric_spread(latest_quarter.gross_margin, trailing_four.gross_margin if trailing_four else None) > 0.05:
        flags.append("latest_quarter_gross_margin_above_ltm")
    if _metric_spread(latest_quarter.operating_margin, trailing_four.operating_margin if trailing_four else None) > 0.05:
        flags.append("latest_quarter_operating_margin_above_ltm")
    if _metric_spread(latest_quarter.free_cash_flow_margin, trailing_four.free_cash_flow_margin if trailing_four else None) > 0.05:
        flags.append("latest_quarter_fcf_margin_above_ltm")
    if (
        latest_quarter.revenue is not None
        and trailing_four is not None
        and trailing_four.revenue is not None
        and trailing_four.revenue > 0
        and (latest_quarter.revenue * 4) / trailing_four.revenue > 1.25
    ):
        flags.append("latest_quarter_revenue_run_rate_above_ltm")
    if _metric_spread(latest_quarter.gross_margin, prior_quarter.gross_margin if prior_quarter else None) > 0:
        flags.append("gross_margin_expanding_sequentially")
    if _metric_spread(latest_quarter.operating_margin, prior_quarter.operating_margin if prior_quarter else None) > 0:
        flags.append("operating_margin_expanding_sequentially")
    if (
        latest_quarter.ebitda_margin is not None
        and latest_quarter.free_cash_flow_margin is not None
        and latest_quarter.ebitda_margin - latest_quarter.free_cash_flow_margin > 0.15
    ):
        flags.append("fcf_conversion_lagging_ebitda")
    if latest_quarter.capex_as_pct_revenue is not None and latest_quarter.capex_as_pct_revenue > 0.20:
        flags.append("capex_intensity_elevated")
    if (
        prior_quarter is not None
        and latest_quarter.net_debt_to_ebitda is not None
        and prior_quarter.net_debt_to_ebitda is not None
        and latest_quarter.net_debt_to_ebitda < prior_quarter.net_debt_to_ebitda
    ):
        flags.append("leverage_improving")
    if stale:
        flags.append("financial_data_stale")
    return _dedupe_preserve_order(flags)


def _build_price_snapshot(
    ticker: str,
    yf_ticker: Any,
    info: dict[str, Any],
    missing_fields: list[str],
    source_notes: list[str],
) -> PriceSnapshot:
    current_price = _coalesce(
        _to_float(info.get("currentPrice")),
        _to_float(info.get("regularMarketPrice")),
    )
    market_cap = _to_float(info.get("marketCap"))
    beta = _to_float(info.get("beta"))

    close = pd.Series(dtype="float64")
    if yf_ticker is not None:
        try:
            history = yf_ticker.history(period="1y", auto_adjust=True)
            if isinstance(history, pd.DataFrame) and not history.empty and "Close" in history:
                close = history["Close"].dropna()
        except Exception as exc:
            missing_fields.append("price_history")
            source_notes.append(f"yfinance price history fetch failed: {exc}")

    if close.empty:
        missing_fields.append("price_history")
        source_notes.append(f"No usable one-year price history returned for {ticker}.")
    elif current_price is None:
        current_price = _to_float(close.iloc[-1])

    current_for_ranges = current_price if current_price is not None else None
    if current_for_ranges is None and not close.empty:
        current_for_ranges = _to_float(close.iloc[-1])

    high_52w = _to_float(close.max()) if not close.empty else None
    low_52w = _to_float(close.min()) if not close.empty else None

    return PriceSnapshot(
        current_price=current_price,
        market_cap=market_cap,
        return_1m=_period_return(close, 21),
        return_3m=_period_return(close, 63),
        return_6m=_period_return(close, 126),
        return_1y=_period_return(close, 252),
        drawdown_from_52w_high=_safe_margin(
            current_for_ranges - high_52w
            if current_for_ranges is not None and high_52w is not None
            else None,
            high_52w,
        ),
        distance_from_52w_low=_safe_margin(
            current_for_ranges - low_52w
            if current_for_ranges is not None and low_52w is not None
            else None,
            low_52w,
        ),
        beta=beta,
    )


def _build_valuation_snapshot(
    info: dict[str, Any],
    missing_fields: list[str],
) -> ValuationSnapshot:
    snapshot = ValuationSnapshot(
        trailing_pe=_to_float(info.get("trailingPE")),
        forward_pe=_to_float(info.get("forwardPE")),
        ev_to_ebitda=_to_float(info.get("enterpriseToEbitda")),
        price_to_sales=_to_float(info.get("priceToSalesTrailing12Months")),
        price_to_book=_to_float(info.get("priceToBook")),
    )

    notes: list[str] = []
    if snapshot.trailing_pe is None and snapshot.forward_pe is None:
        missing_fields.append("valuation.pe")
        notes.append("Trailing and forward P/E were unavailable.")
    if snapshot.ev_to_ebitda is None:
        missing_fields.append("valuation.ev_to_ebitda")
    if snapshot.price_to_sales is None:
        missing_fields.append("valuation.price_to_sales")

    return snapshot.model_copy(update={"valuation_notes": notes})


def _build_peer_relative_snapshot(
    ticker: str,
    peer_tickers: list[str] | None,
    info: dict[str, Any],
    price_snapshot: PriceSnapshot,
    valuation_snapshot: ValuationSnapshot,
    missing_fields: list[str],
) -> PeerRelativeSnapshot | None:
    peers = [
        peer.upper().strip()
        for peer in (peer_tickers or [])
        if peer and peer.upper().strip() != ticker
    ]
    if not peers:
        return None

    notes: list[str] = []
    relative_return_3m = None
    relative_return_6m = None

    try:
        downloaded = yf.download(
            [ticker] + peers,
            period="6mo",
            auto_adjust=True,
            progress=False,
            threads=False,
        )
        close = _extract_close_frame(downloaded, ticker)
        if close is None or close.empty or ticker not in close:
            missing_fields.append("peer_relative.price_history")
            notes.append("Peer-relative price history was unavailable.")
        else:
            target_3m = _period_return(close[ticker].dropna(), 63)
            target_6m = _period_return(close[ticker].dropna(), 126)
            peer_returns_3m = [
                _period_return(close[peer].dropna(), 63)
                for peer in peers
                if peer in close
            ]
            peer_returns_6m = [
                _period_return(close[peer].dropna(), 126)
                for peer in peers
                if peer in close
            ]
            relative_return_3m = _relative_return_text(
                target_3m, _median_or_none(peer_returns_3m)
            )
            relative_return_6m = _relative_return_text(
                target_6m, _median_or_none(peer_returns_6m)
            )
    except Exception as exc:
        missing_fields.append("peer_relative.price_history")
        notes.append(f"Peer-relative price download failed: {exc}")

    peer_infos = _fetch_peer_infos(peers, notes)
    relative_valuation = _relative_metric_text(
        _coalesce(valuation_snapshot.forward_pe, valuation_snapshot.trailing_pe),
        _median_or_none(
            [
                _coalesce(_to_float(peer.get("forwardPE")), _to_float(peer.get("trailingPE")))
                for peer in peer_infos
            ]
        ),
        label="valuation multiple",
        lower_is_better=True,
    )
    relative_margin_profile = _relative_metric_text(
        _coalesce(_to_float(info.get("operatingMargins")), _to_float(info.get("profitMargins"))),
        _median_or_none(
            [
                _coalesce(
                    _to_float(peer.get("operatingMargins")),
                    _to_float(peer.get("profitMargins")),
                )
                for peer in peer_infos
            ]
        ),
        label="margin profile",
        lower_is_better=False,
    )
    relative_growth_profile = _relative_metric_text(
        _to_float(info.get("revenueGrowth")),
        _median_or_none([_to_float(peer.get("revenueGrowth")) for peer in peer_infos]),
        label="revenue growth",
        lower_is_better=False,
    )

    if peer_infos and relative_valuation is None:
        missing_fields.append("peer_relative.valuation")
    if peer_infos and relative_margin_profile is None:
        missing_fields.append("peer_relative.margin_profile")
    if peer_infos and relative_growth_profile is None:
        missing_fields.append("peer_relative.growth_profile")

    return PeerRelativeSnapshot(
        peer_tickers=peers,
        relative_return_3m=relative_return_3m,
        relative_return_6m=relative_return_6m,
        relative_valuation=relative_valuation,
        relative_margin_profile=relative_margin_profile,
        relative_growth_profile=relative_growth_profile,
        notes=notes,
    )


def _get_statement_value(
    statement: pd.DataFrame | None,
    labels: list[str],
    column_offset: int = 0,
) -> float | None:
    if statement is None or statement.empty or column_offset >= len(statement.columns):
        return None

    normalized_index = {
        _normalize_label(str(label)): label for label in statement.index
    }
    column = statement.columns[column_offset]

    for label in labels:
        actual_label = normalized_index.get(_normalize_label(label))
        if actual_label is None:
            continue
        value = statement.loc[actual_label, column]
        if isinstance(value, pd.Series):
            for item in value:
                parsed = _to_float(item)
                if parsed is not None:
                    return parsed
            return None
        return _to_float(value)

    return None


def _get_statement_value_at_column(
    statement: pd.DataFrame | None,
    labels: list[str],
    column: Any,
) -> float | None:
    if statement is None or statement.empty:
        return None

    actual_column = _find_matching_column(statement, column)
    if actual_column is None:
        return None

    normalized_index = {
        _normalize_label(str(label)): label for label in statement.index
    }
    for label in labels:
        actual_label = normalized_index.get(_normalize_label(label))
        if actual_label is None:
            continue
        value = statement.loc[actual_label, actual_column]
        if isinstance(value, pd.Series):
            for item in value:
                parsed = _to_float(item)
                if parsed is not None:
                    return parsed
            return None
        return _to_float(value)
    return None


def _find_matching_column(statement: pd.DataFrame, requested_column: Any) -> Any | None:
    requested_date = _column_to_date(requested_column)
    for column in statement.columns:
        if column == requested_column:
            return column
        if requested_date is not None and _column_to_date(column) == requested_date:
            return column
    return None


def _statement_columns_desc(*statements: pd.DataFrame | None) -> list[Any]:
    columns_by_date: dict[date, Any] = {}
    undated: list[Any] = []
    for statement in statements:
        if statement is None or statement.empty:
            continue
        for column in statement.columns:
            column_date = _column_to_date(column)
            if column_date is None:
                undated.append(column)
                continue
            columns_by_date.setdefault(column_date, column)
    dated = [
        columns_by_date[column_date]
        for column_date in sorted(columns_by_date.keys(), reverse=True)
    ]
    return dated + undated


def _column_to_date(column: Any) -> date | None:
    if isinstance(column, pd.Timestamp):
        return column.date()
    if isinstance(column, datetime):
        return column.date()
    if isinstance(column, date):
        return column
    try:
        parsed = pd.to_datetime(column, errors="coerce")
    except Exception:
        return None
    if pd.isna(parsed):
        return None
    if isinstance(parsed, pd.Timestamp):
        return parsed.date()
    return None


def _safe_margin(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def _safe_divide(numerator: float | None, denominator: float | None) -> float | None:
    return _safe_margin(numerator, denominator)


def _safe_growth(latest: float | None, prior: float | None) -> float | None:
    if latest is None or prior is None or prior == 0:
        return None
    return (latest - prior) / abs(prior)


def _normalize_capex(value: float | None) -> float | None:
    if value is None:
        return None
    return -abs(value)


def _compute_fcf(
    operating_cash_flow: float | None,
    capex: float | None,
) -> float | None:
    if operating_cash_flow is None:
        return None
    if capex is None:
        return None
    return operating_cash_flow + capex if capex < 0 else operating_cash_flow - abs(capex)


def _period_return(close: pd.Series, trading_days: int) -> float | None:
    if close.empty:
        return None
    current = _to_float(close.iloc[-1])
    if current is None:
        return None
    base_index = -trading_days - 1 if len(close) > trading_days else 0
    base = _to_float(close.iloc[base_index])
    if base is None or base == 0:
        return None
    return (current - base) / base


def _direction(
    latest: float | None,
    prior: float | None,
    *,
    stable_threshold: float = 0.01,
) -> str:
    if latest is None or prior is None:
        return "unknown"
    delta = latest - prior
    if abs(delta) <= stable_threshold:
        return "stable"
    return "improving" if delta > 0 else "deteriorating"


def _inverse_direction(
    latest: float | None,
    prior: float | None,
    *,
    stable_threshold: float = 0.05,
) -> str:
    if latest is None or prior is None:
        return "unknown"
    delta = latest - prior
    if abs(delta) <= stable_threshold:
        return "stable"
    return "improving" if delta < 0 else "deteriorating"


def _revenue_growth_direction_from_quarterly(
    trend: QuarterlyFinancialTrendPack,
) -> str:
    latest_q = trend.latest_quarter.revenue_growth_yoy if trend.latest_quarter else None
    ltm = (
        trend.trailing_four_quarters.revenue_growth_yoy
        if trend.trailing_four_quarters
        else None
    )
    if latest_q is not None and ltm is not None:
        return _direction(latest_q, ltm, stable_threshold=0.02)
    if latest_q is not None:
        if latest_q > 0.02:
            return "improving"
        if latest_q < -0.02:
            return "deteriorating"
        return "stable"
    return trend.revenue_trend_8q or "unknown"


def _quarterly_metric_direction(
    latest_quarter: FinancialPeriodSnapshot | None,
    prior_quarter: FinancialPeriodSnapshot | None,
    year_ago_quarter: FinancialPeriodSnapshot | None,
    metric: str,
) -> str:
    latest = getattr(latest_quarter, metric) if latest_quarter else None
    prior = getattr(prior_quarter, metric) if prior_quarter else None
    year_ago = getattr(year_ago_quarter, metric) if year_ago_quarter else None
    if latest is not None and year_ago is not None:
        return _direction(latest, year_ago)
    if latest is not None and prior is not None:
        return _direction(latest, prior)
    return "unknown"


def _inverse_quarterly_metric_direction(
    latest_quarter: FinancialPeriodSnapshot | None,
    prior_quarter: FinancialPeriodSnapshot | None,
    year_ago_quarter: FinancialPeriodSnapshot | None,
    metric: str,
) -> str:
    latest = getattr(latest_quarter, metric) if latest_quarter else None
    prior = getattr(prior_quarter, metric) if prior_quarter else None
    year_ago = getattr(year_ago_quarter, metric) if year_ago_quarter else None
    if latest is not None and year_ago is not None:
        return _inverse_direction(latest, year_ago)
    if latest is not None and prior is not None:
        return _inverse_direction(latest, prior)
    return "unknown"


def _series_trend(values: list[float | None]) -> str:
    cleaned = [value for value in values if value is not None]
    if len(cleaned) < 2:
        return "unknown"
    latest_avg = sum(cleaned[: min(3, len(cleaned))]) / min(3, len(cleaned))
    prior_avg = sum(cleaned[-min(3, len(cleaned)):]) / min(3, len(cleaned))
    return _direction(latest_avg, prior_avg)


def _inverse_series_trend(values: list[float | None]) -> str:
    cleaned = [value for value in values if value is not None]
    if len(cleaned) < 2:
        return "unknown"
    latest_avg = sum(cleaned[: min(3, len(cleaned))]) / min(3, len(cleaned))
    prior_avg = sum(cleaned[-min(3, len(cleaned)):]) / min(3, len(cleaned))
    return _inverse_direction(latest_avg, prior_avg)


def _metric_spread(latest: float | None, prior: float | None) -> float:
    if latest is None or prior is None:
        return 0.0
    return latest - prior


def _sum_or_none(values: list[float | None]) -> float | None:
    cleaned = [value for value in values if value is not None]
    return sum(cleaned) if cleaned else None


def _period_snapshot_has_data(snapshot: FinancialPeriodSnapshot | None) -> bool:
    if snapshot is None:
        return False
    ignored = {"period_type", "fiscal_period", "period_end_date", "filing_date", "source"}
    return any(
        value is not None
        for key, value in snapshot.model_dump().items()
        if key not in ignored
    )


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, pd.Series):
        for item in value:
            parsed = _to_float(item)
            if parsed is not None:
                return parsed
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(parsed):
        return None
    return parsed


def _determine_context_confidence(
    *,
    financial_trend: FinancialTrendSnapshot | None,
    quarterly_financial_trend: QuarterlyFinancialTrendPack | None,
    price_snapshot: PriceSnapshot | None,
    valuation_snapshot: ValuationSnapshot | None,
    peer_relative_snapshot: PeerRelativeSnapshot | None,
) -> DataConfidence:
    populated = 0

    latest = financial_trend.latest if financial_trend else None
    if latest:
        populated += sum(
            value is not None
            for value in (
                latest.revenue,
                latest.revenue_growth_yoy,
                latest.operating_margin,
                latest.free_cash_flow,
                latest.net_debt_to_ebitda,
            )
        )

    if quarterly_financial_trend and quarterly_financial_trend.latest_quarter:
        latest_q = quarterly_financial_trend.latest_quarter
        populated += sum(
            value is not None
            for value in (
                latest_q.revenue,
                latest_q.revenue_growth_yoy,
                latest_q.operating_margin,
                latest_q.free_cash_flow,
                latest_q.net_debt_to_ebitda,
            )
        )
        if quarterly_financial_trend.trailing_four_quarters is not None:
            populated += 2
        if len(quarterly_financial_trend.trailing_eight_quarters) >= 6:
            populated += 2

    if price_snapshot:
        populated += sum(
            value is not None
            for value in (
                price_snapshot.current_price,
                price_snapshot.market_cap,
                price_snapshot.return_3m,
                price_snapshot.return_6m,
            )
        )

    if valuation_snapshot:
        populated += sum(
            value is not None
            for value in (
                valuation_snapshot.trailing_pe,
                valuation_snapshot.forward_pe,
                valuation_snapshot.ev_to_ebitda,
                valuation_snapshot.price_to_sales,
            )
        )

    if peer_relative_snapshot:
        populated += sum(
            value is not None
            for value in (
                peer_relative_snapshot.relative_return_6m,
                peer_relative_snapshot.relative_valuation,
                peer_relative_snapshot.relative_margin_profile,
            )
        )

    if (
        populated >= 12
        and latest
        and price_snapshot
        and valuation_snapshot
        and quarterly_financial_trend
        and quarterly_financial_trend.latest_quarter
    ):
        return DataConfidence.HIGH
    if populated >= 5:
        return DataConfidence.MEDIUM
    return DataConfidence.LOW


def _extract_close_frame(downloaded: pd.DataFrame, ticker: str) -> pd.DataFrame | None:
    if not isinstance(downloaded, pd.DataFrame) or downloaded.empty:
        return None
    if isinstance(downloaded.columns, pd.MultiIndex):
        if "Close" in downloaded.columns.get_level_values(0):
            return downloaded["Close"].dropna(how="all")
        if "Close" in downloaded.columns.get_level_values(1):
            return downloaded.xs("Close", axis=1, level=1).dropna(how="all")
        return None
    if "Close" in downloaded:
        close = downloaded["Close"]
        if isinstance(close, pd.Series):
            return close.to_frame(name=ticker)
        return close.dropna(how="all")
    return downloaded.dropna(how="all")


def _fetch_peer_infos(peers: list[str], notes: list[str]) -> list[dict[str, Any]]:
    peer_infos: list[dict[str, Any]] = []
    for peer in peers:
        try:
            info = yf.Ticker(peer).info
        except Exception as exc:
            notes.append(f"Peer info fetch failed for {peer}: {exc}")
            continue
        if isinstance(info, dict) and info:
            peer_infos.append(info)
    return peer_infos


def _relative_return_text(target: float | None, peer_median: float | None) -> str | None:
    if target is None or peer_median is None:
        return None
    spread = target - peer_median
    direction = "outperforming" if spread > 0 else "underperforming"
    if abs(spread) < 0.01:
        direction = "in line with"
    return f"{direction} peer median by {spread:+.1%}"


def _relative_metric_text(
    target: float | None,
    peer_median: float | None,
    *,
    label: str,
    lower_is_better: bool,
) -> str | None:
    if target is None or peer_median is None:
        return None
    spread = target - peer_median
    if abs(spread) < 0.01:
        return f"{label} roughly in line with peer median"
    if lower_is_better:
        profile = "cheaper" if spread < 0 else "more expensive"
    else:
        profile = "above peers" if spread > 0 else "below peers"
    return f"{label} {profile} versus peer median ({target:.2f} vs {peer_median:.2f})"


def _median_or_none(values: Iterable[float | None]) -> float | None:
    cleaned = [value for value in values if value is not None]
    if not cleaned:
        return None
    return _to_float(pd.Series(cleaned).median())


def _first_metric(snapshot: FinancialSnapshot | None, names: tuple[str, ...]) -> float | None:
    if snapshot is None:
        return None
    for name in names:
        value = getattr(snapshot, name)
        if value is not None:
            return value
    return None


def _snapshot_has_data(snapshot: FinancialSnapshot) -> bool:
    return any(value is not None for value in snapshot.model_dump().values())


def _coalesce(*values: float | None) -> float | None:
    for value in values:
        if value is not None:
            return value
    return None


def _normalize_label(value: str) -> str:
    return "".join(char.lower() for char in value if char.isalnum())


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value not in seen:
            deduped.append(value)
            seen.add(value)
    return deduped
