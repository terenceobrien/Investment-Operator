from pathlib import Path
import sys
import shutil
import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

import pytest
from narrative.sources.local_file import LocalFileSource
from narrative.daily import build_narrative_scores
from narrative.sources.base import RawTextItem

def write_jsonl(path: Path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for l in lines:
            fh.write(json.dumps(l, ensure_ascii=False) + "\n")

def test_local_file_source_writes_errors(tmp_path, monkeypatch):
    data_dir = tmp_path / "data" / "narrative" / "raw"
    data_dir.mkdir(parents=True, exist_ok=True)
    good = {"id":"g1","source":"fixture","published_at":"2023-03-01T12:00:00Z","body":"Good text"}
    bad_line = '{"id": "b1", "source": "fixture", "published_at": "not-a-date", "body": "Bad"}'
    fpath = data_dir / "mix.jsonl"
    with fpath.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps(good, ensure_ascii=False) + "\n")
        fh.write(bad_line + "\n")
    src = LocalFileSource(directory=data_dir)
    items = src.fetch()
    # good item parsed, bad line skipped
    assert len(items) == 1
    assert src.last_parse_errors_count >= 1
    # error file exists
    err_files = list((Path("data") / "narrative" / "errors").glob("mix_errors.jsonl"))
    assert err_files, "error file should be written"
    # cleanup
    shutil.rmtree(Path("data") / "narrative")

def test_chunk_cache_hit_behavior(tmp_path):
    # ensure cache dir is clean
    cache_dir = Path("data") / "narrative" / "cache"
    if cache_dir.exists():
        shutil.rmtree(cache_dir)
    # write fixture raw files (use existing repo fixtures if present)
    # run pipeline twice and assert cache gets populated and second run yields cache hits via deterministic CSV equality
    df1 = build_narrative_scores("2023-01-01", "2023-01-03")
    csv_path = Path("data") / "narrative" / "narrative_daily.csv"
    assert csv_path.exists()
    c1 = csv_path.read_bytes()
    # second run
    df2 = build_narrative_scores("2023-01-01", "2023-01-03")
    c2 = csv_path.read_bytes()
    assert c1 == c2
    # cache file should exist
    pq = cache_dir / "chunk_scores.parquet"
    jn = cache_dir / "chunk_scores.jsonl"
    assert pq.exists() or jn.exists()
    # cleanup
    # shutil.rmtree(Path("data") / "narrative")