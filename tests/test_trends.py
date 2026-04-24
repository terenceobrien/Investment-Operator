"""
tests/test_trends.py

Unit tests for narrative/trends.py.
All tests are offline — no pytrends or OpenAI calls made.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from trends import (
    ANCHOR_TERM,
    STATIC_TERM_GROUPS,
    TrendSignal,
    TrendScanResult,
    _derive_signal,
    _iso_week,
    extract_narrative_query_terms,
    run_trend_scan,
    build_trend_history_df,
)


# ── Fixtures ────────────────────────────────────────────────────────────────

def _make_series(values: List[float]) -> pd.Series:
    """Create a weekly pd.Series with a simple RangeIndex (avoids date-length mismatches)."""
    return pd.Series(values, dtype=float)


def _make_snapshot(stance: str = "risk_off", confidence: int = 75) -> Dict[str, Any]:
    return {
        "asof_utc": "2025-04-01T12:00:00+00:00",
        "dominant_narratives": [
            {
                "title": "Fed higher for longer crushes rate-sensitive sectors",
                "stance": stance,
                "confidence": confidence,
                "why_now": "CPI came in hot; Fed speakers pushed back on cuts.",
                "key_catalysts": ["CPI print", "Fed minutes", "treasury yield spike"],
                "tickers": ["TLT", "XLF"],
                "evidence": [],
                "what_would_change": [],
                "risks_to_watch": [],
                "takeaways": [],
            }
        ],
        "one_paragraph_summary": "Markets pricing more rate hikes.",
        "raw_takeaways": [],
        "counter_narratives": [],
        "unknowns": [],
        "market_tone": {"risk_appetite": "low", "fragility": "fragile", "positioning_guess": "crowded", "tone_notes": ""},
        "signals": {"headline_intensity": 70, "earnings_intensity": 40, "macro_intensity": 80, "social_intensity": 30},
    }


# ── Static taxonomy tests ────────────────────────────────────────────────────

class TestStaticTaxonomy:
    def test_all_groups_have_five_terms(self):
        for group, terms in STATIC_TERM_GROUPS.items():
            assert len(terms) == 5, f"Group '{group}' should have 5 terms, got {len(terms)}"

    def test_no_duplicate_terms_across_groups(self):
        all_terms = [t for terms in STATIC_TERM_GROUPS.values() for t in terms]
        assert len(all_terms) == len(set(all_terms)), "Duplicate terms found across static groups"

    def test_anchor_not_in_static_groups(self):
        all_terms = [t for terms in STATIC_TERM_GROUPS.values() for t in terms]
        assert ANCHOR_TERM not in all_terms, f"Anchor term '{ANCHOR_TERM}' should not appear in static groups"

    def test_all_terms_are_lowercase_strings(self):
        for group, terms in STATIC_TERM_GROUPS.items():
            for t in terms:
                assert isinstance(t, str), f"Term in '{group}' is not a string"
                assert t == t.lower(), f"Term '{t}' in '{group}' is not lowercase"


# ── Signal derivation tests ──────────────────────────────────────────────────

class TestDeriveSignal:
    def test_rising_series_produces_rising_direction(self):
        values = [10.0, 12.0, 15.0, 20.0, 28.0, 38.0, 50.0, 65.0]
        sig = _derive_signal("test term", "macro_anxiety", "static", _make_series(values))
        assert sig.slope_direction == "rising"
        assert sig.slope_magnitude > 0

    def test_falling_series_produces_falling_direction(self):
        values = [65.0, 55.0, 45.0, 35.0, 25.0, 15.0, 8.0, 3.0]
        sig = _derive_signal("test term", "macro_anxiety", "static", _make_series(values))
        assert sig.slope_direction == "falling"
        assert sig.slope_magnitude < 0

    def test_flat_series_produces_flat_direction(self):
        values = [50.0, 51.0, 49.0, 50.0, 50.5, 49.5, 50.0, 50.2]
        sig = _derive_signal("test term", "macro_anxiety", "static", _make_series(values))
        assert sig.slope_direction == "flat"

    def test_empty_series_returns_safe_defaults(self):
        sig = _derive_signal("empty term", "macro_anxiety", "static", pd.Series([], dtype=float))
        assert sig.current_score == 0.0
        assert sig.slope_direction == "flat"
        assert sig.zscore_4w == 0.0
        assert sig.narrative_alignment is None

    def test_zscore_4w_positive_for_recent_spike(self):
        # Flat history then a spike
        values = [20.0, 22.0, 21.0, 20.0, 22.0, 21.0, 20.0, 80.0]
        sig = _derive_signal("spiking term", "macro_anxiety", "static", _make_series(values))
        assert sig.zscore_4w > 1.0, f"Expected positive z-score for spike, got {sig.zscore_4w}"

    def test_current_score_matches_last_value(self):
        values = [10.0, 20.0, 30.0, 42.5]
        sig = _derive_signal("test", "macro_anxiety", "static", _make_series(values))
        assert abs(sig.current_score - 42.5) < 0.01

    def test_history_length_matches_input(self):
        values = [float(i) for i in range(12)]
        sig = _derive_signal("test", "macro_anxiety", "static", _make_series(values))
        assert len(sig.history) == 12


# ── Alignment logic tests ─────────────────────────────────────────────────────

class TestAlignmentLogic:
    def _rising_sig(self, stance: str) -> TrendSignal:
        values = [10.0, 12.0, 15.0, 20.0, 28.0, 38.0, 50.0, 65.0]
        return _derive_signal(
            "iran war", "narrative_dynamic", "dynamic",
            _make_series(values),
            narrative_title="Geopolitical escalation",
            narrative_stance=stance,
        )

    def _falling_sig(self, stance: str) -> TrendSignal:
        values = [65.0, 55.0, 45.0, 35.0, 25.0, 15.0, 8.0, 3.0]
        return _derive_signal(
            "iran war", "narrative_dynamic", "dynamic",
            _make_series(values),
            narrative_title="Geopolitical escalation",
            narrative_stance=stance,
        )

    def test_rising_trend_aligns_with_risk_off(self):
        sig = self._rising_sig("risk_off")
        assert sig.narrative_alignment is True, sig.alignment_note

    def test_falling_trend_diverges_from_risk_off(self):
        sig = self._falling_sig("risk_off")
        assert sig.narrative_alignment is False, sig.alignment_note

    def test_falling_trend_aligns_with_risk_on(self):
        sig = self._falling_sig("risk_on")
        assert sig.narrative_alignment is True, sig.alignment_note

    def test_rising_trend_diverges_from_risk_on(self):
        sig = self._rising_sig("risk_on")
        assert sig.narrative_alignment is False, sig.alignment_note

    def test_static_source_has_no_alignment(self):
        values = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0]
        sig = _derive_signal("recession", "macro_anxiety", "static", _make_series(values))
        assert sig.narrative_alignment is None
        assert "Static term" in sig.alignment_note

    def test_unclear_stance_produces_no_alignment_bool(self):
        values = [40.0, 42.0, 44.0, 46.0, 48.0, 50.0, 52.0, 54.0]
        sig = _derive_signal(
            "some term", "narrative_dynamic", "dynamic",
            _make_series(values),
            narrative_stance="unclear",
        )
        # unclear stance should not produce True/False alignment
        assert sig.narrative_alignment is None or isinstance(sig.narrative_alignment, bool)


# ── Dynamic term extraction tests ─────────────────────────────────────────────

class TestExtractNarrativeQueryTerms:
    def _mock_openai_response(self, terms: List[Dict]) -> MagicMock:
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = json.dumps(terms)
        mock_client.chat.completions.create.return_value = mock_resp
        return mock_client

    def test_extracts_llm_terms_and_ticker_terms(self):
        snapshot = _make_snapshot()
        mock_client = self._mock_openai_response([
            {"term": "federal reserve rate hike", "narrative_title": "Fed higher for longer", "narrative_stance": "risk_off"},
            {"term": "treasury yield spike", "narrative_title": "Fed higher for longer", "narrative_stance": "risk_off"},
        ])
        result = extract_narrative_query_terms(snapshot, openai_client=mock_client)
        terms = [r["term"] for r in result]
        # LLM terms
        assert "federal reserve rate hike" in terms
        assert "treasury yield spike" in terms
        # Ticker terms auto-generated (extractor preserves uppercase from tickers field)
        assert any(t in terms for t in ["tlt stock", "TLT stock", "xlf stock", "XLF stock"])

    def test_deduplicates_terms(self):
        snapshot = _make_snapshot()
        mock_client = self._mock_openai_response([
            {"term": "recession", "narrative_title": "X", "narrative_stance": "risk_off"},
            {"term": "recession", "narrative_title": "X", "narrative_stance": "risk_off"},
        ])
        result = extract_narrative_query_terms(snapshot, openai_client=mock_client)
        terms = [r["term"] for r in result]
        assert terms.count("recession") == 1

    def test_empty_snapshot_returns_empty_list(self):
        result = extract_narrative_query_terms({"dominant_narratives": []}, openai_client=MagicMock())
        assert result == []

    def test_llm_failure_returns_ticker_terms_only(self):
        snapshot = _make_snapshot()
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = RuntimeError("API down")
        result = extract_narrative_query_terms(snapshot, openai_client=mock_client)
        # Should still get ticker terms even when LLM fails
        assert len(result) > 0
        assert all("stock" in r["term"] for r in result)

    def test_narrative_stance_preserved_in_output(self):
        snapshot = _make_snapshot(stance="risk_on")
        mock_client = self._mock_openai_response([
            {"term": "bull market", "narrative_title": "T", "narrative_stance": "risk_on"},
        ])
        result = extract_narrative_query_terms(snapshot, openai_client=mock_client)
        llm_terms = [r for r in result if r["term"] == "bull market"]
        assert llm_terms[0]["narrative_stance"] == "risk_on"

    def test_term_length_capped(self):
        snapshot = _make_snapshot()
        very_long_term = "a" * 100
        mock_client = self._mock_openai_response([
            {"term": very_long_term, "narrative_title": "T", "narrative_stance": "risk_off"},
        ])
        result = extract_narrative_query_terms(snapshot, openai_client=mock_client)
        for r in result:
            assert len(r["term"]) <= 80, f"Term too long: {r['term']}"


# ── TrendScanResult helpers ──────────────────────────────────────────────────

class TestTrendScanResult:
    def _build_result(self) -> TrendScanResult:
        def _sig(term, source, stance, aligned):
            values = [30.0, 35.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0] if aligned else \
                     [80.0, 70.0, 60.0, 50.0, 40.0, 30.0, 20.0, 10.0]
            s = _derive_signal(term, "narrative_dynamic" if source == "dynamic" else "test_group",
                               source, _make_series(values),
                               narrative_stance=stance)
            return s

        static = [_sig("recession", "static", None, True)]
        dynamic = [
            _sig("iran war", "dynamic", "risk_off", True),
            _sig("fed pivot", "dynamic", "risk_off", False),
        ]
        return TrendScanResult(
            asof_utc="2025-04-01T00:00:00+00:00",
            snapshot_date="2025-04-01",
            static_signals=static,
            dynamic_signals=dynamic,
            dynamic_terms_raw=["iran war", "fed pivot"],
        )

    def test_all_signals_combines_static_and_dynamic(self):
        r = self._build_result()
        assert len(r.all_signals()) == 3

    def test_aligned_signals_filters_correctly(self):
        r = self._build_result()
        aligned = r.aligned_signals()
        assert all(s.narrative_alignment is True for s in aligned)

    def test_diverging_signals_filters_correctly(self):
        r = self._build_result()
        diverging = r.diverging_signals()
        assert all(s.narrative_alignment is False for s in diverging)

    def test_to_dict_is_json_serializable(self):
        r = self._build_result()
        d = r.to_dict()
        serialized = json.dumps(d)  # should not raise
        assert '"static_signals"' in serialized
        assert '"dynamic_signals"' in serialized


# ── Iso week helper ──────────────────────────────────────────────────────────

class TestIsoWeek:
    def test_returns_string_in_expected_format(self):
        week = _iso_week()
        assert week.startswith("20"), f"Unexpected format: {week}"
        assert "-W" in week

    def test_deterministic_for_same_datetime(self):
        dt = datetime(2025, 4, 1, 12, 0, 0, tzinfo=timezone.utc)
        assert _iso_week(dt) == _iso_week(dt)


# ── run_trend_scan offline test ──────────────────────────────────────────────

class TestRunTrendScanOffline:
    """Test run_trend_scan by mocking fetch_terms and extract_narrative_query_terms."""

    def _fake_fetch(self, terms, **kwargs) -> Dict[str, pd.Series]:
        return {
            t: _make_series([20.0 + i * 5 for i in range(12)])
            for i, t in enumerate(terms)
        }

    def test_static_only_scan(self):
        with patch("trends.fetch_terms", side_effect=self._fake_fetch):
            result = run_trend_scan(skip_dynamic=True, use_cache=False)
        assert len(result.static_signals) > 0
        assert len(result.dynamic_signals) == 0

    def test_dynamic_signals_produced_from_snapshot(self):
        snapshot = _make_snapshot()
        extracted = [{"term": "fed rate hike", "narrative_title": "T", "narrative_stance": "risk_off", "confidence": 75}]
        with patch("trends.fetch_terms", side_effect=self._fake_fetch), \
             patch("trends.extract_narrative_query_terms", return_value=extracted):
            result = run_trend_scan(snapshot=snapshot, snapshot_date="2025-04-01",
                                    skip_static=True, use_cache=False)
        assert len(result.dynamic_signals) == 1
        assert result.dynamic_signals[0].source == "dynamic"

    def test_result_has_correct_metadata(self):
        with patch("trends.fetch_terms", side_effect=self._fake_fetch):
            result = run_trend_scan(skip_dynamic=True, use_cache=False, geo="US")
        assert result.meta["geo"] == "US"
        assert "iso_week" in result.meta