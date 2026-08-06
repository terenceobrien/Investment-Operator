"""Migrate stranded root data/agent_system artifacts into backend/data.

By default this is a dry-run. Use ``--execute`` to move/dedupe files.
Root ``data/narrative`` is legacy Pipeline A output and is only reported.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.agent_system.paths import backend_root, project_root  # noqa: E402
from migrate_macro_forecast_layout import target_for_macro_forecast_artifact  # noqa: E402


@dataclass
class Counts:
    moved: int = 0
    deduped: int = 0
    conflicts: int = 0
    skipped: int = 0


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _tree_size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    total = 0
    for child in path.rglob("*"):
        if child.is_file():
            total += child.stat().st_size
    return total


def _fmt_size(size: int) -> str:
    units = ("B", "KB", "MB", "GB")
    value = float(size)
    for unit in units:
        if value < 1024.0 or unit == units[-1]:
            return f"{value:.1f}{unit}"
        value /= 1024.0
    return f"{size}B"


def _is_flat_macro_forecast_file(rel: Path) -> bool:
    return len(rel.parts) == 3 and rel.parts[0] == "reports" and rel.parts[1] == "macro_forecasts"


def _destination_for(source: Path, source_agent_root: Path, dest_agent_root: Path) -> Path:
    rel = source.relative_to(source_agent_root)
    if _is_flat_macro_forecast_file(rel):
        routed = target_for_macro_forecast_artifact(source)
        if routed is not None:
            return routed
    return dest_agent_root / rel


def _log_root_inventory(root_data: Path) -> None:
    narrative = root_data / "narrative"
    if narrative.exists():
        print(
            "LEGACY narrative left in place: "
            f"{narrative} ({_fmt_size(_tree_size(narrative))})"
        )
    unclassified = sorted(
        child
        for child in root_data.iterdir()
        if child.name not in {"agent_system", "narrative"}
    ) if root_data.exists() else []
    if unclassified:
        print("UNCLASSIFIED root data entries left in place:")
        for child in unclassified:
            print(f"  {child} ({_fmt_size(_tree_size(child))})")


def _print_remaining_root_data(root_data: Path) -> None:
    print("Residual root data listing:")
    if not root_data.exists():
        print(f"  {root_data} does not exist")
        return
    for path in sorted(root_data.rglob("*")):
        print(f"  {path.relative_to(project_root())}")


def _prune_empty_dirs(root: Path) -> int:
    if not root.exists():
        return 0
    removed = 0
    for path in sorted((p for p in root.rglob("*") if p.is_dir()), reverse=True):
        try:
            path.rmdir()
        except OSError:
            continue
        removed += 1
        print(f"EXECUTE PRUNE empty dir: {path}")
    try:
        root.rmdir()
    except OSError:
        pass
    else:
        removed += 1
        print(f"EXECUTE PRUNE empty dir: {root}")
    return removed


def migrate(*, execute: bool, prefer_newer: bool) -> int:
    root_data = project_root() / "data"
    source_agent_root = root_data / "agent_system"
    dest_agent_root = backend_root() / "data" / "agent_system"
    action_prefix = "EXECUTE" if execute else "DRY-RUN"
    counts = Counts()

    print(f"source_agent_root={source_agent_root}")
    print(f"dest_agent_root={dest_agent_root}")
    _log_root_inventory(root_data)

    if not source_agent_root.exists():
        print(f"No root agent_system tree found; nothing to migrate: {source_agent_root}")
        if execute:
            _print_remaining_root_data(root_data)
        return 0

    conflicts: list[tuple[Path, Path]] = []
    files = sorted(path for path in source_agent_root.rglob("*") if path.is_file())
    for source in files:
        dest = _destination_for(source, source_agent_root, dest_agent_root)
        if source.resolve() == dest.resolve():
            counts.skipped += 1
            print(f"{action_prefix} SKIP same path: {source}")
            continue
        if dest.exists():
            if _sha256(source) == _sha256(dest):
                counts.deduped += 1
                print(f"{action_prefix} DEDUPE identical: {source} -> {dest}")
                if execute:
                    source.unlink()
                continue
            if prefer_newer:
                source_mtime = source.stat().st_mtime
                dest_mtime = dest.stat().st_mtime
                if source_mtime > dest_mtime:
                    counts.moved += 1
                    print(f"{action_prefix} PREFER-NEWER source replaces dest: {source} -> {dest}")
                    if execute:
                        dest.unlink()
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(source), str(dest))
                    continue
                if dest_mtime > source_mtime:
                    counts.deduped += 1
                    print(f"{action_prefix} PREFER-NEWER dest kept, source removed: {source} -> {dest}")
                    if execute:
                        source.unlink()
                    continue
            counts.conflicts += 1
            conflicts.append((source, dest))
            print(
                f"{action_prefix} CONFLICT differs: {source} "
                f"(mtime={source.stat().st_mtime:.0f}, size={source.stat().st_size}) -> {dest} "
                f"(mtime={dest.stat().st_mtime:.0f}, size={dest.stat().st_size})"
            )
            continue

        counts.moved += 1
        print(f"{action_prefix} MOVE: {source} -> {dest}")
        if execute:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(dest))

    print(
        "SUMMARY "
        f"moved={counts.moved} deduped={counts.deduped} "
        f"conflicts={counts.conflicts} skipped={counts.skipped}"
    )
    if conflicts:
        print("CONFLICTS:")
        for source, dest in conflicts:
            print(f"  source={source}")
            print(f"  dest={dest}")
    if execute:
        pruned = _prune_empty_dirs(source_agent_root)
        print(f"SUMMARY empty_dirs_pruned={pruned}")
        _print_remaining_root_data(root_data)
    return 0 if (not execute or not conflicts or prefer_newer) else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Print planned actions without moving files.")
    mode.add_argument("--execute", action="store_true", help="Move/dedupe files.")
    parser.add_argument(
        "--prefer-newer",
        action="store_true",
        help="Resolve differing destination conflicts by keeping the newer mtime.",
    )
    args = parser.parse_args()
    return migrate(execute=bool(args.execute), prefer_newer=bool(args.prefer_newer))


if __name__ == "__main__":
    raise SystemExit(main())
