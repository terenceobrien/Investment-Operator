from __future__ import annotations

import os
import finnhub


def get_finnhub_client() -> finnhub.Client:
    api_key = os.getenv("FINNHUB_API_KEY")
    if not api_key:
        raise RuntimeError("Missing FINNHUB_API_KEY in environment.")
    return finnhub.Client(api_key=api_key)
