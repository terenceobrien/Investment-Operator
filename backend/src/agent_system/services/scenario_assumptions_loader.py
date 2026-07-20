"""Validated loader for scenario-conditioned Monte Carlo assumptions."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from src.agent_system.schemas.monte_carlo import (
    BucketReturnAssumption,
    ScenarioReturnAssumption,
    ScenarioReturnAssumptions,
)


class ScenarioAssumptionsLoader:
    """Load and expose scenario return assumptions from calibrated references."""

    def __init__(
        self,
        path: str = "data/reference/scenario_return_assumptions.json",
        *,
        market_returns_path: str = "data/reference/scenario_market_returns.csv",
        theme_returns_path: str = "data/reference/scenario_theme_returns.csv",
        prefer_calibrated_csv: bool = True,
    ) -> None:
        self.path = Path(path)
        self.market_returns_path = Path(market_returns_path)
        self.theme_returns_path = Path(theme_returns_path)
        if (
            prefer_calibrated_csv
            and self.market_returns_path.exists()
            and self.theme_returns_path.exists()
        ):
            payload = self._load_csv_assumptions()
        else:
            payload = self._load_json_assumptions()
        if not isinstance(payload, dict):
            raise ValueError(
                f"Scenario return assumptions must contain a JSON object: {self.path}"
            )
        try:
            self.assumptions = ScenarioReturnAssumptions.model_validate(payload)
        except ValidationError as exc:
            raise ValueError(
                f"Scenario return assumptions failed schema validation: {self.path}"
            ) from exc

    def _load_json_assumptions(self) -> dict[str, Any]:
        if not self.path.exists():
            raise FileNotFoundError(
                f"Scenario return assumptions file is missing: {self.path}"
            )
        try:
            payload: dict[str, Any] = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Scenario return assumptions file is not valid JSON: {self.path}"
            ) from exc
        return payload

    def _load_csv_assumptions(self) -> dict[str, Any]:
        scenarios: dict[str, dict[str, Any]] = {}
        last_updated_values: list[str] = []
        horizon_days_values: list[int] = []

        for row in self._read_csv_rows(self.market_returns_path):
            scenario_id = str(row.get("scenario_id") or "").strip()
            ticker = str(row.get("ticker") or "").strip().upper()
            bucket = self._bucket_from_row(row)
            if not scenario_id or not ticker or bucket is None:
                continue
            scenario = scenarios.setdefault(scenario_id, {"market": {}, "themes": {}})
            scenario["market"][ticker] = bucket
            self._collect_metadata(row, last_updated_values, horizon_days_values)

        for row in self._read_csv_rows(self.theme_returns_path):
            scenario_id = str(row.get("scenario_id") or "").strip()
            theme_id = str(row.get("theme_id") or "").strip()
            bucket = self._bucket_from_row(row)
            if not scenario_id or not theme_id or bucket is None:
                continue
            scenario = scenarios.setdefault(scenario_id, {"market": {}, "themes": {}})
            scenario["themes"][theme_id] = bucket
            self._collect_metadata(row, last_updated_values, horizon_days_values)

        if not scenarios:
            raise ValueError(
                "Calibrated scenario return CSVs did not contain any usable rows: "
                f"{self.market_returns_path}, {self.theme_returns_path}"
            )

        horizon_days = (
            max(set(horizon_days_values), key=horizon_days_values.count)
            if horizon_days_values
            else 63
        )
        return {
            "metadata": {
                "description": (
                    "Scenario-conditioned return and volatility assumptions loaded "
                    "from calibrated CSV files."
                ),
                "last_updated": max(last_updated_values) if last_updated_values else None,
                "horizon_days": horizon_days,
                "market_returns_path": str(self.market_returns_path),
                "theme_returns_path": str(self.theme_returns_path),
            },
            "scenarios": scenarios,
        }

    @staticmethod
    def _read_csv_rows(path: Path) -> list[dict[str, str]]:
        with path.open("r", encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))

    @staticmethod
    def _bucket_from_row(row: dict[str, str]) -> dict[str, float] | None:
        try:
            expected_return = float(row.get("expected_return") or "")
            volatility = float(row.get("volatility") or "")
        except ValueError:
            return None
        return {"expected_return": expected_return, "volatility": volatility}

    @staticmethod
    def _collect_metadata(
        row: dict[str, str],
        last_updated_values: list[str],
        horizon_days_values: list[int],
    ) -> None:
        last_updated = str(row.get("last_updated") or "").strip()
        if last_updated:
            last_updated_values.append(last_updated)
        try:
            horizon_days_values.append(int(float(row.get("horizon_days") or "")))
        except ValueError:
            pass

    def get_scenario(self, scenario_id: str) -> ScenarioReturnAssumption:
        try:
            return self.assumptions.scenarios[scenario_id]
        except KeyError as exc:
            available = ", ".join(self.available_scenarios())
            raise KeyError(
                f"Scenario return assumptions not found for {scenario_id!r}. "
                f"Available scenarios: {available}"
            ) from exc

    def get_market_return(
        self,
        scenario_id: str,
        ticker: str,
    ) -> BucketReturnAssumption:
        scenario = self.get_scenario(scenario_id)
        key = ticker.strip().upper()
        if key in scenario.market:
            return scenario.market[key]
        if "SPY" in scenario.market:
            return scenario.market["SPY"]
        raise KeyError(
            f"Market return assumption for {key!r} and SPY fallback are missing "
            f"in scenario {scenario_id!r}."
        )

    def get_theme_return(
        self,
        scenario_id: str,
        theme: str,
    ) -> BucketReturnAssumption:
        scenario = self.get_scenario(scenario_id)
        key = theme.strip()
        if key in scenario.themes:
            return scenario.themes[key]
        if "unclassified" in scenario.themes:
            return scenario.themes["unclassified"]
        return BucketReturnAssumption(expected_return=0.0, volatility=0.20)

    def available_scenarios(self) -> list[str]:
        return list(self.assumptions.scenarios)

    def probability_weighted_market_return(
        self,
        scenario_probabilities: dict[str, float],
        ticker: str = "SPY",
    ) -> float:
        return sum(
            float(probability)
            * self.get_market_return(scenario_id, ticker).expected_return
            for scenario_id, probability in scenario_probabilities.items()
        )
