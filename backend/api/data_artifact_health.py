"""Warning-only startup checks for API data artifacts."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

import api.macro_router as macro_router_module
import api.portfolio_router as portfolio_router_module
import api.strategy_router as strategy_router_module


logger = logging.getLogger("api.main")


@dataclass(frozen=True)
class DataArtifactCheck:
    name: str
    path: Path
    resolution_source: str
    kind: str = "file"
    alternates: tuple[Path, ...] = ()

    def exists(self) -> bool:
        if self.kind == "dir":
            return self.path.is_dir()
        if self.kind == "file_or_dir":
            return self.path.exists() or self.path.is_symlink()
        if self.kind == "any_file":
            return any(path.is_file() for path in (self.path, *self.alternates))
        return self.path.is_file()


def _env_source(name: str, default: str) -> str:
    return f"env:{name}" if os.getenv(name) else default


def required_data_artifacts() -> list[DataArtifactCheck]:
    from src.agent_system.forecasting.theme_exposure_matrix import (
        scenario_theme_returns_artifact_path,
    )

    theme_returns_path, theme_returns_source = scenario_theme_returns_artifact_path()
    checks = [
        DataArtifactCheck(
            name="behavioral_scenario_theme_returns_csv",
            path=theme_returns_path,
            resolution_source=theme_returns_source,
        ),
        DataArtifactCheck(
            name="strategy_research_data_csv",
            path=strategy_router_module.DATA_PATH,
            resolution_source=_env_source("RESEARCH_DATA_PATH", "default:api.strategy_router.DATA_PATH"),
        ),
        DataArtifactCheck(
            name="macro_forecast_report_dir",
            path=macro_router_module._forecast_root(),
            resolution_source=_env_source("MACRO_FORECAST_DIR", "default:repo_data_macro_forecasts"),
            kind="dir",
        ),
        DataArtifactCheck(
            name="portfolio_risk_source",
            path=portfolio_router_module._configured_risk_source(),
            resolution_source=_env_source("RISK_REPORT_PATH", "default:risk/current"),
            kind="file_or_dir",
        ),
    ]

    backtest_candidates = tuple(macro_router_module._backtest_master_candidates())
    if backtest_candidates:
        checks.append(
            DataArtifactCheck(
                name="macro_indicator_backtest_csv",
                path=macro_router_module._resolve_backtest_master_path() or backtest_candidates[0],
                resolution_source=(
                    "env:BACKTEST_MASTER_FILE"
                    if os.getenv("BACKTEST_MASTER_FILE") or os.getenv("BACKTEST_MASTER_PATH")
                    else _env_source("RESEARCH_DATA_PATH", "default:macro_router_backtest_candidates")
                ),
                kind="any_file",
                alternates=backtest_candidates[1:],
            )
        )

    try:
        from src.analysis import analogues

        checks.append(
            DataArtifactCheck(
                name="legacy_analogue_research_csv",
                path=analogues.DATA_PATH,
                resolution_source=_env_source("RESEARCH_DATA_PATH", "default:analysis.analogues.DATA_PATH"),
            )
        )
    except Exception as exc:
        logger.warning("startup data artifact resolver failed: name=legacy_analogue_research_csv error=%s", exc)

    try:
        from src.analysis import conditional_probability

        checks.append(
            DataArtifactCheck(
                name="conditional_probability_research_csv",
                path=conditional_probability.DATA_PATH,
                resolution_source=_env_source("RESEARCH_DATA_PATH", "default:analysis.conditional_probability.DATA_PATH"),
            )
        )
    except Exception as exc:
        logger.warning("startup data artifact resolver failed: name=conditional_probability_research_csv error=%s", exc)

    try:
        from src.analysis import historical_narrative

        checks.append(
            DataArtifactCheck(
                name="historical_narrative_research_csv",
                path=historical_narrative.DATA_PATH,
                resolution_source=_env_source("RESEARCH_DATA_PATH", "default:analysis.historical_narrative.DATA_PATH"),
            )
        )
    except Exception as exc:
        logger.warning("startup data artifact resolver failed: name=historical_narrative_research_csv error=%s", exc)

    return checks


def log_required_data_artifact_health() -> None:
    try:
        checks = required_data_artifacts()
    except Exception as exc:
        logger.warning("startup data artifact health check failed before completion: %s", exc)
        return

    for check in checks:
        if check.exists():
            continue
        alternate_text = (
            " checked_alternates="
            + ",".join(str(path) for path in check.alternates)
            if check.alternates
            else ""
        )
        logger.warning(
            "startup data artifact missing: name=%s resolved_path=%s resolution_source=%s kind=%s%s",
            check.name,
            check.path,
            check.resolution_source,
            check.kind,
            alternate_text,
        )
