from __future__ import annotations

import os


def get_finnhub_client():
    import finnhub
    api_key = os.getenv("FINNHUB_API_KEY")
    if not api_key:
        raise RuntimeError("Missing FINNHUB_API_KEY in environment.")
    return finnhub.Client(api_key=api_key)
