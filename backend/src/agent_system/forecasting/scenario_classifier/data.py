"""Cached FRED data layer for the standalone scenario classifier."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.agent_system.forecasting.scenario_classifier.registry import (
    VariableRegistry,
    VariableSpec,
)
from src.agent_system.paths import classifier_cache_dir


class ClassifierDataError(RuntimeError):
    """Raised when classifier data are missing or malformed."""


def default_cache_dir() -> Path:
    return classifier_cache_dir(create=False)


def refresh_fred_cache(
    registry: VariableRegistry,
    *,
    cache_dir: str | Path | None = None,
) -> dict[str, Any]:
    target_dir = Path(cache_dir) if cache_dir is not None else default_cache_dir()
    target_dir.mkdir(parents=True, exist_ok=True)

    manifest = _load_manifest(target_dir)
    series_entries = manifest.setdefault("series", {})
    if not isinstance(series_entries, dict):
        series_entries = {}
        manifest["series"] = series_entries

    for series_id in registry.unique_fred_series_ids():
        series = _fetch_fred_series(series_id)
        if series.empty:
            raise ClassifierDataError(f"FRED returned no usable rows for {series_id}")
        path = _series_cache_path(target_dir, series_id)
        _write_series_parquet(series, path)
        series_entries[series_id] = {
            "fetched_at": _utc_now(),
            "row_count": int(len(series)),
            "first_date": _index_date_text(series.index.min()),
            "last_date": _index_date_text(series.index.max()),
            "path": str(path),
        }

    manifest["updated_at"] = _utc_now()
    manifest["cache_dir"] = str(target_dir)
    _manifest_path(target_dir).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def ensure_cache_available(
    registry: VariableRegistry,
    *,
    cache_dir: str | Path | None = None,
) -> None:
    target_dir = Path(cache_dir) if cache_dir is not None else default_cache_dir()
    missing = [
        series_id
        for series_id in registry.unique_fred_series_ids()
        if not _series_cache_path(target_dir, series_id).is_file()
    ]
    if missing:
        raise ClassifierDataError(
            "Missing cached FRED series "
            f"{', '.join(missing)} under {target_dir}; run refresh-data first."
        )


def load_transformed_history(
    registry: VariableRegistry,
    variable: VariableSpec | str,
    *,
    cache_dir: str | Path | None = None,
) -> pd.Series:
    spec = registry.get(variable) if isinstance(variable, str) else variable
    raw_quarterly = _load_quarterly_untransformed(registry, spec, cache_dir=cache_dir)
    transformed = _apply_transform(raw_quarterly, spec.transform)
    transformed.name = spec.name
    return transformed.dropna()


def load_signature_histories(
    registry: VariableRegistry,
    *,
    variables: list[str] | None = None,
    cache_dir: str | Path | None = None,
) -> dict[str, pd.Series]:
    selected = variables or registry.signature_variable_names()
    return {
        variable_name: load_transformed_history(
            registry,
            variable_name,
            cache_dir=cache_dir,
        )
        for variable_name in selected
    }


def _load_quarterly_untransformed(
    registry: VariableRegistry,
    spec: VariableSpec,
    *,
    cache_dir: str | Path | None,
) -> pd.Series:
    if spec.fred_series:
        return _resample_quarterly_mean(
            _load_cached_raw_series(spec.fred_series, cache_dir=cache_dir)
        )

    if not spec.fred_components or spec.combine != "subtract":
        raise ClassifierDataError(
            f"variable {spec.name} has unsupported composite definition"
        )
    component_series = [
        _resample_quarterly_mean(
            _load_cached_raw_series(series_id, cache_dir=cache_dir)
        ).rename(series_id)
        for series_id in spec.fred_components
    ]
    combined = pd.concat(component_series, axis=1, join="inner").dropna()
    if combined.empty:
        raise ClassifierDataError(
            f"composite variable {spec.name} has no overlapping component history"
        )
    result = combined.iloc[:, 0].copy()
    for column in combined.columns[1:]:
        result = result - combined[column]
    result.name = spec.name
    return result


def _load_cached_raw_series(
    series_id: str,
    *,
    cache_dir: str | Path | None,
) -> pd.Series:
    target_dir = Path(cache_dir) if cache_dir is not None else default_cache_dir()
    path = _series_cache_path(target_dir, series_id)
    if not path.is_file():
        raise ClassifierDataError(
            f"Missing cached FRED series {series_id} at {path}; run refresh-data first."
        )
    try:
        frame = pd.read_parquet(path)
    except Exception as exc:
        raise ClassifierDataError(f"Could not read cached series {series_id}: {exc}") from exc
    if "value" not in frame.columns:
        raise ClassifierDataError(f"Cached series {series_id} missing value column: {path}")
    series = pd.to_numeric(frame["value"], errors="coerce").dropna()
    series.index = pd.to_datetime(series.index)
    series.name = series_id
    if series.empty:
        raise ClassifierDataError(f"Cached series {series_id} has no numeric rows: {path}")
    return series.sort_index()


def _fetch_fred_series(series_id: str) -> pd.Series:
    try:
        from fredapi import Fred

        api_key = os.environ.get("FRED_API_KEY", "")
        fred = Fred(api_key=api_key)
        data = fred.get_series(series_id)
    except Exception as exc:
        raise ClassifierDataError(f"FRED fetch failed for {series_id}: {exc}") from exc
    if data is None or data.empty:
        return pd.Series(dtype=float)
    series = pd.to_numeric(data, errors="coerce").dropna()
    series.index = pd.to_datetime(series.index)
    series.name = series_id
    return series.sort_index()


def _write_series_parquet(series: pd.Series, path: Path) -> None:
    frame = pd.DataFrame({"value": pd.to_numeric(series, errors="coerce")}).dropna()
    if frame.empty:
        raise ClassifierDataError(f"refusing to cache empty series at {path}")
    try:
        frame.to_parquet(path)
    except Exception as exc:
        raise ClassifierDataError(f"Could not write parquet cache {path}: {exc}") from exc


def _resample_quarterly_mean(series: pd.Series) -> pd.Series:
    if series.empty:
        return pd.Series(dtype=float)
    clean = pd.to_numeric(series, errors="coerce").dropna()
    clean.index = pd.to_datetime(clean.index)
    quarterly = clean.groupby(clean.index.to_period("Q")).mean()
    quarterly.name = series.name
    return quarterly.sort_index()


def _apply_transform(series: pd.Series, transform: str) -> pd.Series:
    clean = pd.to_numeric(series, errors="coerce").dropna().sort_index()
    if transform == "level":
        return clean
    if transform == "yoy_pct":
        return (clean / clean.shift(4) - 1.0) * 100.0
    if transform == "qoq_ann_pct":
        return ((clean / clean.shift(1)) ** 4 - 1.0) * 100.0
    if transform == "diff":
        return clean.diff()
    raise ClassifierDataError(f"unknown transform requested at runtime: {transform}")


def _series_cache_path(cache_dir: Path, series_id: str) -> Path:
    safe = series_id.replace("/", "_").replace("\\", "_")
    return cache_dir / f"{safe}.parquet"


def _manifest_path(cache_dir: Path) -> Path:
    return cache_dir / "cache_manifest.json"


def _load_manifest(cache_dir: Path) -> dict[str, Any]:
    path = _manifest_path(cache_dir)
    if not path.is_file():
        return {"series": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"series": {}}
    return payload if isinstance(payload, dict) else {"series": {}}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _index_date_text(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "date"):
        return value.date().isoformat()
    if isinstance(value, pd.Period):
        return str(value)
    if isinstance(value, (float, int)) and not np.isfinite(value):
        return None
    return str(value)[:10]
