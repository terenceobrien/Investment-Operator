from __future__ import annotations

import json
from types import SimpleNamespace

from src.narrative import synth as synth_mod
from src.narrative.schema import DominantNarrative, ExecutiveSnapshot, NarrativeStateV1


class _MockCompletions:
    def __init__(self, parsed: NarrativeStateV1) -> None:
        self.parsed = parsed
        self.calls: list[dict] = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(parsed=self.parsed),
                )
            ]
        )


class _MockClient:
    def __init__(self, parsed: NarrativeStateV1) -> None:
        self.completions = _MockCompletions(parsed)
        self.beta = SimpleNamespace(
            chat=SimpleNamespace(completions=self.completions),
        )


def _patch_synth_io(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(synth_mod, "assert_llm_calls_allowed", lambda context="": None)
    monkeypatch.setattr(synth_mod, "snapshots_dir", lambda create=False: tmp_path)


def test_old_prior_snapshot_without_persistent_fields_loads(tmp_path):
    old_snapshot = {
        "asof_utc": "2026-06-04T14:30:00+00:00",
        "dominant_narratives": [
            {
                "title": "Rates stay higher for longer",
                "stance": "risk_off",
                "confidence": 72,
                "why_now": "Older snapshot predates persistent narrative fields.",
                "takeaways": ["PRICE: yields are pressuring duration."],
            }
        ],
        "one_paragraph_summary": "Older saved state.",
    }
    synth_mod.save_narrative_snapshot(
        old_snapshot,
        tmp_path,
        "2026-06-04",
        subject_key="SPY",
    )

    prior_date, loaded = synth_mod.load_latest_narrative_snapshot(
        tmp_path,
        today_date_str="2026-06-05",
        subject_key="SPY",
    )
    parsed = NarrativeStateV1.model_validate(loaded)
    narrative = parsed.dominant_narratives[0]

    assert prior_date == "2026-06-04"
    assert narrative.narrative_id == ""
    assert narrative.lifecycle_state == "emerging"
    assert narrative.direction == "stable"
    assert narrative.fundamental_trend == "unclear"


def test_synthesis_payload_includes_full_prior_context_and_preserves_id(
    monkeypatch,
    tmp_path,
):
    _patch_synth_io(monkeypatch, tmp_path)
    prior_narrative = {
        "title": "AI capex ROI concerns",
        "narrative_id": "ai_capex_roi_concerns",
        "lifecycle_state": "established",
        "first_seen": "2026-05-20",
        "last_updated": "2026-06-04",
        "age_days": 15,
        "direction": "stable",
        "fundamental_trend": "mixed",
        "stance": "risk_off",
        "confidence": 78,
        "why_now": "Prior concern about AI infrastructure returns.",
    }
    prior_state = {
        "asof_utc": "2026-06-04T14:30:00+00:00",
        "one_paragraph_summary": "AI capex return concerns remain established.",
        "dominant_narratives": [prior_narrative],
    }
    parsed = NarrativeStateV1(
        asof_utc="2026-06-05T15:00:00+00:00",
        dominant_narratives=[
            DominantNarrative(
                title="AI capex ROI concerns",
                stance="risk_off",
                confidence=80,
                why_now=(
                    "New earnings commentary is incremental evidence within the "
                    "long-running AI capex ROI debate."
                ),
            )
        ],
        executive_snapshot=ExecutiveSnapshot(price_confirmation="Mixed"),
    )
    client = _MockClient(parsed)

    out = synth_mod.synthesize_narrative_state(
        {"asof_utc": "2026-06-05T15:00:00+00:00", "items": [], "watch_tickers": ["NVDA"]},
        prior_state=prior_state,
        client=client,
        model="mock-model",
    )

    narrative = out["dominant_narratives"][0]
    assert narrative["narrative_id"] == "ai_capex_roi_concerns"
    assert narrative["first_seen"] == "2026-05-20"
    assert narrative["last_updated"] == "2026-06-05"
    assert narrative["age_days"] == 16

    dump = json.loads((tmp_path / "synth_input_2026-06-05.json").read_text())
    prior_context = dump["payload"]["prior_context"]
    assert prior_context["dominant_titles"] == ["AI capex ROI concerns"]
    assert prior_context["dominant_narratives"] == [prior_narrative]

    system_prompt = client.completions.calls[0]["messages"][0]["content"]
    assert system_prompt.startswith(
        "You are a senior portfolio manager maintaining a persistent model"
    )
    assert "daily narrative-regime delta note" not in system_prompt
    assert "PERSISTENT NARRATIVE IDENTITY RULES" in system_prompt
    assert "TIME-HORIZON RULES" in system_prompt
    assert "`why_now` should explain why the narrative deserves attention now" in (
        dump["payload"]["instructions"]["dominant_narratives"]
    )


def test_new_narrative_missing_persistent_fields_gets_stable_defaults(
    monkeypatch,
    tmp_path,
):
    _patch_synth_io(monkeypatch, tmp_path)
    parsed = NarrativeStateV1(
        asof_utc="2026-06-05T15:00:00+00:00",
        dominant_narratives=[
            DominantNarrative(
                title="Soft landing without recession",
                stance="risk_on",
                confidence=70,
                why_now="Fresh data supports the soft-landing debate.",
            )
        ],
    )
    client = _MockClient(parsed)

    out = synth_mod.synthesize_narrative_state(
        {"asof_utc": "2026-06-05T15:00:00+00:00", "items": []},
        prior_state={"asof_utc": "2026-06-04T14:30:00+00:00", "dominant_narratives": []},
        client=client,
        model="mock-model",
    )

    narrative = out["dominant_narratives"][0]
    assert narrative["narrative_id"] == "soft_landing_without_recession"
    assert narrative["first_seen"] == "2026-06-05"
    assert narrative["last_updated"] == "2026-06-05"
    assert narrative["age_days"] == 0


def test_time_horizon_fixture_does_not_flip_medium_term_narrative_on_1d_move(
    monkeypatch,
    tmp_path,
):
    _patch_synth_io(monkeypatch, tmp_path)
    prior_state = {
        "asof_utc": "2026-06-04T14:30:00+00:00",
        "dominant_narratives": [
            {
                "title": "AI capex ROI concerns",
                "narrative_id": "ai_capex_roi_concerns",
                "first_seen": "2026-05-01",
                "direction": "weakening",
                "fundamental_trend": "mixed",
            }
        ],
    }
    price_context = {
        "format": "multi_timeframe",
        "horizons": ["1D", "5D", "1M", "3M", "YTD", "1Y"],
        "single_names": [
            {
                "ticker": "NVDA",
                "returns": {"1D": 12.0, "5D": 3.0, "1M": -14.0, "3M": -23.0},
            }
        ],
        "sectors": [
            {
                "ticker": "SMH",
                "returns": {"1D": 4.0, "5D": 1.0, "1M": -8.0, "3M": -15.0},
            }
        ],
        "relationships": [],
    }
    parsed = NarrativeStateV1(
        asof_utc="2026-06-05T15:00:00+00:00",
        dominant_narratives=[
            DominantNarrative(
                title="AI capex ROI concerns",
                narrative_id="ai_capex_roi_concerns",
                lifecycle_state="challenged",
                first_seen="2026-05-01",
                last_updated="2026-06-05",
                age_days=35,
                direction="weakening",
                fundamental_trend="mixed",
                stance="risk_off",
                confidence=74,
                why_now=(
                    "The 1D rally is a possible abrupt narrative reversal, but "
                    "1M/3M price behavior remains bearish, so the medium-term "
                    "narrative has not automatically flipped."
                ),
                takeaways=[
                    "REALITY: fundamentals are mixed rather than clearly improving.",
                    "STORY: investors are still debating AI capex returns.",
                    "PRICE: 1M and 3M remain bearish while 1D is a sharp counter-move requiring confirmation.",
                    "GAP: the rally tests but does not yet invalidate the established narrative.",
                ],
            )
        ],
        executive_snapshot=ExecutiveSnapshot(
            price_confirmation="Partially confirming",
            primary_gap="Medium-horizon price remains weaker than the 1D catalyst response.",
        ),
    )
    client = _MockClient(parsed)

    out = synth_mod.synthesize_narrative_state(
        {"asof_utc": "2026-06-05T15:00:00+00:00", "items": [], "watch_tickers": ["NVDA"]},
        prior_state=prior_state,
        price_context=price_context,
        client=client,
        model="mock-model",
    )

    narrative = out["dominant_narratives"][0]
    assert narrative["direction"] == "weakening"
    assert "possible abrupt narrative reversal" in narrative["why_now"]
    assert "1M and 3M remain bearish" in narrative["takeaways"][2]

    dump = json.loads((tmp_path / "synth_input_2026-06-05.json").read_text())
    assert dump["price_context"] == price_context
    assert any(
        block["type"] == "single_name_returns"
        for block in dump["payload"]["information_ledgers"]["price_ledger"]
    )
    assert "based primarily on 1M/3M evidence" in (
        dump["payload"]["instructions"]["executive_snapshot"]
    )
    assert "Avoid creating an inefficiency solely" in (
        dump["payload"]["instructions"]["inefficiency_map"]
    )
