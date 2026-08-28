from __future__ import annotations

import asyncio

from api import main


def test_latest_narrative_surfaces_generation_error_instead_of_retry_loop(monkeypatch):
    main._cache_generating.clear()
    attempts = 0

    async def failing_generation(ticker: str):
        nonlocal attempts
        attempts += 1
        raise RuntimeError("structured parse failed")

    monkeypatch.setattr(main, "is_supported_ticker", lambda ticker: True)
    monkeypatch.setattr(main, "get_ticker_profile", lambda ticker: {"ticker": ticker, "subject_type": "ticker"})
    monkeypatch.setattr(main, "prompt_subject_profile", lambda profile: profile)
    monkeypatch.setattr(main, "load_narrative_cache", lambda ticker, day: None)
    monkeypatch.setattr(main, "load_latest_narrative_cache", lambda ticker: {"output": {"asof_utc": "2026-06-05T00:00:00Z"}})
    monkeypatch.setattr(main, "llm_calls_allowed", lambda: True)
    monkeypatch.setattr(main, "assert_llm_calls_allowed", lambda context="": None)
    monkeypatch.setattr(main, "run_narrative_for_ticker", failing_generation)

    async def scenario():
        first = await main.get_latest_narrative(ticker="SPY", user={})
        await asyncio.sleep(0)
        second = await main.get_latest_narrative(ticker="SPY", user={})
        await asyncio.sleep(0)
        third = await main.get_latest_narrative(ticker="SPY", user={})
        return first, second, third

    first, second, third = asyncio.run(scenario())

    assert first["status"] == "generating"
    assert second["status"] == "error"
    assert second["last_error"] == "structured parse failed"
    assert second["last_cached_result"]["output"]["asof_utc"] == "2026-06-05T00:00:00Z"
    assert third["status"] == "error"
    assert attempts == 1

    main._cache_generating.clear()
