from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from src.agent_system.paths import (
    analogue_fans_dir,
    data_root,
    macro_forecast_dir,
    macro_json_dir,
    macro_regime_dir,
    macro_reports_dir,
)


def test_macro_path_accessors_honor_helix_data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("HELIX_DATA_ROOT", str(tmp_path))

    assert data_root() == tmp_path
    assert macro_forecast_dir() == tmp_path / "agent_system" / "reports" / "macro_forecasts"
    assert macro_reports_dir() == macro_forecast_dir() / "Reports"
    assert macro_json_dir() == macro_forecast_dir() / "JSON"
    assert macro_regime_dir() == macro_forecast_dir() / "Regime"
    assert analogue_fans_dir() == macro_forecast_dir() / "analogue_fans"


def test_default_runner_output_helpers_use_layout_subfolders(tmp_path, monkeypatch):
    monkeypatch.setenv("HELIX_DATA_ROOT", str(tmp_path))

    from src.agent_system.forecasting import macro_forecast_runner as runner

    result = SimpleNamespace(
        asof_date="2026-08-04",
        created_at=datetime(2026, 8, 5, 15, 2, 7, tzinfo=timezone.utc),
    )

    assert runner._default_docx_output_path(result, None).parent == macro_reports_dir(create=True)
    assert runner._default_json_output_path(result, None).parent == macro_json_dir(create=True)
    assert runner._default_current_regime_output_dir(reports_dir=None) == macro_regime_dir(create=True)
    assert runner._default_fan_output_dir(None) == analogue_fans_dir(create=True)


def test_macro_forecast_layout_migration_is_idempotent(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HELIX_DATA_ROOT", str(tmp_path))
    root = macro_forecast_dir(create=True)
    (root / "macro_forecast_fixture.json").write_text(json.dumps({"created_at": "2026-08-05T00:00:00Z"}), encoding="utf-8")
    (root / "macro_forecast_fixture.docx").write_bytes(b"docx")
    (root / "current_regime_fixture.yaml").write_text("scenario_taxonomy: behavioral_v1\n", encoding="utf-8")

    import scripts.migrate_macro_forecast_layout as migration

    assert migration.migrate(dry_run=False) == 0
    first_output = capsys.readouterr().out
    assert "MOVED:" in first_output
    assert (macro_json_dir() / "macro_forecast_fixture.json").is_file()
    assert (macro_reports_dir() / "macro_forecast_fixture.docx").is_file()
    assert (macro_regime_dir() / "current_regime_fixture.yaml").is_file()

    assert migration.migrate(dry_run=False) == 0
    second_output = capsys.readouterr().out
    assert "No eligible flat-layout macro forecast artifacts found" in second_output
