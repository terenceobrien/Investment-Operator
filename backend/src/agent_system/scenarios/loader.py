"""Scenario artifact loading, writing, and path helpers."""
from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

import yaml

from src.agent_system.scenarios.types import ScenarioSet


BACKEND_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_AGENT_DATA_DIR = BACKEND_ROOT / "data" / "agent_system"


def agent_data_dir() -> Path:
    return Path(os.getenv("AGENT_SYSTEM_DATA_DIR", str(DEFAULT_AGENT_DATA_DIR)))


def scenario_root() -> Path:
    return agent_data_dir() / "scenarios"


def proposed_path() -> Path:
    return scenario_root() / "proposed_scenarios.yaml"


def current_path() -> Path:
    return scenario_root() / "current_scenarios.yaml"


def archive_dir() -> Path:
    return scenario_root() / "archive"


def _read_scenario_set(path: Path) -> ScenarioSet | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as fh:
        payload = yaml.safe_load(fh)
    if payload is None:
        return None
    return ScenarioSet.model_validate(payload)


def _scenario_set_to_yaml(scenario_set: ScenarioSet) -> str:
    return yaml.safe_dump(
        scenario_set.model_dump(mode="json"),
        sort_keys=False,
        allow_unicode=False,
        width=88,
    )


def write_scenario_set(path: Path, scenario_set: ScenarioSet) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_scenario_set_to_yaml(scenario_set), encoding="utf-8")


def load_current_scenarios() -> ScenarioSet | None:
    """Returns the current ScenarioSet, or None if none exists."""
    return _read_scenario_set(current_path())


def load_proposed_scenarios() -> ScenarioSet | None:
    """Returns the proposed ScenarioSet, or None if none exists."""
    return _read_scenario_set(proposed_path())


def archive_current_scenarios() -> Path | None:
    """Archive current_scenarios.yaml if present and return the archive path."""
    source = current_path()
    if not source.exists():
        return None
    current = _read_scenario_set(source)
    generated_at = current.generated_at if current else datetime.now(timezone.utc)
    timestamp = generated_at.strftime("%Y%m%d_%H%M%S")
    destination = archive_dir() / f"scenarios_{timestamp}.yaml"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination
