"""Post-portfolio exposure enrichment for Monte Carlo inputs."""
from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any

from src.agent_system.scenarios.types import TradeScenarioAnalysis
from src.agent_system.schemas.monte_carlo import TradeExposure
from src.agent_system.schemas.thematic import InstrumentType
from src.agent_system.schemas.trade import TradeIdea
from src.agent_system.services.market_data_cache import MarketDataCache
from src.agent_system.paths import reference_data_dir


REFERENCE_DIR = reference_data_dir(create=False)
logger = logging.getLogger(__name__)

DEFAULT_THEME_BETAS = {
    "metadata": {
        "description": "Theme-level beta scalars relative to SPY. Manually maintained.",
        "last_updated": "2026-06-14",
    },
    "theme_betas": {
        "grid_power_infrastructure": 0.90,
        "quality_ex_ai_cash_flow": 0.72,
        "electrical_equipment": 0.85,
        "engineering_construction": 0.88,
        "industrial_distribution": 0.75,
        "environmental_services": 0.45,
        "financial_data_exchanges": 0.42,
        "insurance_brokers": 0.44,
        "payroll_human_capital": 0.50,
        "auto_parts_salvage": 0.48,
        "cash_short_duration": 0.08,
        "quality_ai": 1.15,
        "high_beta_ai_semis": 1.45,
        "small_caps": 1.20,
        "long_duration_growth": 1.10,
        "unclassified": 1.0,
    },
}

CONVICTION_THEME_EXPOSURE = {
    "exceptional": 0.95,
    "strong": 0.90,
    "moderate": 0.70,
    "weak": 0.50,
    "pass": 0.30,
}


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    if not isinstance(payload, dict):
        raise ValueError(f"Reference file must contain a JSON object: {path}")
    return payload


def _normalize_key(value: str | None) -> str:
    return " ".join((value or "").strip().lower().replace("_", " ").split())


def _enum_value(value: Any) -> str:
    return getattr(value, "value", str(value))


class ExposureEnrichmentService:
    """Enrich accepted trades with beta, theme, scenario, and confidence inputs."""

    def __init__(
        self,
        *,
        market_data_cache: MarketDataCache | None = None,
        theme_betas_path: str | Path | None = None,
        priority_theme_map_path: str | Path | None = None,
    ) -> None:
        self.market_data_cache = market_data_cache or MarketDataCache()
        self.theme_betas_path = Path(theme_betas_path) if theme_betas_path else REFERENCE_DIR / "theme_betas.json"
        self.priority_theme_map_path = (
            Path(priority_theme_map_path) if priority_theme_map_path else REFERENCE_DIR / "priority_theme_map.json"
        )
        self.theme_betas_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.theme_betas_path.exists():
            self.theme_betas_path.write_text(
                json.dumps(DEFAULT_THEME_BETAS, indent=2, sort_keys=False) + "\n",
                encoding="utf-8",
            )
        self._theme_betas = _load_json(self.theme_betas_path)
        if self.priority_theme_map_path.exists():
            self._priority_theme_map = _load_json(self.priority_theme_map_path)
        else:
            logger.warning("Priority theme map not found at %s; using empty theme mappings", self.priority_theme_map_path)
            self._priority_theme_map = {}

    def enrich(
        self,
        trade_idea: TradeIdea,
        scenario_analysis: TradeScenarioAnalysis,
        final_size_pct: float,
    ) -> TradeExposure:
        """Build a standalone exposure artifact for one accepted trade."""
        if trade_idea.expression is None:
            raise ValueError("TradeExposure enrichment requires trade_idea.expression")

        instrument = trade_idea.expression.primary_instrument
        instrument_type = _enum_value(instrument.instrument_type)
        sector, beta, beta_source = self._lookup_beta(trade_idea.underlying)
        theme = self._theme(trade_idea)
        theme_exposure, theme_source = self._lookup_theme_exposure(trade_idea)
        theme_beta, theme_beta_source = self._lookup_theme_beta(theme)
        scenario_exposures = self._scenario_exposures(scenario_analysis)
        idio_vol = self._idiosyncratic_volatility(scenario_analysis)
        scenario_source = "derived_from_scenario_pnl"
        idio_source = "scenario_pnl_range"
        confidence = self._overall_confidence(
            beta_source,
            beta_source,
            theme_source,
            theme_beta_source,
            scenario_source,
            idio_source,
        )

        return TradeExposure(
            trade_idea_id=trade_idea.id or trade_idea.underlying,
            underlying=trade_idea.underlying,
            theme=theme,
            instrument_type=instrument_type,
            position_size_pct=final_size_pct,
            delta=self._delta(instrument_type, _enum_value(instrument.direction)),
            market_beta=beta,
            market_beta_source=beta_source,
            sector=sector,
            sector_beta=beta,
            sector_beta_source=beta_source,
            theme_exposure=theme_exposure,
            theme_exposure_source=theme_source,
            theme_beta=theme_beta,
            theme_beta_source=theme_beta_source,
            scenario_exposures=scenario_exposures,
            scenario_exposure_source=scenario_source,
            idiosyncratic_volatility=idio_vol,
            idiosyncratic_vol_source=idio_source,
            fundamental_conviction=self._fundamental_conviction(trade_idea),
            narrative_conviction=self._narrative_conviction(trade_idea),
            overall_confidence=confidence,
        )

    def enrich_portfolio(
        self,
        accepted_trades: list[tuple[TradeIdea, TradeScenarioAnalysis, float]],
    ) -> list[TradeExposure]:
        """Enrich a batch of accepted trade/scenario/final-size tuples."""
        return [
            self.enrich(trade_idea, scenario_analysis, final_size_pct)
            for trade_idea, scenario_analysis, final_size_pct in accepted_trades
        ]

    def _lookup_beta(
        self,
        ticker: str,
    ) -> tuple[str, float, str]:
        beta, sector, source = self.market_data_cache.get_beta_and_sector(ticker)
        return sector, beta, source

    def _lookup_theme_exposure(self, trade_idea: TradeIdea) -> tuple[float, str]:
        rating = _enum_value(trade_idea.combined_conviction.rating).lower()
        return CONVICTION_THEME_EXPOSURE.get(rating, 0.50), "conviction_derived"

    def _lookup_theme_beta(self, theme: str) -> tuple[float, str]:
        theme_betas = self._theme_betas.get("theme_betas", self._theme_betas)
        if not isinstance(theme_betas, dict):
            return 1.0, "manual_estimate"
        normalized = _normalize_key(theme)
        for key, value in theme_betas.items():
            if _normalize_key(str(key)) == normalized and isinstance(value, (int, float)):
                return float(value), "theme_betas_file"
        return 1.0, "manual_estimate"

    def _theme(self, trade_idea: TradeIdea) -> str:
        if trade_idea.research_priority is None:
            return "unclassified"
        raw = trade_idea.research_priority.theme or ""
        return self._normalize_theme(raw)

    def _normalize_theme(self, raw: str) -> str:
        key = raw.strip().lower()
        mappings = self._priority_theme_map.get("mappings", self._priority_theme_map)
        if key in mappings:
            return mappings[key]

        theme_betas = self._theme_betas.get("theme_betas", self._theme_betas)
        if not isinstance(theme_betas, dict):
            logger.warning("Theme betas reference is invalid; using 'unclassified' for theme '%s'", raw)
            return "unclassified"

        direct_key = raw.strip().lower().replace(" ", "_")
        if direct_key in theme_betas:
            return direct_key

        spaced_key = raw.strip().lower().replace("_", " ").replace("-", " ")
        if spaced_key in {k.replace("_", " ") for k in theme_betas}:
            return raw.strip().lower().replace(" ", "_").replace("-", "_")

        raw_words = set(key.replace("_", " ").replace("-", " ").split())
        best_key, best_score = "unclassified", 0
        for theme_key in theme_betas:
            theme_words = set(theme_key.replace("_", " ").split())
            score = len(raw_words & theme_words)
            if score > best_score:
                best_key, best_score = theme_key, score
        if best_score >= 2:
            logger.info("Theme '%s' fuzzy-matched to '%s' (score %d)", raw, best_key, best_score)
            return best_key

        logger.warning("Could not map theme '%s' to a known theme ID; using 'unclassified'", raw)
        return "unclassified"

    def _scenario_exposures(
        self,
        scenario_analysis: TradeScenarioAnalysis,
    ) -> dict[str, float]:
        expected = scenario_analysis.expected_return
        return {
            score.scenario_id: max(-1.5, min(1.5, score.expected_pnl_pct - expected))
            for score in scenario_analysis.scenario_scores
        }

    def _idiosyncratic_volatility(
        self,
        scenario_analysis: TradeScenarioAnalysis,
    ) -> float:
        scores = scenario_analysis.scenario_scores
        if not scores:
            return 0.0
        weights = {
            score.scenario_id: float(scenario_analysis.scenario_weights_used.get(score.scenario_id, 0.0))
            for score in scores
        }
        total_weight = sum(max(0.0, weight) for weight in weights.values())
        if total_weight <= 0.0:
            weights = {score.scenario_id: 1.0 / len(scores) for score in scores}
            total_weight = 1.0
        values = {score.scenario_id: score.expected_pnl_pct for score in scores}
        mean = sum(values[scenario_id] * max(0.0, weight) for scenario_id, weight in weights.items()) / total_weight
        variance = sum(
            max(0.0, weight) * (values[scenario_id] - mean) ** 2
            for scenario_id, weight in weights.items()
        ) / total_weight
        return math.sqrt(max(0.0, variance))

    def _delta(self, instrument_type: str, direction: str) -> float:
        if instrument_type == InstrumentType.SINGLE_STOCK.value:
            return 1.0
        if instrument_type == InstrumentType.OPTION_UNDERLYING.value or direction == "spread":
            return 0.5
        return 0.5

    def _fundamental_conviction(self, trade_idea: TradeIdea) -> str:
        if trade_idea.fundamental is not None:
            return _enum_value(trade_idea.fundamental.conviction.rating)
        return _enum_value(trade_idea.combined_conviction.rating)

    def _narrative_conviction(self, trade_idea: TradeIdea) -> str:
        if trade_idea.narrative is not None:
            return _enum_value(trade_idea.narrative.conviction.rating)
        return "unknown"

    def _overall_confidence(self, *sources: str) -> str:
        if any(source == "manual_estimate" for source in sources):
            return "low"
        if any(source == "sector_proxy" for source in sources):
            return "medium"
        return "high"

    @staticmethod
    def _clip_unit(value: float) -> float:
        return max(0.0, min(1.0, value))
