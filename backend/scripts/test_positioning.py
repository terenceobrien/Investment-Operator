#!/usr/bin/env python3
"""Test the new positioning data fetches."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.state.regime_data import _fetch_cboe_pcr, _fetch_cftc_cot

print("Testing CBOE put/call ratio fetch...")
pcr = _fetch_cboe_pcr()
print(f"Result: {pcr}")
print()

print("Testing CFTC COT fetch...")
cot = _fetch_cftc_cot()
print(f"Result: {cot}")
