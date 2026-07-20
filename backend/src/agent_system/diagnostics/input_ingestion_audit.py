"""Input ingestion and provenance audit for the Helix Macro Forecast Engine."""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from src.agent_system.diagnostics.input_matrix import (
    EXPECTED_INPUT_SPECS,
    InputSpec,
    _candidate_signal_ids,
    _contribution_diagnostics,
    _has_value,
    _historical_column_diagnostics,
    _historical_similarity_inputs,
    _load_historical_df,
    _matching_signals,
    _safe_float,
    _stringify,
    _write_minimal_xlsx,
    resolve_current_input_value,
)
from src.agent_system.forecasting.input_signals import build_forecast_input_set
from src.agent_system.forecasting.macro_forecast_runner import (
    DEFAULT_SCENARIO_PRIORS,
    MacroForecastRunConfig,
    _load_market_state_for_cli,
    _load_regime_for_cli,
    _load_regime_inputs_for_cli,
)
from src.agent_system.forecasting.scenario_probability_engine import update_scenario_probabilities
from src.agent_system.schemas.macro_forecast import ForecastInputSet, MacroInputSignal


DEFAULT_OUTPUT_DIR = "data/agent_system/diagnostics"
CBOE_PUT_CALL_URL = "https://www.cboe.com/markets/us/options/market-statistics/daily/"

HORIZON_LOOKBACK_LABELS = {
    "1m": "1M / 21 trading days",
    "3m": "3M / 63 trading days",
    "6m": "6M / 126 trading days",
    "1y": "1Y / 252 trading days",
}

INPUT_CALCULATION_METHODS: dict[str, str] = {
    "net_liquidity": "WALCL minus Treasury General Account minus reverse repo balances.",
    "net_liquidity_z": "Net liquidity level normalized as a z-score over the regime-data lookback window.",
    "nfci": "Chicago Fed National Financial Conditions Index latest value.",
    "nfci_inverted": "Negative NFCI transformed so easier financial conditions are positive.",
    "m2_growth_yoy": "M2 money stock year-over-year percent change.",
    "fci_z": "Financial conditions index transformed to a z-score.",
    "hy_spread_level": "High-yield option-adjusted spread latest value in basis points.",
    "hy_spread_z": "High-yield spread minus trailing mean divided by trailing standard deviation.",
    "hy_spread_chg_4w": "Current high-yield OAS minus high-yield OAS four weeks prior.",
    "ig_spread_level": "Investment-grade option-adjusted spread latest value in basis points.",
    "ig_spread_z": "Investment-grade spread minus trailing mean divided by trailing standard deviation.",
    "hyg_tlt_ratio_z": "HYG/TLT relative performance normalized as a z-score.",
    "vix_level": "Latest VIX close.",
    "vix_z_20d": "Current VIX minus 20D mean divided by 20D standard deviation.",
    "vix_term_slope": "VIX3M minus VIX.",
    "vvix_level": "Latest VVIX close.",
    "vvix_z": "VVIX minus trailing mean divided by trailing standard deviation.",
    "put_call_ratio": "Generic internal put/call ratio; source must be disambiguated before labeling equity, total, index, or ETP.",
    "put_call_ratio_internal": "Internal generic put/call ratio copied from the available regime input field.",
    "put_call_5d_ma": "Five-day moving average of the available put/call series if separately ingested.",
    "cboe_equity_put_call_ratio": "Cboe equity put/call ratio from Daily Market Statistics.",
    "cboe_total_put_call_ratio": "Cboe total put/call ratio from Daily Market Statistics.",
    "cboe_index_put_call_ratio": "Cboe index put/call ratio from Daily Market Statistics.",
    "cboe_etp_put_call_ratio": "Cboe ETP put/call ratio from Daily Market Statistics.",
    "skew_index": "Latest Cboe SKEW index close.",
    "pct_above_200d": "Percent of tracked universe trading above the 200-day moving average.",
    "new_highs_minus_lows_z": "New highs minus new lows normalized as a z-score.",
    "sectors_green": "Count of sectors with positive return over the selected market-state horizon.",
    "rsp_vs_spy_z": "RSP/SPY relative performance normalized as a z-score.",
    "adl_slope": "Advance/decline line slope.",
    "dealer_gamma_z": "Dealer gamma estimate normalized as a z-score.",
    "aaii_bull_minus_bear": "AAII bulls minus bears survey spread.",
    "cot_net_large_spec_z": "CFTC large speculator net positioning normalized as a z-score.",
    "equity_etf_flow_z": "Equity ETF flow normalized as a z-score.",
    "rsp_minus_spy": "RSP return over selected horizon minus SPY return over selected horizon.",
    "hyg_minus_tlt": "HYG return over selected horizon minus TLT return over selected horizon.",
    "qqq_minus_spy": "QQQ return over selected horizon minus SPY return over selected horizon.",
    "iwm_minus_spy": "IWM return over selected horizon minus SPY return over selected horizon.",
    "spy_return": "SPY return over the selected market-state horizon.",
    "qqq_return": "QQQ return over the selected market-state horizon.",
    "iwm_return": "IWM return over the selected market-state horizon.",
    "rsp_return": "RSP return over the selected market-state horizon.",
    "hyg_return": "HYG return over the selected market-state horizon.",
    "tlt_return": "TLT return over the selected market-state horizon.",
    "gld_return": "GLD return over the selected market-state horizon.",
    "uso_return": "USO return over the selected market-state horizon.",
    "btc_return": "BTC return over the selected market-state horizon.",
    "sector_dispersion": "Cross-sectional standard deviation of sector returns.",
    "spy_clv": "SPY close location value inside the daily range.",
    "spy_range_pct": "SPY high-low range divided by close, expressed as a percent.",
    "spy_vol_z_20d": "SPY volume minus 20D mean divided by 20D standard deviation.",
    "volume_confirmation": "Sign of SPY return multiplied by SPY volume z-score.",
    "spy_above_vwap": "Boolean flag indicating whether SPY trades above VWAP.",
    "spy_above_prev_close": "Boolean flag indicating whether SPY trades above previous close.",
    "vix_change_pct_1d": "One-day percent change in VIX.",
    "fed_path_hold_hike_prob": "Probability assigned to a Fed hold or hike path.",
    "fed_path_cut_prob": "One minus the Fed hold/hike path probability when no direct cut probability is provided.",
}

INPUT_LOOKBACK_WINDOWS: dict[str, str] = {
    "net_liquidity_z": "52 weeks",
    "nfci_inverted": "latest weekly reading transformed to inverted stress score",
    "m2_growth_yoy": "12 months",
    "fci_z": "regime-data z-score window",
    "hy_spread_z": "2 years / 504 trading days",
    "hy_spread_chg_4w": "4 weeks",
    "ig_spread_z": "2 years / 504 trading days",
    "hyg_tlt_ratio_z": "252 trading days",
    "vix_z_20d": "20 trading days",
    "vix_term_slope": "current VIX3M - VIX",
    "vvix_z": "252 trading days",
    "put_call_5d_ma": "5 trading days",
    "pct_above_200d": "200 trading days",
    "new_highs_minus_lows_z": "regime-data z-score window",
    "rsp_vs_spy_z": "252 trading days",
    "adl_slope": "regime-data trend window",
    "dealer_gamma_z": "regime-data z-score window",
    "aaii_bull_minus_bear": "weekly survey",
    "cot_net_large_spec_z": "weekly CFTC series",
    "equity_etf_flow_z": "regime-data z-score window",
    "spy_clv": "current day",
    "spy_range_pct": "current day",
    "spy_vol_z_20d": "20 trading days",
    "volume_confirmation": "current day with 20D volume z-score",
    "spy_above_vwap": "current day",
    "spy_above_prev_close": "current day",
    "vix_change_pct_1d": "1 trading day",
}

for _market_id in [
    "spy_return",
    "qqq_return",
    "iwm_return",
    "rsp_return",
    "hyg_return",
    "tlt_return",
    "gld_return",
    "uso_return",
    "btc_return",
    "rsp_minus_spy",
    "hyg_minus_tlt",
    "qqq_minus_spy",
    "iwm_minus_spy",
    "sector_dispersion",
]:
    INPUT_LOOKBACK_WINDOWS.setdefault(_market_id, "selected MarketState horizon")

INPUT_FREQUENCIES: dict[str, str] = {
    "net_liquidity": "weekly",
    "net_liquidity_z": "weekly",
    "nfci": "weekly",
    "nfci_inverted": "weekly",
    "m2_growth_yoy": "monthly",
    "aaii_bull_minus_bear": "weekly",
    "cot_net_large_spec_z": "weekly",
}

for _daily_id in [
    "fci_z",
    "hy_spread_level",
    "hy_spread_z",
    "hy_spread_chg_4w",
    "ig_spread_level",
    "ig_spread_z",
    "hyg_tlt_ratio_z",
    "vix_level",
    "vix_z_20d",
    "vix_term_slope",
    "vvix_level",
    "vvix_z",
    "put_call_ratio",
    "put_call_ratio_internal",
    "put_call_5d_ma",
    "cboe_equity_put_call_ratio",
    "cboe_total_put_call_ratio",
    "cboe_index_put_call_ratio",
    "cboe_etp_put_call_ratio",
    "skew_index",
    "pct_above_200d",
    "new_highs_minus_lows_z",
    "sectors_green",
    "rsp_vs_spy_z",
    "adl_slope",
    "dealer_gamma_z",
    "equity_etf_flow_z",
    "spy_return",
    "qqq_return",
    "iwm_return",
    "rsp_return",
    "hyg_return",
    "tlt_return",
    "gld_return",
    "uso_return",
    "btc_return",
    "hyg_minus_tlt",
    "rsp_minus_spy",
    "iwm_minus_spy",
    "qqq_minus_spy",
    "sector_dispersion",
    "spy_clv",
    "spy_range_pct",
    "spy_vol_z_20d",
    "volume_confirmation",
    "spy_above_vwap",
    "spy_above_prev_close",
    "vix_change_pct_1d",
]:
    INPUT_FREQUENCIES.setdefault(_daily_id, "daily")

INPUT_UNITS: dict[str, str] = {
    "net_liquidity": "billions",
    "m2_growth_yoy": "%",
    "hy_spread_level": "bps",
    "hy_spread_chg_4w": "bps",
    "ig_spread_level": "bps",
    "put_call_ratio": "ratio",
    "put_call_ratio_internal": "ratio",
    "put_call_5d_ma": "ratio",
    "cboe_equity_put_call_ratio": "ratio",
    "cboe_total_put_call_ratio": "ratio",
    "cboe_index_put_call_ratio": "ratio",
    "cboe_etp_put_call_ratio": "ratio",
    "vix_level": "index",
    "vvix_level": "index",
    "skew_index": "index",
    "pct_above_200d": "%",
    "sectors_green": "sectors",
}

for _ret_id in [
    "spy_return",
    "qqq_return",
    "iwm_return",
    "rsp_return",
    "hyg_return",
    "tlt_return",
    "gld_return",
    "uso_return",
    "btc_return",
    "rsp_minus_spy",
    "hyg_minus_tlt",
    "qqq_minus_spy",
    "iwm_minus_spy",
    "vix_change_pct_1d",
    "spy_range_pct",
]:
    INPUT_UNITS.setdefault(_ret_id, "%")

HIGH_PRIORITY_PROVENANCE_INPUTS = [
    "vix_level",
    "vix_term_slope",
    "put_call_ratio",
    "put_call_5d_ma",
    "hy_spread_level",
    "ig_spread_level",
    "rsp_minus_spy",
    "hyg_minus_tlt",
    "pct_above_200d",
    "sectors_green",
    "net_liquidity_z",
    "nfci",
    "fed_path_hold_hike_prob",
    "uso_return",
    "qqq_minus_spy",
    "iwm_minus_spy",
]

HIGH_PRIORITY_STALE_INPUTS = {
    "vix_level",
    "put_call_ratio",
    "put_call_5d_ma",
    "rsp_minus_spy",
    "hyg_minus_tlt",
    "hy_spread_level",
    "sectors_green",
    "spy_return",
    "qqq_return",
    "iwm_return",
}


def _audit_put_call_specs() -> list[InputSpec]:
    base = next(spec for spec in EXPECTED_INPUT_SPECS if spec.input_id == "put_call_ratio")
    return [
        replace(
            base,
            input_id="cboe_equity_put_call_ratio",
            label="Cboe equity put/call ratio",
            possible_source_fields=("cboe_equity_put_call_ratio", "equity_put_call_ratio"),
            historical_column="cboe_equity_put_call_ratio",
            notes="Explicit Cboe equity put/call series. Generic put_call_ratio must not be labeled as this.",
        ),
        replace(
            base,
            input_id="cboe_total_put_call_ratio",
            label="Cboe total put/call ratio",
            possible_source_fields=("cboe_total_put_call_ratio", "total_put_call_ratio"),
            historical_column="cboe_total_put_call_ratio",
            notes="Explicit Cboe total put/call series.",
        ),
        replace(
            base,
            input_id="cboe_index_put_call_ratio",
            label="Cboe index put/call ratio",
            possible_source_fields=("cboe_index_put_call_ratio", "index_put_call_ratio"),
            historical_column="cboe_index_put_call_ratio",
            notes="Explicit Cboe index put/call series.",
        ),
        replace(
            base,
            input_id="cboe_etp_put_call_ratio",
            label="Cboe ETP put/call ratio",
            possible_source_fields=("cboe_etp_put_call_ratio", "etp_put_call_ratio"),
            historical_column="cboe_etp_put_call_ratio",
            notes="Explicit Cboe ETP put/call series.",
        ),
        replace(
            base,
            input_id="put_call_ratio_internal",
            label="Internal generic put/call ratio",
            possible_source_fields=("put_call_ratio",),
            historical_column="put_call_ratio",
            notes="Generic internal field; source identity must be verified before equity/total/index interpretation.",
        ),
    ]


AUDIT_INPUT_SPECS = [*EXPECTED_INPUT_SPECS, *_audit_put_call_specs()]


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return datetime.strptime(text[:10], "%Y-%m-%d").date()
        except ValueError:
            return None


def _date_text(value: Any) -> str | None:
    parsed = _parse_date(value)
    return parsed.isoformat() if parsed is not None else None


def _trading_day_lag(observed: date, asof: date) -> int:
    if observed >= asof:
        return 0
    days = 0
    current = observed
    while current < asof:
        current = date.fromordinal(current.toordinal() + 1)
        if current.weekday() < 5:
            days += 1
    return days


def calculate_freshness(
    observed_date: str | None,
    asof_date: str | None,
    frequency: str,
) -> tuple[str, float | None, int | None]:
    """Classify input freshness using the macro audit lag policy."""

    observed = _parse_date(observed_date)
    asof = _parse_date(asof_date)
    if observed is None or asof is None:
        return "unknown", None, None
    if frequency in {"daily", "intraday"}:
        lag = _trading_day_lag(observed, asof)
        if lag == 0:
            return "fresh", float(lag), 0
        if lag <= 3:
            return "acceptable_lag", float(lag), 3
        return "stale", float(lag), 3
    calendar_lag = max(0, (asof - observed).days)
    if frequency == "weekly":
        return ("stale" if calendar_lag > 14 else "fresh" if calendar_lag <= 7 else "acceptable_lag", float(calendar_lag), 14)
    if frequency == "monthly":
        return ("stale" if calendar_lag > 45 else "fresh" if calendar_lag <= 31 else "acceptable_lag", float(calendar_lag), 45)
    if frequency == "quarterly":
        return ("stale" if calendar_lag > 120 else "fresh" if calendar_lag <= 90 else "acceptable_lag", float(calendar_lag), 120)
    return "unknown", float(calendar_lag), None


def _provider_metadata(input_id: str, source_object: str | None, source_field: str | None) -> tuple[str | None, str | None, str | None]:
    if input_id.startswith("cboe_"):
        return "Cboe", "Cboe Daily Market Statistics", CBOE_PUT_CALL_URL
    if input_id in {"put_call_ratio", "put_call_ratio_internal", "put_call_5d_ma"}:
        return None, "Internal generic put/call input", None
    if input_id in {"nfci", "nfci_inverted", "m2_growth_yoy", "net_liquidity", "net_liquidity_z"}:
        return "FRED/Chicago Fed", "RegimeInputs macro data fetch", None
    if input_id.startswith("hy_") or input_id.startswith("ig_"):
        return "FRED", "RegimeInputs credit spread data fetch", None
    if input_id in {"vix_level", "vix_z_20d", "vix_term_slope", "vvix_level", "vvix_z", "skew_index"}:
        return "Yahoo Finance/Cboe", "RegimeInputs volatility data fetch", None
    if source_object == "MarketState" or (source_field or "").startswith("cross_asset_returns"):
        return "MarketState", "MarketState cross-asset/tape builder", None
    return None, source_object, None


def _frequency(input_id: str) -> str:
    return INPUT_FREQUENCIES.get(input_id, "unknown")


def _lookback(input_id: str, horizon: str) -> str | None:
    lookback = INPUT_LOOKBACK_WINDOWS.get(input_id)
    if lookback == "selected MarketState horizon":
        return HORIZON_LOOKBACK_LABELS.get(horizon.lower(), horizon)
    return lookback


def _calculation_method(input_id: str) -> str | None:
    return INPUT_CALCULATION_METHODS.get(input_id)


def _observed_date_for_source(
    source_object: str | None,
    signal: MacroInputSignal | None,
    regime_inputs: Any,
    regime_state: Any,
    market_state: Any,
    asof_date: str | None,
) -> str | None:
    provenance = getattr(signal, "provenance", None)
    if provenance is not None and provenance.observed_date:
        return provenance.observed_date
    if signal is not None and signal.last_updated is not None:
        return _date_text(signal.last_updated)
    if source_object == "RegimeInputs":
        return _date_text(getattr(regime_inputs, "asof_date", None)) or asof_date
    if source_object == "RegimeState":
        return _date_text(getattr(regime_state, "asof_date", None)) or asof_date
    if source_object == "MarketState":
        return (
            _date_text(getattr(market_state, "market_session_date", None))
            or _date_text(getattr(market_state, "asof_utc", None))
            or asof_date
        )
    if source_object == "ForecastInputSet":
        return asof_date
    return asof_date if source_object else None


def _raw_inputs_used(input_id: str, market_state: Any) -> dict[str, Any]:
    cross = getattr(market_state, "cross_asset_returns", {}) or {}
    pairs = {
        "rsp_minus_spy": ("RSP", "SPY"),
        "hyg_minus_tlt": ("HYG", "TLT"),
        "qqq_minus_spy": ("QQQ", "SPY"),
        "iwm_minus_spy": ("IWM", "SPY"),
    }
    if input_id in pairs:
        left, right = pairs[input_id]
        return {left: cross.get(left), right: cross.get(right)}
    tickers = {
        "spy_return": "SPY",
        "qqq_return": "QQQ",
        "iwm_return": "IWM",
        "rsp_return": "RSP",
        "hyg_return": "HYG",
        "tlt_return": "TLT",
        "gld_return": "GLD",
        "uso_return": "USO",
        "btc_return": "BTC-USD",
    }
    if input_id in tickers:
        ticker = tickers[input_id]
        return {ticker: cross.get(ticker)}
    return {}


def _interpretation(input_id: str, value: Any, source_field: str | None) -> tuple[str | None, str | None, str | None]:
    numeric = _safe_float(value)
    if input_id == "vix_level" and numeric is not None:
        if numeric < 15:
            return "calm/complacency", "vix_level_thresholds", "VIX below 15 supports trend continuation but can signal complacency."
        if numeric <= 22:
            return "orderly", "vix_level_thresholds", "VIX between 15 and 22 is treated as normal/orderly."
        if numeric <= 30:
            return "stressed", "vix_level_thresholds", "VIX between 22 and 30 indicates stress."
        return "risk-off stress", "vix_level_thresholds", "VIX above 30 indicates risk-off stress."
    if input_id in {"put_call_ratio", "put_call_ratio_internal", "put_call_5d_ma"}:
        return (
            "generic put/call unresolved",
            "put_call_source_disambiguation",
            "Interpretation is intentionally limited until the series is identified as equity, total, index, or ETP.",
        )
    if input_id == "cboe_equity_put_call_ratio":
        return "equity put/call", "put_call_source_disambiguation", "Low equity put/call may indicate speculation/complacency; high may indicate hedging."
    if input_id == "cboe_total_put_call_ratio":
        return "total put/call", "put_call_source_disambiguation", "High total put/call can indicate hedging demand."
    if input_id in {"rsp_minus_spy", "rsp_vs_spy_z"} and numeric is not None:
        return (
            "breadth leadership",
            "equal_weight_vs_cap_weight",
            "Positive RSP relative performance supports broadening; negative relative performance indicates narrow leadership.",
        )
    if input_id == "hyg_minus_tlt" and numeric is not None:
        return "credit risk appetite", "hyg_tlt_relative_performance", "Positive HYG minus TLT supports credit/risk appetite."
    return None, None, None


def _find_signal(input_set: ForecastInputSet | None, input_id: str) -> MacroInputSignal | None:
    if input_set is None:
        return None
    for signal in input_set.all_signals:
        if input_id in {signal.input_id, signal.historical_feature_id, signal.historical_column}:
            return signal
    if input_id == "fed_path_hold_hike_prob":
        return _find_signal(input_set, "fed_path")
    return None


def _value_from_signal(signal: MacroInputSignal | None) -> Any:
    if signal is None:
        return None
    return signal.transformed_value if signal.transformed_value is not None else signal.raw_value if signal.raw_value is not None else signal.current_value


def _put_call_duplicate_warning(input_set: ForecastInputSet | None, regime_inputs: Any) -> bool:
    spot = _safe_float(_value_from_signal(_find_signal(input_set, "put_call_ratio")))
    ma = _safe_float(_value_from_signal(_find_signal(input_set, "put_call_5d_ma")))
    if spot is None:
        spot = _safe_float(getattr(regime_inputs, "put_call_ratio", None))
    if ma is None:
        ma = _safe_float(getattr(regime_inputs, "put_call_5d_ma", None))
    return spot is not None and ma is not None and math.isclose(spot, ma, rel_tol=0.0, abs_tol=1e-12)


def _has_explicit_cboe_equity(input_set: ForecastInputSet | None, regime_inputs: Any) -> bool:
    return _find_signal(input_set, "cboe_equity_put_call_ratio") is not None or _has_value(getattr(regime_inputs, "cboe_equity_put_call_ratio", None))


def _audit_statuses(
    *,
    input_id: str,
    value: Any,
    source_object: str | None,
    source_field: str | None,
    observed_date: str | None,
    freshness_status: str,
    lookback_window: str | None,
    calculation_method: str | None,
    duplicate_put_call: bool,
    has_explicit_cboe_equity: bool,
) -> tuple[str, list[str]]:
    warnings: list[str] = []
    statuses: list[str] = []
    if not _has_value(value):
        statuses.append("missing_current_value")
    if input_id in {"put_call_ratio", "put_call_ratio_internal", "put_call_5d_ma"}:
        if not has_explicit_cboe_equity:
            statuses.append("source_ambiguous")
            warnings.append("put_call_ratio source unresolved; do not interpret as Cboe equity put/call.")
    if input_id.startswith("cboe_") and _has_value(value) and source_object not in {"Cboe", "RegimeInputs", "ForecastInputSet"}:
        statuses.append("provider_mismatch")
    if duplicate_put_call and input_id in {"put_call_ratio", "put_call_ratio_internal", "put_call_5d_ma"}:
        statuses.append("duplicated_value")
        warnings.append("Spot put_call_ratio equals 5D MA; verify these are not duplicated.")
    if freshness_status == "stale":
        statuses.append("stale")
        if input_id in HIGH_PRIORITY_STALE_INPUTS:
            warnings.append("High-priority input stale: observed_date older than expected.")
    if _has_value(value) and not observed_date:
        statuses.append("missing_observed_date")
    if _has_value(value) and input_id in INPUT_CALCULATION_METHODS and input_id in INPUT_LOOKBACK_WINDOWS and not lookback_window:
        statuses.append("missing_lookback")
    if _has_value(value) and input_id in INPUT_CALCULATION_METHODS and not calculation_method:
        statuses.append("missing_calculation_method")
    deduped_statuses = list(dict.fromkeys(statuses))
    return ";".join(deduped_statuses) if deduped_statuses else "ok", list(dict.fromkeys(warnings))


def _build_row(
    spec: InputSpec,
    *,
    asof_date: str,
    horizon: str,
    regime_inputs: Any = None,
    regime_state: Any = None,
    market_state: Any = None,
    forecast_input_set: ForecastInputSet | None = None,
    contribution_by_input: Mapping[str, Mapping[str, Any]] | None = None,
    historical_df: pd.DataFrame | None = None,
    current_features: Mapping[str, Any] | None = None,
    feature_specs: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    resolution = resolve_current_input_value(
        spec,
        regime_inputs,
        regime_state,
        market_state,
        forecast_input_set,
    )
    matches = _matching_signals(spec, forecast_input_set)
    signal = matches[0] if matches else None
    value = resolution.value
    if spec.input_id == "fed_path_cut_prob" and _has_value(value):
        numeric = _safe_float(value)
        if numeric is not None and numeric > 0.5:
            value = max(0.0, min(1.0, 1.0 - numeric))
    source_object = resolution.source_object
    source_field = resolution.source_field
    source_alias_used = resolution.source_alias_used
    provider, source_name, source_url = _provider_metadata(spec.input_id, source_object, source_field)
    observed_date = _observed_date_for_source(source_object, signal, regime_inputs, regime_state, market_state, asof_date)
    frequency = _frequency(spec.input_id)
    freshness_status, staleness_days, expected_lag = calculate_freshness(observed_date, asof_date, frequency)
    lookback_window = _lookback(spec.input_id, horizon)
    calculation_method = _calculation_method(spec.input_id)
    label, rule_id, detail = _interpretation(spec.input_id, value, source_field)
    duplicate_put_call = _put_call_duplicate_warning(forecast_input_set, regime_inputs)
    has_equity = _has_explicit_cboe_equity(forecast_input_set, regime_inputs)
    audit_status, warnings = _audit_statuses(
        input_id=spec.input_id,
        value=value,
        source_object=source_object,
        source_field=source_field,
        observed_date=observed_date,
        freshness_status=freshness_status,
        lookback_window=lookback_window,
        calculation_method=calculation_method,
        duplicate_put_call=duplicate_put_call,
        has_explicit_cboe_equity=has_equity,
    )

    contribution_by_input = contribution_by_input or {}
    contribution: Mapping[str, Any] = {}
    for signal_id in _candidate_signal_ids(spec):
        if signal_id in contribution_by_input:
            contribution = contribution_by_input[signal_id]
            break
    deterministic_count = int(contribution.get("deterministic_contribution_count") or 0)
    deterministic_total = float(contribution.get("deterministic_total_abs_contribution") or 0.0)
    used_in_deterministic = deterministic_count > 0 and deterministic_total > 0.0

    hist = _historical_column_diagnostics(historical_df if historical_df is not None else pd.DataFrame(), spec.historical_column)
    historical_feature_id = signal.historical_feature_id if signal is not None and signal.historical_feature_id else spec.input_id
    current_features = current_features or {}
    feature_specs = feature_specs or {}
    included_v2 = bool(
        historical_feature_id in current_features
        and historical_feature_id in feature_specs
        and hist["historical_column_exists"]
        and (hist["historical_non_null_count"] or 0) > 0
    )
    used_in_historical = bool(signal.used_in_historical_similarity) if signal is not None else False
    transformed = signal.transformed_value if signal is not None else None
    provenance = getattr(signal, "provenance", None)
    if provenance is not None:
        warnings.extend(provenance.warnings)

    return {
        "input_id": spec.input_id,
        "display_label": spec.label,
        "group": spec.group,
        "parent_layer": spec.parent_layer,
        "value": _stringify(value),
        "transformed_value": _stringify(transformed),
        "units": INPUT_UNITS.get(spec.input_id),
        "provider": provider,
        "source_name": source_name,
        "source_url": source_url,
        "source_object": source_object,
        "source_field": source_field,
        "source_alias_used": source_alias_used,
        "asof_date": asof_date,
        "observed_date": observed_date,
        "last_updated_at": str(signal.last_updated) if signal is not None and signal.last_updated is not None else None,
        "cache_timestamp": getattr(provenance, "cache_timestamp", None) if provenance is not None else None,
        "is_cached": bool(getattr(provenance, "is_cached", False)) if provenance is not None else False,
        "frequency": frequency,
        "expected_lag_days": expected_lag,
        "staleness_days": staleness_days,
        "freshness_status": freshness_status,
        "lookback_window": lookback_window,
        "calculation_method": calculation_method,
        "raw_inputs_used": json.dumps(_raw_inputs_used(spec.input_id, market_state), default=str),
        "interpretation_label": label,
        "interpretation_rule_id": rule_id,
        "interpretation_detail": detail,
        "used_in_deterministic": used_in_deterministic,
        "used_in_historical_similarity": used_in_historical,
        "historical_feature_id": historical_feature_id,
        "historical_column": signal.historical_column if signal is not None and signal.historical_column else spec.historical_column,
        "historical_column_exists": bool(hist["historical_column_exists"]),
        "historical_non_null_count": int(hist["historical_non_null_count"]),
        "historical_non_null_pct": float(hist["historical_non_null_pct"]),
        "included_in_analogue_v2": included_v2,
        "warnings": " | ".join(list(dict.fromkeys(warnings))),
        "audit_status": audit_status,
    }


def _build_group_summary(matrix: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for group, subset in matrix.groupby("group", sort=False):
        rows.append(
            {
                "group": group,
                "expected_count": len(subset),
                "available_current_count": int(subset["value"].apply(_has_value).sum()),
                "ok_count": int((subset["audit_status"] == "ok").sum()),
                "stale_count": int(subset["audit_status"].str.contains("stale", na=False).sum()),
                "source_ambiguous_count": int(subset["audit_status"].str.contains("source_ambiguous", na=False).sum()),
                "duplicated_value_count": int(subset["audit_status"].str.contains("duplicated_value", na=False).sum()),
                "missing_current_count": int(subset["audit_status"].str.contains("missing_current_value", na=False).sum()),
                "missing_lookback_count": int(subset["audit_status"].str.contains("missing_lookback", na=False).sum()),
                "deterministic_used_count": int(subset["used_in_deterministic"].sum()),
                "historical_similarity_used_count": int(subset["included_in_analogue_v2"].sum()),
                "coverage_pct": round(float(subset["value"].apply(_has_value).sum()) / len(subset), 4) if len(subset) else 0.0,
            }
        )
    return pd.DataFrame(rows)


def _sheet_frames(matrix: pd.DataFrame) -> dict[str, pd.DataFrame]:
    group_summary = matrix.attrs.get("group_summary")
    if not isinstance(group_summary, pd.DataFrame):
        group_summary = _build_group_summary(matrix)
    return {
        "All Inputs": matrix,
        "Warnings": matrix[matrix["warnings"].astype(str) != ""],
        "Stale": matrix[matrix["audit_status"].str.contains("stale", na=False)],
        "Source Ambiguous": matrix[matrix["audit_status"].str.contains("source_ambiguous", na=False)],
        "Missing Current": matrix[matrix["audit_status"].str.contains("missing_current_value", na=False)],
        "Missing Lookback": matrix[matrix["audit_status"].str.contains("missing_lookback", na=False)],
        "Missing Method": matrix[matrix["audit_status"].str.contains("missing_calculation_method", na=False)],
        "Group Summary": group_summary,
    }


def _save_outputs(
    matrix: pd.DataFrame,
    asof_date: str,
    output_dir: str,
    save_csv: bool,
    save_xlsx: bool,
    save_json: bool,
) -> dict[str, str]:
    base = Path(output_dir)
    base.mkdir(parents=True, exist_ok=True)
    stem = f"input_ingestion_audit_{asof_date}"
    paths: dict[str, str] = {}
    if save_csv:
        csv_path = base / f"{stem}.csv"
        matrix.to_csv(csv_path, index=False)
        paths["csv"] = str(csv_path)
    if save_xlsx:
        xlsx_path = base / f"{stem}.xlsx"
        _write_minimal_xlsx(xlsx_path, _sheet_frames(matrix))
        paths["xlsx"] = str(xlsx_path)
    if save_json:
        json_path = base / f"{stem}.json"
        group_summary = matrix.attrs.get("group_summary")
        if not isinstance(group_summary, pd.DataFrame):
            group_summary = _build_group_summary(matrix)
        payload = {
            "asof_date": asof_date,
            "horizon": matrix.attrs.get("horizon"),
            "inputs": matrix.where(pd.notna(matrix), None).to_dict(orient="records"),
            "group_summary": group_summary.where(pd.notna(group_summary), None).to_dict(orient="records"),
        }
        json_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        paths["json"] = str(json_path)
    return paths


def build_input_ingestion_audit(
    asof_date: str | None = None,
    horizon: str = "3m",
    output_dir: str = DEFAULT_OUTPUT_DIR,
    save_csv: bool = True,
    save_xlsx: bool = True,
    save_json: bool = True,
) -> pd.DataFrame:
    """Build and optionally save the current-input ingestion/provenance audit."""

    regime_state = _load_regime_for_cli(asof_date)
    resolved_asof = asof_date or getattr(regime_state, "asof_date", None) or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    regime_inputs = _load_regime_inputs_for_cli(resolved_asof)
    market_state = _load_market_state_for_cli(resolved_asof, horizon)

    run_config = MacroForecastRunConfig(asof_date=resolved_asof, horizon=horizon)  # type: ignore[arg-type]
    forecast_input_set = build_forecast_input_set(
        regime_state,
        raw_inputs=regime_inputs,
        market_state=market_state,
        horizon=horizon,
        dedupe_config=run_config.dedupe_config(),
    )
    updates = update_scenario_probabilities(
        DEFAULT_SCENARIO_PRIORS,
        forecast_input_set,
        dedupe_config=run_config.dedupe_config(),
        horizon=horizon,
    )
    contribution_by_input = _contribution_diagnostics(updates)
    historical_df = _load_historical_df()
    current_features, feature_specs = _historical_similarity_inputs(forecast_input_set)

    rows = [
        _build_row(
            spec,
            asof_date=str(resolved_asof),
            horizon=horizon,
            regime_inputs=regime_inputs,
            regime_state=regime_state,
            market_state=market_state,
            forecast_input_set=forecast_input_set,
            contribution_by_input=contribution_by_input,
            historical_df=historical_df,
            current_features=current_features,
            feature_specs=feature_specs,
        )
        for spec in AUDIT_INPUT_SPECS
    ]
    matrix = pd.DataFrame(rows)
    matrix.attrs["asof_date"] = str(resolved_asof)
    matrix.attrs["horizon"] = horizon
    matrix.attrs["group_summary"] = _build_group_summary(matrix)
    matrix.attrs["output_paths"] = _save_outputs(matrix, str(resolved_asof), output_dir, save_csv, save_xlsx, save_json)
    return matrix


def provenance_summary_rows_from_input_set(
    input_set: ForecastInputSet | None,
    *,
    asof_date: str | None = None,
    horizon: str = "3m",
) -> list[dict[str, Any]]:
    """Build compact provenance rows for the DOCX report without refetching live data."""

    if input_set is None:
        return []
    resolved_asof = asof_date or input_set.asof_date
    specs_by_id = {spec.input_id: spec for spec in AUDIT_INPUT_SPECS}
    rows: list[dict[str, Any]] = []
    for input_id in HIGH_PRIORITY_PROVENANCE_INPUTS:
        spec = specs_by_id.get(input_id)
        if spec is None:
            continue
        rows.append(
            _build_row(
                spec,
                asof_date=resolved_asof,
                horizon=horizon,
                forecast_input_set=input_set,
            )
        )
    return rows


def input_audit_warnings_from_input_set(input_set: ForecastInputSet | None, *, horizon: str = "3m") -> list[str]:
    if input_set is None:
        return ["ForecastInputSet unavailable; input provenance could not be audited."]
    rows = provenance_summary_rows_from_input_set(input_set, asof_date=input_set.asof_date, horizon=horizon)
    warnings: list[str] = []
    for row in rows:
        if row.get("warnings"):
            warnings.extend(str(row["warnings"]).split(" | "))
    if _find_signal(input_set, "put_call_ratio") is not None and _find_signal(input_set, "cboe_equity_put_call_ratio") is None:
        warnings.append("put_call_ratio source unresolved; do not interpret as Cboe equity put/call.")
        warnings.append("Cboe equity put/call not ingested; current volatility/positioning interpretation may be incomplete.")
    if _put_call_duplicate_warning(input_set, None):
        warnings.append("put_call_ratio equals put_call_5d_ma; verify duplication.")
    return list(dict.fromkeys(item for item in warnings if item))


def _fmt_number(value: Any, places: int = 2) -> str:
    numeric = _safe_float(value)
    if numeric is None:
        return "?"
    return f"{numeric:.{places}f}"


def _fmt_signed(value: Any, places: int = 2, suffix: str = "") -> str:
    numeric = _safe_float(value)
    if numeric is None:
        return "?"
    return f"{numeric:+.{places}f}{suffix}"


def _signal_value_by_id(input_set: ForecastInputSet, *input_ids: str) -> Any:
    for input_id in input_ids:
        signal = _find_signal(input_set, input_id)
        value = _value_from_signal(signal)
        if _has_value(value):
            return value
    return None


def _source_for_signal(input_set: ForecastInputSet, input_id: str, default_field: str | None = None) -> str:
    signal = _find_signal(input_set, input_id)
    source = signal.source_object if signal is not None and signal.source_object else "unknown"
    field = default_field or (signal.input_id if signal is not None else input_id)
    return f"{source}.{field}" if source != "unknown" else f"unknown.{field}"


def format_auditable_layer_key_signal(
    input_set: ForecastInputSet | None,
    layer_signal: MacroInputSignal,
    *,
    horizon: str = "3m",
) -> str:
    """Return a compact, auditable key-signal string for a layer summary row."""

    if input_set is None:
        return layer_signal.notes or "-"
    observed = input_set.asof_date
    lookback = HORIZON_LOOKBACK_LABELS.get(horizon.lower(), horizon)
    layer = layer_signal.parent_layer or layer_signal.category

    if layer == "breadth":
        diff = _signal_value_by_id(input_set, "rsp_minus_spy", "rsp_vs_spy_z")
        rsp = _signal_value_by_id(input_set, "market_tape_rsp_return", "rsp_return")
        spy = _signal_value_by_id(input_set, "market_tape_spy_return", "spy_return")
        if _has_value(diff) and _has_value(rsp) and _has_value(spy):
            return (
                f"RSP-SPY: {_fmt_signed(diff, suffix=' pp')} over {lookback} | "
                f"RSP {_fmt_signed(rsp, suffix='%')}, SPY {_fmt_signed(spy, suffix='%')} | "
                f"source=MarketState.cross_asset_returns | observed_date={observed}"
            )
        if _has_value(diff):
            source = _source_for_signal(input_set, "rsp_vs_spy_z")
            return f"RSP/SPY z: {_fmt_signed(diff)} | lookback=252 trading days | source={source} | observed_date={observed}"

    if layer == "volatility":
        vix = _signal_value_by_id(input_set, "vix_level")
        z20 = _signal_value_by_id(input_set, "vix_z_20d")
        slope = _signal_value_by_id(input_set, "vix_term_slope")
        return (
            f"VIX: {_fmt_number(vix)} | z20D {_fmt_signed(z20)} | term slope {_fmt_signed(slope)} | "
            f"source={_source_for_signal(input_set, 'vix_level')} | observed_date={observed}"
        )

    if layer == "credit":
        hy = _signal_value_by_id(input_set, "hy_spread_level")
        hy_z = _signal_value_by_id(input_set, "hy_spread_z")
        chg = _signal_value_by_id(input_set, "hy_spread_chg_4w")
        ig = _signal_value_by_id(input_set, "ig_spread_level")
        return (
            f"HY OAS: {_fmt_number(hy, 0)} bps | z {_fmt_signed(hy_z)} | 4W chg {_fmt_signed(chg, 0)} bps | "
            f"IG OAS {_fmt_number(ig, 0)} bps | source=RegimeInputs/FRED | observed_date={observed}"
        )

    if layer == "monetary":
        nfci = _signal_value_by_id(input_set, "nfci")
        nfci_inv = _signal_value_by_id(input_set, "nfci_inverted")
        m2 = _signal_value_by_id(input_set, "m2_growth_yoy")
        netliq = _signal_value_by_id(input_set, "net_liquidity_z")
        return (
            f"NFCI: {_fmt_signed(nfci)} | inverted {_fmt_signed(nfci_inv)} | M2 YoY {_fmt_signed(m2, suffix='%')} | "
            f"net liquidity z {_fmt_signed(netliq)} | source=RegimeInputs/FRED | observed_date={observed}"
        )

    if layer == "positioning":
        pcr = _signal_value_by_id(input_set, "put_call_ratio")
        pcr_ma = _signal_value_by_id(input_set, "put_call_5d_ma")
        if _find_signal(input_set, "cboe_equity_put_call_ratio") is not None:
            eq = _signal_value_by_id(input_set, "cboe_equity_put_call_ratio")
            return f"Equity put/call: {_fmt_number(eq)} | source=Cboe Daily Market Statistics | observed_date={observed}"
        parts = [
            f"Generic put/call ratio: {_fmt_number(pcr)}",
            "field=put_call_ratio",
            f"5D MA {_fmt_number(pcr_ma)}",
            f"source={_source_for_signal(input_set, 'put_call_ratio')}",
            f"observed_date={observed}",
            "Cboe equity unresolved",
        ]
        return " | ".join(parts)

    return f"{layer_signal.notes or 'Layer summary'} | value={_fmt_number(layer_signal.current_value)} | source=RegimeState | observed_date={observed}"


def _summary_lines(matrix: pd.DataFrame) -> list[str]:
    paths = matrix.attrs.get("output_paths") or {}
    lines = [
        "Input ingestion audit complete.",
        f"As-of date: {matrix.attrs.get('asof_date')}",
        f"Total expected inputs: {len(matrix)}",
        f"Available current inputs: {int(matrix['value'].apply(_has_value).sum())}",
        f"Used in deterministic math: {int(matrix['used_in_deterministic'].sum())}",
        f"Used in historical similarity: {int(matrix['included_in_analogue_v2'].sum())}",
        f"Stale inputs: {int(matrix['audit_status'].str.contains('stale', na=False).sum())}",
        f"Source ambiguous inputs: {int(matrix['audit_status'].str.contains('source_ambiguous', na=False).sum())}",
        f"Missing current inputs: {int(matrix['audit_status'].str.contains('missing_current_value', na=False).sum())}",
    ]
    if paths.get("csv"):
        lines.append(f"CSV saved to: {paths['csv']}")
    if paths.get("xlsx"):
        lines.append(f"XLSX saved to: {paths['xlsx']}")
    if paths.get("json"):
        lines.append(f"JSON saved to: {paths['json']}")
    return lines


def _print_missing(matrix: pd.DataFrame) -> None:
    flagged = matrix[matrix["audit_status"] != "ok"]
    if flagged.empty:
        print("No flagged inputs.")
        return
    cols = ["input_id", "group", "value", "source_object", "source_field", "audit_status", "warnings"]
    print(flagged[cols].to_string(index=False))


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the Helix macro forecast input ingestion/provenance audit.")
    parser.add_argument("--asof-date", default=None)
    parser.add_argument("--horizon", default="3m")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--no-csv", action="store_true")
    parser.add_argument("--no-xlsx", action="store_true")
    parser.add_argument("--no-json", action="store_true")
    parser.add_argument("--print-missing-only", action="store_true")
    parser.add_argument("--print-summary", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    matrix = build_input_ingestion_audit(
        asof_date=args.asof_date,
        horizon=args.horizon,
        output_dir=args.output_dir,
        save_csv=not args.no_csv,
        save_xlsx=not args.no_xlsx,
        save_json=not args.no_json,
    )
    if args.print_missing_only:
        _print_missing(matrix)
    if args.print_summary or not args.print_missing_only:
        for line in _summary_lines(matrix):
            print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
