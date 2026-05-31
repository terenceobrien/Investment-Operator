"""
ForwardContext builder.

This module assembles forward-looking macro context from static configuration
and optional data fetchers. It deliberately does not attach the result to
RegimeState; integration into the regime-building pipeline is a later step.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import yaml

from src.agent_system.schemas.forward import (
    FedPathReading,
    ForwardContext,
    InflationExpectations,
    MarketEvent,
    PredictionMarketReading,
)

FredFetcher = Callable[[str], Optional[float]]


class ForwardContextBuilder:
    """
    Builds a ForwardContext from available data sources with graceful
    degradation. Each sub-component can fail independently; the builder
    returns whatever is available.

    Sources, in current implementation:
    - Fed path: agent_system/config/fed_path.yaml (manually maintained)
    - Inflation expectations: FRED series T2YIE, T5YIE, T10YIE, T5YIFR
      (fetched via the existing FRED client; pass a fetcher to the
      constructor so it's testable with mocks)
    - Catalysts: agent_system/config/forward_calendar.yaml
    - Prediction markets: STUB for v1 — returns empty list; the field
      remains in the schema so it can be populated later without
      schema changes.

    The build() method always returns a ForwardContext, never None — even
    if every data source fails, it returns a ForwardContext with empty
    lists and data_quality_notes explaining what failed. The CALLER
    (regime builder) decides whether to attach it to RegimeState or set
    forward_context=None entirely.
    """

    def __init__(
        self,
        fred_fetcher: Optional[FredFetcher] = None,
        config_dir: Optional[Path] = None,
    ):
        self.fred_fetcher = fred_fetcher
        self.config_dir = (
            Path(config_dir)
            if config_dir is not None
            else Path(__file__).resolve().parents[1] / "config"
        )

    def build(self) -> ForwardContext:
        """Build a ForwardContext from all currently configured sources."""
        notes: list[str] = []

        fed_path, fed_error = self._build_fed_path()
        if fed_error:
            notes.append(f"Fed path: {fed_error}")

        inflation, inflation_error = self._build_inflation_expectations()
        if inflation_error:
            notes.append(f"Inflation expectations: {inflation_error}")

        catalysts, catalyst_error = self._build_catalysts()
        if catalyst_error:
            notes.append(f"Catalysts: {catalyst_error}")

        prediction_markets, prediction_error = self._build_prediction_markets()
        if prediction_error:
            notes.append(f"Prediction markets: {prediction_error}")

        return ForwardContext(
            fed_path=fed_path,
            inflation_expectations=inflation,
            upcoming_catalysts=catalysts,
            prediction_market_signals=prediction_markets,
            as_of=datetime.now(timezone.utc),
            data_quality_notes="; ".join(notes),
        )

    def _build_fed_path(self) -> tuple[list[FedPathReading], Optional[str]]:
        """Returns (readings, error_note). Empty readings + error_note on failure."""
        path = self.config_dir / "fed_path.yaml"
        try:
            data = self._load_yaml_mapping(path)
            source_note = data.get("source_note", "")
            meetings = data.get("meetings", [])
            if not isinstance(meetings, list):
                return [], "fed_path.yaml field 'meetings' must be a list"

            readings = [
                FedPathReading(source=source_note, **meeting)
                for meeting in meetings
                if isinstance(meeting, dict)
            ]
            if len(readings) != len(meetings):
                return readings, "fed_path.yaml contained non-mapping meeting entries"
            return readings, None
        except Exception as exc:
            return [], f"{path.name} unavailable or invalid ({exc})"

    def _build_inflation_expectations(
        self,
    ) -> tuple[Optional[InflationExpectations], Optional[str]]:
        if self.fred_fetcher is None:
            return None, "fred_fetcher not provided; skipped TIPS breakevens"

        series_map = {
            "breakeven_2y": "T2YIE",
            "breakeven_5y": "T5YIE",
            "breakeven_10y": "T10YIE",
            "forward_5y5y": "T5YIFR",
        }
        values: dict[str, Optional[float]] = {}
        failed: list[str] = []

        for field_name, series_id in series_map.items():
            try:
                values[field_name] = self.fred_fetcher(series_id)
            except Exception as exc:
                values[field_name] = None
                failed.append(f"{series_id}: {exc}")

        notes = "30-day trend not computed in v1; historical FRED fetcher required."
        if failed:
            notes = f"{notes} Fetch failures: {', '.join(failed)}."

        inflation = InflationExpectations(
            **values,
            as_of=datetime.now(timezone.utc),
            trend_30d=None,
            notes=notes,
        )
        if all(value is None for value in values.values()):
            return inflation, "fred_fetcher returned no breakeven values"
        if failed:
            return inflation, "partial FRED fetch failure"
        return inflation, None

    def _build_catalysts(self) -> tuple[list[MarketEvent], Optional[str]]:
        path = self.config_dir / "forward_calendar.yaml"
        try:
            data = self._load_yaml_mapping(path)
            events = data.get("events", [])
            if not isinstance(events, list):
                return [], "forward_calendar.yaml field 'events' must be a list"

            catalysts = [
                MarketEvent(**event)
                for event in events
                if isinstance(event, dict)
            ]
            if len(catalysts) != len(events):
                return catalysts, "forward_calendar.yaml contained non-mapping event entries"
            return catalysts, None
        except Exception as exc:
            return [], f"{path.name} unavailable or invalid ({exc})"

    def _build_prediction_markets(
        self,
    ) -> tuple[list[PredictionMarketReading], Optional[str]]:
        # Stub: returns ([], None) for v1. Wired in a later phase.
        return [], None

    def _load_yaml_mapping(self, path: Path) -> dict:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise ValueError(f"{path.name} must contain a YAML mapping")
        return data
