"""Guardrails against cwd-relative backend data paths."""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterable

import pytest


REPO_ROOT = Path(__file__).resolve().parents[4]
SCAN_ROOTS = (
    REPO_ROOT / "backend" / "src",
    REPO_ROOT / "backend" / "api",
    REPO_ROOT / "backend" / "scripts",
)
EXCLUDED_FILES = {
    REPO_ROOT / "backend" / "src" / "agent_system" / "paths.py",
    REPO_ROOT / "scripts" / "migrate_macro_forecast_layout.py",
    REPO_ROOT / "scripts" / "migrate_root_data_to_backend.py",
}
ALLOWLIST: set[tuple[str, int]] = set()


def _is_bad_data_literal(value: object) -> bool:
    if not isinstance(value, str):
        return False
    stripped = value.strip()
    return stripped == "data" or stripped.startswith("data/") or stripped.startswith("/data")


def _call_name(func: ast.AST) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return f"{_call_name(func.value)}.{func.attr}"
    return ""


def _target_name(target: ast.AST) -> str:
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return ""


def _path_literal_violations(path: Path) -> Iterable[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _call_name(node.func)
            path_constructor = name in {"Path", "open", "os.path.join", "join"}
            argparse_default = name.endswith("add_argument")
            if path_constructor:
                args = list(node.args)
                if name == "os.path.join":
                    args = args[:1]
                for arg in args:
                    if isinstance(arg, ast.Constant) and _is_bad_data_literal(arg.value):
                        yield node.lineno, f"{name}({arg.value!r})"
            if path_constructor or argparse_default:
                for kw in node.keywords:
                    if isinstance(kw.value, ast.Constant) and _is_bad_data_literal(kw.value.value):
                        yield node.lineno, f"{name} {kw.arg}={kw.value.value!r}"

        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = getattr(node, "value", None)
            if not isinstance(value, ast.Constant) or not _is_bad_data_literal(value.value):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            target_text = " ".join(_target_name(target).upper() for target in targets)
            if any(token in target_text for token in ("PATH", "DIR", "ROOT", "FILE")):
                yield node.lineno, f"{target_text}={value.value!r}"


def test_no_cwd_relative_data_path_construction() -> None:
    violations: list[str] = []
    for root in SCAN_ROOTS:
        for path in sorted(root.rglob("*.py")):
            resolved = path.resolve()
            if resolved in EXCLUDED_FILES:
                continue
            for line, expression in _path_literal_violations(path):
                key = (str(path.relative_to(REPO_ROOT)), line)
                if key in ALLOWLIST:
                    continue
                violations.append(f"{path.relative_to(REPO_ROOT)}:{line}: {expression}")

    assert not violations, "cwd-relative backend data path construction found:\n" + "\n".join(violations)


def test_accessors_and_writer_are_cwd_independent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    helix_root = tmp_path / "helix-data"
    unrelated_cwd = tmp_path / "unrelated-cwd"
    unrelated_cwd.mkdir()
    monkeypatch.chdir(unrelated_cwd)
    monkeypatch.setenv("HELIX_DATA_ROOT", str(helix_root))
    monkeypatch.delenv("AGENT_SYSTEM_DATA_DIR", raising=False)

    from src.agent_system.paths import (
        classifier_cache_dir,
        macro_json_dir,
        macro_regime_dir,
    )

    assert macro_json_dir(create=True) == helix_root / "agent_system" / "reports" / "macro_forecasts" / "JSON"
    assert macro_regime_dir(create=True) == helix_root / "agent_system" / "reports" / "macro_forecasts" / "Regime"
    assert classifier_cache_dir(create=True) == helix_root / "agent_system" / "classifier_cache"

    from src.agent_system.forecasting.current_regime_export import save_current_regime_yaml

    monkeypatch.setenv("HELIX_DATA_ROOT", str(helix_root))
    monkeypatch.delenv("AGENT_SYSTEM_DATA_DIR", raising=False)

    class DummyHandoff:
        def model_dump(self, *, mode: str) -> dict[str, object]:
            assert mode == "json"
            return {"scenario_taxonomy": "behavioral_v1", "asof_date": "2026-08-06"}

    path = save_current_regime_yaml(
        DummyHandoff(),
        output_dir=None,
        asof_date="2026-08-06",
        overwrite=True,
    )
    assert path == helix_root / "agent_system" / "reports" / "macro_forecasts" / "Regime" / "current_regime_2026-08-06.yaml"
    assert path.is_file()
