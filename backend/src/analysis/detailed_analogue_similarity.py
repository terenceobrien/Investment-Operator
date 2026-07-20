"""Detailed raw-input analogue similarity for Macro Forecast V2."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

import numpy as np
import pandas as pd

from src.agent_system.schemas.macro_forecast import ForecastInputSet, MacroInputSignal


DEFAULT_GROUP_WEIGHTS_3M: dict[str, float] = {
    "regime_layers": 0.20,
    "monetary_liquidity": 0.15,
    "credit": 0.15,
    "volatility": 0.10,
    "breadth_market_structure": 0.15,
    "positioning": 0.05,
    "rates_fx": 0.10,
    "commodities_oil": 0.07,
    "sector_leadership": 0.02,
    "path_momentum": 0.01,
    "theme_catalysts": 0.00,
}


@dataclass(frozen=True)
class FeatureSpec:
    feature_id: str
    historical_column: str
    group: str
    transform: str = "identity"
    weight: float = 1.0
    missing_policy: str = "skip"
    clip_z: float = 3.0


@dataclass(frozen=True)
class GroupMatchResult:
    group: str
    similarity: float
    distance: float
    features_used: int
    features_missing: int
    top_matched_features: list[str] = field(default_factory=list)
    top_mismatched_features: list[str] = field(default_factory=list)
    missing_feature_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DetailedAnalogueSimilarityResult:
    overall_similarity: float
    overall_distance: float
    group_results: list[GroupMatchResult]
    features_used: int
    features_missing: list[str]
    warnings: list[str] = field(default_factory=list)


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        out = float(value)
        if not np.isfinite(out):
            return None
        return out
    except (TypeError, ValueError):
        return None


def _historical_group_for_signal(signal: MacroInputSignal) -> str:
    if signal.historical_similarity_group:
        return signal.historical_similarity_group
    mapping = {
        "monetary": "monetary_liquidity",
        "credit": "credit",
        "volatility": "volatility",
        "breadth": "breadth_market_structure",
        "positioning": "positioning",
        "market_state": "path_momentum",
        "rates_fx": "rates_fx",
        "commodities": "commodities_oil",
        "earnings": "theme_catalysts",
        "geopolitical": "theme_catalysts",
    }
    return mapping.get(str(signal.parent_layer or ""), "regime_layers")


def _feature_value_from_signal(signal: MacroInputSignal) -> Any:
    return signal.transformed_value if signal.transformed_value is not None else signal.raw_value


def feature_specs_from_forecast_input_set(forecast_input_set: ForecastInputSet) -> list[FeatureSpec]:
    specs: list[FeatureSpec] = []
    seen: set[str] = set()
    for signal in forecast_input_set.all_signals:
        if not signal.used_in_historical_similarity:
            continue
        feature_id = signal.historical_feature_id
        column = signal.historical_column
        if not feature_id or not column:
            continue
        if feature_id in seen:
            continue
        seen.add(feature_id)
        specs.append(
            FeatureSpec(
                feature_id=feature_id,
                historical_column=column,
                group=_historical_group_for_signal(signal),
                weight=float(signal.historical_similarity_weight or signal.confidence or 1.0),
            )
        )
    return specs


def build_current_feature_vector_for_analogues(
    forecast_input_set: ForecastInputSet,
    regime_state: Any | None = None,
    market_state: Any | None = None,
    extra_features: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current_features: dict[str, Any] = {}
    for signal in forecast_input_set.all_signals:
        if not signal.used_in_historical_similarity:
            continue
        feature_id = signal.historical_feature_id
        if not feature_id or not signal.historical_column:
            continue
        value = _feature_value_from_signal(signal)
        if value is not None:
            current_features[feature_id] = value

    if regime_state is not None:
        current_features.setdefault("score_total", getattr(regime_state, "composite", None))
        current_features.setdefault("environment", getattr(regime_state, "environment", None) or getattr(regime_state, "regime_label", None))
        current_features.setdefault("confidence", getattr(regime_state, "composite_confidence", None))
        layers = getattr(regime_state, "layers", None)
        if layers is not None:
            for layer_name in ["monetary", "credit", "volatility", "breadth", "positioning"]:
                layer = getattr(layers, layer_name, None)
                if layer is not None:
                    current_features.setdefault(f"layer_{layer_name}", getattr(layer, "score", None))
            layer_scores = [
                _safe_float(getattr(getattr(layers, layer_name, None), "score", None))
                for layer_name in ["monetary", "credit", "volatility", "breadth", "positioning"]
            ]
            clean_scores = [value for value in layer_scores if value is not None]
            if clean_scores:
                current_features.setdefault("layer_agreement", 1.0 - min(float(np.std(clean_scores)) / 5.0, 1.0))

    if market_state is not None:
        for field in ["vix_level", "sectors_green", "score_delta"]:
            value = getattr(market_state, field, None)
            if value is not None:
                current_features.setdefault(field, value)

    if extra_features:
        current_features.update(extra_features)
    return current_features


def diagnose_forecast_input_set_for_analogue_features(
    forecast_input_set: ForecastInputSet,
) -> dict[str, Any]:
    """Audit which ForecastInputSet signals can truly feed detailed similarity."""

    current_features_by_group: dict[str, list[str]] = {}
    raw_signals_used: list[str] = []
    raw_signals_missing_values: list[str] = []
    raw_signals_missing_historical_column: list[str] = []
    raw_signals_missing_feature_id: list[str] = []

    current_features_count = 0
    for signal in forecast_input_set.all_signals:
        if not signal.used_in_historical_similarity:
            continue
        feature_id = signal.historical_feature_id
        column = signal.historical_column
        value = _feature_value_from_signal(signal)
        if value is None:
            if signal.role == "raw_component":
                raw_signals_missing_values.append(signal.input_id)
            continue
        if not feature_id:
            if signal.role == "raw_component":
                raw_signals_missing_feature_id.append(signal.input_id)
            continue
        if not column:
            if signal.role == "raw_component":
                raw_signals_missing_historical_column.append(signal.input_id)
            continue

        current_features_count += 1
        group = _historical_group_for_signal(signal)
        current_features_by_group.setdefault(group, []).append(feature_id)
        if signal.role == "raw_component":
            raw_signals_used.append(feature_id)

    return {
        "current_features_count": current_features_count,
        "current_features_by_group": {
            group: sorted(dict.fromkeys(features))
            for group, features in sorted(current_features_by_group.items())
        },
        "raw_signals_used_for_similarity": sorted(dict.fromkeys(raw_signals_used)),
        "raw_signals_missing_values": sorted(dict.fromkeys(raw_signals_missing_values)),
        "raw_signals_missing_historical_column": sorted(dict.fromkeys(raw_signals_missing_historical_column)),
        "raw_signals_missing_feature_id": sorted(dict.fromkeys(raw_signals_missing_feature_id)),
    }


def default_feature_specs(current_features: Mapping[str, Any]) -> list[FeatureSpec]:
    group_by_feature = {
        "score_total": "regime_layers",
        "confidence": "regime_layers",
        "layer_agreement": "regime_layers",
        "layer_monetary": "regime_layers",
        "layer_credit": "regime_layers",
        "layer_volatility": "regime_layers",
        "layer_breadth": "regime_layers",
        "layer_positioning": "regime_layers",
        "vix_level": "volatility",
        "vix_z_20d": "volatility",
        "vix_term_slope": "volatility",
        "vvix_level": "volatility",
        "vvix_z": "volatility",
        "put_call_ratio": "volatility",
        "skew_index": "volatility",
        "sectors_green": "breadth_market_structure",
        "score_delta": "path_momentum",
    }
    specs: list[FeatureSpec] = []
    for feature_id, value in current_features.items():
        if feature_id.startswith("_"):
            continue
        if _safe_float(value) is None:
            continue
        specs.append(
            FeatureSpec(
                feature_id=str(feature_id),
                historical_column=str(feature_id),
                group=group_by_feature.get(str(feature_id), "regime_layers"),
            )
        )
    return specs


def _row_value(row: Mapping[str, Any] | pd.Series, column: str) -> Any:
    if isinstance(row, pd.Series):
        return row.get(column)
    return row.get(column)


def compute_detailed_similarity(
    current_features: Mapping[str, Any],
    historical_row: Mapping[str, Any] | pd.Series,
    feature_specs: list[FeatureSpec] | None = None,
    group_weights: dict[str, float] | None = None,
) -> DetailedAnalogueSimilarityResult:
    specs = feature_specs or default_feature_specs(current_features)
    weights = group_weights or DEFAULT_GROUP_WEIGHTS_3M
    warnings: list[str] = []
    group_items: dict[str, list[tuple[str, float, float]]] = {}
    group_missing: dict[str, list[str]] = {}
    missing_features: list[str] = []

    for spec in specs:
        current_value = _safe_float(current_features.get(spec.feature_id))
        historical_value = _safe_float(_row_value(historical_row, spec.historical_column))
        if current_value is None or historical_value is None:
            missing_features.append(spec.feature_id)
            group_missing.setdefault(spec.group, []).append(spec.feature_id)
            continue
        clip = max(float(spec.clip_z or 3.0), 1e-6)
        distance = min(abs(current_value - historical_value), clip) / clip
        similarity = max(0.0, 100.0 * (1.0 - distance))
        group_items.setdefault(spec.group, []).append((spec.feature_id, distance, similarity * max(spec.weight, 0.0)))

    group_results: list[GroupMatchResult] = []
    weighted_distances: list[tuple[float, float]] = []
    for group in sorted(set(group_items) | set(group_missing)):
        items = group_items.get(group, [])
        if items:
            distances = np.array([item[1] for item in items], dtype=float)
            distance = float(distances.mean())
            similarity = max(0.0, 100.0 * (1.0 - distance))
            ordered = sorted(items, key=lambda item: item[1])
            top_matched = [item[0] for item in ordered[:3]]
            top_mismatched = [item[0] for item in ordered[-3:]][::-1]
            weight = weights.get(group, 0.0)
            if weight > 0:
                weighted_distances.append((distance, weight))
        else:
            distance = 1.0
            similarity = 0.0
            top_matched = []
            top_mismatched = []
        group_results.append(
            GroupMatchResult(
                group=group,
                similarity=round(similarity, 2),
                distance=round(distance, 4),
                features_used=len(items),
                features_missing=len(group_missing.get(group, [])),
                top_matched_features=top_matched,
                top_mismatched_features=top_mismatched,
                missing_feature_ids=group_missing.get(group, []),
            )
        )

    if weighted_distances:
        total_weight = sum(weight for _, weight in weighted_distances)
        overall_distance = sum(distance * weight for distance, weight in weighted_distances) / total_weight
    else:
        overall_distance = 1.0
        warnings.append("No detailed analogue features were usable; detailed similarity set to zero.")
    overall_similarity = max(0.0, 100.0 * (1.0 - overall_distance))

    return DetailedAnalogueSimilarityResult(
        overall_similarity=round(overall_similarity, 2),
        overall_distance=round(overall_distance, 4),
        group_results=group_results,
        features_used=sum(result.features_used for result in group_results),
        features_missing=missing_features,
        warnings=warnings,
    )


def result_to_dict(result: DetailedAnalogueSimilarityResult) -> dict[str, Any]:
    return {
        "overall_similarity": result.overall_similarity,
        "overall_distance": result.overall_distance,
        "features_used": result.features_used,
        "features_missing": result.features_missing,
        "warnings": result.warnings,
        "group_results": [
            {
                "group": group.group,
                "similarity": group.similarity,
                "distance": group.distance,
                "features_used": group.features_used,
                "features_missing": group.features_missing,
                "top_matched_features": group.top_matched_features,
                "top_mismatched_features": group.top_mismatched_features,
                "missing_feature_ids": group.missing_feature_ids,
            }
            for group in result.group_results
        ],
    }
