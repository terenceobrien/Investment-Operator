"""Configuration loader for the regime scoring system.

Reads tunable parameters from data/agent_system/AGENT_SYSTEM_INPUTS.xlsx and
exposes them as typed namespaces. Code calls into this module instead of
hardcoding threshold values.

Loaded once at module-import time and cached. To pick up config changes,
restart the Python process or call reload() in tests.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd

from src.agent_system.paths import agent_system_data_root


logger = logging.getLogger(__name__)


CONFIG_FILE_PATH = agent_system_data_root(create=False) / "AGENT_SYSTEM_INPUTS.xlsx"
PARAMETER_CONFIG_SHEETS = (
    "regime_layers",
    "classify_environment",
    "composite_weights",
    "existing_position_filter",
)
RESEARCH_PRIORITY_EXCLUSIONS_SHEET = "research_priority_exclusions"
CONFIG_SHEETS = PARAMETER_CONFIG_SHEETS + (RESEARCH_PRIORITY_EXCLUSIONS_SHEET,)


class ConfigError(RuntimeError):
    """Raised when the config file is missing, malformed, or incomplete."""


class ConfigNamespace:
    """Read-only dict wrapper with attribute-style typed values."""

    def __init__(self, data: dict[str, Any], sheet_name: str):
        self._data = data
        self._sheet_name = sheet_name

    def __getitem__(self, key: str) -> Any:
        if key not in self._data:
            raise ConfigError(
                f"Missing required config key {key!r} in sheet {self._sheet_name!r}. "
                f"Add a row to {CONFIG_FILE_PATH} or check parameter_key spelling."
            )
        return self._data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def keys(self):
        return self._data.keys()

    def items(self):
        return self._data.items()


def _coerce_value(value: Any, type_str: str) -> Any:
    """Cast a workbook cell value to its declared type."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if type_str is None or pd.isna(type_str):
        type_str = "float"
    type_str = str(type_str).strip().lower()
    try:
        if type_str == "float":
            return float(value)
        if type_str == "int":
            return int(value)
        if type_str == "bool":
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() in ("true", "yes", "1", "y")
        return str(value)
    except (ValueError, TypeError) as exc:
        raise ConfigError(f"Could not coerce {value!r} to {type_str}: {exc}") from exc


def _load_sheet(xls: pd.ExcelFile, sheet_name: str) -> dict[str, Any]:
    df = pd.read_excel(xls, sheet_name=sheet_name)
    required_cols = {"parameter_key", "value", "type"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ConfigError(
            f"Sheet {sheet_name!r} missing required columns: {missing}. "
            f"Expected columns: {required_cols}"
        )

    result: dict[str, Any] = {}
    for _, row in df.iterrows():
        key = row.get("parameter_key")
        if pd.isna(key) or not str(key).strip():
            continue
        key = str(key).strip()
        if key in result:
            raise ConfigError(f"Duplicate parameter_key {key!r} in sheet {sheet_name!r}")
        result[key] = _coerce_value(row.get("value"), row.get("type", "float"))
    return result


def _load_research_priority_exclusions(xls: pd.ExcelFile) -> dict[str, str]:
    df = pd.read_excel(xls, sheet_name=RESEARCH_PRIORITY_EXCLUSIONS_SHEET)
    required_cols = {"theme_id", "reason"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ConfigError(
            f"Sheet {RESEARCH_PRIORITY_EXCLUSIONS_SHEET!r} missing required columns: {missing}. "
            f"Expected columns: {required_cols}"
        )

    result: dict[str, str] = {}
    for _, row in df.iterrows():
        theme_id = row.get("theme_id")
        if pd.isna(theme_id) or not str(theme_id).strip():
            continue
        theme_id = str(theme_id).strip()
        if theme_id in result:
            raise ConfigError(
                f"Duplicate theme_id {theme_id!r} in sheet {RESEARCH_PRIORITY_EXCLUSIONS_SHEET!r}"
            )
        reason = row.get("reason")
        result[theme_id] = "" if pd.isna(reason) else str(reason).strip()
    return result


@lru_cache(maxsize=1)
def _load_all() -> dict[str, Any]:
    if not CONFIG_FILE_PATH.exists():
        raise ConfigError(
            f"Config file not found at {CONFIG_FILE_PATH}. "
            f"Place AGENT_SYSTEM_INPUTS.xlsx at that path before importing this module."
        )

    try:
        xls = pd.ExcelFile(CONFIG_FILE_PATH)
    except Exception as exc:
        raise ConfigError(f"Could not open {CONFIG_FILE_PATH}: {exc}") from exc

    missing_sheets = set(CONFIG_SHEETS) - set(xls.sheet_names)
    if missing_sheets:
        raise ConfigError(
            f"Config file missing required sheets: {missing_sheets}. "
            f"Found sheets: {xls.sheet_names}"
        )

    namespaces = {}
    for sheet in PARAMETER_CONFIG_SHEETS:
        data = _load_sheet(xls, sheet)
        namespaces[sheet] = ConfigNamespace(data, sheet)
        logger.info("Loaded %d params from sheet %r", len(data), sheet)
    exclusions = _load_research_priority_exclusions(xls)
    namespaces[RESEARCH_PRIORITY_EXCLUSIONS_SHEET] = exclusions
    logger.info(
        "Loaded %d research priority exclusion(s) from sheet %r",
        len(exclusions),
        RESEARCH_PRIORITY_EXCLUSIONS_SHEET,
    )
    return namespaces


def get_regime_params() -> ConfigNamespace:
    return _load_all()["regime_layers"]


def get_env_params() -> ConfigNamespace:
    return _load_all()["classify_environment"]


def get_weights() -> ConfigNamespace:
    return _load_all()["composite_weights"]


def get_existing_position_filter_params() -> ConfigNamespace:
    return _load_all()["existing_position_filter"]


def get_research_priority_exclusions() -> dict[str, str]:
    return dict(_load_all()[RESEARCH_PRIORITY_EXCLUSIONS_SHEET])


def get(key: str, default: Any = None) -> Any:
    """Look up a key across all three config namespaces."""
    loaded = _load_all()
    for sheet in PARAMETER_CONFIG_SHEETS:
        namespace = loaded[sheet]
        if key in namespace:
            return namespace[key]
    return default


def reload() -> None:
    """Clear the cache and force re-read on next access. Mainly for tests."""
    _load_all.cache_clear()


REGIME_PARAMS = get_regime_params()
ENV_PARAMS = get_env_params()
WEIGHTS = get_weights()
EXISTING_POSITION_FILTER_PARAMS = get_existing_position_filter_params()
RESEARCH_PRIORITY_EXCLUSIONS = get_research_priority_exclusions()
