"""
tests/conftest.py

Adds backend/src/narrative to sys.path so test files can import narrative
modules directly by bare name (e.g. `from trends import ...` rather than
`from src.narrative.trends import ...`).
"""
import sys
from pathlib import Path

# Insert once — idempotent if already on path
_narrative_dir = str(Path(__file__).resolve().parents[1] / "backend" / "src" / "narrative")
if _narrative_dir not in sys.path:
    sys.path.insert(0, _narrative_dir)

# Also make backend/src importable for any cross-module imports inside narrative
_src_dir = str(Path(__file__).resolve().parents[1] / "backend" / "src")
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)
