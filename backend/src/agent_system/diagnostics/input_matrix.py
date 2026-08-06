"""Input diagnostic matrix for the Helix Macro Forecast Engine."""
from __future__ import annotations

import argparse
import json
import math
import sys
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd

from src.agent_system.forecasting.input_signals import build_forecast_input_set
from src.agent_system.forecasting.macro_forecast_runner import (
    MacroForecastRunConfig,
    _load_market_state_for_cli,
    _load_regime_for_cli,
    _load_regime_inputs_for_cli,
)
from src.agent_system.schemas.macro_forecast import ForecastInputSet, MacroInputSignal


DEFAULT_OUTPUT_DIR = "data/agent_system/diagnostics"
HISTORICAL_SPARSITY_THRESHOLD = 0.60


@dataclass(frozen=True)
class InputSpec:
    input_id: str
    label: str
    group: str
    parent_layer: str
    input_scope: str
    role: str
    expected_source_objects: tuple[str, ...]
    possible_source_fields: tuple[str, ...]
    historical_column: str | None
    required_for_deterministic: bool
    required_for_historical_similarity: bool
    priority: str = "medium"
    signal_ids: tuple[str, ...] = ()
    notes: str = ""


@dataclass(frozen=True)
class InputValueResolution:
    value: Any = None
    source_object: str | None = None
    source_field: str | None = None
    source_alias_used: str | None = None
    missing_reason: str | None = None


def _spec(
    input_id: str,
    label: str,
    group: str,
    parent_layer: str,
    *,
    source_fields: Iterable[str] | None = None,
    source_objects: Iterable[str] = ("RegimeInputs", "RegimeState", "MarketState"),
    historical_column: str | None = None,
    required_det: bool = True,
    required_hist: bool = True,
    priority: str = "medium",
    input_scope: str = "core_macro",
    role: str = "raw_component",
    signal_ids: Iterable[str] | None = None,
    notes: str = "",
) -> InputSpec:
    return InputSpec(
        input_id=input_id,
        label=label,
        group=group,
        parent_layer=parent_layer,
        input_scope=input_scope,
        role=role,
        expected_source_objects=tuple(source_objects),
        possible_source_fields=tuple(source_fields or (input_id,)),
        historical_column=historical_column if historical_column is not None else input_id,
        required_for_deterministic=required_det,
        required_for_historical_similarity=required_hist,
        priority=priority,
        signal_ids=tuple(signal_ids or ()),
        notes=notes,
    )


def expected_input_registry() -> list[InputSpec]:
    """Canonical expected input universe for the macro forecast engine."""

    specs: list[InputSpec] = []
    add = specs.append

    for input_id, label, aliases, priority in [
        ("net_liquidity", "Net liquidity", ("net_liquidity",), "medium"),
        ("net_liquidity_z", "Net liquidity z-score", ("net_liquidity_z",), "high"),
        ("nfci", "NFCI level", ("nfci",), "medium"),
        ("nfci_inverted", "NFCI inverted", ("nfci_inverted",), "high"),
        ("m2_growth_yoy", "M2 growth YoY", ("m2_growth_yoy",), "medium"),
        ("fci_z", "Financial conditions z-score", ("fci_z",), "medium"),
    ]:
        add(_spec(input_id, label, "Monetary", "monetary", source_fields=aliases, priority=priority))
    add(
        _spec(
            "fed_path_hold_hike_prob",
            "Fed hold/hike probability",
            "Monetary",
            "monetary",
            source_fields=("fed_path_hold_hike_prob", "fed_path", "hold_hike_probability"),
            source_objects=("ForecastInputSet", "RegimeState"),
            historical_column=None,
            priority="high",
            signal_ids=("fed_path",),
            notes="Derived from the Fed path signal current value when available.",
        )
    )
    add(
        _spec(
            "fed_path_cut_prob",
            "Fed cut probability",
            "Monetary",
            "monetary",
            source_fields=("fed_path_cut_prob", "fed_path", "cut_probability"),
            source_objects=("ForecastInputSet", "RegimeState"),
            historical_column=None,
            priority="high",
            signal_ids=("fed_path",),
            notes="Derived as 1 - hold/hike probability when only the Fed path signal is available.",
        )
    )

    for input_id, label, aliases, priority in [
        ("hy_spread_level", "HY spread level", ("hy_spread_level", "hy_spread", "hy_oas"), "high"),
        ("hy_spread_z", "HY spread z-score", ("hy_spread_z",), "high"),
        ("hy_spread_chg_4w", "HY spread 4-week change", ("hy_spread_chg_4w", "hy_spread_change_4w"), "high"),
        ("ig_spread_level", "IG spread level", ("ig_spread_level", "ig_spread", "ig_oas"), "medium"),
        ("ig_spread_z", "IG spread z-score", ("ig_spread_z",), "medium"),
        ("hyg_tlt_ratio_z", "HYG/TLT ratio z-score", ("hyg_tlt_ratio_z", "hyg_minus_tlt"), "high"),
    ]:
        add(_spec(input_id, label, "Credit", "credit", source_fields=aliases, priority=priority))

    for input_id, label, aliases, priority in [
        ("vix_level", "VIX level", ("vix_level", "vix"), "high"),
        ("vix_z_20d", "VIX 20-day z-score", ("vix_z_20d",), "high"),
        ("vix_term_slope", "VIX term slope", ("vix_term_slope",), "high"),
        ("vvix_level", "VVIX level", ("vvix_level", "vvix"), "medium"),
        ("vvix_z", "VVIX z-score", ("vvix_z",), "medium"),
        ("put_call_ratio", "Put/call ratio", ("put_call_ratio", "put_call_5d_ma"), "medium"),
        ("skew_index", "SKEW index", ("skew_index", "skew"), "medium"),
    ]:
        add(_spec(input_id, label, "Volatility", "volatility", source_fields=aliases, priority=priority, input_scope="market_structure"))

    for input_id, label, aliases, priority in [
        ("pct_above_200d", "% above 200D", ("pct_above_200d", "percent_above_200d"), "high"),
        ("new_highs_minus_lows_z", "New highs minus lows z-score", ("new_highs_minus_lows_z", "nh_nl_z"), "high"),
        ("sectors_green", "Sectors green", ("sectors_green",), "high"),
        ("rsp_vs_spy_z", "RSP/SPY z-score", ("rsp_vs_spy_z", "rsp_minus_spy"), "high"),
        ("adl_slope", "Advance/decline slope", ("adl_slope",), "medium"),
    ]:
        add(_spec(input_id, label, "Breadth", "breadth", source_fields=aliases, priority=priority, input_scope="market_structure"))

    for input_id, label, aliases, priority in [
        ("dealer_gamma_z", "Dealer gamma z-score", ("dealer_gamma_z",), "medium"),
        ("put_call_5d_ma", "Put/call 5D average", ("put_call_5d_ma", "put_call_ratio"), "medium"),
        ("aaii_bull_minus_bear", "AAII bull minus bear", ("aaii_bull_minus_bear",), "low"),
        ("cot_net_large_spec_z", "COT large spec z-score", ("cot_net_large_spec_z",), "low"),
        ("equity_etf_flow_z", "Equity ETF flow z-score", ("equity_etf_flow_z",), "low"),
    ]:
        add(_spec(input_id, label, "Positioning", "positioning", source_fields=aliases, priority=priority, input_scope="market_structure"))

    market_specs = [
        ("spy_return", "SPY return", "market_tape_spy_return", "ret_SPY_1d", "SPY"),
        ("qqq_return", "QQQ return", "market_tape_qqq_return", "ret_QQQ_1d", "QQQ"),
        ("iwm_return", "IWM return", "market_tape_iwm_return", "ret_IWM_1d", "IWM"),
        ("rsp_return", "RSP return", "market_tape_rsp_return", "ret_RSP_1d", "RSP"),
        ("hyg_return", "HYG return", "market_tape_hyg_return", "ret_HYG_1d", "HYG"),
        ("tlt_return", "TLT return", "market_tape_tlt_return", "ret_TLT_1d", "TLT"),
        ("gld_return", "GLD return", "market_tape_gld_return", "ret_GLD_1d", "GLD"),
        ("uso_return", "USO return", "market_tape_uso_return", "ret_USO_1d", "USO"),
        ("btc_return", "BTC return", "market_tape_btc_return", "ret_BTC_1d", "BTC-USD"),
    ]
    for input_id, label, signal_id, historical_column, ticker in market_specs:
        add(
            _spec(
                input_id,
                label,
                "Market/Tape",
                "market_state",
                source_fields=(input_id, f"cross_asset_returns.{ticker}"),
                source_objects=("MarketState",),
                historical_column=historical_column,
                required_hist=False,
                priority="medium",
                input_scope="market_tape",
                signal_ids=(signal_id,),
            )
        )
    for input_id, label, aliases, historical_column in [
        ("hyg_minus_tlt", "HYG minus TLT", ("hyg_minus_tlt",), "hyg_minus_tlt"),
        ("rsp_minus_spy", "RSP minus SPY", ("rsp_minus_spy",), "rsp_minus_spy"),
        ("iwm_minus_spy", "IWM minus SPY", ("iwm_minus_spy",), "iwm_minus_spy"),
        ("qqq_minus_spy", "QQQ minus SPY", ("qqq_minus_spy",), "qqq_minus_spy"),
        ("sector_dispersion", "Sector dispersion", ("sector_dispersion", "dispersion"), "dispersion"),
        ("spy_clv", "SPY close location value", ("spy_clv",), "spy_clv"),
        ("spy_range_pct", "SPY range percent", ("spy_range_pct",), "spy_range_pct"),
        ("spy_vol_z_20d", "SPY volume z-score", ("spy_vol_z_20d",), "spy_vol_z_20d"),
        ("volume_confirmation", "Volume confirmation", ("volume_confirmation",), "volume_confirmation"),
        ("spy_above_vwap", "SPY above VWAP", ("spy_above_vwap",), None),
        ("spy_above_prev_close", "SPY above previous close", ("spy_above_prev_close",), None),
        ("vix_change_pct_1d", "VIX 1D percent change", ("vix_change_pct_1d",), "vix_change_pct_1d"),
    ]:
        add(
            _spec(
                input_id,
                label,
                "Market/Tape",
                "market_state",
                source_fields=aliases,
                source_objects=("MarketState",),
                historical_column=historical_column,
                required_hist=historical_column is not None,
                input_scope="market_tape",
                signal_ids=(input_id,),
            )
        )

    for input_id in [
        "us10y_level",
        "us10y_chg_1m",
        "us2y_level",
        "us2y_chg_1m",
        "yield_curve_10y2y",
        "real_yield_10y",
        "real_yield_chg_1m",
        "dxy_level",
        "dxy_chg_1m",
    ]:
        add(_spec(input_id, input_id.replace("_", " ").title(), "Rates/FX", "rates_fx", source_objects=("extra_features",), priority="medium"))

    for input_id in [
        "oil_level",
        "oil_return_1m",
        "oil_return_3m",
        "oil_z_1y",
        "uso_return_1m",
        "uso_return_3m",
        "xle_vs_spy_z",
        "breakeven_10y",
        "breakeven_10y_chg_1m",
    ]:
        add(_spec(input_id, input_id.replace("_", " ").title(), "Commodities/Oil", "commodities", source_objects=("MarketState", "extra_features"), priority="medium"))

    for input_id in [
        "ai_infra_basket_return_1m",
        "semis_basket_return_1m",
        "memory_basket_return_1m",
        "grid_power_basket_return_1m",
        "hyperscaler_capex_proxy",
        "ai_earnings_revision_proxy",
    ]:
        add(_spec(input_id, input_id.replace("_", " ").title(), "Theme/Earnings", "earnings", source_objects=("extra_features",), priority="low"))

    return specs


EXPECTED_INPUT_SPECS = expected_input_registry()


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        out = float(value)
        return out if math.isfinite(out) else None
    except (TypeError, ValueError):
        return None


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, float) and not math.isfinite(value):
        return False
    if isinstance(value, str) and value == "":
        return False
    return True


def _object_dict(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    if isinstance(obj, Mapping):
        return dict(obj)
    if hasattr(obj, "to_dict"):
        try:
            return dict(obj.to_dict())
        except Exception:
            return {}
    if hasattr(obj, "__dataclass_fields__"):
        try:
            return asdict(obj)
        except Exception:
            return {}
    return {}


def _regime_state_inputs(regime_state: Any | None) -> dict[str, Any]:
    if regime_state is None:
        return {}
    values: dict[str, Any] = {}
    layers = getattr(regime_state, "layers", None)
    for layer_name in ["monetary", "credit", "volatility", "breadth", "positioning"]:
        layer = getattr(layers, layer_name, None) if layers is not None else None
        values.update(getattr(layer, "inputs", {}) or {})
    return values


def _market_cross_return(market_state: Any | None, ticker: str) -> Any:
    cross = getattr(market_state, "cross_asset_returns", {}) or {}
    return cross.get(ticker)


def _market_derived_value(input_id: str, market_state: Any | None) -> tuple[Any, str | None]:
    if market_state is None:
        return None, None
    cross = getattr(market_state, "cross_asset_returns", {}) or {}

    def diff(left: str, right: str) -> float | None:
        left_value = _safe_float(cross.get(left))
        right_value = _safe_float(cross.get(right))
        if left_value is None or right_value is None:
            return None
        return left_value - right_value

    ticker_by_id = {
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
    if input_id in ticker_by_id:
        ticker = ticker_by_id[input_id]
        return _market_cross_return(market_state, ticker), f"cross_asset_returns.{ticker}"
    if input_id == "rsp_minus_spy":
        return diff("RSP", "SPY"), "cross_asset_returns.RSP-SPY"
    if input_id == "iwm_minus_spy":
        return diff("IWM", "SPY"), "cross_asset_returns.IWM-SPY"
    if input_id == "hyg_minus_tlt":
        return diff("HYG", "TLT"), "cross_asset_returns.HYG-TLT"
    if input_id == "qqq_minus_spy":
        return diff("QQQ", "SPY"), "cross_asset_returns.QQQ-SPY"
    if input_id == "sector_dispersion":
        return getattr(market_state, "dispersion", None), "dispersion"
    return None, None


def _get_field(obj: Any, field: str) -> Any:
    if obj is None:
        return None
    if "." in field:
        head, tail = field.split(".", 1)
        nested = _get_field(obj, head)
        return _get_field(nested, tail)
    if isinstance(obj, Mapping):
        return obj.get(field)
    return getattr(obj, field, None)


def _signal_value(signal: MacroInputSignal, spec: InputSpec) -> Any:
    value = signal.transformed_value if signal.transformed_value is not None else signal.raw_value
    if value is None:
        value = signal.current_value
    hold_hike = _safe_float(value)
    if spec.input_id == "fed_path_cut_prob" and hold_hike is not None:
        return max(0.0, min(1.0, 1.0 - hold_hike))
    return value


def _candidate_signal_ids(spec: InputSpec) -> set[str]:
    ids = {spec.input_id, *spec.signal_ids}
    if spec.historical_column:
        ids.add(spec.historical_column)
    ids.update(spec.possible_source_fields)
    return {item for item in ids if item}


def _matching_signals(spec: InputSpec, forecast_input_set: ForecastInputSet | None) -> list[MacroInputSignal]:
    if forecast_input_set is None:
        return []
    ids = _candidate_signal_ids(spec)
    matches: list[MacroInputSignal] = []
    for signal in forecast_input_set.all_signals:
        values = {
            signal.input_id,
            signal.historical_feature_id,
            signal.historical_column,
        }
        if ids.intersection({str(item) for item in values if item}):
            matches.append(signal)
    return matches


def resolve_current_input_value(
    input_spec: InputSpec,
    regime_inputs: Any,
    regime_state: Any,
    market_state: Any,
    forecast_input_set: ForecastInputSet | None,
    extra_features: Mapping[str, Any] | None = None,
) -> InputValueResolution:
    """Resolve one input's current value and record where it came from."""

    matches = _matching_signals(input_spec, forecast_input_set)
    for signal in matches:
        value = _signal_value(signal, input_spec)
        if _has_value(value):
            return InputValueResolution(
                value=value,
                source_object=signal.source_object or "ForecastInputSet",
                source_field=signal.input_id,
                source_alias_used=signal.input_id if signal.input_id != input_spec.input_id else None,
            )

    for source_object, obj in [
        ("RegimeInputs", regime_inputs),
        ("RegimeState", _regime_state_inputs(regime_state)),
        ("MarketState", market_state),
        ("extra_features", extra_features or {}),
    ]:
        for field in input_spec.possible_source_fields:
            value = _get_field(obj, field)
            if _has_value(value):
                return InputValueResolution(
                    value=value,
                    source_object=source_object,
                    source_field=field,
                    source_alias_used=field if field != input_spec.input_id else None,
                )

        if source_object == "MarketState":
            value, field = _market_derived_value(input_spec.input_id, market_state)
            if _has_value(value):
                return InputValueResolution(
                    value=value,
                    source_object="MarketState",
                    source_field=field,
                    source_alias_used=field if field != input_spec.input_id else None,
                )

    return InputValueResolution(missing_reason="No current value found in ForecastInputSet, RegimeInputs, RegimeState, MarketState, or extra_features.")


def _load_historical_df() -> pd.DataFrame:
    try:
        from src.analysis.analogues import _load_df

        return _load_df()
    except Exception:
        return pd.DataFrame()


def _historical_column_diagnostics(df: pd.DataFrame, historical_column: str | None) -> dict[str, Any]:
    if not historical_column:
        return {
            "historical_column_exists": False,
            "historical_non_null_count": 0,
            "historical_non_null_pct": 0.0,
            "historical_latest_value": None,
            "historical_latest_date": None,
            "missing_historical_reason": "no_historical_column_configured",
        }
    if df.empty:
        return {
            "historical_column_exists": False,
            "historical_non_null_count": 0,
            "historical_non_null_pct": 0.0,
            "historical_latest_value": None,
            "historical_latest_date": None,
            "missing_historical_reason": "historical_dataset_unavailable",
        }
    if historical_column not in df.columns:
        return {
            "historical_column_exists": False,
            "historical_non_null_count": 0,
            "historical_non_null_pct": 0.0,
            "historical_latest_value": None,
            "historical_latest_date": None,
            "missing_historical_reason": "historical_column_missing",
        }

    series = df[historical_column]
    non_null = series.notna()
    count = int(non_null.sum())
    pct = float(count / len(df)) if len(df) else 0.0
    latest_value = None
    latest_date = None
    if count:
        latest_row = df.loc[non_null].sort_values("date").iloc[-1] if "date" in df.columns else df.loc[non_null].iloc[-1]
        latest_value = latest_row.get(historical_column)
        latest_date = latest_row.get("date") if "date" in df.columns else None
        if hasattr(latest_date, "strftime"):
            latest_date = latest_date.strftime("%Y-%m-%d")
    reason = None
    if pct < HISTORICAL_SPARSITY_THRESHOLD:
        reason = "historical_column_sparse"
    return {
        "historical_column_exists": True,
        "historical_non_null_count": count,
        "historical_non_null_pct": round(pct, 4),
        "historical_latest_value": latest_value,
        "historical_latest_date": latest_date,
        "missing_historical_reason": reason,
    }


def _contribution_diagnostics(updates: list[Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for update in updates:
        for contribution in update.contributions:
            entry = out.setdefault(
                contribution.input_id,
                {
                    "deterministic_contribution_count": 0,
                    "deterministic_scenarios_affected": set(),
                    "deterministic_total_abs_contribution": 0.0,
                    "capped_by_dedupe": False,
                },
            )
            value = contribution.final_contribution
            if value is None:
                value = contribution.adjusted_contribution
            entry["deterministic_contribution_count"] += 1
            entry["deterministic_scenarios_affected"].add(contribution.scenario_id)
            entry["deterministic_total_abs_contribution"] += abs(float(value or 0.0))
            entry["capped_by_dedupe"] = entry["capped_by_dedupe"] or bool(contribution.capped_by_dedupe)
    for entry in out.values():
        entry["deterministic_scenarios_affected"] = sorted(entry["deterministic_scenarios_affected"])
        entry["deterministic_total_abs_contribution"] = round(entry["deterministic_total_abs_contribution"], 6)
    return out


def _historical_similarity_inputs(forecast_input_set: ForecastInputSet | None) -> tuple[dict[str, Any], dict[str, Any]]:
    if forecast_input_set is None:
        return {}, {}
    try:
        from src.analysis.detailed_analogue_similarity import (
            build_current_feature_vector_for_analogues,
            feature_specs_from_forecast_input_set,
        )

        current_features = build_current_feature_vector_for_analogues(forecast_input_set)
        feature_specs = {
            spec.feature_id: spec
            for spec in feature_specs_from_forecast_input_set(forecast_input_set)
        }
        return current_features, feature_specs
    except Exception:
        return {}, {}


def _stringify(value: Any) -> Any:
    if isinstance(value, (set, tuple, list)):
        return ", ".join(str(item) for item in value)
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            return str(value)
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    return value


def _coverage_status(
    *,
    available_current: bool,
    in_forecast_input_set: bool,
    used_in_deterministic: bool,
    deterministic_count: int,
    used_in_historical_similarity: bool,
    included_in_analogue_v2: bool,
    historical_column_exists: bool,
    historical_non_null_pct: float,
    signal: MacroInputSignal | None,
    spec: InputSpec,
) -> str:
    if not available_current:
        return "current_missing"
    if not in_forecast_input_set:
        return "forecast_signal_missing"
    if signal is not None and signal.display_only:
        if signal.dedupe_role == "display_only" or signal.exclusion_reason:
            return "excluded_by_composite"
        return "display_only"
    if spec.required_for_historical_similarity and not historical_column_exists:
        return "historical_column_missing"
    if included_in_analogue_v2 and historical_non_null_pct < HISTORICAL_SPARSITY_THRESHOLD:
        return "active_sparse_history"
    if used_in_deterministic and included_in_analogue_v2:
        return "active_full"
    if used_in_deterministic:
        return "deterministic_only" if deterministic_count > 0 else "available_but_zero"
    if included_in_analogue_v2:
        return "historical_only"
    if signal is not None and signal.dedupe_role == "modifier" and deterministic_count == 0:
        return "missing_scenario_impacts"
    return "not_configured"


def _build_group_summary(matrix: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for group, subset in matrix.groupby("group", sort=False):
        expected = len(subset)
        available = int(subset["available_current"].sum())
        forecast_count = int(subset["in_forecast_input_set"].sum())
        det_count = int(subset["used_in_deterministic"].sum())
        hist_count = int(subset["included_in_analogue_v2"].sum())
        hist_exists = int(subset["historical_column_exists"].sum())
        sparse = int((subset["coverage_status"] == "active_sparse_history").sum())
        missing_current = int((~subset["available_current"]).sum())
        missing_hist = int((subset["missing_historical_reason"] == "historical_column_missing").sum())
        notes: list[str] = []
        if missing_current == expected:
            notes.append("No current values wired.")
        if missing_hist == expected:
            notes.append("Historical columns absent.")
        if sparse:
            notes.append("Historical columns sparse.")
        if group == "Commodities/Oil" and available:
            notes.append("Coverage may be via tape proxies rather than true oil/breakeven inputs.")
        if group == "Theme/Earnings" and available == 0:
            notes.append("Theme catalyst inputs are not yet implemented.")
        rows.append(
            {
                "group": group,
                "expected_count": expected,
                "available_current_count": available,
                "forecast_input_set_count": forecast_count,
                "deterministic_used_count": det_count,
                "historical_similarity_used_count": hist_count,
                "historical_column_exists_count": hist_exists,
                "historical_sparse_count": sparse,
                "missing_current_count": missing_current,
                "missing_historical_count": missing_hist,
                "coverage_pct": round(available / expected, 4) if expected else 0.0,
                "notes": " ".join(notes) if notes else "-",
            }
        )
    return pd.DataFrame(rows)


def build_input_diagnostic_matrix(
    asof_date: str | None = None,
    horizon: str = "3m",
    output_dir: str = DEFAULT_OUTPUT_DIR,
    save_csv: bool = True,
    save_xlsx: bool = True,
    save_json: bool = True,
) -> pd.DataFrame:
    """Build and optionally save the macro forecast input diagnostic matrix."""

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
    contribution_by_input = _contribution_diagnostics([])
    historical_df = _load_historical_df()
    current_features, feature_specs = _historical_similarity_inputs(forecast_input_set)

    rows: list[dict[str, Any]] = []
    for spec in EXPECTED_INPUT_SPECS:
        resolution = resolve_current_input_value(
            spec,
            regime_inputs,
            regime_state,
            market_state,
            forecast_input_set,
        )
        matches = _matching_signals(spec, forecast_input_set)
        signal = matches[0] if matches else None
        hist = _historical_column_diagnostics(historical_df, spec.historical_column)
        contribution = {}
        for signal_id in _candidate_signal_ids(spec):
            if signal_id in contribution_by_input:
                contribution = contribution_by_input[signal_id]
                break
        deterministic_count = int(contribution.get("deterministic_contribution_count") or 0)
        deterministic_total = float(contribution.get("deterministic_total_abs_contribution") or 0.0)
        deterministic_scenarios = contribution.get("deterministic_scenarios_affected") or []
        signal_used_prob = bool(signal.used_in_probability_update) if signal is not None else False
        signal_used_hist = bool(signal.used_in_historical_similarity) if signal is not None else False
        historical_feature_id = signal.historical_feature_id if signal is not None else spec.input_id
        historical_column = signal.historical_column if signal is not None and signal.historical_column else spec.historical_column
        has_feature_spec = historical_feature_id in feature_specs if historical_feature_id else False
        has_current_feature = historical_feature_id in current_features if historical_feature_id else False
        included_v2 = bool(
            has_feature_spec
            and has_current_feature
            and hist["historical_column_exists"]
            and (hist["historical_non_null_count"] or 0) > 0
        )
        used_in_det = bool(signal_used_prob and deterministic_count > 0)
        available_current = _has_value(resolution.value)
        missing_hist_reason = hist["missing_historical_reason"]
        if included_v2 and missing_hist_reason == "historical_column_sparse":
            missing_hist_reason = "historical_column_sparse"
        status = _coverage_status(
            available_current=available_current,
            in_forecast_input_set=bool(matches),
            used_in_deterministic=used_in_det,
            deterministic_count=deterministic_count,
            used_in_historical_similarity=signal_used_hist,
            included_in_analogue_v2=included_v2,
            historical_column_exists=bool(hist["historical_column_exists"]),
            historical_non_null_pct=float(hist["historical_non_null_pct"] or 0.0),
            signal=signal,
            spec=spec,
        )
        if contribution.get("capped_by_dedupe"):
            status = "excluded_by_dedupe" if deterministic_total == 0 else status
        missing_current_reason = None if available_current else resolution.missing_reason
        notes = spec.notes
        if signal is not None and signal.exclusion_reason:
            notes = f"{notes} {signal.exclusion_reason}".strip()
        rows.append(
            {
                "input_id": spec.input_id,
                "label": spec.label,
                "group": spec.group,
                "parent_layer": spec.parent_layer,
                "input_scope": signal.input_scope if signal is not None else spec.input_scope,
                "role": signal.role if signal is not None else spec.role,
                "expected": True,
                "available_current": available_current,
                "current_value": _stringify(resolution.value),
                "current_value_type": type(resolution.value).__name__ if available_current else None,
                "source_object": resolution.source_object,
                "source_field": resolution.source_field,
                "source_alias_used": resolution.source_alias_used,
                "in_forecast_input_set": bool(matches),
                "used_in_deterministic": used_in_det,
                "deterministic_contribution_count": deterministic_count,
                "deterministic_scenarios_affected": _stringify(deterministic_scenarios),
                "deterministic_total_abs_contribution": deterministic_total,
                "used_in_historical_similarity": signal_used_hist,
                "historical_feature_id": historical_feature_id,
                "historical_column": historical_column,
                "historical_column_exists": bool(hist["historical_column_exists"]),
                "historical_non_null_count": int(hist["historical_non_null_count"]),
                "historical_non_null_pct": float(hist["historical_non_null_pct"]),
                "historical_latest_value": _stringify(hist["historical_latest_value"]),
                "historical_latest_date": hist["historical_latest_date"],
                "included_in_analogue_v2": included_v2,
                "missing_current_reason": missing_current_reason,
                "missing_historical_reason": missing_hist_reason,
                "coverage_status": status,
                "notes": notes,
            }
        )

    matrix = pd.DataFrame(rows)
    matrix.attrs["asof_date"] = str(resolved_asof)
    matrix.attrs["horizon"] = horizon
    matrix.attrs["group_summary"] = _build_group_summary(matrix)
    matrix.attrs["output_paths"] = _save_outputs(matrix, resolved_asof, output_dir, save_csv, save_xlsx, save_json)
    return matrix


def _sheet_frames(matrix: pd.DataFrame) -> dict[str, pd.DataFrame]:
    group_summary = matrix.attrs.get("group_summary")
    if not isinstance(group_summary, pd.DataFrame):
        group_summary = _build_group_summary(matrix)
    return {
        "All Inputs": matrix,
        "Missing Current": matrix[~matrix["available_current"]],
        "Missing Historical": matrix[matrix["missing_historical_reason"] == "historical_column_missing"],
        "Sparse Historical": matrix[matrix["missing_historical_reason"] == "historical_column_sparse"],
        "Active Deterministic": matrix[matrix["used_in_deterministic"]],
        "Active Historical Similarity": matrix[matrix["included_in_analogue_v2"]],
        "Group Summary": group_summary,
    }


def _column_name(index: int) -> str:
    name = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        name = chr(65 + rem) + name
    return name


def _worksheet_xml(frame: pd.DataFrame) -> str:
    rows = [list(frame.columns)] + frame.fillna("").astype(str).values.tolist()
    xml_rows: list[str] = []
    for row_idx, row in enumerate(rows, 1):
        cells: list[str] = []
        for col_idx, value in enumerate(row):
            ref = f"{_column_name(col_idx)}{row_idx}"
            text = escape(str(value))
            cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{text}</t></is></c>')
        xml_rows.append(f'<row r="{row_idx}">{"".join(cells)}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(xml_rows)}</sheetData></worksheet>'
    )


def _write_minimal_xlsx(path: Path, sheets: Mapping[str, pd.DataFrame]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    names = list(sheets)
    workbook_sheets = "".join(
        f'<sheet name="{escape(name[:31])}" sheetId="{idx}" r:id="rId{idx}"/>'
        for idx, name in enumerate(names, 1)
    )
    workbook_rels = "".join(
        f'<Relationship Id="rId{idx}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{idx}.xml"/>'
        for idx, _ in enumerate(names, 1)
    )
    content_overrides = "".join(
        f'<Override PartName="/xl/worksheets/sheet{idx}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for idx, _ in enumerate(names, 1)
    )
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            f"{content_overrides}</Types>",
        )
        zf.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>",
        )
        zf.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f"<sheets>{workbook_sheets}</sheets></workbook>",
        )
        zf.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{workbook_rels}</Relationships>',
        )
        for idx, (_, frame) in enumerate(sheets.items(), 1):
            zf.writestr(f"xl/worksheets/sheet{idx}.xml", _worksheet_xml(frame))


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
    stem = f"input_matrix_{asof_date}"
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


def _summary_lines(matrix: pd.DataFrame) -> list[str]:
    paths = matrix.attrs.get("output_paths") or {}
    lines = [
        "Input diagnostic complete.",
        f"As-of date: {matrix.attrs.get('asof_date')}",
        f"Total expected inputs: {len(matrix)}",
        f"Available current inputs: {int(matrix['available_current'].sum())}",
        f"In ForecastInputSet: {int(matrix['in_forecast_input_set'].sum())}",
        f"Used in deterministic math: {int(matrix['used_in_deterministic'].sum())}",
        f"Used in historical similarity: {int(matrix['included_in_analogue_v2'].sum())}",
        f"Missing current: {int((~matrix['available_current']).sum())}",
        f"Missing historical columns: {int((matrix['missing_historical_reason'] == 'historical_column_missing').sum())}",
        f"Sparse historical columns: {int((matrix['missing_historical_reason'] == 'historical_column_sparse').sum())}",
    ]
    if paths.get("csv"):
        lines.append(f"CSV saved to: {paths['csv']}")
    if paths.get("xlsx"):
        lines.append(f"XLSX saved to: {paths['xlsx']}")
    if paths.get("json"):
        lines.append(f"JSON saved to: {paths['json']}")
    return lines


def _print_missing(matrix: pd.DataFrame) -> None:
    missing = matrix[
        (~matrix["available_current"])
        | (matrix["missing_historical_reason"].isin(["historical_column_missing", "historical_column_sparse"]))
        | (~matrix["in_forecast_input_set"])
    ]
    if missing.empty:
        print("No missing or sparse inputs.")
        return
    cols = ["input_id", "group", "coverage_status", "missing_current_reason", "missing_historical_reason"]
    print(missing[cols].to_string(index=False))


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the Helix macro forecast input diagnostic matrix.")
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
    matrix = build_input_diagnostic_matrix(
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
