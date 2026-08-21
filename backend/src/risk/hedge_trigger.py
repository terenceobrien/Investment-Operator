"""Validated hedge-trigger state for Portfolio Monitor.

This module deliberately separates:

1. data adapters that read already-built Helix data artifacts/providers, and
2. pure evaluation functions that apply fixed production thresholds.

It does not size hedges or construct trades.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timezone
from typing import Any, Mapping

import pandas as pd

from src.agent_system.paths import backend_root, project_root


BREADTH_DISPERSION_20D_THRESHOLD = 0.1243
BREADTH_NEW_LOWS_252D_THRESHOLD = 4.87
BREADTH_PCT_ABOVE_20D_CHG_5D_THRESHOLD = -25.1
BREADTH_PCT_ABOVE_50D_CHG_10D_THRESHOLD = -21.4
BREADTH_PCT_ABOVE_200D_CHG_10D_THRESHOLD = -10.1
BREADTH_SECTOR_DECLINE_COUNT_THRESHOLD = 10.0
BREADTH_SECTOR_DECLINE_PCT_THRESHOLD = 10.0 / 11.0 * 100.0

CREDIT_BAA10Y_THRESHOLD = 3.08
CREDIT_BAA_AAA_THRESHOLD = 1.24
CREDIT_BAA10Y_CHG_10D_THRESHOLD = 0.09
CREDIT_BAA_AAA_CHG_10D_THRESHOLD = 0.05

VOL_VIX_THRESHOLD = 27.0
VOL_VIX_CHG_5D_THRESHOLD = 2.37
VOL_VVIX_THRESHOLD = 110.1


def _num(value: Any) -> float | None:
    try:
        if value is None or value is pd.NA:
            return None
        out = float(value)
        return out if math.isfinite(out) else None
    except Exception:
        return None


def _bool_or_none(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)


def _iso_date(value: Any) -> str | None:
    if value is None:
        return None
    try:
        ts = pd.Timestamp(value)
        if pd.isna(ts):
            return None
        return ts.date().isoformat()
    except Exception:
        return str(value)


def _age_days(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return (date.today() - pd.Timestamp(value).date()).days
    except Exception:
        return None


def _status_from_values(values: list[Any], *, optional_missing_ok: bool = False) -> str:
    available = sum(_num(v) is not None for v in values)
    if available == 0:
        return "unavailable"
    if available < len(values) and not optional_missing_ok:
        return "partial"
    return "available"


def _format_value(value: float | None, unit: str) -> str:
    if value is None:
        return "unavailable"
    if unit == "decimal_return":
        return f"{value * 100.0:.2f}%"
    if unit == "percent":
        return f"{value:.1f}%"
    if unit == "percentage_points":
        return f"{value:+.1f} pp"
    if unit == "spread_points":
        return f"{value:.2f}%"
    if unit == "spread_change_points":
        return f"{value:+.2f} pp"
    if unit == "index_points":
        return f"{value:.2f}"
    if unit == "index_change_points":
        return f"{value:+.2f}"
    if unit == "count":
        return f"{value:.0f}"
    return f"{value:.4f}"


def _format_threshold(value: float | None, direction: str | None, unit: str) -> str | None:
    if value is None or direction not in {"high", "low"}:
        return None
    prefix = ">=" if direction == "high" else "<="
    return f"{prefix} {_format_value(value, unit).lstrip('+')}"


def _metric(
    *,
    label: str,
    value: float | None,
    threshold: float | None,
    direction: str | None,
    unit: str,
    reason: str | None = None,
) -> dict[str, Any]:
    trigger = None
    if value is not None and threshold is not None and direction in {"high", "low"}:
        trigger = value >= threshold if direction == "high" else value <= threshold
    return {
        "label": label,
        "value": value,
        "threshold": threshold,
        "direction": direction,
        "trigger": trigger,
        "unit": unit,
        "display_value": _format_value(value, unit),
        "display_threshold": _format_threshold(threshold, direction, unit),
        "reason": reason,
    }


def _trigger_count(metrics: Mapping[str, Mapping[str, Any]]) -> int:
    return sum(1 for metric in metrics.values() if metric.get("trigger") is True)


def _firing_names(metrics: Mapping[str, Mapping[str, Any]]) -> list[str]:
    return [name for name, metric in metrics.items() if metric.get("trigger") is True]


def _reasons(metrics: Mapping[str, Mapping[str, Any]]) -> list[str]:
    return [
        str(metric["reason"])
        for metric in metrics.values()
        if metric.get("trigger") is True and metric.get("reason")
    ]


def _breadth_label(count: int) -> str:
    if count >= 3:
        return "severe"
    if count >= 1:
        return "fragile"
    return "normal"


def _sector_threshold(value: float | None, metrics: Mapping[str, Any]) -> tuple[float, str]:
    unit = str(metrics.get("sectors_50dma_declining_10d_unit") or "").lower()
    if unit in {"count", "sectors"}:
        return BREADTH_SECTOR_DECLINE_COUNT_THRESHOLD, "count"
    if unit in {"percent", "pct", "percentage"}:
        return BREADTH_SECTOR_DECLINE_PCT_THRESHOLD, "percent"
    if value is None:
        return BREADTH_SECTOR_DECLINE_PCT_THRESHOLD, "percent"
    if value > 11:
        return BREADTH_SECTOR_DECLINE_PCT_THRESHOLD, "percent"
    return BREADTH_SECTOR_DECLINE_COUNT_THRESHOLD, "count"


def _dispersion_threshold(value: float | None) -> tuple[float, str]:
    if value is not None and abs(value) > 1.0:
        return 12.43, "percent"
    return BREADTH_DISPERSION_20D_THRESHOLD, "decimal_return"


def evaluate_breadth_state(metrics: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate fixed Breadth High-Recall conditions."""
    dispersion = _num(metrics.get("dispersion_20d"))
    dispersion_threshold, dispersion_unit = _dispersion_threshold(dispersion)
    sector_ratio = _num(metrics.get("sectors_50dma_declining_10d"))
    sector_count = _num(metrics.get("sector_deterioration_count"))
    valid_sector_count = _num(metrics.get("valid_sector_count"))
    if valid_sector_count is not None:
        # The validated rule is exactly 10 of 11 sectors. If all sectors are not
        # represented, this one condition is unavailable rather than rescaled.
        sector_value = sector_count if valid_sector_count == 11 else None
        sector_threshold, sector_unit = BREADTH_SECTOR_DECLINE_COUNT_THRESHOLD, "count"
    else:
        # Backward-compatible pure evaluator input for callers/tests that provide
        # either the legacy count or 0-100 percentage representation.
        sector_value = sector_ratio
        sector_threshold, sector_unit = _sector_threshold(sector_value, metrics)

    metric_map = {
        "dispersion_20d": _metric(
            label="20d cross-sectional return dispersion",
            value=dispersion,
            threshold=dispersion_threshold,
            direction="high",
            unit=dispersion_unit,
            reason="20d return dispersion above threshold",
        ),
        "pct_new_lows_252d": _metric(
            label="S&P 500 members at 252d new lows",
            value=_num(metrics.get("pct_new_lows_252d")),
            threshold=BREADTH_NEW_LOWS_252D_THRESHOLD,
            direction="high",
            unit="percent",
            reason="252d new lows above threshold",
        ),
        "pct_above_20dma": _metric(
            label="% above 20DMA",
            value=_num(metrics.get("pct_above_20dma")),
            threshold=None,
            direction=None,
            unit="percent",
        ),
        "pct_above_50dma": _metric(
            label="% above 50DMA",
            value=_num(metrics.get("pct_above_50dma")),
            threshold=None,
            direction=None,
            unit="percent",
        ),
        "pct_above_200dma": _metric(
            label="% above 200DMA",
            value=_num(metrics.get("pct_above_200dma")),
            threshold=None,
            direction=None,
            unit="percent",
        ),
        "pct_above_20dma_chg_5d": _metric(
            label="5d change in % above 20DMA",
            value=_num(metrics.get("pct_above_20dma_chg_5d")),
            threshold=BREADTH_PCT_ABOVE_20D_CHG_5D_THRESHOLD,
            direction="low",
            unit="percentage_points",
            reason="20DMA breadth velocity below threshold",
        ),
        "pct_above_50dma_chg_10d": _metric(
            label="10d change in % above 50DMA",
            value=_num(metrics.get("pct_above_50dma_chg_10d")),
            threshold=BREADTH_PCT_ABOVE_50D_CHG_10D_THRESHOLD,
            direction="low",
            unit="percentage_points",
            reason="50DMA breadth velocity below threshold",
        ),
        "pct_above_200dma_chg_10d": _metric(
            label="10d change in % above 200DMA",
            value=_num(metrics.get("pct_above_200dma_chg_10d")),
            threshold=BREADTH_PCT_ABOVE_200D_CHG_10D_THRESHOLD,
            direction="low",
            unit="percentage_points",
            reason="200DMA breadth velocity below threshold",
        ),
        "sectors_50dma_declining_10d": _metric(
            label="Sectors with declining 50DMA breadth over 10d",
            value=sector_value,
            threshold=sector_threshold,
            direction="high",
            unit=sector_unit,
            reason="Sector breadth deterioration above threshold",
        ),
    }
    firing = _firing_names(metric_map)
    count = len(firing)
    required_values = [
        metric_map["dispersion_20d"]["value"],
        metric_map["pct_new_lows_252d"]["value"],
        metric_map["pct_above_20dma_chg_5d"]["value"],
        metric_map["pct_above_50dma_chg_10d"]["value"],
        metric_map["pct_above_200dma_chg_10d"]["value"],
        metric_map["sectors_50dma_declining_10d"]["value"],
    ]
    latest_date = _iso_date(metrics.get("latest_observation_date"))
    stale_days = _age_days(latest_date)
    is_stale = metrics.get("is_stale")
    if is_stale is None:
        is_stale = stale_days is not None and stale_days > 5
    source_quality = metrics.get("data_quality")
    if not isinstance(source_quality, Mapping):
        source_quality = {}
    return {
        "status": _status_from_values(required_values),
        "as_of": _iso_date(metrics.get("as_of")) or latest_date,
        "data_source": metrics.get("data_source") or metrics.get("source"),
        "latest_observation_date": latest_date,
        "is_stale": bool(is_stale),
        "stale": bool(is_stale),
        "stale_days": stale_days,
        "metrics": metric_map,
        "bhr_active": count > 0 if any(v is not None for v in required_values) else None,
        "signals_firing": count,
        "firing_signals": firing,
        "state_label": _breadth_label(count),
        "reasons": _reasons(metric_map),
        "sector_deterioration_count": sector_count,
        "sectors_50dma_declining_10d": sector_ratio,
        "valid_sector_count": valid_sector_count,
        "data_quality": {
            "source": metrics.get("data_source") or metrics.get("source"),
            "source_path": metrics.get("source_path"),
            "member_count": _num(metrics.get("member_count")),
            "price_count": _num(metrics.get("price_count")),
            "price_coverage_pct": _num(metrics.get("price_coverage_pct")),
            "breadth_data_quality_ok": _bool_or_none(metrics.get("breadth_data_quality_ok")),
            "valid_sector_count": valid_sector_count,
            "expected_latest_session": metrics.get("expected_latest_session"),
            "history": metrics.get("history"),
            "requested_constituent_count": _num(
                source_quality.get("requested_constituent_count")
            ),
            "successful_ticker_count": _num(
                source_quality.get("successful_ticker_count")
            ),
            "failed_ticker_count": _num(source_quality.get("failed_ticker_count")),
            "failed_tickers": list(source_quality.get("failed_tickers") or []),
            "valid_20dma_count": _num(metrics.get("valid_20dma_count")),
            "valid_50dma_count": _num(metrics.get("valid_50dma_count")),
            "valid_200dma_count": _num(metrics.get("valid_200dma_count")),
            "valid_252d_count": _num(metrics.get("valid_252d_count")),
            "live_download_attempted": source_quality.get("live_download_attempted"),
            "live_download_succeeded": source_quality.get("live_download_succeeded"),
            "cached_fallback_used": source_quality.get("cached_fallback_used"),
            "constituent_cache_path": source_quality.get("constituent_cache_path"),
            "warnings": list(source_quality.get("warnings") or []),
        },
    }


def evaluate_credit_state(metrics: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate backtest-consistent Moody's Baa credit stress triggers."""
    metric_map = {
        "baa10y": _metric(
            label="Moody's Baa minus 10Y Treasury",
            value=_num(metrics.get("baa10y")),
            threshold=CREDIT_BAA10Y_THRESHOLD,
            direction="high",
            unit="spread_points",
            reason="BAA-10Y spread above stress threshold",
        ),
        "baa_aaa": _metric(
            label="Moody's Baa minus Aaa yield spread",
            value=_num(metrics.get("baa_aaa")),
            threshold=CREDIT_BAA_AAA_THRESHOLD,
            direction="high",
            unit="spread_points",
            reason="BAA-AAA spread above stress threshold",
        ),
        "baa10y_chg_10d": _metric(
            label="10-observation widening in BAA-10Y",
            value=_num(metrics.get("baa10y_chg_10d")),
            threshold=CREDIT_BAA10Y_CHG_10D_THRESHOLD,
            direction="high",
            unit="spread_change_points",
            reason="BAA-10Y spread widening above threshold",
        ),
        "baa_aaa_chg_10d": _metric(
            label="10-observation widening in BAA-AAA",
            value=_num(metrics.get("baa_aaa_chg_10d")),
            threshold=CREDIT_BAA_AAA_CHG_10D_THRESHOLD,
            direction="high",
            unit="spread_change_points",
            reason="BAA-AAA spread widening above threshold",
        ),
        "hy_oas": _metric(
            label="HY OAS descriptive",
            value=_num(metrics.get("hy_oas")),
            threshold=None,
            direction=None,
            unit="spread_points",
        ),
        "ig_oas": _metric(
            label="IG / corporate OAS descriptive",
            value=_num(metrics.get("ig_oas")),
            threshold=None,
            direction=None,
            unit="spread_points",
        ),
    }
    trigger_metrics = {
        key: metric_map[key]
        for key in ("baa10y", "baa_aaa", "baa10y_chg_10d", "baa_aaa_chg_10d")
    }
    values = [metric["value"] for metric in trigger_metrics.values()]
    firing = _firing_names(trigger_metrics)
    latest_date = _iso_date(metrics.get("latest_observation_date"))
    stale_days = _age_days(latest_date)
    status = _status_from_values(values)
    return {
        "status": status,
        "latest_observation_date": latest_date,
        "stale": stale_days is not None and stale_days > 14,
        "stale_days": stale_days,
        "metrics": metric_map,
        "triggers": {key: metric["trigger"] for key, metric in trigger_metrics.items()},
        "conditions_firing": len(firing),
        "firing_signals": firing,
        "credit_stress": None if status == "unavailable" else len(firing) > 0,
        "reasons": _reasons(trigger_metrics),
        "data_quality": {
            "warnings": list(metrics.get("warnings") or []),
            "descriptive_hy_ig_not_used_for_trigger": True,
        },
    }


def evaluate_volatility_state(metrics: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate fixed VIX/VVIX stress triggers."""
    metric_map = {
        "vix": _metric(
            label="VIX",
            value=_num(metrics.get("vix")),
            threshold=VOL_VIX_THRESHOLD,
            direction="high",
            unit="index_points",
            reason="VIX above stress threshold",
        ),
        "vix_chg_5d": _metric(
            label="5d VIX change",
            value=_num(metrics.get("vix_chg_5d")),
            threshold=VOL_VIX_CHG_5D_THRESHOLD,
            direction="high",
            unit="index_change_points",
            reason="VIX 5d change above threshold",
        ),
        "vvix": _metric(
            label="VVIX",
            value=_num(metrics.get("vvix")),
            threshold=VOL_VVIX_THRESHOLD,
            direction="high",
            unit="index_points",
            reason="VVIX above stress threshold",
        ),
    }
    values = [metric["value"] for metric in metric_map.values()]
    firing = _firing_names(metric_map)
    latest_date = _iso_date(metrics.get("latest_observation_date"))
    stale_days = _age_days(latest_date)
    status = _status_from_values(values, optional_missing_ok=True)
    if status == "available" and any(v is None for v in values):
        status = "partial"
    return {
        "status": status,
        "latest_observation_date": latest_date,
        "stale": stale_days is not None and stale_days > 5,
        "stale_days": stale_days,
        "metrics": metric_map,
        "triggers": {key: metric["trigger"] for key, metric in metric_map.items()},
        "conditions_firing": len(firing),
        "firing_signals": firing,
        "vol_stress": None if status == "unavailable" else len(firing) > 0,
        "reasons": _reasons(metric_map),
        "data_quality": {
            "vvix_available": metric_map["vvix"]["value"] is not None,
            "warnings": list(metrics.get("warnings") or []),
        },
    }


def evaluate_combined_state(
    breadth: Mapping[str, Any],
    credit: Mapping[str, Any],
    volatility: Mapping[str, Any],
) -> dict[str, Any]:
    """Combine family states without implying hedge size or trade construction."""
    bhr = breadth.get("bhr_active")
    credit_active = credit.get("credit_stress")
    vol_active = volatility.get("vol_stress")
    reasons = [
        *list(breadth.get("reasons") or []),
        *list(credit.get("reasons") or []),
        *list(volatility.get("reasons") or []),
    ]

    if bhr is None:
        stage = None
        label = "Unavailable"
        combined: bool | None = None
    elif bhr is not True:
        stage = 0
        label = "Normal"
        combined = False
    elif credit_active is True and vol_active is True:
        stage = 3
        label = "Multi-Family Stress"
        combined = True
    elif credit_active is True or vol_active is True:
        stage = 2
        label = "Confirmed Hedge Trigger"
        combined = True
    else:
        stage = 1
        label = "Breadth Fragility"
        if credit_active is None or vol_active is None:
            combined = None
            reasons.append("Breadth is active but confirmation family data is incomplete")
        else:
            combined = False

    families_active_count = sum(
        1 for value in (bhr, credit_active, vol_active) if value is True
    )
    return {
        "stage": stage,
        "label": label,
        "combined_trigger": combined,
        "breadth_active": bhr,
        "credit_active": credit_active,
        "vol_active": vol_active,
        "families_active_count": families_active_count,
        "reasons": reasons,
        "portfolio_risk": None,
        "target_hedge_size": None,
    }


def load_breadth_inputs(asof_date: str | None = None) -> dict[str, Any]:
    """Load BHR inputs from the same live breadth object used by Layer 4."""
    try:
        from src.state.regime_data import get_live_breadth_state

        return get_live_breadth_state(asof_date=asof_date)
    except Exception as exc:
        return {
            "source": "yfinance_live",
            "data_source": "yfinance_live",
            "is_stale": True,
            "data_quality": {
                "warnings": [f"Could not build shared live breadth state: {exc}"]
            },
        }


def _series_change(series: pd.Series, periods: int) -> float | None:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if len(clean) <= periods:
        return None
    return float(clean.iloc[-1] - clean.iloc[-periods - 1])


def _latest(series: pd.Series) -> float | None:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    return float(clean.iloc[-1]) if not clean.empty else None


def _latest_series_date(series: pd.Series) -> str | None:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if clean.empty:
        return None
    return _iso_date(clean.index[-1])


def load_credit_inputs(asof_date: str | None = None) -> dict[str, Any]:
    """Fetch credit inputs through the existing FRED client mechanism."""
    warnings: list[str] = []
    try:
        from dotenv import load_dotenv

        load_dotenv()
        load_dotenv(project_root() / ".env.local")
        load_dotenv(backend_root() / ".env")
    except Exception as exc:
        warnings.append(f"dotenv load skipped: {exc}")
    try:
        from src.data.macro import _fred_client, _to_series

        fred = _fred_client()
    except Exception as exc:
        return {
            "latest_observation_date": None,
            "warnings": [f"FRED client unavailable: {exc}"],
        }

    def get_series(series_id: str) -> pd.Series:
        try:
            series = _to_series(fred.get_series(series_id)).dropna()
            if asof_date:
                series = series[series.index <= pd.Timestamp(asof_date)]
            return series.tail(520)
        except Exception as exc:
            warnings.append(f"FRED fetch failed for {series_id}: {exc}")
            return pd.Series(dtype=float)

    baa10y = get_series("BAA10Y")
    dbaa = get_series("DBAA")
    daaa = get_series("DAAA")
    hy = get_series("BAMLH0A0HYM2")
    ig = get_series("BAMLC0A0CM")

    baa_aaa = pd.Series(dtype=float)
    if not dbaa.empty and not daaa.empty:
        aligned = pd.concat([dbaa, daaa], axis=1, join="inner").dropna()
        if not aligned.empty:
            baa_aaa = aligned.iloc[:, 0] - aligned.iloc[:, 1]

    dates = [
        _latest_series_date(series)
        for series in (baa10y, baa_aaa, hy, ig)
        if not series.empty
    ]
    latest_date = max(dates) if dates else None
    return {
        "latest_observation_date": latest_date,
        "baa10y": _latest(baa10y),
        "baa10y_chg_10d": _series_change(baa10y, 10),
        "baa_aaa": _latest(baa_aaa),
        "baa_aaa_chg_10d": _series_change(baa_aaa, 10),
        "hy_oas": _latest(hy),
        "ig_oas": _latest(ig),
        "warnings": warnings,
    }


def load_volatility_inputs(asof_date: str | None = None) -> dict[str, Any]:
    """Fetch VIX/VVIX using the existing regime yfinance helper."""
    warnings: list[str] = []
    try:
        from src.state.regime_data import _yf_close

        vix = _yf_close("^VIX", period="3mo", asof_date=asof_date)
        vvix = _yf_close("^VVIX", period="3mo", asof_date=asof_date)
    except Exception as exc:
        warnings.append(f"yfinance volatility fetch failed: {exc}")
        vix = pd.Series(dtype=float)
        vvix = pd.Series(dtype=float)

    if vix.empty:
        try:
            from src.state.regime_state import RegimeState

            snap = (
                RegimeState.load_snapshot(asof_date)
                if asof_date
                else RegimeState.load_latest_snapshot()
            )
            if snap and snap.vix_level is not None:
                warnings.append("Using latest regime snapshot for VIX level fallback")
                return {
                    "latest_observation_date": snap.asof_date,
                    "vix": snap.vix_level,
                    "vix_chg_5d": None,
                    "vvix": None,
                    "warnings": warnings,
                }
        except Exception as exc:
            warnings.append(f"regime snapshot VIX fallback failed: {exc}")

    dates = [
        _latest_series_date(series)
        for series in (vix, vvix)
        if not series.empty
    ]
    return {
        "latest_observation_date": max(dates) if dates else None,
        "vix": _latest(vix),
        "vix_chg_5d": _series_change(vix, 5),
        "vvix": _latest(vvix),
        "warnings": warnings,
    }


def get_hedge_trigger_state(asof_date: str | None = None) -> dict[str, Any]:
    """Return the full serializable hedge-trigger state for Portfolio Monitor."""
    breadth = evaluate_breadth_state(load_breadth_inputs(asof_date=asof_date))
    credit = evaluate_credit_state(load_credit_inputs(asof_date=asof_date))
    volatility = evaluate_volatility_state(load_volatility_inputs(asof_date=asof_date))
    hedge_state = evaluate_combined_state(breadth, credit, volatility)

    unavailable = [
        name
        for name, state in (
            ("breadth", breadth),
            ("credit", credit),
            ("volatility", volatility),
        )
        if state.get("status") == "unavailable"
    ]
    stale = [
        name
        for name, state in (
            ("breadth", breadth),
            ("credit", credit),
            ("volatility", volatility),
        )
        if state.get("stale") is True
    ]

    return _serializable(
        {
            "as_of": (asof_date or date.today().isoformat()),
            "asof_utc": datetime.now(timezone.utc).isoformat(),
            "breadth": breadth,
            "credit": credit,
            "volatility": volatility,
            "hedge_state": hedge_state,
            "data_quality": {
                "unavailable_families": unavailable,
                "stale_families": stale,
                "combined_trigger_evaluable": hedge_state.get("combined_trigger") is not None,
                "notes": [
                    "Forward-looking outcomes and hedge sizing are not used in this state.",
                    "HY OAS and IG OAS are descriptive only; validated credit triggers use BAA10Y and BAA-AAA.",
                ],
            },
        }
    )


def _serializable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _serializable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_serializable(v) for v in value]
    if isinstance(value, tuple):
        return [_serializable(v) for v in value]
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return value
