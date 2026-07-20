"""Adapters from macro forecast JSON into deep-fundamental context packs."""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

from src.agent_system.schemas.deep_fundamental import (
    CompanyProfile,
    DataConfidence,
    MacroContextPack,
    MacroImpactDirection,
    MacroRankingContext,
    MacroScenarioContext,
    MacroSignalContext,
    RejectedThemeMapping,
    ThemeCatalogItem,
    ThemeContextPack,
    ThemeImpactContext,
    ThemeMappingResult,
    ThemeScoreContext,
)
from src.agent_system.services.theme_mapping_agent import (
    FIT_WEIGHTS,
    build_theme_mapping_for_ticker,
)


PRIMARY_SIGNAL_ROLES = {
    "layer_summary",
    "composite",
    "regime_driver",
    "scenario_falsifier",
}


def load_macro_forecast_json(path: str | Path) -> dict[str, Any]:
    forecast_path = Path(path)
    data = json.loads(forecast_path.read_text())
    if isinstance(data, dict):
        data["_source_path"] = str(forecast_path)
        return data
    raise ValueError(f"Macro forecast JSON at {forecast_path} did not contain an object.")


def build_macro_and_theme_context_from_forecast(
    macro_forecast: dict[str, Any],
    ticker: str,
    company_profile: CompanyProfile,
    refresh_theme_mapping: bool = False,
) -> tuple[MacroContextPack, ThemeContextPack]:
    source_path = macro_forecast.get("_source_path")
    macro_context = extract_macro_context_pack(
        macro_forecast,
        source_path=str(source_path) if source_path else None,
    )
    theme_context = extract_theme_context_pack(
        macro_forecast=macro_forecast,
        ticker=ticker,
        company_profile=company_profile,
        refresh_theme_mapping=refresh_theme_mapping,
    )
    return macro_context, theme_context


def extract_macro_context_pack(
    macro_forecast: dict[str, Any],
    source_path: str | None = None,
) -> MacroContextPack:
    interpretation = _as_dict(macro_forecast.get("forecast_interpretation"))
    source_notes = ["Macro context extracted from existing macro forecast JSON."]
    if source_path:
        source_notes.append(f"Source forecast: {source_path}")

    return MacroContextPack(
        asof_date=_parse_date(macro_forecast.get("asof_date")),
        created_at=_parse_datetime(macro_forecast.get("created_at")),
        regime_id=_to_str(_first_present(macro_forecast, ["regime_id", "id"])),
        regime_label=_to_str(
            _first_present(
                macro_forecast,
                ["regime_label", "regime_read"],
            )
            or interpretation.get("regime_read")
            or interpretation.get("headline")
        ),
        top_scenarios=_extract_scenarios(macro_forecast),
        top_macro_signals=_extract_top_macro_signals(macro_forecast),
        sector_rankings=_extract_rankings(macro_forecast.get("sector_rankings")),
        factor_rankings=_extract_rankings(macro_forecast.get("factor_rankings")),
        summary=_to_str(
            macro_forecast.get("summary")
            or interpretation.get("summary")
            or interpretation.get("headline")
        ),
        source_path=source_path,
        source_notes=source_notes,
    )


def extract_theme_context_pack(
    macro_forecast: dict[str, Any],
    ticker: str,
    company_profile: CompanyProfile,
    refresh_theme_mapping: bool = False,
) -> ThemeContextPack:
    theme_catalog = _extract_theme_catalog(macro_forecast)
    catalog_by_id = {item.theme_id: item for item in theme_catalog}
    mapping = build_theme_mapping_for_ticker(
        ticker=ticker,
        company_profile=company_profile,
        theme_catalog=theme_catalog,
        refresh=refresh_theme_mapping,
        use_llm=False,
    )

    valid_mapped = [
        item for item in mapping.mapped_themes if item.theme_id in catalog_by_id
    ]
    invalid_rejected = [
        RejectedThemeMapping(
            theme_id=item.theme_id,
            theme_label=item.theme_label,
            reason="Mapped theme ID was not present in macro forecast theme catalog.",
        )
        for item in mapping.mapped_themes
        if item.theme_id not in catalog_by_id
    ]
    mapping = mapping.model_copy(
        update={
            "mapped_themes": valid_mapped,
            "rejected_themes": mapping.rejected_themes + invalid_rejected,
        }
    )

    selected_theme_ids = [item.theme_id for item in valid_mapped]
    relevant_scores = _build_theme_scores(catalog_by_id, valid_mapped)
    aggregate_score = _aggregate_theme_support_score(relevant_scores)

    impacts, linked_scenarios, positive, negative, mixed = _extract_theme_impacts(
        macro_forecast,
        selected_theme_ids,
        catalog_by_id,
    )

    if selected_theme_ids:
        summary = (
            f"{ticker.upper()} maps to macro-forecast themes "
            f"{', '.join(selected_theme_ids)}. "
        )
        if aggregate_score is not None:
            summary += f"Aggregate theme support score is {aggregate_score:.2f}."
        else:
            summary += "Aggregate theme support score is unavailable."
    else:
        summary = (
            f"No valid macro-forecast theme mapping was found for {ticker.upper()}."
        )

    notes = ["Theme context extracted from macro forecast theme rankings and signals."]
    if not theme_catalog:
        notes.append("No theme catalog could be extracted from macro forecast.")

    return ThemeContextPack(
        ticker=ticker.upper().strip(),
        selected_theme_ids=selected_theme_ids,
        theme_mapping=mapping,
        relevant_theme_scores=relevant_scores,
        relevant_theme_impacts=impacts,
        linked_scenarios=_dedupe(linked_scenarios),
        positive_drivers=_dedupe(positive),
        negative_drivers=_dedupe(negative),
        mixed_drivers=_dedupe(mixed),
        aggregate_theme_support_score=aggregate_score,
        theme_fit_summary=summary,
        source_notes=notes,
    )


def _extract_scenarios(macro_forecast: dict[str, Any]) -> list[MacroScenarioContext]:
    raw_items: list[dict[str, Any]] = []

    for key in (
        "scenario_rankings",
        "ranked_scenarios",
        "scenarios",
        "scenario_probabilities",
        "scenario_probabilities_blended",
        "scenario_probabilities_deterministic",
    ):
        value = macro_forecast.get(key)
        if isinstance(value, dict):
            for scenario_id, payload in value.items():
                if isinstance(payload, dict):
                    raw_items.append({"scenario_id": scenario_id, **payload})
                else:
                    raw_items.append({"scenario_id": scenario_id, "probability": payload})
        elif isinstance(value, list):
            raw_items.extend(_dict_items(value))
        if raw_items:
            break

    scenarios: list[MacroScenarioContext] = []
    for item in raw_items:
        scenario_id = _to_str(
            item.get("scenario_id")
            or item.get("item_id")
            or item.get("id")
            or item.get("source_id")
        )
        if not scenario_id:
            continue
        scenarios.append(
            MacroScenarioContext(
                scenario_id=scenario_id,
                label=_to_str(item.get("label") or item.get("name")),
                probability=_to_float(item.get("probability") or item.get("prob")),
                score=_to_float(item.get("score") or item.get("source_score")),
                rationale=_to_str(item.get("rationale") or item.get("summary")),
            )
        )

    return sorted(
        scenarios,
        key=lambda item: item.probability if item.probability is not None else -999,
        reverse=True,
    )[:8]


def _extract_top_macro_signals(
    macro_forecast: dict[str, Any],
) -> list[MacroSignalContext]:
    signals = _all_signals(macro_forecast)
    preferred = [
        signal
        for signal in signals
        if signal.get("dedupe_role") == "primary"
        or signal.get("role") in PRIMARY_SIGNAL_ROLES
    ]
    selected = preferred or signals
    selected = sorted(
        enumerate(selected),
        key=lambda pair: (
            _to_float(pair[1].get("signal_strength")) is not None,
            abs(_to_float(pair[1].get("signal_strength")) or 0.0),
            -pair[0],
        ),
        reverse=True,
    )

    contexts: list[MacroSignalContext] = []
    for _, signal in selected[:10]:
        input_id = _to_str(signal.get("input_id") or signal.get("id"))
        if not input_id:
            continue
        contexts.append(
            MacroSignalContext(
                input_id=input_id,
                label=_to_str(signal.get("label") or signal.get("name")),
                category=_to_str(signal.get("category") or signal.get("parent_layer")),
                signal=_to_str(signal.get("signal")),
                signal_strength=_to_float(signal.get("signal_strength")),
                level_status=_to_str(signal.get("level_status")),
                trend_status=_to_str(signal.get("trend_status") or signal.get("trend")),
                current_value=_scalar_value(signal.get("current_value")),
                notes=_to_str(signal.get("notes")),
                related_scenario_ids=_scenario_ids_from_signal(signal),
                related_theme_ids=_theme_ids_from_signal(signal),
            )
        )
    return contexts


def _extract_rankings(value: Any) -> list[MacroRankingContext]:
    rankings: list[MacroRankingContext] = []
    for item in _dict_items(value):
        item_id = _to_str(item.get("item_id") or item.get("id") or item.get("ticker"))
        if not item_id:
            continue
        rankings.append(
            MacroRankingContext(
                item_id=item_id,
                label=_to_str(item.get("label") or item.get("name")),
                score=_to_float(item.get("score") or item.get("source_score")),
                rationale=_to_str(item.get("rationale") or item.get("summary")),
            )
        )
    return rankings[:12]


def _extract_theme_catalog(macro_forecast: dict[str, Any]) -> list[ThemeCatalogItem]:
    by_id: dict[str, ThemeCatalogItem] = {}

    def add_theme(
        theme_id: Any,
        label: Any = None,
        score: Any = None,
        rationale: Any = None,
    ) -> None:
        clean_id = _to_str(theme_id)
        if not clean_id:
            return
        current = by_id.get(clean_id)
        item = ThemeCatalogItem(
            theme_id=clean_id,
            label=_to_str(label) or (current.label if current else None),
            score=_coalesce_float(_to_float(score), current.score if current else None),
            rationale=(
                current.rationale
                if current is not None and current.rationale
                else _to_str(rationale)
            ),
        )
        by_id[clean_id] = item

    for item in _dict_items(macro_forecast.get("theme_rankings")):
        add_theme(
            item.get("theme_id") or item.get("source_id") or item.get("item_id"),
            item.get("label") or item.get("source_label"),
            _first_present(
                item,
                ["theme_macro_support_score", "macro_support_score", "score", "source_score", "final_score", "macro_score"],
            ),
            item.get("rationale") or item.get("summary"),
        )

    for key in ("research_priorities", "recommended_research_priorities"):
        for item in _dict_items(macro_forecast.get(key)):
            add_theme(
                item.get("theme_id") or item.get("source_theme_id") or item.get("source_id"),
                item.get("theme") or item.get("label") or item.get("source_label"),
                item.get("score") or item.get("source_score"),
                item.get("rationale"),
            )

    for ranking_key in ("factor_rankings", "sector_rankings"):
        for item in _dict_items(macro_forecast.get(ranking_key)):
            for contribution in _dict_items(item.get("contributions")):
                add_theme(
                    contribution.get("theme_id")
                    or contribution.get("source_id")
                    or contribution.get("item_id"),
                    contribution.get("theme_label")
                    or contribution.get("source_label")
                    or contribution.get("label"),
                    contribution.get("theme_macro_support_score")
                    or contribution.get("source_score")
                    or contribution.get("score")
                    or contribution.get("contribution"),
                    contribution.get("rationale"),
                )

    for signal in _all_signals(macro_forecast):
        for theme_id in signal.get("related_theme_ids") or []:
            add_theme(theme_id)
        for key in ("theme_impacts", "affected_themes"):
            for impact in _dict_items(signal.get(key)):
                add_theme(
                    impact.get("theme_id") or impact.get("source_id"),
                    impact.get("theme_label") or impact.get("label"),
                    None,
                    impact.get("rationale"),
                )

    return sorted(by_id.values(), key=lambda item: item.theme_id)


def _build_theme_scores(
    catalog_by_id: dict[str, ThemeCatalogItem],
    mapped_themes: list,
) -> list[ThemeScoreContext]:
    scores: list[ThemeScoreContext] = []
    for mapping in mapped_themes:
        catalog_item = catalog_by_id[mapping.theme_id]
        weight = FIT_WEIGHTS[mapping.fit] * mapping.confidence
        weighted_score = (
            catalog_item.score * weight
            if catalog_item.score is not None
            else None
        )
        scores.append(
            ThemeScoreContext(
                theme_id=mapping.theme_id,
                label=catalog_item.label or mapping.theme_label,
                score=catalog_item.score,
                fit=mapping.fit,
                fit_confidence=mapping.confidence,
                weighted_score=weighted_score,
                rationale=catalog_item.rationale or mapping.rationale,
            )
        )
    return scores


def _aggregate_theme_support_score(scores: list[ThemeScoreContext]) -> float | None:
    numerator = 0.0
    denominator = 0.0
    for score in scores:
        if score.score is None or score.fit is None or score.fit_confidence is None:
            continue
        weight = FIT_WEIGHTS[score.fit] * score.fit_confidence
        numerator += score.score * weight
        denominator += weight
    if denominator == 0:
        return None
    return numerator / denominator


def _extract_theme_impacts(
    macro_forecast: dict[str, Any],
    selected_theme_ids: list[str],
    catalog_by_id: dict[str, ThemeCatalogItem],
) -> tuple[list[ThemeImpactContext], list[str], list[str], list[str], list[str]]:
    selected = set(selected_theme_ids)
    impacts: list[ThemeImpactContext] = []
    linked_scenarios: list[str] = []
    positive: list[str] = []
    negative: list[str] = []
    mixed: list[str] = []

    if not selected:
        return impacts, linked_scenarios, positive, negative, mixed

    for signal in _all_signals(macro_forecast):
        parent_scenarios = _scenario_ids_from_signal(signal)
        for key in ("theme_impacts", "affected_themes"):
            for impact in _dict_items(signal.get(key)):
                theme_id = _to_str(impact.get("theme_id") or impact.get("source_id"))
                if theme_id not in selected:
                    continue

                direction = _impact_direction(impact.get("direction") or impact.get("impact"))
                rationale = _to_str(impact.get("rationale"))
                source_label = _to_str(signal.get("label") or signal.get("name"))
                theme_label = (
                    catalog_by_id.get(theme_id).label
                    if catalog_by_id.get(theme_id)
                    else None
                )
                impacts.append(
                    ThemeImpactContext(
                        theme_id=theme_id,
                        theme_label=theme_label,
                        direction=direction,
                        strength=_to_float(impact.get("strength")),
                        rationale=rationale,
                        source_input_id=_to_str(signal.get("input_id") or signal.get("id")),
                        source_label=source_label,
                        category=_to_str(signal.get("category") or signal.get("parent_layer")),
                    )
                )

                linked_scenarios.extend(parent_scenarios)
                driver = _driver_text(source_label, rationale)
                if direction == MacroImpactDirection.POSITIVE:
                    positive.append(driver)
                elif direction == MacroImpactDirection.NEGATIVE:
                    negative.append(driver)
                elif direction == MacroImpactDirection.MIXED:
                    mixed.append(driver)

    return _dedupe_impacts(impacts), linked_scenarios, positive, negative, mixed


def _dedupe_impacts(impacts: list[ThemeImpactContext]) -> list[ThemeImpactContext]:
    seen: set[tuple[str, str | None, str, str | None]] = set()
    deduped: list[ThemeImpactContext] = []
    for impact in impacts:
        key = (
            impact.theme_id,
            impact.source_input_id,
            impact.direction.value,
            impact.rationale,
        )
        if key not in seen:
            deduped.append(impact)
            seen.add(key)
    return deduped


def _all_signals(macro_forecast: dict[str, Any]) -> list[dict[str, Any]]:
    forecast_input_set = _as_dict(macro_forecast.get("forecast_input_set"))
    signals = forecast_input_set.get("all_signals") or macro_forecast.get("input_signals")
    return _dict_items(signals)


def _scenario_ids_from_signal(signal: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for value in signal.get("related_scenario_ids") or []:
        clean = _to_str(value)
        if clean:
            ids.append(clean)
    for key in ("scenario_impacts", "affected_scenarios"):
        for item in _dict_items(signal.get(key)):
            clean = _to_str(item.get("scenario_id") or item.get("source_id"))
            if clean:
                ids.append(clean)
    return _dedupe(ids)


def _theme_ids_from_signal(signal: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for value in signal.get("related_theme_ids") or []:
        clean = _to_str(value)
        if clean:
            ids.append(clean)
    for key in ("theme_impacts", "affected_themes"):
        for item in _dict_items(signal.get(key)):
            clean = _to_str(item.get("theme_id") or item.get("source_id"))
            if clean:
                ids.append(clean)
    return _dedupe(ids)


def _impact_direction(value: Any) -> MacroImpactDirection:
    normalized = str(value or "").lower()
    if normalized == "positive":
        return MacroImpactDirection.POSITIVE
    if normalized == "negative":
        return MacroImpactDirection.NEGATIVE
    if normalized == "neutral":
        return MacroImpactDirection.NEUTRAL
    if normalized == "mixed":
        return MacroImpactDirection.MIXED
    return MacroImpactDirection.UNKNOWN


def _driver_text(source_label: str | None, rationale: str | None) -> str:
    if source_label and rationale:
        return f"{source_label}: {rationale}"
    return source_label or rationale or "Theme impact driver unavailable."


def _dict_items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [item for item in value.values() if isinstance(item, dict)]
    return []


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _first_present(item: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        value = item.get(key)
        if value is not None:
            return value
    return None


def _parse_date(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    text = str(value)
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed


def _coalesce_float(*values: float | None) -> float | None:
    for value in values:
        if value is not None:
            return value
    return None


def _to_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _scalar_value(value: Any) -> str | float | int | bool | None:
    if isinstance(value, (str, float, int, bool)) or value is None:
        return value
    return str(value)


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value and value not in seen:
            deduped.append(value)
            seen.add(value)
    return deduped
