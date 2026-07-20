from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

import pytest

from scripts.run_deep_fundamental import resolve_transcript_paths


def _args(
    *,
    transcript_path: str | None = None,
    transcript_paths: list[str] | None = None,
    transcript_map: list[str] | None = None,
    transcript_dir: str | None = None,
) -> argparse.Namespace:
    return argparse.Namespace(
        transcript_path=transcript_path,
        transcript_paths=transcript_paths,
        transcript_map=transcript_map,
        transcript_dir=transcript_dir,
    )


def _touch(path: Path) -> str:
    path.write_text("transcript text")
    return str(path)


def test_single_ticker_transcript_path_works(tmp_path: Path) -> None:
    transcript_path = _touch(tmp_path / "MU_transcript.txt")

    resolution = resolve_transcript_paths(
        _args(transcript_path=transcript_path),
        ["MU"],
    )

    assert resolution.paths_by_ticker["MU"] == [str(Path(transcript_path).resolve())]
    assert resolution.source_by_ticker["MU"] == "transcript_path"


def test_multi_ticker_transcript_path_raises_clear_error(tmp_path: Path) -> None:
    transcript_path = _touch(tmp_path / "MU_transcript.txt")

    with pytest.raises(ValueError, match="ambiguous for multi-ticker runs"):
        resolve_transcript_paths(
            _args(transcript_path=transcript_path),
            ["MU", "AAPL"],
        )


def test_transcript_map_maps_correct_path_to_each_ticker(tmp_path: Path) -> None:
    mu_path = _touch(tmp_path / "MU_transcript.txt")
    aapl_path = _touch(tmp_path / "AAPL_transcript.txt")

    resolution = resolve_transcript_paths(
        _args(transcript_map=[f"MU={mu_path}", f"AAPL={aapl_path}"]),
        ["MU", "AAPL"],
    )

    assert resolution.paths_by_ticker["MU"] == [str(Path(mu_path).resolve())]
    assert resolution.paths_by_ticker["AAPL"] == [str(Path(aapl_path).resolve())]
    assert resolution.source_by_ticker["MU"] == "transcript_map"
    assert resolution.source_by_ticker["AAPL"] == "transcript_map"


def test_transcript_map_malformed_value_raises() -> None:
    with pytest.raises(ValueError, match="Malformed `--transcript-map` entry"):
        resolve_transcript_paths(
            _args(transcript_map=["MU"]),
            ["MU"],
        )


def test_transcript_map_duplicate_ticker_raises(tmp_path: Path) -> None:
    first_path = _touch(tmp_path / "MU_transcript.txt")
    second_path = _touch(tmp_path / "MU_latest_transcript.txt")

    with pytest.raises(ValueError, match="Duplicate `--transcript-map` entry"):
        resolve_transcript_paths(
            _args(transcript_map=[f"MU={first_path}", f"MU={second_path}"]),
            ["MU"],
        )


def test_transcript_map_missing_path_raises(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing.txt"

    with pytest.raises(ValueError, match="path does not exist"):
        resolve_transcript_paths(
            _args(transcript_map=[f"MU={missing_path}"]),
            ["MU"],
        )


def test_transcript_dir_resolves_ticker_file_names(tmp_path: Path) -> None:
    mu_path = _touch(tmp_path / "MU_transcript.txt")
    aapl_path = _touch(tmp_path / "aapl_latest_transcript.txt")

    resolution = resolve_transcript_paths(
        _args(transcript_dir=str(tmp_path)),
        ["MU", "AAPL"],
    )

    assert resolution.paths_by_ticker["MU"] == [str(Path(mu_path).resolve())]
    assert resolution.paths_by_ticker["AAPL"] == [str(Path(aapl_path).resolve())]
    assert resolution.source_by_ticker["MU"] == "transcript_dir"
    assert resolution.source_by_ticker["AAPL"] == "transcript_dir"


def test_transcript_dir_selects_newest_when_multiple_match(tmp_path: Path) -> None:
    older_path = Path(_touch(tmp_path / "MU_transcript.txt"))
    time.sleep(0.01)
    newer_path = Path(_touch(tmp_path / "MU_latest_transcript.txt"))
    os.utime(older_path, (older_path.stat().st_atime, older_path.stat().st_mtime - 10))

    resolution = resolve_transcript_paths(
        _args(transcript_dir=str(tmp_path)),
        ["MU"],
    )

    assert resolution.paths_by_ticker["MU"] == [str(newer_path.resolve())]
    assert "Multiple transcript files found for MU" in (
        resolution.warnings_by_ticker["MU"][0]
    )


def test_transcript_dir_missing_file_continues_with_warning(tmp_path: Path) -> None:
    resolution = resolve_transcript_paths(
        _args(transcript_dir=str(tmp_path)),
        ["MU"],
    )

    assert resolution.paths_by_ticker["MU"] == []
    assert resolution.source_by_ticker.get("MU") is None
    assert resolution.warnings_by_ticker["MU"] == [
        "No manual transcript found in transcript directory for MU."
    ]


def test_transcript_mapping_never_applies_to_unmapped_ticker(tmp_path: Path) -> None:
    mu_path = _touch(tmp_path / "MU_transcript.txt")

    resolution = resolve_transcript_paths(
        _args(transcript_map=[f"MU={mu_path}"]),
        ["MU", "AAPL"],
    )

    assert resolution.paths_by_ticker["MU"] == [str(Path(mu_path).resolve())]
    assert resolution.paths_by_ticker["AAPL"] == []
    assert resolution.source_by_ticker.get("AAPL") is None
