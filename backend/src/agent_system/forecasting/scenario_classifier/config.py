"""Configuration loading for the standalone scenario classifier."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from src.agent_system.forecasting.scenario_classifier.deltas import BASELINE_MODES


class ClassifierConfigError(RuntimeError):
    """Raised when classifier_config.yaml is missing or malformed."""


def default_classifier_config_path() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "classifier_config.yaml"


def load_classifier_config(
    path: str | Path | None = None,
    *,
    horizon_quarters: int | None = None,
    baseline_mode: str | None = None,
    kernel_sigma: float | None = None,
) -> dict[str, Any]:
    config_path = Path(path) if path is not None else default_classifier_config_path()
    if not config_path.is_file():
        raise ClassifierConfigError(f"classifier config not found: {config_path}")
    with config_path.open("r", encoding="utf-8") as fh:
        payload = yaml.safe_load(fh)
    if not isinstance(payload, dict):
        raise ClassifierConfigError(f"classifier config must be a YAML mapping: {config_path}")

    config = {
        "horizon_quarters": int(payload.get("horizon_quarters")),
        "baseline_mode": str(payload.get("baseline_mode")),
        "kernel_sigma": float(payload.get("kernel_sigma")),
        "scaling": str(payload.get("scaling")),
    }
    if horizon_quarters is not None:
        config["horizon_quarters"] = int(horizon_quarters)
    if baseline_mode is not None:
        config["baseline_mode"] = str(baseline_mode)
    if kernel_sigma is not None:
        config["kernel_sigma"] = float(kernel_sigma)
    _validate_config(config)
    return config


def _validate_config(config: dict[str, Any]) -> None:
    if int(config["horizon_quarters"]) < 1:
        raise ClassifierConfigError("classifier_config horizon_quarters must be positive")
    if str(config["baseline_mode"]) not in BASELINE_MODES:
        raise ClassifierConfigError(
            f"classifier_config baseline_mode must be one of {sorted(BASELINE_MODES)}"
        )
    if float(config["kernel_sigma"]) <= 0:
        raise ClassifierConfigError("classifier_config kernel_sigma must be positive")
    if str(config["scaling"]) not in {"std", "mad"}:
        raise ClassifierConfigError("classifier_config scaling must be std or mad")
