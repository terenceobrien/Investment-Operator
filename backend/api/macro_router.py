"""Authenticated macro forecast report endpoints."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from api.auth import verify_clerk_token


macro_router = APIRouter(prefix="/api/macro", tags=["macro"])

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
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


def _forecast_root() -> Path:
    default_root = (
        REPO_ROOT
        / "data"
        / "agent_system"
        / "reports"
        / "macro_forecasts"
    )
    return Path(os.getenv("MACRO_FORECAST_DIR", str(default_root)))


def _forecast_candidate_paths(root: Path) -> list[Path]:
    if not root.exists():
        raise FileNotFoundError(
            f"Macro forecast directory not found: {root}. "
            f"Generate it with: {RUNNER_COMMAND}"
        )

    candidates = list(root.glob("macro_forecast_*.json"))
    current = root / "current"
    if current.exists() or current.is_symlink():
        source = current.resolve(strict=True) if current.is_symlink() else current
        if source.is_file() and source.name.startswith("macro_forecast_") and source.suffix == ".json":
            candidates.append(source)
        elif source.is_dir():
            candidates.extend(source.glob("macro_forecast_*.json"))

    unique: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(candidate)
    if not unique:
        raise FileNotFoundError(
            f"No macro_forecast_*.json files found in {root}. "
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
        for value in (
            payload.get("generated_at"),
            payload.get("created_at"),
            (payload.get("bvar_provenance") or {}).get("generated_at")
            if isinstance(payload.get("bvar_provenance"), dict)
            else None,
        ):
            parsed = _parse_timestamp(value)
            if parsed is not None:
                return parsed
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def _latest_forecast_artifact() -> tuple[Path, dict[str, Any]]:
    candidates = _forecast_candidate_paths(_forecast_root())
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


def _resolve_artifact_path(value: Any) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise FileNotFoundError(
            "Latest forecast does not reference analogue_fan_artifact_path. "
            f"Regenerate with: {RUNNER_COMMAND}"
        )
    path = Path(value)
    if path.is_absolute():
        return path
    candidates = [
        REPO_ROOT / path,
        BACKEND_ROOT / path,
        _forecast_root() / path,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


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
    cwd = Path.cwd()
    paths.extend(
        [
            BACKEND_ROOT / "data" / "operator_research_v3.csv",
            BACKEND_ROOT / "data" / "backtest_master_file.csv",
            REPO_ROOT / "data" / "operator_research_v3.csv",
            REPO_ROOT / "data" / "backtest_master_file.csv",
            cwd / "data" / "operator_research_v3.csv",
            cwd / "data" / "backtest_master_file.csv",
            cwd.parent / "data" / "operator_research_v3.csv",
            cwd.parent / "data" / "backtest_master_file.csv",
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
    checked = ", ".join(str(path) for path in _backtest_master_candidates())
    return f"backtest master file not found; checked: {checked}"


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
        fan_path = _resolve_artifact_path(mixture_report.get("analogue_fan_artifact_path"))
        if not fan_path.exists():
            raise FileNotFoundError(
                f"Analogue fan artifact not found: {fan_path}. "
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
