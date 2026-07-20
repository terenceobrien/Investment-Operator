from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from src.agent_system.forecasting.scenario_classifier.classifier import (
    ClassifierError,
    ScenarioClassifier,
)
from src.agent_system.forecasting.scenario_classifier.registry import VariableRegistry
from src.agent_system.forecasting.scenario_classifier.scaling import ScaleSet
from src.agent_system.forecasting.scenario_classifier.signatures import (
    MISSING_RBBBP_WARNING,
    ScenarioSignatures,
    load_signatures_from_handoff,
)


def test_state_vector_registry_loads_and_validates_signature_roles():
    registry = VariableRegistry.load()

    assert registry.get("credit_spread").signature_map == "rbbbp_pct"
    assert registry.get("activity").fred_series == "GDPC1"
    assert "credit_spread" in registry.signature_variable_names()


def test_handoff_missing_rbbbp_drops_credit_spread_with_warning():
    registry = VariableRegistry.load()
    handoff = Path(
        "backend/src/agent_system/forecasting/output/"
        "frbus_scenario_paths_2026Q3_20260713T172023Z.json"
    )

    if not handoff.is_file():
        pytest.skip("FRB/US handoff fixture not present")

    signatures = load_signatures_from_handoff(
        registry,
        handoff_path=handoff,
        horizon_quarters=4,
    )

    assert signatures.missing_credit_spread is True
    assert "credit_spread" not in signatures.active_variables
    assert MISSING_RBBBP_WARNING in signatures.warnings
    assert signatures.matrix.shape == (6, 4, len(signatures.active_variables))


def test_classifier_assigns_nearest_signature_deterministically(tmp_path):
    registry = VariableRegistry.load()
    signatures = ScenarioSignatures(
        scenario_ids=["a", "b"],
        active_variables=["activity", "lur"],
        signature_maps={"activity": "xgdp_growth_4q_pct", "lur": "lur_pct"},
        matrix=np.asarray(
            [
                [[0.0, 0.0], [0.0, 0.0]],
                [[2.0, 2.0], [2.0, 2.0]],
            ],
            dtype=float,
        ),
        handoff_path=tmp_path / "handoff.json",
        baseline_data_fingerprint="abc123",
        map_version="test",
        generated_at="2026-01-01T00:00:00Z",
        horizon_quarters=2,
    )
    scales = ScaleSet(
        horizon_quarters=2,
        variables={
            "activity": {"std": 1.0, "mad": 1.0},
            "lur": {"std": 1.0, "mad": 1.0},
        },
        path=tmp_path / "scales.json",
    )
    classifier = ScenarioClassifier(
        registry,
        signatures,
        scales,
        {"kernel_sigma": 1.0},
    )

    result = classifier.classify(
        np.asarray([[[1.8, 2.1], [2.0, 1.9]]], dtype=float),
        path_ids=["path-1"],
    )

    assert result.loc[0, "assigned"] == "b"
    assert result.loc[0, "margin"] > 0
    assert result.metadata["baseline_data_fingerprint"] == "abc123"


def test_classifier_rejects_include_and_exclude_together(tmp_path):
    registry = VariableRegistry.load()
    signatures = ScenarioSignatures(
        scenario_ids=["a"],
        active_variables=["activity"],
        signature_maps={"activity": "xgdp_growth_4q_pct"},
        matrix=np.zeros((1, 2, 1)),
        handoff_path=tmp_path / "handoff.json",
        baseline_data_fingerprint=None,
        map_version=None,
        generated_at=None,
        horizon_quarters=2,
    )
    scales = ScaleSet(
        horizon_quarters=2,
        variables={"activity": {"std": 1.0, "mad": 1.0}},
        path=tmp_path / "scales.json",
    )

    with pytest.raises(ClassifierError, match="mutually exclusive"):
        ScenarioClassifier(
            registry,
            signatures,
            scales,
            {"kernel_sigma": 1.0},
            include_only=["activity"],
            exclude=["activity"],
        )
