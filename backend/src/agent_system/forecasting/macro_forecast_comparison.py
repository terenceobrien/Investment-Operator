"""Shadow-mode comparison between narrative macro and BVAR ensemble forecasts."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from src.agent_system.forecasting.behavioral_scenarios_loader import (
    load_behavioral_scenarios,
    scenario_metadata,
)
from src.agent_system.forecasting.macro_forecast_shadow import (
    ShadowForecastResult,
    shadow_forecast_dir,
)
from src.agent_system.schemas.macro_forecast import MacroForecastResult
from src.agent_system.services.scenario_translation import (
    BEHAVIORAL_SCENARIO_IDS,
    translate_narrative_to_behavioral,
)


class ForecastComparisonError(RuntimeError):
    """Raised when a shadow comparison artifact cannot be produced."""


def build_forecast_comparison(
    narrative_forecast: Any,
    shadow_result: ShadowForecastResult | dict[str, Any],
    cycle_id: str,
    cycle_date: str,
) -> None:
    """Write JSON and markdown comparison artifacts in behavioral scenario space."""

    narrative_payload = _coerce_payload(narrative_forecast)
    shadow_payload = (
        shadow_result.model_dump(mode="json")
        if isinstance(shadow_result, BaseModel)
        else dict(shadow_result)
    )
    narrative_probs = _narrative_probabilities(narrative_payload)
    narrative_behavioral = translate_narrative_to_behavioral(narrative_probs)
    ensemble_probs = {
        str(key): float(value)
        for key, value in (shadow_payload.get("scenario_probabilities") or {}).items()
    }
    scenarios = load_behavioral_scenarios()
    metadata = scenario_metadata(scenarios)

    rows: list[dict[str, Any]] = []
    for scenario_id in BEHAVIORAL_SCENARIO_IDS:
        narrative_value = float(narrative_behavioral.get(scenario_id, 0.0))
        ensemble_value = float(ensemble_probs.get(scenario_id, 0.0))
        rows.append(
            {
                "behavioral_scenario_id": scenario_id,
                "label": metadata.get(scenario_id, {}).get("label", scenario_id),
                "narrative_derived_probability": narrative_value,
                "ensemble_probability": ensemble_value,
                "delta_ensemble_minus_narrative": ensemble_value - narrative_value,
            }
        )

    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = shadow_forecast_dir()
    json_path = output_dir / f"comparison_{cycle_date}_{timestamp}.json"
    md_path = output_dir / f"comparison_{cycle_date}_{timestamp}.md"
    payload = {
        "mode": "SHADOW_MODE",
        "consumed_by_live_pipeline": False,
        "cycle_id": cycle_id,
        "cycle_date": cycle_date,
        "generated_at": generated_at,
        "statement": (
            "The BVAR ensemble is in SHADOW MODE. It is consumed by nothing and is "
            "included for evaluation only."
        ),
        "taxonomy": "behavioral",
        "narrative_source": {
            "asof_date": narrative_payload.get("asof_date"),
            "horizon": narrative_payload.get("horizon"),
            "probability_mode": narrative_payload.get("probability_mode"),
            "raw_probabilities": narrative_probs,
            "translated_probabilities": narrative_behavioral,
        },
        "ensemble_source": {
            "asof_quarter": shadow_payload.get("asof_quarter"),
            "generated_at": shadow_payload.get("generated_at"),
            "artifact_path": shadow_payload.get("artifact_path"),
            "scenario_probabilities": ensemble_probs,
        },
        "regime_stress_context": {
            "narrative": "N/A",
            "ensemble": shadow_payload.get("regime_stress_gauge") or {},
        },
        "margin_context": {
            "narrative": "N/A",
            "ensemble": shadow_payload.get("margin_stats") or {},
        },
        "model_limitations": shadow_payload.get("model_limitations") or {},
        "comparison_table": rows,
    }
    json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(_markdown_summary(payload), encoding="utf-8")


def _coerce_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, (str, Path)):
        path = Path(value)
        if not path.is_file():
            raise ForecastComparisonError(f"narrative forecast JSON not found: {path}")
        return json.loads(path.read_text(encoding="utf-8"))
    if isinstance(value, MacroForecastResult):
        return value.model_dump(mode="json")
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return dict(value)
    raise ForecastComparisonError(
        f"unsupported narrative forecast type for comparison: {type(value).__name__}"
    )


def _narrative_probabilities(payload: dict[str, Any]) -> dict[str, float]:
    calibration = payload.get("historical_calibration")
    candidates = [
        payload.get("scenario_probabilities_blended"),
        (
            calibration.get("blended_scenario_probabilities")
            if isinstance(calibration, dict)
            else None
        ),
        payload.get("scenario_probabilities"),
    ]
    for candidate in candidates:
        if isinstance(candidate, dict) and candidate:
            return {str(key): float(value) for key, value in candidate.items()}
    raise ForecastComparisonError("narrative forecast has no scenario probabilities")


def _markdown_summary(payload: dict[str, Any]) -> str:
    stress = payload.get("regime_stress_context", {}).get("ensemble") or {}
    margin = payload.get("margin_context", {}).get("ensemble") or {}
    lines = [
        "# Macro Forecast Shadow Comparison",
        "",
        "**SHADOW MODE: the BVAR ensemble is consumed by nothing and is for evaluation only.**",
        "",
        f"- Cycle: `{payload.get('cycle_id')}`",
        f"- Cycle date: `{payload.get('cycle_date')}`",
        f"- Generated: `{payload.get('generated_at')}`",
        f"- Narrative as-of: `{payload.get('narrative_source', {}).get('asof_date')}`",
        f"- Ensemble as-of quarter: `{payload.get('ensemble_source', {}).get('asof_quarter')}`",
        "",
        "## Behavioral Scenario Probabilities",
        "",
        "| Behavioral scenario | Narrative-derived | Ensemble | Delta |",
        "|---|---:|---:|---:|",
    ]
    for row in payload.get("comparison_table", []):
        lines.append(
            "| {label} | {narrative:.1%} | {ensemble:.1%} | {delta:+.1%} |".format(
                label=row["label"],
                narrative=float(row["narrative_derived_probability"]),
                ensemble=float(row["ensemble_probability"]),
                delta=float(row["delta_ensemble_minus_narrative"]),
            )
        )
    lines.extend(
        [
            "",
            "## Ensemble Context",
            "",
            f"- Anchor p_enter: {_fmt_pct(stress.get('anchor_p_enter'))}",
            f"- Fraction entering stress: {_fmt_pct(stress.get('fraction_entered_stress'))}",
            f"- Share low margin: {_fmt_pct(margin.get('share_low_margin'))}",
            "- Narrative analogue for regime stress gauge: N/A",
            "",
            "## Model Limitations",
            "",
        ]
    )
    limitations = payload.get("model_limitations") or {}
    if limitations:
        lines.append(f"- Credit tail magnitude: `{limitations.get('credit_tail_magnitude', 'n/a')}`")
        if limitations.get("detail"):
            lines.append(f"- {limitations['detail']}")
    else:
        lines.append("- None supplied.")
    lines.append("")
    return "\n".join(lines)


def _fmt_pct(value: Any) -> str:
    if value is None:
        return "N/A"
    try:
        return f"{float(value):.1%}"
    except (TypeError, ValueError):
        return "N/A"
