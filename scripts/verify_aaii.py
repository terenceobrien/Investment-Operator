"""Quick sanity check that the AAII XLS parses cleanly."""
from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

load_dotenv()
load_dotenv(REPO_ROOT / ".env.local")
load_dotenv(BACKEND_ROOT / ".env", override=True)

from src.state.sentiment_data import get_aaii_asof, get_aaii_history


def main() -> int:
    history = get_aaii_history()
    print(f"\nParsed {len(history)} weekly AAII readings")
    print(f"  range:     {history.index[0].date()} -> {history.index[-1].date()}")
    print(f"  min:       {history.min():+.1f}pp")
    print(f"  max:       {history.max():+.1f}pp")
    print(f"  mean:      {history.mean():+.1f}pp")
    print(f"  latest:    {history.iloc[-1]:+.1f}pp on {history.index[-1].date()}")

    print("\nPoint-in-time lookups:")
    for asof in ["2024-06-15", "2025-01-15", "2025-04-15", "2026-06-15"]:
        value = get_aaii_asof(asof_date=asof)
        if value is None:
            print(f"  asof {asof}: no data")
        else:
            print(f"  asof {asof}: {value:+.1f}pp")

    panic = int((history < -28).sum())
    euphoria = int((history > 37).sum())
    print("\nThreshold sanity check (against full history):")
    print(f"  readings < -28pp (panic):    {panic} ({panic / len(history) * 100:.1f}%)")
    print(f"  readings > +37pp (euphoria): {euphoria} ({euphoria / len(history) * 100:.1f}%)")
    print("  If these are under roughly 15% each, thresholds are calibrated to extremes.")

    print("\nAAII module verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
