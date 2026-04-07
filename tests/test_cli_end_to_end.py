from pathlib import Path
import sys
import hashlib
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from narrative.daily import build_narrative_scores

def test_cli_end_to_end_and_zcols(tmp_path):
    csv_path = Path("data") / "narrative" / "narrative_daily.csv"
    parquet_path = Path("data") / "narrative" / "narrative_daily.parquet"
    # remove existing files if present to ensure test writes fresh outputs
    if csv_path.exists():
        csv_path.unlink()
    if parquet_path.exists():
        parquet_path.unlink()

    # run over fixture dates that exist in data/narrative/raw (a.jsonl b.jsonl)
    df = build_narrative_scores("2023-01-01", "2023-01-03")
    # files should be present (CSV guaranteed)
    assert csv_path.exists()
    # CSV bytes hash
    c1 = csv_path.read_bytes()
    # rerun
    df2 = build_narrative_scores("2023-01-01", "2023-01-03")
    c2 = csv_path.read_bytes()
    assert c1 == c2
    # load CSV via pandas and check z_ columns exist
    df_csv = pd.read_csv(csv_path)
    assert "z_tone" in df_csv.columns
    assert "z_conviction" in df_csv.columns
    assert "z_cohesion" in df_csv.columns
    # deterministic CSV hash
    assert hashlib.sha256(c1).hexdigest() == hashlib.sha256(c2).hexdigest()