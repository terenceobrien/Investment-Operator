from __future__ import annotations

from dotenv import load_dotenv
load_dotenv()  # Load environment variables from .env file

import argparse
import csv
import sys
from pathlib import Path

try:
    from narrative.daily import build_narrative_scores
    from narrative.sources import RssSource, LocalFileSource
except Exception:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
    from narrative.daily import build_narrative_scores
    from narrative.sources import RssSource, LocalFileSource


def load_sources_from_csv(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"Sources CSV not found: {path}")

    rss_feeds = []
    sources = []

    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        required = {"Enabled", "Type", "Source Name", "Filepath"}
        if not required.issubset(set(reader.fieldnames or [])):
            raise ValueError(f"Sources CSV must have columns: {sorted(required)}")

        for row in reader:
            enabled = str(row["Enabled"]).strip() in {"1", "true", "TRUE", "True", "yes", "YES"}
            if not enabled:
                continue

            typ = row["Type"].strip().lower()
            name = row["Source Name"].strip()
            val = row["Filepath"].strip()

            if typ == "rss":
                rss_feeds.append({"name": name, "url": val})
            elif typ == "local":
                sources.append(LocalFileSource(directory=val))
            else:
                raise ValueError(f"Unknown source type: {typ}")

    if rss_feeds:
        sources.append(RssSource(feeds=rss_feeds, user_agent="ai-operator/1.0"))

    return sources


def main(argv=None):
    p = argparse.ArgumentParser(description="Run narrative scoring pipeline")
    p.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    p.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    p.add_argument(
        "--sources-csv",
        default="config/narrative_sources.csv",
        help="CSV file defining narrative sources",
    )
    args = p.parse_args(argv)

    sources = load_sources_from_csv(Path(args.sources_csv))
    df = build_narrative_scores(args.start, args.end, sources=sources)

    out_dir = Path("data") / "narrative"
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = out_dir / "narrative_daily.csv"
    parquet_path = out_dir / "narrative_daily.parquet"

    df.to_csv(csv_path, index=False)
    try:
        df.to_parquet(parquet_path, index=False)
        wrote_parquet = True
    except Exception:
        wrote_parquet = False

    n_rows = len(df)
    n_has_text = int(df["has_text"].sum()) if "has_text" in df.columns else 0

    print(f"Narrative pipeline ran for {args.start} -> {args.end}")
    print(f"Sources enabled: {len(sources)}")
    print(f"Rows: {n_rows}, days with text: {n_has_text}")
    print(f"Wrote CSV: {csv_path}")
    if wrote_parquet:
        print(f"Wrote Parquet: {parquet_path}")
    else:
        print("Skipped Parquet write (missing dependency like pyarrow/fastparquet?)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())