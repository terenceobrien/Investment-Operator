"""Migrate macro forecast artifacts into the Reports/JSON/Regime layout."""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from src.agent_system.paths import (
    macro_forecast_dir,
    macro_json_dir,
    macro_regime_dir,
    macro_reports_dir,
)


def target_for_macro_forecast_artifact(path: Path) -> Path | None:
    if not path.is_file():
        return None
    if path.suffix.lower() == ".docx":
        return macro_reports_dir(create=False) / path.name
    if path.suffix.lower() == ".json" and path.name.startswith("macro_forecast"):
        return macro_json_dir(create=False) / path.name
    if path.suffix.lower() in {".yaml", ".yml"} and path.name.startswith("current_regime"):
        return macro_regime_dir(create=False) / path.name
    return None


def _target_for(path: Path) -> Path | None:
    return target_for_macro_forecast_artifact(path)


def migrate(*, dry_run: bool) -> int:
    root = macro_forecast_dir(create=False)
    if not root.exists():
        print(f"Macro forecast root does not exist; nothing to migrate: {root}")
        return 0

    moves = 0
    for child in sorted(root.iterdir(), key=lambda item: item.name):
        target = _target_for(child)
        if target is None:
            continue
        if child.resolve() == target.resolve():
            print(f"SKIP already migrated: {child}")
            continue
        if target.exists():
            print(f"SKIP target exists: {child} -> {target}")
            continue
        moves += 1
        if dry_run:
            print(f"DRY-RUN move: {child} -> {target}")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(child), str(target))
        print(f"MOVED: {child} -> {target}")

    if moves == 0:
        print(f"No eligible flat-layout macro forecast artifacts found under: {root}")
    elif dry_run:
        print(f"Dry-run complete; {moves} artifact(s) would move.")
    else:
        print(f"Migration complete; moved {moves} artifact(s).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print planned moves without moving files.")
    args = parser.parse_args()
    return migrate(dry_run=bool(args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
