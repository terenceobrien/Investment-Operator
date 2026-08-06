from __future__ import annotations

import importlib
import logging
import warnings

import pandas as pd
import pytest


def test_instrumented_modules_are_import_time_silent():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        importlib.import_module("src.analysis.analogues")
        importlib.import_module("src.analysis.rolling_composite")
        importlib.import_module("src.agent_system.forecasting.current_regime_export")

    assert not [
        item for item in caught if issubclass(item.category, DeprecationWarning)
    ]


def test_analogue_entry_point_warns_once_and_logs_caller(caplog):
    from src.analysis import analogues

    analogues._NARRATIVE_FOSSIL_EMITTED = False
    caplog.set_level(logging.WARNING, logger="narrative_fossil")

    with pytest.warns(DeprecationWarning):
        analogues.shock_window_diagnostics_for_analogues([])

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        analogues.shock_window_diagnostics_for_analogues([])

    assert not [
        item for item in caught if issubclass(item.category, DeprecationWarning)
    ]
    records = [
        record
        for record in caplog.records
        if record.name == "narrative_fossil"
        and record.getMessage() == "legacy_narrative_analogue_invoked"
    ]
    assert len(records) == 1
    assert getattr(records[0], "caller_module")
    assert records[0].entry_point == "shock_window_diagnostics_for_analogues"


def test_rolling_entry_point_warns_once_and_logs_caller(monkeypatch, caplog):
    from src.analysis import rolling_composite

    rolling_composite._NARRATIVE_FOSSIL_EMITTED = False
    monkeypatch.setattr(rolling_composite, "_load_df", lambda: pd.DataFrame())
    caplog.set_level(logging.WARNING, logger="narrative_fossil")

    with pytest.warns(DeprecationWarning):
        with pytest.raises(ValueError, match="empty"):
            rolling_composite.get_rolling_composite()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with pytest.raises(ValueError, match="empty"):
            rolling_composite.get_rolling_composite()

    assert not [
        item for item in caught if issubclass(item.category, DeprecationWarning)
    ]
    records = [
        record
        for record in caplog.records
        if record.name == "narrative_fossil"
        and record.getMessage() == "legacy_narrative_rolling_composite_invoked"
    ]
    assert len(records) == 1
    assert getattr(records[0], "caller_module")
    assert records[0].entry_point == "get_rolling_composite"


def test_legacy_current_regime_handoff_warns_once_and_logs_caller(caplog):
    from src.agent_system.forecasting import current_regime_export

    current_regime_export._NARRATIVE_FOSSIL_EMITTED = False
    caplog.set_level(logging.WARNING, logger="narrative_fossil")

    with pytest.warns(DeprecationWarning):
        with pytest.raises(current_regime_export.CurrentRegimeExportError):
            current_regime_export.build_current_regime_handoff(None)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with pytest.raises(current_regime_export.CurrentRegimeExportError):
            current_regime_export.build_current_regime_handoff(None)

    assert not [
        item for item in caught if issubclass(item.category, DeprecationWarning)
    ]
    records = [
        record
        for record in caplog.records
        if record.name == "narrative_fossil"
        and record.getMessage() == "legacy_narrative_current_regime_handoff_invoked"
    ]
    assert len(records) == 1
    assert getattr(records[0], "caller_module")
    assert records[0].entry_point == "build_current_regime_handoff"


def test_scenario_translation_logs_without_deprecation_warning(caplog):
    from src.agent_system.services import scenario_translation

    scenario_translation._NARRATIVE_TRANSLATION_LOGGED = False
    caplog.set_level(logging.WARNING, logger="narrative_fossil")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        translated = scenario_translation.translate_narrative_to_behavioral(
            {"reopening_soft_landing": 1.0}
        )

    assert translated["expansion_disinflation"] == pytest.approx(1.0)
    assert not [
        item for item in caught if issubclass(item.category, DeprecationWarning)
    ]
    records = [
        record
        for record in caplog.records
        if record.name == "narrative_fossil"
        and record.getMessage() == "narrative_translation_boundary_invoked"
    ]
    assert len(records) == 1
    assert getattr(records[0], "caller_module")
    assert records[0].entry_point == "translate_narrative_to_behavioral"
