"""Shared filesystem paths for agent-system runtime artifacts."""
from __future__ import annotations

import os
from pathlib import Path


def project_root() -> Path:
    """Return the repository root."""
    return Path(__file__).resolve().parents[3]


def agent_system_data_root() -> Path:
    """Return the canonical agent-system data root."""
    default_root = project_root() / "data" / "agent_system"
    root = Path(os.getenv("AGENT_SYSTEM_DATA_DIR", str(default_root)))
    root.mkdir(parents=True, exist_ok=True)
    return root


def cycles_dir() -> Path:
    """Return the directory containing file-backed cycle status records."""
    path = agent_system_data_root() / "cycles"
    path.mkdir(parents=True, exist_ok=True)
    return path


def schema_records_path() -> Path:
    return agent_system_data_root() / "schema_records.jsonl"


def decision_log_path() -> Path:
    return agent_system_data_root() / "decision_log.jsonl"
