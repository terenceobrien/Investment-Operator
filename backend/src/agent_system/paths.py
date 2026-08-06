"""Shared filesystem paths for backend runtime artifacts.

All live backend artifacts resolve from ``HELIX_DATA_ROOT`` when set, otherwise
from ``backend/data`` derived from this file. Nothing here depends on the
process cwd.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ResolvedPath:
    path: Path
    source: str


MACRO_FORECAST_RELATIVE = "agent_system/reports/macro_forecasts"


def project_root() -> Path:
    """Return the repository root."""
    return Path(__file__).resolve().parents[3]


def backend_root() -> Path:
    """Return the backend package root, the directory containing ``src/``."""
    return Path(__file__).resolve().parents[2]


def data_root_info(*, create: bool = False) -> ResolvedPath:
    """Return the canonical data root plus how it was resolved."""

    configured = os.getenv("HELIX_DATA_ROOT")
    configured_root = Path(configured).expanduser() if configured else None
    stale_railway_data_root = Path("/app/data")
    running_under_railway_app_root = backend_root().resolve().is_relative_to(Path("/app"))
    if (
        configured_root is not None
        and configured_root.resolve() == stale_railway_data_root.resolve()
        and not running_under_railway_app_root
    ):
        configured_root = None
    if configured_root is not None:
        root = configured_root
        source = "env:HELIX_DATA_ROOT"
    else:
        root = backend_root() / "data"
        source = "default:backend_package_root_from_file"
    if create:
        root.mkdir(parents=True, exist_ok=True)
    return ResolvedPath(root, source)


def data_root(*, create: bool = False) -> Path:
    """Return the canonical repo data root."""

    return data_root_info(create=create).path


def _child(info: ResolvedPath, relative: Path, *, create: bool) -> ResolvedPath:
    path = info.path / relative
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return ResolvedPath(path, info.source)


def _data_child(relative: str | Path, *, create: bool = False) -> ResolvedPath:
    return _child(data_root_info(create=False), Path(relative), create=create)


def resolved_path_message(label: str, info: ResolvedPath, *, command: str | None = None) -> str:
    """Return a fail-loud path message with path and resolution source."""

    message = f"{label}: {info.path} (resolution_source={info.source})"
    if command:
        message = f"{message}. Generate it with: {command}"
    return message


def agent_system_data_root_info(*, create: bool = True) -> ResolvedPath:
    """Return the canonical agent-system data root plus resolution source."""

    base = data_root_info(create=False)
    configured = os.getenv("AGENT_SYSTEM_DATA_DIR")
    legacy_repo_root_agent_dir = project_root() / "data" / "agent_system"
    stale_railway_agent_dir = Path("/app/data/agent_system")
    configured_root = Path(configured).expanduser() if configured else None
    is_legacy_repo_root = (
        configured_root is not None
        and configured_root.resolve() == legacy_repo_root_agent_dir.resolve()
    )
    is_stale_railway_env_file = (
        configured_root is not None
        and configured_root.resolve() == stale_railway_agent_dir.resolve()
        and base.path.resolve() != Path("/app/data").resolve()
    )
    is_same_as_base = (
        configured_root is not None
        and configured_root.resolve() == (base.path / "agent_system").resolve()
    )
    if configured_root is not None and not is_legacy_repo_root and not is_stale_railway_env_file:
        if is_same_as_base:
            root = base.path / "agent_system"
            source = base.source
        else:
            root = configured_root
            source = "env:AGENT_SYSTEM_DATA_DIR"
    else:
        root = base.path / "agent_system"
        source = base.source
    if create:
        root.mkdir(parents=True, exist_ok=True)
    return ResolvedPath(root, source)


def agent_system_data_root(*, create: bool = True) -> Path:
    """Return the canonical agent-system data root."""
    return agent_system_data_root_info(create=create).path


def cache_dir_info(*, create: bool = False) -> ResolvedPath:
    return _data_child("cache", create=create)


def cache_dir(*, create: bool = False) -> Path:
    return cache_dir_info(create=create).path


def backtest_cache_dir_info(*, create: bool = False) -> ResolvedPath:
    return _child(cache_dir_info(create=False), Path("backtest"), create=create)


def backtest_cache_dir(*, create: bool = False) -> Path:
    return backtest_cache_dir_info(create=create).path


def analogue_lookup_cache_dir_info(*, create: bool = False) -> ResolvedPath:
    return _child(cache_dir_info(create=False), Path("analogue_lookups"), create=create)


def analogue_lookup_cache_dir(*, create: bool = False) -> Path:
    return analogue_lookup_cache_dir_info(create=create).path


def price_history_cache_dir_info(*, create: bool = False) -> ResolvedPath:
    return _child(cache_dir_info(create=False), Path("price_history"), create=create)


def price_history_cache_dir(*, create: bool = False) -> Path:
    return price_history_cache_dir_info(create=create).path


def raw_data_dir_info(*, create: bool = False) -> ResolvedPath:
    return _data_child("raw", create=create)


def raw_data_dir(*, create: bool = False) -> Path:
    return raw_data_dir_info(create=create).path


def research_data_dir_info(*, create: bool = False) -> ResolvedPath:
    return _data_child("research", create=create)


def research_data_dir(*, create: bool = False) -> Path:
    return research_data_dir_info(create=create).path


def snapshots_dir_info(*, create: bool = False) -> ResolvedPath:
    return _data_child("snapshots", create=create)


def snapshots_dir(*, create: bool = False) -> Path:
    return snapshots_dir_info(create=create).path


def narrative_dir_info(*, create: bool = False) -> ResolvedPath:
    return _data_child("narrative", create=create)


def narrative_dir(*, create: bool = False) -> Path:
    return narrative_dir_info(create=create).path


def narrative_cache_dir_info(*, create: bool = False) -> ResolvedPath:
    return _child(narrative_dir_info(create=False), Path("cache"), create=create)


def narrative_cache_dir(*, create: bool = False) -> Path:
    return narrative_cache_dir_info(create=create).path


def narrative_trends_dir_info(*, create: bool = False) -> ResolvedPath:
    return _child(narrative_dir_info(create=False), Path("trends"), create=create)


def narrative_trends_dir(*, create: bool = False) -> Path:
    return narrative_trends_dir_info(create=create).path


def narrative_raw_dir_info(*, create: bool = False) -> ResolvedPath:
    return _child(narrative_dir_info(create=False), Path("raw"), create=create)


def narrative_raw_dir(*, create: bool = False) -> Path:
    return narrative_raw_dir_info(create=create).path


def narrative_errors_dir_info(*, create: bool = False) -> ResolvedPath:
    return _child(narrative_dir_info(create=False), Path("errors"), create=create)


def narrative_errors_dir(*, create: bool = False) -> Path:
    return narrative_errors_dir_info(create=create).path


def narrative_memory_dir_info(*, create: bool = False) -> ResolvedPath:
    return _child(narrative_dir_info(create=False), Path("memory"), create=create)


def narrative_memory_dir(*, create: bool = False) -> Path:
    return narrative_memory_dir_info(create=create).path


def fixtures_dir_info(*, create: bool = False) -> ResolvedPath:
    return _data_child("fixtures", create=create)


def fixtures_dir(*, create: bool = False) -> Path:
    return fixtures_dir_info(create=create).path


def universe_dir_info(*, create: bool = False) -> ResolvedPath:
    return _data_child("universe", create=create)


def universe_dir(*, create: bool = False) -> Path:
    return universe_dir_info(create=create).path


def theme_mappings_dir_info(*, create: bool = False) -> ResolvedPath:
    return _data_child("theme_mappings", create=create)


def theme_mappings_dir(*, create: bool = False) -> Path:
    return theme_mappings_dir_info(create=create).path


def deep_fundamental_reports_dir_info(*, create: bool = False) -> ResolvedPath:
    return _data_child("deep_fundamental_reports", create=create)


def deep_fundamental_reports_dir(*, create: bool = False) -> Path:
    return deep_fundamental_reports_dir_info(create=create).path


def strategies_dir_info(*, create: bool = False) -> ResolvedPath:
    return _data_child("strategies", create=create)


def strategies_dir(*, create: bool = False) -> Path:
    return strategies_dir_info(create=create).path


def fed_model_dir_info(*, create: bool = False) -> ResolvedPath:
    return _data_child("Fed_Model", create=create)


def fed_model_dir(*, create: bool = False) -> Path:
    return fed_model_dir_info(create=create).path


def agent_data_cache_dir_info(*, create: bool = False) -> ResolvedPath:
    return _child(agent_system_data_root_info(create=False), Path("data_cache"), create=create)


def agent_data_cache_dir(*, create: bool = False) -> Path:
    return agent_data_cache_dir_info(create=create).path


def classifier_cache_dir_info(*, create: bool = False) -> ResolvedPath:
    return _child(agent_system_data_root_info(create=False), Path("classifier_cache"), create=create)


def classifier_cache_dir(*, create: bool = False) -> Path:
    return classifier_cache_dir_info(create=create).path


def bvar_cache_dir_info(*, create: bool = False) -> ResolvedPath:
    return _child(agent_system_data_root_info(create=False), Path("bvar_cache"), create=create)


def bvar_cache_dir(*, create: bool = False) -> Path:
    return bvar_cache_dir_info(create=create).path


def bvar_reports_dir_info(*, create: bool = False) -> ResolvedPath:
    return _child(bvar_cache_dir_info(create=False), Path("reports"), create=create)


def bvar_reports_dir(*, create: bool = False) -> Path:
    return bvar_reports_dir_info(create=create).path


def audits_dir_info(*, create: bool = False) -> ResolvedPath:
    return _child(agent_system_data_root_info(create=False), Path("reports") / "audits", create=create)


def audits_dir(*, create: bool = False) -> Path:
    return audits_dir_info(create=create).path


def diagnostics_dir_info(*, create: bool = False) -> ResolvedPath:
    return _child(agent_system_data_root_info(create=False), Path("diagnostics"), create=create)


def diagnostics_dir(*, create: bool = False) -> Path:
    return diagnostics_dir_info(create=create).path


def macro_agent_evals_dir(*, create: bool = False) -> Path:
    return _child(agent_system_data_root_info(create=False), Path("macro_agent_evals"), create=create).path


def thematic_agent_evals_dir(*, create: bool = False) -> Path:
    return _child(agent_system_data_root_info(create=False), Path("thematic_agent_evals"), create=create).path


def screen_evals_dir(*, create: bool = False) -> Path:
    return _child(agent_system_data_root_info(create=False), Path("screen_evals"), create=create).path


def calibration_dir(*, create: bool = False) -> Path:
    return _child(agent_system_data_root_info(create=False), Path("calibration"), create=create).path


def company_profiles_dir(*, create: bool = False) -> Path:
    return _child(agent_system_data_root_info(create=False), Path("company_profiles"), create=create).path


def frbus_handoffs_dir(*, create: bool = False) -> Path:
    return _child(agent_system_data_root_info(create=False), Path("frbus_handoffs"), create=create).path


def priorities_dir(*, create: bool = False) -> Path:
    return _child(agent_system_data_root_info(create=False), Path("priorities"), create=create).path


def scenarios_dir(*, create: bool = False) -> Path:
    return _child(agent_system_data_root_info(create=False), Path("scenarios"), create=create).path


def positions_dir(*, create: bool = False) -> Path:
    return _child(agent_system_data_root_info(create=False), Path("positions"), create=create).path


def shadow_forecasts_dir(*, create: bool = False) -> Path:
    return _child(agent_system_data_root_info(create=False), Path("shadow_forecasts"), create=create).path


def research_contexts_dir(*, create: bool = False) -> Path:
    return _child(agent_system_data_root_info(create=False), Path("research_contexts"), create=create).path


def trade_outcomes_dir(*, create: bool = False) -> Path:
    return _child(agent_system_data_root_info(create=False), Path("trade_outcomes"), create=create).path
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


def reference_data_dir_info(*, create: bool = False) -> ResolvedPath:
    return _child(data_root_info(create=False), Path("reference"), create=create)


def reference_data_dir(*, create: bool = False) -> Path:
    return reference_data_dir_info(create=create).path


def scenario_theme_returns_path_info(*, create_parent: bool = False) -> ResolvedPath:
    directory = reference_data_dir_info(create=create_parent)
    return ResolvedPath(directory.path / "scenario_theme_returns.csv", directory.source)


def macro_forecast_dir_info(*, create: bool = False) -> ResolvedPath:
    return _child(
        data_root_info(create=False),
        Path(*MACRO_FORECAST_RELATIVE.split("/")),
        create=create,
    )


def macro_forecast_dir(*, create: bool = False) -> Path:
    return macro_forecast_dir_info(create=create).path


def macro_reports_dir_info(*, create: bool = False) -> ResolvedPath:
    return _child(macro_forecast_dir_info(create=False), Path("Reports"), create=create)


def macro_reports_dir(*, create: bool = False) -> Path:
    return macro_reports_dir_info(create=create).path


def macro_json_dir_info(*, create: bool = False) -> ResolvedPath:
    return _child(macro_forecast_dir_info(create=False), Path("JSON"), create=create)


def macro_json_dir(*, create: bool = False) -> Path:
    return macro_json_dir_info(create=create).path


def macro_regime_dir_info(*, create: bool = False) -> ResolvedPath:
    return _child(macro_forecast_dir_info(create=False), Path("Regime"), create=create)


def macro_regime_dir(*, create: bool = False) -> Path:
    return macro_regime_dir_info(create=create).path


def analogue_fans_dir_info(*, create: bool = False) -> ResolvedPath:
    return _child(macro_forecast_dir_info(create=False), Path("analogue_fans"), create=create)


def analogue_fans_dir(*, create: bool = False) -> Path:
    return analogue_fans_dir_info(create=create).path
