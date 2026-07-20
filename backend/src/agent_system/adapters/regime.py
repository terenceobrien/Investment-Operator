"""
Adapter from Helix's dataclass regime snapshot to agent-system RegimeState.
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

import yaml
from pydantic import ValidationError

from src.agent_system.schemas.common import (
    DerivedEvidence,
    Falsifier,
    FalsifierFrequency,
    FalsifierObservable,
)
from src.agent_system.schemas.forward import ForwardContext
from src.agent_system.schemas.regime import (
    EdgeDecayHorizon,
    LayerWeights,
    RegimeDriver,
    RegimeHorizon,
    RegimeLayers,
    RegimeLayerScore,
    RegimeLayerStatus,
    RegimeState as PydanticRegimeState,
    ResearchPriority,
)

if TYPE_CHECKING:
    from src.state.regime_state import RegimeState as DataclassRegimeState


logger = logging.getLogger(__name__)

_LAYER_NAMES = ("monetary", "credit", "volatility", "breadth", "positioning")
_REQUIRED_CURATION_FIELDS = (
    "regime_id",
    "regime_label",
    "regime_call_confidence",
)


class RegimeAdapterError(Exception):
    """Raised when the adapter cannot produce a valid Pydantic
    RegimeState from a dataclass + YAML combination. Caller should
    handle by falling back to the stub regime state."""


def adapt_regime_state(
    dataclass_state: "DataclassRegimeState",
    *,
    forward_context: Optional[ForwardContext] = None,
    curation_config_path: Optional[Path] = None,
) -> PydanticRegimeState:
    """
    Translate a dataclass RegimeState (from src/state/regime_state.py)
    into the Pydantic RegimeState consumed by the agent system.

    Merges three sources:
    1. Algorithmic layer scores from the dataclass (monetary, credit,
       volatility, breadth, positioning + composite + agreement +
       confidence + environment + environment_drivers)
    2. Curated qualitative fields from current_regime.yaml (regime_id,
       label, headline, summary, drivers, etc.)
    3. Forward-looking context if provided (attaches as-is)

    Args:
        dataclass_state: The output of build_regime_state() from
            src/state/regime_state.py
        forward_context: Optional ForwardContext to attach. Built
            separately by ForwardContextBuilder; the caller decides
            whether to invoke it.
        curation_config_path: Override path to current_regime.yaml.
            Defaults to src/agent_system/config/current_regime.yaml.

    Returns:
        Fully-populated Pydantic RegimeState ready for agent consumption.

    Raises:
        RegimeAdapterError: If required curation fields are missing,
            YAML is malformed, or dataclass layer scores can't be
            translated to the Pydantic schema.
    """
    try:
        curation = _load_curation_config(curation_config_path)
        layers = _build_layers(dataclass_state)
        weights = LayerWeights(**_resolve_weights(dataclass_state))
        research_priorities = _build_seed_research_priorities(
            curation.get("seed_research_priorities", [])
        )
        falsifiers = _build_falsifiers(curation.get("falsifiers", []))
        scenario_probabilities = _build_scenario_probabilities(
            curation.get("scenario_probabilities")
        )

        return PydanticRegimeState(
            asof_date=_extract_asof_date(dataclass_state),
            horizon=RegimeHorizon.DEFAULT,
            layers=layers,
            weights=weights,
            composite=_require_number(
                getattr(dataclass_state, "score_total", None),
                "score_total",
            ),
            layer_agreement=_require_number(
                getattr(dataclass_state, "layer_agreement", None),
                "layer_agreement",
            ),
            composite_confidence=_require_number(
                getattr(dataclass_state, "confidence", None),
                "confidence",
            ),
            environment=getattr(dataclass_state, "environment", "") or "Unknown",
            environment_drivers=list(
                getattr(dataclass_state, "environment_drivers", []) or []
            ),
            regime_id=curation["regime_id"],
            regime_label=curation["regime_label"],
            headline=curation.get("headline", "") or "",
            summary=curation.get("summary", "") or "",
            risk_summary=curation.get("risk_summary", "") or "",
            scenario_probabilities=scenario_probabilities,
            scenario_probability_source=(
                "current_regime_yaml" if scenario_probabilities else None
            ),
            key_drivers=[
                RegimeDriver(**driver)
                for driver in curation.get("key_drivers", [])
                if isinstance(driver, dict)
            ],
            portfolio_implications=list(curation.get("portfolio_implications", []) or []),
            best_positioned=list(curation.get("best_positioned", []) or []),
            most_vulnerable=list(curation.get("most_vulnerable", []) or []),
            regime_call_confidence=curation["regime_call_confidence"],
            falsifiers=falsifiers,
            research_priorities=research_priorities,
            forward_context=forward_context,
        )
    except RegimeAdapterError:
        raise
    except (TypeError, ValueError, ValidationError) as exc:
        raise RegimeAdapterError(f"failed to adapt regime state: {exc}") from exc


def _load_curation_config(path: Optional[Path]) -> dict[str, Any]:
    config_path = (
        Path(path)
        if path is not None
        else Path(__file__).resolve().parents[1] / "config" / "current_regime.yaml"
    )
    try:
        with config_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception as exc:
        raise RegimeAdapterError(
            f"unable to load current regime curation config {config_path}: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise RegimeAdapterError("current_regime.yaml must contain a mapping")

    missing = [field for field in _REQUIRED_CURATION_FIELDS if field not in data]
    if missing:
        raise RegimeAdapterError(
            f"current_regime.yaml missing required fields: {', '.join(missing)}"
        )
    return data


def _build_scenario_probabilities(value: Any) -> dict[str, float]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise RegimeAdapterError("scenario_probabilities must be a mapping")
    probabilities: dict[str, float] = {}
    for scenario_id, probability in value.items():
        try:
            probabilities[str(scenario_id)] = float(probability)
        except (TypeError, ValueError) as exc:
            raise RegimeAdapterError(
                f"scenario_probabilities contains non-numeric value for {scenario_id!r}"
            ) from exc
    return probabilities


def _build_layers(dataclass_state: "DataclassRegimeState") -> RegimeLayers:
    layer_values = {
        layer_name: _build_layer_score(dataclass_state, layer_name)
        for layer_name in _LAYER_NAMES
    }
    return RegimeLayers(**layer_values)


def _build_layer_score(
    dataclass_state: "DataclassRegimeState",
    layer_name: str,
) -> RegimeLayerScore:
    raw_score = getattr(dataclass_state, f"layer_{layer_name}", None)
    score = 5.0 if raw_score is None else float(raw_score)
    signals = (getattr(dataclass_state, "layer_signals", {}) or {}).get(layer_name, [])
    return RegimeLayerScore(
        score=score,
        inputs={},
        signals=list(signals),
        status=_status_from_score(raw_score),
        data_quality=1.0 if raw_score is not None else 0.0,
    )


def _status_from_score(score: Optional[float]) -> RegimeLayerStatus:
    if score is None:
        return RegimeLayerStatus.NEUTRAL
    if score >= 6.5:
        return RegimeLayerStatus.BULLISH
    if score <= 3.5:
        return RegimeLayerStatus.BEARISH
    return RegimeLayerStatus.NEUTRAL


def _build_seed_research_priorities(items: Any) -> list[ResearchPriority]:
    if items is None:
        return []
    if not isinstance(items, list):
        raise RegimeAdapterError("seed_research_priorities must be a list")

    priorities: list[ResearchPriority] = []
    for item in items:
        if not isinstance(item, dict):
            raise RegimeAdapterError("seed_research_priorities entries must be mappings")
        payload = dict(item)
        if "expected_edge_decay" in payload:
            payload["expected_edge_decay"] = EdgeDecayHorizon(
                payload["expected_edge_decay"]
            )
        if not payload.get("supporting_evidence"):
            theme = str(payload.get("theme", "unknown seed priority"))
            payload["supporting_evidence"] = [
                DerivedEvidence(
                    claim=f"Seed research priority from current_regime.yaml: {theme}",
                    supports=True,
                    computation="manually curated regime overlay",
                    upstream_claims=["current_regime.yaml seed_research_priorities"],
                )
            ]
        priorities.append(ResearchPriority(**payload))
    return priorities


def _build_falsifiers(items: Any) -> list[Falsifier]:
    if items is None:
        return []
    if not isinstance(items, list):
        raise RegimeAdapterError("falsifiers must be a list")

    falsifiers: list[Falsifier] = []
    for item in items:
        if not isinstance(item, dict):
            logger.warning("Skipping malformed falsifier entry: %r", item)
            continue
        try:
            falsifiers.append(
                Falsifier(
                    condition=item["condition"],
                    observable_in=FalsifierObservable(item["observable_in"]),
                    check_frequency=FalsifierFrequency(item["check_frequency"]),
                )
            )
        except Exception as exc:
            logger.warning("Skipping malformed falsifier entry %r: %s", item, exc)
    return falsifiers


def _extract_asof_date(dataclass_state: "DataclassRegimeState") -> str:
    asof_date = getattr(dataclass_state, "asof_date", "") or ""
    if len(asof_date) == 10 and asof_date[4] == "-" and asof_date[7] == "-":
        return asof_date

    asof_utc = getattr(dataclass_state, "asof_utc", "") or ""
    if asof_utc:
        try:
            return datetime.fromisoformat(asof_utc).strftime("%Y-%m-%d")
        except ValueError as exc:
            raise RegimeAdapterError(
                f"could not derive asof_date from asof_utc={asof_utc!r}"
            ) from exc

    raise RegimeAdapterError("dataclass_state must include asof_date or asof_utc")


def _require_mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RegimeAdapterError(f"dataclass_state.{field_name} must be a mapping")
    return value


def _resolve_weights(dataclass_state: "DataclassRegimeState") -> dict[str, Any]:
    weights = getattr(dataclass_state, "weights", None)
    if isinstance(weights, dict):
        return weights

    # Current src.state.regime_state.RegimeState stores horizon but not the
    # weight dict. Rehydrate from regime_layers.WEIGHTS so existing snapshots
    # can still be adapted without changing the dataclass.
    horizon = getattr(dataclass_state, "horizon", "default") or "default"
    try:
        from src.state.regime_layers import WEIGHTS
    except Exception as exc:
        raise RegimeAdapterError(
            "dataclass_state.weights missing and regime_layers.WEIGHTS unavailable"
        ) from exc
    return dict(WEIGHTS.get(horizon, WEIGHTS["default"]))


def _require_number(value: Any, field_name: str) -> float:
    if value is None:
        raise RegimeAdapterError(f"dataclass_state.{field_name} is required")
    return float(value)
