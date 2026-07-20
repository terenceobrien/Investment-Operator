from __future__ import annotations

from src.agent_system import narrative_service
from src.agent_system.orchestration import stub_agents
from src.agent_system.schemas.common import ConvictionRating


def _candidate(ticker: str = "NVDA"):
    regime = stub_agents.make_stub_regime_state()
    candidate = stub_agents.make_stub_thematic_map(regime).candidates[0]
    return candidate.model_copy_validate({"ticker": ticker})


def test_build_narrative_analysis_maps_service_content(monkeypatch):
    ticker_narrative = narrative_service.TickerNarrative(
        ticker="NVDA",
        coverage_quality="high",
        dominant_narrative_title="AI capex breadth is still expanding",
        dominant_narrative_summary=(
            "Hyperscaler spending and semiconductor leadership remain linked "
            "to broad risk appetite in the latest QQQ snapshot."
        ),
        stance="risk_on",
        confidence=82,
        inefficiency_archetype_id="momentum_trend_persistence",
        inefficiency_archetype_name="momentum trend persistence",
        price_confirmation="confirming",
        sector_etf="SMH",
        sector_narrative_alignment="aligned",
        snapshot_date="2026-06-05",
        snapshot_subject="QQQ",
        source_narrative_indices=[1],
    )
    monkeypatch.setattr(
        stub_agents,
        "get_ticker_narrative",
        lambda ticker: ticker_narrative,
    )

    analysis = stub_agents.build_narrative_analysis(_candidate("NVDA"))

    assert analysis.coverage_quality == "high"
    assert analysis.snapshot_subject == "QQQ"
    assert analysis.inefficiency_archetype_id == "momentum_trend_persistence"
    assert analysis.price_confirmation == "confirming"
    assert analysis.sector_etf == "SMH"
    assert analysis.source_narrative_indices == [1]
    assert "AI capex breadth" in analysis.current_narrative.summary
    assert "AI infrastructure lens" not in analysis.current_narrative.summary
    assert analysis.conviction.rating == ConvictionRating.MODERATE


def test_build_narrative_analysis_absent_is_honest(monkeypatch):
    ticker_narrative = narrative_service.TickerNarrative(
        ticker="CCL",
        coverage_quality="absent",
        sector_etf="XLY",
        sector_narrative_alignment="no_sector_signal",
        snapshot_date="",
    )
    monkeypatch.setattr(
        stub_agents,
        "get_ticker_narrative",
        lambda ticker: ticker_narrative,
    )

    analysis = stub_agents.build_narrative_analysis(_candidate("CCL"))

    assert analysis.coverage_quality == "absent"
    assert analysis.sector_etf == "XLY"
    assert analysis.current_narrative.summary.startswith("No current narrative coverage.")
    assert "Thematic agent's consensus view:" in analysis.current_narrative.summary
    assert analysis.conviction.rating == ConvictionRating.WEAK
