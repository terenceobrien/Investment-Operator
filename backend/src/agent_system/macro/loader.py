"""Load, stage, and promote macro-agent research priorities."""
from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from src.agent_system.paths import agent_system_data_root
from src.agent_system.schemas.common import DerivedEvidence
from src.agent_system.schemas.regime import (
    ClarificationRequest,
    EdgeDecayHorizon,
    ResearchPriority,
)


DEFAULT_CURRENT_REGIME_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "current_regime.yaml"
)

try:  # pragma: no cover - environment-dependent optional dependency
    from ruamel.yaml import YAML as _RuamelYAML
except Exception:  # pragma: no cover - exercised implicitly in this env
    _RuamelYAML = None


def data_root() -> Path:
    """Return the canonical agent-system data root."""
    return agent_system_data_root(create=True)


def priorities_dir() -> Path:
    return data_root() / "priorities"


def default_inputs_file() -> Path:
    return priorities_dir() / "inputs.txt"


def proposed_priorities_path() -> Path:
    return priorities_dir() / "proposed_priorities.yaml"


def archive_dir() -> Path:
    return priorities_dir() / "archive"


def load_input_lines(path: Path) -> list[str]:
    """Read non-blank, non-comment input lines."""
    if not path.exists():
        raise FileNotFoundError(f"inputs file not found: {path}")
    lines: list[str] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            lines.append(stripped)
    return lines


def _minimal_evidence(item: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "source_type",
        "claim",
        "supports",
        "computation",
        "upstream_claims",
        "series_id",
        "observation_date",
        "observation_value",
        "publisher",
        "title",
        "url",
        "published_at",
        "channel",
        "cik",
        "accession_number",
        "form_type",
        "filed_at",
        "excerpt",
        "ticker",
        "metric",
        "value",
        "as_of",
        "timeframe",
        "instrument",
        "percentile_vs_history",
    }
    return {key: value for key, value in item.items() if key in allowed and value is not None}


def priority_to_yaml_dict(priority: ResearchPriority) -> dict[str, Any]:
    """Serialize a ResearchPriority in current_regime.yaml-friendly shape."""
    payload = priority.model_dump(mode="json")
    return {
        "theme": payload["theme"],
        "rationale": payload["rationale"],
        "edge_hypothesis": payload["edge_hypothesis"],
        "sub_questions": payload.get("sub_questions", []),
        "priority_rank": payload["priority_rank"],
        "expected_edge_decay": payload["expected_edge_decay"],
        "supporting_evidence": [
            _minimal_evidence(evidence)
            for evidence in payload.get("supporting_evidence", [])
            if isinstance(evidence, dict)
        ],
    }


def clarification_to_yaml_dict(
    user_input: str,
    clarification: ClarificationRequest,
) -> dict[str, Any]:
    payload = clarification.model_dump(mode="json")
    return {
        "original_user_input": user_input,
        "question": payload["question"],
        "suggested_options": payload["suggested_options"],
        "reasoning": payload["reasoning"],
        "original_input": payload["original_input"],
    }


def _dump_yaml(data: Any) -> str:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88)


def write_proposed_priorities(
    priorities: list[ResearchPriority],
    clarifications: list[dict[str, Any]],
    path: Path | None = None,
) -> Path:
    target = path or proposed_priorities_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "priorities": [priority_to_yaml_dict(priority) for priority in priorities],
        "clarifications": clarifications,
    }
    target.write_text(_dump_yaml(payload), encoding="utf-8")
    return target


def _priority_with_default_evidence(payload: dict[str, Any]) -> ResearchPriority:
    data = dict(payload)
    if "expected_edge_decay" in data:
        data["expected_edge_decay"] = EdgeDecayHorizon(data["expected_edge_decay"])
    if not data.get("supporting_evidence"):
        theme = str(data.get("theme", "unknown seed priority"))
        data["supporting_evidence"] = [
            DerivedEvidence(
                claim=f"Seed research priority from current_regime.yaml: {theme}",
                supports=True,
                computation="manually curated regime overlay",
                upstream_claims=["current_regime.yaml seed_research_priorities"],
            )
        ]
    return ResearchPriority.model_validate(data)


def load_proposed_priorities(path: Path | None = None) -> tuple[list[ResearchPriority], list[dict[str, Any]]]:
    source = path or proposed_priorities_path()
    if not source.exists():
        raise FileNotFoundError(f"proposed priorities file not found: {source}")
    raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError("proposed_priorities.yaml must contain a mapping")
    priorities_raw = raw.get("priorities", [])
    clarifications = raw.get("clarifications", [])
    if not isinstance(priorities_raw, list):
        raise ValueError("proposed priorities field must be a list")
    if not isinstance(clarifications, list):
        raise ValueError("proposed clarifications field must be a list")
    priorities = [
        _priority_with_default_evidence(item)
        for item in priorities_raw
        if isinstance(item, dict)
    ]
    return priorities, list(clarifications)


def load_current_regime_yaml(path: Path | None = None) -> dict[str, Any]:
    source = path or DEFAULT_CURRENT_REGIME_PATH
    raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"current_regime.yaml must contain a mapping: {source}")
    return raw


def load_current_priorities(path: Path | None = None) -> list[ResearchPriority]:
    raw = load_current_regime_yaml(path)
    items = raw.get("seed_research_priorities", []) or []
    if not isinstance(items, list):
        raise ValueError("seed_research_priorities must be a list")
    return [
        _priority_with_default_evidence(item)
        for item in items
        if isinstance(item, dict)
    ]


def _load_roundtrip_yaml(path: Path) -> tuple[Any, bool]:
    if _RuamelYAML is not None:
        rt_yaml = _RuamelYAML()
        rt_yaml.preserve_quotes = True
        with path.open("r", encoding="utf-8") as fh:
            return rt_yaml.load(fh), True
    return yaml.safe_load(path.read_text(encoding="utf-8")), False


def _write_roundtrip_yaml(path: Path, data: Any, *, use_ruamel: bool) -> None:
    if use_ruamel and _RuamelYAML is not None:
        rt_yaml = _RuamelYAML()
        rt_yaml.preserve_quotes = True
        with path.open("w", encoding="utf-8") as fh:
            rt_yaml.dump(data, fh)
        return
    path.write_text(_dump_yaml(data), encoding="utf-8")


def archive_promoted_priorities(
    priorities: list[ResearchPriority],
    *,
    archive_root: Path | None = None,
) -> Path:
    root = archive_root or archive_dir()
    root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    target = root / f"promoted_{timestamp}.yaml"
    target.write_text(
        _dump_yaml(
            {
                "promoted_at": datetime.now(timezone.utc).isoformat(),
                "priorities": [
                    priority_to_yaml_dict(priority)
                    for priority in priorities
                ],
            }
        ),
        encoding="utf-8",
    )
    return target


def promote_priorities(
    *,
    append: bool = False,
    proposed_path: Path | None = None,
    current_regime_path: Path | None = None,
    archive_root: Path | None = None,
) -> tuple[int, Path, bool]:
    """
    Promote staged priorities into current_regime.yaml.

    Returns (count_promoted, archive_path, comments_preserved).
    """
    priorities, _clarifications = load_proposed_priorities(proposed_path)
    target = current_regime_path or DEFAULT_CURRENT_REGIME_PATH
    data, used_ruamel = _load_roundtrip_yaml(target)
    if not isinstance(data, dict):
        raise ValueError(f"current_regime.yaml must contain a mapping: {target}")
    new_items = [priority_to_yaml_dict(priority) for priority in priorities]
    if append:
        existing = data.get("seed_research_priorities", []) or []
        if not isinstance(existing, list):
            raise ValueError("seed_research_priorities must be a list")
        data["seed_research_priorities"] = list(existing) + new_items
    else:
        data["seed_research_priorities"] = new_items
    _write_roundtrip_yaml(target, data, use_ruamel=used_ruamel)
    archive_path = archive_promoted_priorities(priorities, archive_root=archive_root)
    return len(priorities), archive_path, used_ruamel


def proposed_as_yaml(path: Path | None = None) -> str:
    source = path or proposed_priorities_path()
    return source.read_text(encoding="utf-8")


def current_priorities_as_yaml(path: Path | None = None) -> str:
    return _dump_yaml(
        {"priorities": [priority_to_yaml_dict(p) for p in load_current_priorities(path)]}
    )


def copy_default_inputs_template(path: Path | None = None) -> Path:
    target = path or default_inputs_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_text(
            "# One free-text input per line. Blank lines and # comments ignored.\n",
            encoding="utf-8",
        )
    return target
