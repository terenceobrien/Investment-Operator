"""Authenticated macro forecast report endpoints."""
from __future__ import annotations

import json
import logging
import os
import math
import inspect
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from api.auth import verify_clerk_token
from src.agent_system.paths import (
    analogue_fans_dir_info,
    data_root_info,
    macro_json_dir_info,
    project_root,
    resolved_path_message,
)
from src.agent_system.forecasting.input_signals import RAW_INPUT_FIELD_MAP


macro_router = APIRouter(prefix="/api/macro", tags=["macro"])
logger = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = project_root()
RUNNER_COMMAND = (
    "PYTHONPATH=backend python3 -m "
    "src.agent_system.forecasting.macro_forecast_runner --allow-stale-bvar"
)

# Uvicorn does not automatically load local env files. Loading them here keeps
# the history endpoint aligned with the storage/backfill scripts without
# hardcoding secrets or filesystem-specific paths in code.
load_dotenv()
load_dotenv(REPO_ROOT / ".env.local")
load_dotenv(BACKEND_ROOT / ".env")


def _forecast_root_info():
    return macro_json_dir_info(create=False)


def _forecast_root() -> Path:
    return _forecast_root_info().path


def _forecast_candidate_paths(root: Path, source: str) -> list[Path]:
    if not root.exists():
        raise FileNotFoundError(
            f"Macro forecast JSON directory not found: {root} "
            f"(resolution_source={source}). "
            f"Generate it with: {RUNNER_COMMAND}"
        )

    candidates = list(root.glob("macro_forecast_*.json"))
    unique: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(candidate)
    if not unique:
        raise FileNotFoundError(
            f"No macro_forecast_*.json files found in {root} "
            f"(resolution_source={source}). "
            f"Generate one with: {RUNNER_COMMAND}"
        )
    return unique


def _read_json_file(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON artifact is invalid: {path}: {exc}") from exc


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _forecast_timestamp(payload: Any, path: Path) -> datetime:
    if isinstance(payload, dict):
        parsed = _parse_timestamp(payload.get("created_at"))
        if parsed is not None:
            return parsed
        logger.warning(
            "macro forecast artifact missing/unparseable created_at; falling back to mtime: path=%s",
            path,
        )
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def _latest_forecast_artifact() -> tuple[Path, dict[str, Any]]:
    root_info = _forecast_root_info()
    candidates = _forecast_candidate_paths(root_info.path, root_info.source)
    loaded: list[tuple[datetime, str, Path, dict[str, Any]]] = []
    for candidate in candidates:
        payload = _read_json_file(candidate)
        if not isinstance(payload, dict):
            raise ValueError(f"Macro forecast artifact must be a JSON object: {candidate}")
        loaded.append((_forecast_timestamp(payload, candidate), candidate.name, candidate, payload))
    _, _, path, payload = max(loaded, key=lambda item: (item[0], item[1]))
    return path, payload


def _latest_forecast_path() -> Path:
    path, _ = _latest_forecast_artifact()
    return path


def _validate_two_source_forecast(payload: dict[str, Any], path: Path) -> None:
    mode = payload.get("probability_mode")
    if mode != "two_source_v1":
        raise HTTPException(
            status_code=409,
            detail=(
                f"Latest macro forecast artifact is stale or retired: {path} "
                f"has probability_mode={mode!r}; expected 'two_source_v1'. "
                f"Regenerate with: {RUNNER_COMMAND}"
            ),
        )


def _latest_two_source_forecast() -> tuple[Path, dict[str, Any]]:
    path, payload = _latest_forecast_artifact()
    _validate_two_source_forecast(payload, path)
    return path, payload


def _asof_metadata(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifact_path": str(path),
        "asof_date": payload.get("asof_date"),
        "created_at": payload.get("created_at"),
        "probability_mode": payload.get("probability_mode"),
    }


def _resolve_artifact_path(value: Any) -> tuple[Path, str]:
    if not isinstance(value, str) or not value.strip():
        fan_info = analogue_fans_dir_info(create=False)
        raise FileNotFoundError(
            "Latest forecast does not reference analogue_fan_artifact_path. "
            f"Expected under {fan_info.path} (resolution_source={fan_info.source}). "
            f"Regenerate with: {RUNNER_COMMAND}"
        )
    path = Path(value)
    if path.is_absolute():
        fan_info = analogue_fans_dir_info(create=False)
        candidate = fan_info.path / path.name
        logger.info(
            "Resolved legacy absolute analogue fan artifact path by basename: stored=%s candidate=%s",
            path,
            candidate,
        )
        return candidate, fan_info.source
    root_info = data_root_info(create=False)
    path_parts = path.parts
    data_relative = Path(*path_parts[1:]) if path_parts and path_parts[0] == "data" else path
    return root_info.path / data_relative, root_info.source


@lru_cache(maxsize=1)
def _behavioral_scenario_meta() -> dict[str, dict[str, str]]:
    from src.agent_system.forecasting.behavioral_scenarios_loader import (
        load_behavioral_scenarios,
    )

    scenarios = load_behavioral_scenarios()
    return {
        scenario_id: {
            "display_name": scenario.label,
            "short_description": " ".join(str(scenario.definition).split()),
        }
        for scenario_id, scenario in scenarios.items()
    }


def _backtest_master_candidates() -> list[Path]:
    """Return candidate paths for the historical backtest master file."""
    env_path = os.environ.get("RESEARCH_DATA_PATH")
    explicit_path = os.environ.get("BACKTEST_MASTER_FILE") or os.environ.get(
        "BACKTEST_MASTER_PATH"
    )
    paths: list[Path] = []
    if explicit_path:
        paths.append(Path(explicit_path))
    if env_path:
        paths.append(Path(env_path))
    root_info = data_root_info(create=False)
    paths.extend(
        [
            root_info.path / "operator_research_v3.csv",
            root_info.path / "backtest_master_file.csv",
        ]
    )
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        resolved = str(path.expanduser())
        if resolved not in seen:
            seen.add(resolved)
            unique.append(Path(resolved))
    return unique


def _resolve_backtest_master_path() -> Path | None:
    for path in _backtest_master_candidates():
        if path.exists():
            return path
    return None


def _backtest_not_found_warning() -> str:
    root_info = data_root_info(create=False)
    checked = ", ".join(str(path) for path in _backtest_master_candidates())
    return (
        f"{resolved_path_message('Backtest master data root', root_info)}; "
        f"checked: {checked}"
    )


def _empty_history_frame() -> pd.DataFrame:
    return pd.DataFrame(index=pd.DatetimeIndex([], name="date"))


def _load_regime_history_frame(days: int) -> tuple[pd.DataFrame, str | None]:
    """Load the canonical regime time series, returning a warning on failure."""
    try:
        from src.agent_system.regime.timeseries import load_regime_timeseries

        end = pd.Timestamp.utcnow().normalize().tz_localize(None)
        start = end - pd.Timedelta(days=days)
        df = load_regime_timeseries(
            start_date=start.strftime("%Y-%m-%d"),
            end_date=end.strftime("%Y-%m-%d"),
        )
        if df.empty:
            return _empty_history_frame(), None
        df = df.copy()
        df.index = pd.to_datetime(df.index, errors="coerce")
        df = df[df.index.notna()].sort_index()
        df.index.name = "date"
        return df, None
    except Exception as exc:  # pragma: no cover - storage backend can vary by env
        return _empty_history_frame(), f"regime_timeseries unavailable: {exc}"


REGIME_SCORE_HISTORY_WINDOWS: dict[str, int | None] = {
    "90d": 90,
    "1y": 365,
    "5y": 365 * 5,
    "all": None,
}


def _load_regime_score_history_frame(window: str) -> pd.DataFrame:
    """Load score_total from the canonical regime_states history."""
    if window not in REGIME_SCORE_HISTORY_WINDOWS:
        raise ValueError(f"Unsupported regime score history window: {window}")

    from src.agent_system.regime.timeseries import load_regime_timeseries

    end = pd.Timestamp.utcnow().normalize().tz_localize(None)
    days = REGIME_SCORE_HISTORY_WINDOWS[window]
    start_date = None if days is None else (end - pd.Timedelta(days=days)).strftime("%Y-%m-%d")
    df = load_regime_timeseries(
        start_date=start_date,
        end_date=end.strftime("%Y-%m-%d"),
    )
    if df.empty:
        raise FileNotFoundError(
            "No historical regime scores found in canonical regime_states storage. "
            "Backfill with: PYTHONPATH=backend python3 scripts/backfill_regime_states.py"
        )
    df = df.copy()
    df.index = pd.to_datetime(df.index, errors="coerce")
    df = df[df.index.notna()].sort_index()
    df.index.name = "date"
    if "score_total" not in df.columns:
        raise FileNotFoundError(
            "Canonical regime_states storage has no score_total column. "
            "Backfill with: PYTHONPATH=backend python3 scripts/backfill_regime_states.py"
        )
    return df


def _build_regime_score_history_payload(window: str) -> dict[str, Any]:
    df = _load_regime_score_history_frame(window)
    points = _numeric_points(df, "score_total")
    if not points:
        raise FileNotFoundError(
            "No numeric score_total values found in canonical regime_states storage. "
            "Backfill with: PYTHONPATH=backend python3 scripts/backfill_regime_states.py"
        )
    return {
        "window": window,
        "source": "regime_timeseries",
        "storage_collection": "regime_states",
        "score_column": "score_total",
        "start_date": points[0]["date"],
        "end_date": points[-1]["date"],
        "n": len(points),
        "points": points,
        "available_windows": list(REGIME_SCORE_HISTORY_WINDOWS),
    }


def _load_backtest_history_frame(days: int) -> tuple[pd.DataFrame, str | None]:
    path = _resolve_backtest_master_path()
    if path is None:
        return _empty_history_frame(), _backtest_not_found_warning()

    try:
        df = pd.read_csv(path)
    except Exception as exc:
        return _empty_history_frame(), f"backtest master file unreadable: {exc}"

    if "date" not in df.columns:
        return _empty_history_frame(), f"backtest master file missing date column: {path}"

    if "signal_time" in df.columns:
        close_rows = df[df["signal_time"].astype(str).str.lower() == "close"]
        if not close_rows.empty:
            df = close_rows

    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce", format="mixed")
    df = df[df["date"].notna()].sort_values("date")
    if df.empty:
        return _empty_history_frame(), None

    cutoff = pd.Timestamp.utcnow().normalize().tz_localize(None) - pd.Timedelta(days=days)
    df = df[df["date"] >= cutoff]
    df = df.drop_duplicates(subset=["date"], keep="last").set_index("date").sort_index()
    df.index.name = "date"
    return df, None


def _numeric_points(df: pd.DataFrame, column: str) -> list[dict[str, float | str]]:
    if df.empty or column not in df.columns:
        return []

    values = pd.to_numeric(df[column], errors="coerce").dropna()
    if values.empty:
        return []

    points: list[dict[str, float | str]] = []
    for idx, value in values.items():
        numeric = float(value)
        if pd.notna(numeric):
            points.append({"date": pd.Timestamp(idx).strftime("%Y-%m-%d"), "value": numeric})
    return points


def _build_indicator_history_payload(days: int) -> dict[str, Any]:
    regime_df, regime_warning = _load_regime_history_frame(days)
    master_df, master_warning = _load_backtest_history_frame(days)

    columns = sorted(set(regime_df.columns).union(set(master_df.columns)))
    series: dict[str, Any] = {}
    source_counts = {"regime_timeseries": 0, "backtest_master_file": 0}

    for column in columns:
        regime_points = _numeric_points(regime_df, column)
        if regime_points:
            series[column] = {
                "column": column,
                "source": "regime_timeseries",
                "points": regime_points,
            }
            source_counts["regime_timeseries"] += 1
            continue

        master_points = _numeric_points(master_df, column)
        if master_points:
            series[column] = {
                "column": column,
                "source": "backtest_master_file",
                "points": master_points,
            }
            source_counts["backtest_master_file"] += 1

    dates = [
        pd.Timestamp(idx)
        for df in (regime_df, master_df)
        for idx in df.index
        if pd.notna(idx)
    ]
    warnings = [w for w in (regime_warning, master_warning) if w]

    return {
        "start_date": min(dates).strftime("%Y-%m-%d") if dates else None,
        "end_date": max(dates).strftime("%Y-%m-%d") if dates else None,
        "days": days,
        "series": series,
        "source_counts": source_counts,
        "warnings": warnings,
    }


REGIME_LAYER_IDS = ("monetary", "credit", "volatility", "breadth", "positioning")
REGIME_LAYER_NAMES = {
    "monetary": "Monetary & Liquidity",
    "credit": "Credit & Stress",
    "volatility": "Volatility Structure",
    "breadth": "Breadth & Participation",
    "positioning": "Positioning & Sentiment",
}


@dataclass(frozen=True)
class ComponentSpec:
    layer_id: str
    component_id: str
    display_name: str
    units_note: str | None
    score_kind: str | None
    scale_lo_key: str | None = None
    scale_hi_key: str | None = None
    invert: bool = False
    raw_weight_key: str | None = None
    aliases: tuple[str, ...] = ()
    unscored_reason: str | None = None

    @property
    def scored(self) -> bool:
        return self.score_kind is not None


def _component_aliases(component_id: str, *extra: str) -> tuple[str, ...]:
    aliases: list[str] = []
    for value in (component_id, *RAW_INPUT_FIELD_MAP.get(component_id, []), *extra):
        if value and value not in aliases:
            aliases.append(value)
    return tuple(aliases)


COMPONENT_SPECS: dict[str, tuple[ComponentSpec, ...]] = {
    "monetary": (
        ComponentSpec("monetary", "net_liquidity_z", "Net liquidity z-score", "z-score", "scale", "monetary.net_liquidity_z.scale_lo", "monetary.net_liquidity_z.scale_hi", aliases=_component_aliases("net_liquidity_z")),
        ComponentSpec("monetary", "nfci_inverted", "NFCI inverted", "inverted z-score", "scale", "monetary.nfci_inverted.scale_lo", "monetary.nfci_inverted.scale_hi", aliases=_component_aliases("nfci_inverted")),
        ComponentSpec("monetary", "m2_growth_yoy", "M2 growth YoY", "% y/y", "scale", "monetary.m2_growth_yoy.scale_lo", "monetary.m2_growth_yoy.scale_hi", aliases=_component_aliases("m2_growth_yoy")),
        ComponentSpec("monetary", "fci_z", "Financial conditions z-score", "z-score", "scale", "monetary.fci_z.scale_lo", "monetary.fci_z.scale_hi", aliases=_component_aliases("fci_z")),
    ),
    "credit": (
        ComponentSpec("credit", "hy_spread_level", "HY spread level", "bps", "scale", "credit.hy_spread_level.scale_lo", "credit.hy_spread_level.scale_hi", invert=True, aliases=_component_aliases("hy_spread_level", "hy_oas")),
        ComponentSpec("credit", "hy_spread_z", "HY spread z-score", "z-score", "scale", "credit.hy_spread_z.scale_lo", "credit.hy_spread_z.scale_hi", invert=True, aliases=_component_aliases("hy_spread_z")),
        ComponentSpec("credit", "hy_spread_chg_4w", "HY spread change 4W", "bps", "scale", "credit.hy_spread_chg_4w.scale_lo", "credit.hy_spread_chg_4w.scale_hi", invert=True, aliases=_component_aliases("hy_spread_chg_4w")),
        ComponentSpec("credit", "ig_spread_level", "IG spread level", "bps", "scale", "credit.ig_spread_level.scale_lo", "credit.ig_spread_level.scale_hi", invert=True, aliases=_component_aliases("ig_spread_level", "ig_oas")),
        ComponentSpec("credit", "ig_spread_z", "IG spread z-score", "z-score", None, aliases=_component_aliases("ig_spread_z"), unscored_reason="Captured in layer inputs/data quality but not scored by score_credit()."),
        ComponentSpec("credit", "hyg_tlt_ratio_z", "HYG/TLT ratio z-score", "z-score", "scale", "credit.hyg_tlt_ratio_z.scale_lo", "credit.hyg_tlt_ratio_z.scale_hi", aliases=_component_aliases("hyg_tlt_ratio_z", "hyg_minus_tlt")),
    ),
    "volatility": (
        ComponentSpec("volatility", "vix_level", "VIX level", "index", "scale", "volatility.vix_level.scale_lo", "volatility.vix_level.scale_hi", invert=True, aliases=_component_aliases("vix_level")),
        ComponentSpec("volatility", "vix_z_20d", "VIX z-score 20D", "z-score", "scale", "volatility.vix_z_20d.scale_lo", "volatility.vix_z_20d.scale_hi", invert=True, aliases=_component_aliases("vix_z_20d")),
        ComponentSpec("volatility", "vix_term_slope", "VIX term slope", "VIX3M - VIX", "scale", "volatility.vix_term_slope.scale_lo", "volatility.vix_term_slope.scale_hi", aliases=_component_aliases("vix_term_slope")),
        ComponentSpec("volatility", "vvix_level", "VVIX level", "index", "scale", "volatility.vvix_level.scale_lo", "volatility.vvix_level.scale_hi", invert=True, aliases=_component_aliases("vvix_level")),
        ComponentSpec("volatility", "vvix_z", "VVIX z-score", "z-score", None, aliases=_component_aliases("vvix_z"), unscored_reason="Captured in layer inputs/data quality but not scored by score_volatility()."),
        ComponentSpec("volatility", "put_call_ratio", "Put/call ratio", "ratio", "vol_put_call", aliases=_component_aliases("put_call_ratio", "put_call_5d_ma")),
        ComponentSpec("volatility", "skew_index", "SKEW index", "index", "scale", "volatility.skew_index.scale_lo", "volatility.skew_index.scale_hi", invert=True, aliases=_component_aliases("skew_index", "skew_level")),
    ),
    "breadth": (
        ComponentSpec("breadth", "pct_above_200d", "% above 200D", "%", None, aliases=_component_aliases("pct_above_200d"), unscored_reason="Diagnostic display input; score_breadth() does not include it in the weighted average."),
        ComponentSpec("breadth", "avg_dist_from_200d", "Average distance from 200D", "%", "scale", "breadth.avg_dist_from_200d.scale_lo", "breadth.avg_dist_from_200d.scale_hi", raw_weight_key="breadth.avg_dist_from_200d.weight", aliases=_component_aliases("avg_dist_from_200d")),
        ComponentSpec("breadth", "sectors_green", "Sectors green", "count out of 11", "scale", "breadth.sectors_green.scale_lo", "breadth.sectors_green.scale_hi", raw_weight_key="breadth.sectors_green.weight", aliases=_component_aliases("sectors_green")),
        ComponentSpec("breadth", "rsp_vs_spy_z", "RSP vs SPY z-score", "z-score", "scale", "breadth.rsp_vs_spy_z.scale_lo", "breadth.rsp_vs_spy_z.scale_hi", raw_weight_key="breadth.rsp_vs_spy_z.weight", aliases=_component_aliases("rsp_vs_spy_z", "rsp_minus_spy")),
        ComponentSpec("breadth", "adl_slope", "Advance/decline slope", "20D slope", "scale", "breadth.adl_slope.scale_lo", "breadth.adl_slope.scale_hi", raw_weight_key="breadth.adl_slope.weight", aliases=_component_aliases("adl_slope")),
    ),
    "positioning": (
        ComponentSpec("positioning", "dealer_gamma_z", "Dealer gamma z-score", "z-score", "scale", "positioning.dealer_gamma_z.scale_lo", "positioning.dealer_gamma_z.scale_hi", aliases=_component_aliases("dealer_gamma_z")),
        ComponentSpec("positioning", "put_call_5d_ma", "Put/call 5D average", "ratio", "positioning_put_call", aliases=_component_aliases("put_call_5d_ma", "put_call_ratio")),
        ComponentSpec("positioning", "aaii_bull_minus_bear", "AAII bull minus bear", "percentage points", "aaii", aliases=_component_aliases("aaii_bull_minus_bear")),
        ComponentSpec("positioning", "cot_net_large_spec_z", "COT large spec z-score", "z-score", "scale", "positioning.cot_net_large_spec_z.scale_lo", "positioning.cot_net_large_spec_z.scale_hi", invert=True, aliases=_component_aliases("cot_net_large_spec_z")),
        ComponentSpec("positioning", "equity_etf_flow_z", "Equity ETF flow z-score", "z-score", "scale", "positioning.equity_etf_flow_z.scale_lo", "positioning.equity_etf_flow_z.scale_hi", invert=True, aliases=_component_aliases("equity_etf_flow_z")),
    ),
}


def _validate_component_specs_against_builder() -> None:
    from src.state import regime_layers

    builder_functions = {
        "monetary": regime_layers.score_monetary,
        "credit": regime_layers.score_credit,
        "volatility": regime_layers.score_volatility,
        "breadth": regime_layers.score_breadth,
        "positioning": regime_layers.score_positioning,
    }
    for layer_id, builder in builder_functions.items():
        signature_ids = tuple(inspect.signature(builder).parameters)
        spec_ids = tuple(spec.component_id for spec in COMPONENT_SPECS[layer_id])
        if signature_ids != spec_ids:
            raise RuntimeError(
                f"Macro layer component API is out of sync with {builder.__name__}: "
                f"builder={signature_ids}; api_specs={spec_ids}"
            )


def _component_spec(layer_id: str, component_id: str) -> ComponentSpec:
    for spec in COMPONENT_SPECS.get(layer_id, ()):
        if spec.component_id == component_id:
            return spec
    raise KeyError(f"Unknown macro layer component: {layer_id}/{component_id}")


def _safe_float_value(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None
    except (TypeError, ValueError):
        return None


def _scale_value(value: float, lo: float, hi: float, *, invert: bool = False) -> float:
    if hi == lo:
        return 5.0
    scaled = (value - lo) / (hi - lo) * 10.0
    clipped = max(0.0, min(10.0, scaled))
    return 10.0 - clipped if invert else clipped


def _regime_params():
    from src.state.config_loader import REGIME_PARAMS

    return REGIME_PARAMS


def _component_score(spec: ComponentSpec, value: Any) -> float | None:
    numeric = _safe_float_value(value)
    if numeric is None or not spec.scored:
        return None
    params = _regime_params()
    if spec.score_kind == "scale":
        if spec.scale_lo_key is None or spec.scale_hi_key is None:
            raise ValueError(f"Component {spec.component_id} is missing scale keys.")
        return _scale_value(
            numeric,
            float(params[spec.scale_lo_key]),
            float(params[spec.scale_hi_key]),
            invert=spec.invert,
        )
    if spec.score_kind == "vol_put_call":
        if numeric > params["volatility.put_call_ratio.fear_threshold"]:
            return float(params["volatility.put_call_ratio.fear_score"])
        if numeric < params["volatility.put_call_ratio.complacency_threshold"]:
            return float(params["volatility.put_call_ratio.complacency_score"])
        return _scale_value(
            numeric,
            float(params["volatility.put_call_ratio.complacency_threshold"]),
            float(params["volatility.put_call_ratio.fear_threshold"]),
        )
    if spec.score_kind == "positioning_put_call":
        if numeric > params["positioning.put_call_5d_ma.fear_threshold"]:
            return float(params["positioning.put_call_5d_ma.fear_score"])
        if numeric < params["positioning.put_call_5d_ma.complacency_threshold"]:
            return float(params["positioning.put_call_5d_ma.complacency_score"])
        return float(params["positioning.put_call_5d_ma.neutral_score"])
    if spec.score_kind == "aaii":
        if numeric < params["positioning.aaii_bull_minus_bear.panic_threshold"]:
            return float(params["positioning.aaii_bull_minus_bear.panic_score"])
        if numeric > params["positioning.aaii_bull_minus_bear.euphoria_threshold"]:
            return float(params["positioning.aaii_bull_minus_bear.euphoria_score"])
        return _scale_value(
            numeric,
            float(params["positioning.aaii_bull_minus_bear.scale_lo"]),
            float(params["positioning.aaii_bull_minus_bear.scale_hi"]),
            invert=True,
        )
    raise ValueError(f"Unknown component score_kind={spec.score_kind!r} for {spec.component_id}.")


def _find_history_series(history_payload: dict[str, Any], aliases: tuple[str, ...]) -> dict[str, Any] | None:
    series = history_payload.get("series")
    if not isinstance(series, dict):
        return None
    for alias in aliases:
        raw = series.get(alias)
        if isinstance(raw, dict) and raw.get("points"):
            return raw
    return None


def _series_points(series: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(series, dict):
        return []
    points = series.get("points")
    return points if isinstance(points, list) else []


def _latest_series_value(history_payload: dict[str, Any], aliases: tuple[str, ...]) -> float | None:
    series = _find_history_series(history_payload, aliases)
    points = _series_points(series)
    for point in reversed(points):
        value = _safe_float_value(point.get("value") if isinstance(point, dict) else None)
        if value is not None:
            return value
    return None


def _score_points(spec: ComponentSpec, points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for point in points:
        if not isinstance(point, dict):
            continue
        date_value = point.get("date")
        raw_value = _safe_float_value(point.get("value"))
        if not isinstance(date_value, str) or raw_value is None:
            continue
        score = _component_score(spec, raw_value)
        out.append({"date": date_value, "value": raw_value, "component_score": score})
    return out


def _point_at_or_before(points: list[dict[str, Any]], target: pd.Timestamp) -> dict[str, Any] | None:
    selected: dict[str, Any] | None = None
    for point in points:
        if not isinstance(point, dict):
            continue
        raw_date = point.get("date")
        if not isinstance(raw_date, str):
            continue
        parsed = pd.to_datetime(raw_date, errors="coerce")
        if pd.isna(parsed):
            continue
        if parsed <= target:
            selected = point
    return selected


def _score_delta(score_points: list[dict[str, Any]], days: int) -> tuple[float | None, str | None]:
    usable = [
        point
        for point in score_points
        if _safe_float_value(point.get("component_score")) is not None and isinstance(point.get("date"), str)
    ]
    if len(usable) < 2:
        return None, "component score history unavailable or too sparse"
    latest = usable[-1]
    latest_date = pd.to_datetime(latest["date"], errors="coerce")
    if pd.isna(latest_date):
        return None, "latest history date is invalid"
    prior = _point_at_or_before(usable, latest_date - pd.Timedelta(days=days))
    if prior is None:
        return None, f"no component score observation at least {days} days before latest history point"
    latest_score = _safe_float_value(latest.get("component_score"))
    prior_score = _safe_float_value(prior.get("component_score"))
    if latest_score is None or prior_score is None:
        return None, "component score history unavailable or too sparse"
    return latest_score - prior_score, None


def _layer_delta(history_payload: dict[str, Any], layer_id: str, days: int) -> tuple[float | None, str | None]:
    series = _find_history_series(history_payload, (f"layer_{layer_id}",))
    points = [
        {"date": p.get("date"), "component_score": _safe_float_value(p.get("value"))}
        for p in _series_points(series)
        if isinstance(p, dict)
    ]
    return _score_delta(points, days)


def _raw_weight(spec: ComponentSpec) -> float | None:
    if not spec.scored:
        return None
    if spec.raw_weight_key is None:
        return 1.0
    return float(_regime_params()[spec.raw_weight_key])


def _normalized_component_weights(layer_id: str) -> dict[str, float | None]:
    weighted: dict[str, float] = {}
    for spec in COMPONENT_SPECS[layer_id]:
        raw_weight = _raw_weight(spec)
        if raw_weight is not None:
            weighted[spec.component_id] = raw_weight
    total = sum(weighted.values())
    return {
        spec.component_id: (weighted[spec.component_id] / total if total > 0 and spec.component_id in weighted else None)
        for spec in COMPONENT_SPECS[layer_id]
    }


def _load_latest_regime_state_dict() -> dict[str, Any]:
    from src.state.regime_state import RegimeState

    state = RegimeState.load_latest_snapshot()
    if state is None:
        raise FileNotFoundError(
            "No local regime_state_*.json snapshot found for layer detail. "
            "Generate one through /api/market/regime?refresh=true or run the regime state builder."
        )
    return state.to_dict()


def _current_component_value(
    state: dict[str, Any],
    history_payload: dict[str, Any],
    spec: ComponentSpec,
) -> float | None:
    value = _safe_float_value(state.get(spec.component_id))
    if value is not None:
        return value
    return _latest_series_value(history_payload, spec.aliases)


def _build_macro_layers_detail_payload() -> dict[str, Any]:
    _validate_component_specs_against_builder()
    state = _load_latest_regime_state_dict()
    history_payload = _build_indicator_history_payload(395)
    statuses = state.get("layer_statuses") if isinstance(state.get("layer_statuses"), dict) else {}
    asof = state.get("asof_date") or history_payload.get("end_date")
    layers: list[dict[str, Any]] = []

    for layer_id in REGIME_LAYER_IDS:
        specs = COMPONENT_SPECS[layer_id]
        current_values = {
            spec.component_id: _current_component_value(state, history_payload, spec)
            for spec in specs
        }
        component_scores = {
            spec.component_id: _component_score(spec, current_values[spec.component_id])
            for spec in specs
        }
        weights = _normalized_component_weights(layer_id)
        components: list[dict[str, Any]] = []
        for spec in specs:
            series = _find_history_series(history_payload, spec.aliases)
            scored_points = _score_points(spec, _series_points(series))
            delta_1w, delta_1w_reason = _score_delta(scored_points, 7) if spec.scored else (None, spec.unscored_reason)
            delta_1m, delta_1m_reason = _score_delta(scored_points, 30) if spec.scored else (None, spec.unscored_reason)
            weight = weights.get(spec.component_id)
            score = component_scores[spec.component_id]
            contribution = weight * score if weight is not None and score is not None else None
            change_contribution_1m = (
                weight * delta_1m if weight is not None and delta_1m is not None else None
            )
            components.append(
                {
                    "component_id": spec.component_id,
                    "display_name": spec.display_name,
                    "current_value": current_values[spec.component_id],
                    "units_note": spec.units_note,
                    "component_score": score,
                    "weight": weight,
                    "weight_basis": "nominal_builder_weight" if weight is not None else None,
                    "contribution": contribution,
                    "delta_1w": delta_1w,
                    "delta_1w_reason": delta_1w_reason,
                    "delta_1m": delta_1m,
                    "delta_1m_reason": delta_1m_reason,
                    "change_contribution_1m": change_contribution_1m,
                    "history_available": bool(series),
                    "history_source": series.get("source") if isinstance(series, dict) else None,
                    "scored": spec.scored,
                    "unscored_reason": spec.unscored_reason,
                }
            )

        components.sort(
            key=lambda item: (
                item["change_contribution_1m"] is None,
                -abs(float(item["change_contribution_1m"] or 0.0)),
                item["display_name"],
            )
        )
        score = _safe_float_value(state.get(f"layer_{layer_id}"))
        if score is None:
            score = _latest_series_value(history_payload, (f"layer_{layer_id}",))
        layer_delta_1m, layer_delta_1m_reason = _layer_delta(history_payload, layer_id, 30)
        status = str(statuses.get(layer_id) or "neutral")
        layers.append(
            {
                "layer_id": layer_id,
                "display_name": REGIME_LAYER_NAMES[layer_id],
                "score": score,
                "direction_label": "Bullish" if status == "bullish" else "Bearish" if status == "bearish" else "Neutral",
                "status": status,
                "delta_1m": layer_delta_1m,
                "delta_1m_reason": layer_delta_1m_reason,
                "components": components,
            }
        )

    return {
        "asof": asof,
        "history": {
            "start_date": history_payload.get("start_date"),
            "end_date": history_payload.get("end_date"),
            "source_counts": history_payload.get("source_counts"),
            "warnings": history_payload.get("warnings"),
        },
        "layers": layers,
    }


def _build_component_history_payload(layer_id: str, component_id: str, window: str) -> dict[str, Any]:
    _validate_component_specs_against_builder()
    if layer_id not in COMPONENT_SPECS:
        raise KeyError(f"Unknown macro layer: {layer_id}")
    spec = _component_spec(layer_id, component_id)
    days = 90 if window == "90d" else 365
    history_payload = _build_indicator_history_payload(days)
    series = _find_history_series(history_payload, spec.aliases)
    if series is None:
        checked = ", ".join(spec.aliases)
        warnings = "; ".join(str(item) for item in history_payload.get("warnings", []))
        raise FileNotFoundError(
            f"No stored history for macro layer component {layer_id}/{component_id}. "
            f"Checked indicator-history columns: {checked}. "
            f"History warnings: {warnings or 'none'}"
        )
    layer_series = _find_history_series(history_payload, (f"layer_{layer_id}",))
    return {
        "layer_id": layer_id,
        "component_id": component_id,
        "display_name": spec.display_name,
        "window": window,
        "history_source": series.get("source"),
        "series": _score_points(spec, _series_points(series)),
        "layer_score_series": [
            {"date": point.get("date"), "score": _safe_float_value(point.get("value"))}
            for point in _series_points(layer_series)
            if isinstance(point, dict) and isinstance(point.get("date"), str)
        ],
        "warnings": history_payload.get("warnings", []),
    }


@macro_router.get("/forecast/latest")
async def latest_macro_forecast(user: dict = Depends(verify_clerk_token)) -> JSONResponse:
    """Return the latest generated two_source_v1 macro forecast JSON."""
    del user
    try:
        path, payload = _latest_two_source_forecast()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Macro forecast file is not valid: {exc}",
        ) from exc
    payload = dict(payload)
    payload["asof_metadata"] = _asof_metadata(path, payload)
    return JSONResponse(content=payload)


@macro_router.get("/analogue-fan/latest")
async def latest_analogue_fan(user: dict = Depends(verify_clerk_token)) -> JSONResponse:
    """Return the analogue fan JSON referenced by the latest two_source_v1 forecast."""
    del user
    try:
        forecast_path, forecast = _latest_two_source_forecast()
        mixture_report = forecast.get("mixture_report")
        if not isinstance(mixture_report, dict):
            raise FileNotFoundError(
                f"Latest forecast {forecast_path} has no mixture_report. "
                f"Regenerate with: {RUNNER_COMMAND}"
            )
        fan_path, fan_resolution_source = _resolve_artifact_path(
            mixture_report.get("analogue_fan_artifact_path")
        )
        if not fan_path.exists():
            fan_info = analogue_fans_dir_info(create=False)
            raise FileNotFoundError(
                f"Analogue fan artifact not found: {fan_path} "
                f"(resolution_source={fan_resolution_source}; "
                f"analogue_fans_dir={fan_info.path}; "
                f"analogue_fans_dir_resolution_source={fan_info.source}). "
                f"Regenerate with: {RUNNER_COMMAND}"
            )
        payload = _read_json_file(fan_path)
        if not isinstance(payload, dict):
            raise ValueError(f"Analogue fan artifact must be a JSON object: {fan_path}")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=f"Analogue fan artifact is not valid: {exc}") from exc
    payload = dict(payload)
    payload["asof_metadata"] = {
        "artifact_path": str(fan_path),
        "forecast_artifact_path": str(forecast_path),
        "query_date": payload.get("query_date"),
        "horizon_quarters": payload.get("horizon_quarters"),
    }
    return JSONResponse(content=payload)


@macro_router.get("/scenario-meta")
async def macro_scenario_meta(user: dict = Depends(verify_clerk_token)) -> JSONResponse:
    """Return behavioral scenario display metadata from the taxonomy YAML."""
    del user
    try:
        payload = _behavioral_scenario_meta()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Behavioral scenario metadata unavailable: {exc}") from exc
    return JSONResponse(content=payload)


@macro_router.get("/indicator-history")
async def macro_indicator_history(
    days: int = Query(730, ge=30, le=5000),
    user: dict = Depends(verify_clerk_token),
) -> JSONResponse:
    """Return chartable macro indicator history.

    Regime-state storage is the preferred source. For columns that are not
    persisted there, the historical backtest master file supplies the fallback.
    """
    del user
    payload = _build_indicator_history_payload(days)
    return JSONResponse(content=payload)


@macro_router.get("/regime-score-history")
async def macro_regime_score_history(
    window: str = Query("90d", pattern="^(90d|1y|5y|all)$"),
    user: dict = Depends(verify_clerk_token),
) -> JSONResponse:
    """Return score_total history from the canonical regime_states collection."""
    del user
    try:
        payload = _build_regime_score_history_payload(window)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Regime score history unavailable: {exc}") from exc
    return JSONResponse(content=payload)


@macro_router.get("/layers/detail")
async def macro_layers_detail(user: dict = Depends(verify_clerk_token)) -> JSONResponse:
    """Return latest five-layer monitoring detail with component attribution."""
    del user
    try:
        payload = _build_macro_layers_detail_payload()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Macro layer detail unavailable: {exc}") from exc
    return JSONResponse(content=payload)


@macro_router.get("/layers/{layer_id}/components/{component_id}/history")
async def macro_layer_component_history(
    layer_id: str,
    component_id: str,
    window: str = Query("90d", pattern="^(90d|1y)$"),
    user: dict = Depends(verify_clerk_token),
) -> JSONResponse:
    """Return raw component history and derived component-score history when possible."""
    del user
    try:
        payload = _build_component_history_payload(layer_id, component_id, window)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Macro component history unavailable: {exc}") from exc
    return JSONResponse(content=payload)
