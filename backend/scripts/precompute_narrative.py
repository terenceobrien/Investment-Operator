"""
Generic entrypoint for supported ticker narrative precompute.

Examples:
    python backend/scripts/precompute_narrative.py --ticker MSFT
    python backend/scripts/precompute_narrative.py --ticker AAPL --force
    python backend/scripts/precompute_narrative.py --magnificent7 --force
"""
from __future__ import annotations

import sys

from precompute_spy_narrative import main


if __name__ == "__main__":
    sys.exit(main())
