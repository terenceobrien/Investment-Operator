"""Authenticated macro forecast report endpoints."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from api.auth import verify_clerk_token


macro_router = APIRouter(prefix="/api/macro", tags=["macro"])


def _forecast_root() -> Path:
    default_root = (
        Path(__file__).resolve().parents[1]
        / "data"
        / "agent_system"
        / "reports"
        / "macro_forecasts"
    )
    return Path(os.getenv("MACRO_FORECAST_DIR", str(default_root)))


def _latest_forecast_path() -> Path:
    current = _forecast_root() / "current"
    if not current.exists() and not current.is_symlink():
        raise FileNotFoundError(
            f"Macro forecast pointer not found: {current}. "
            "Set MACRO_FORECAST_DIR to the macro_forecasts directory."
        )

    source = current.resolve(strict=True) if current.is_symlink() else current
    if source.is_file():
        return source

    if source.is_dir():
        candidates = sorted(
            source.glob("macro_forecast_*.json"),
            key=lambda path: (path.stat().st_mtime, path.name),
            reverse=True,
        )
        if candidates:
            return candidates[0]
        raise FileNotFoundError(f"No macro_forecast_*.json files found in {source}")

    raise FileNotFoundError(f"Macro forecast pointer is not a file or directory: {source}")


def _backtest_master_candidates() -> list[Path]:
    """Return candidate paths for the historical backtest master file."""
    backend_root = Path(__file__).resolve().parents[1]
    repo_root = backend_root.parent
    env_path = os.environ.get("RESEARCH_DATA_PATH")
    paths: list[Path] = []
    if env_path:
        paths.append(Path(env_path))
    paths.extend(
        [
            backend_root / "data" / "operator_research_v3.csv",
            backend_root / "data" / "backtest_master_file.csv",
            repo_root / "data" / "operator_research_v3.csv",
            repo_root / "data" / "backtest_master_file.csv",
        ]
    )
    return paths


def _resolve_backtest_master_path() -> Path | None:
    for path in _backtest_master_candidates():
        if path.exists():
            return path
    return None


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
        return _empty_history_frame(), "backtest master file not found"

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
    """Return the latest generated macro forecast JSON."""
    del user
    try:
        path = _latest_forecast_path()
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Macro forecast file is not valid JSON: {exc}",
        ) from exc
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
