"""
Run one deterministic v0 research cycle end-to-end.

This is the execution spine smoke test: no live data, no LLMs, just schemas,
rules, storage, and decision logging.
"""
from __future__ import annotations

import json
from uuid import uuid4

from src.agent_system.orchestration.stub_agents import (
    construct_trade_idea,
    make_stub_fundamental_analysis,
    make_stub_narrative_analysis,
    make_stub_regime_state,
    make_stub_thematic_map,
)
from src.agent_system.rules.constraints import check_portfolio_constraints
from src.agent_system.rules.conviction import evaluate_conviction
from src.agent_system.schemas.common import ConvictionRating
from src.agent_system.schemas.trade import TradeProvenance
from src.agent_system.storage.repository import save_decision_log_entry, save_schema


def _decision_label(rating: ConvictionRating) -> str:
    return "rejected" if rating in (ConvictionRating.PASS, ConvictionRating.WEAK) else "accepted"


def run_stub_research_cycle() -> dict:
    """
    Execute one local deterministic cycle and persist schemas/log entries.

    Returns a summary that is intentionally compact enough for CLI output and
    tests, while detailed artifacts live in JSONL storage.
    """

    cycle_id = str(uuid4())
    regime = make_stub_regime_state()
    regime_id = save_schema(regime)
    regime = regime.model_copy(update={"id": regime_id})

    thematic_maps = 0
    candidates_considered = 0
    trade_ideas_saved = 0
    decision_log_entries = 0
    accepted_underlyings: list[str] = []
    rejected_underlyings: list[str] = []

    for priority in regime.research_priorities:
        priority_id = save_schema(priority)
        thematic_map = make_stub_thematic_map(regime).model_copy_validate(
            {"source_priority_id": priority_id}
        )
        thematic_map_id = save_schema(thematic_map)
        thematic_maps += 1

        for candidate in thematic_map.candidates:
            candidates_considered += 1
            fundamental = make_stub_fundamental_analysis(candidate)
            narrative = make_stub_narrative_analysis(candidate)
            fundamental_id = save_schema(fundamental)
            narrative_id = save_schema(narrative)
            conviction = evaluate_conviction(
                candidate=candidate,
                fundamental=fundamental,
                narrative=narrative,
                regime=regime,
            )
            trade = construct_trade_idea(
                candidate=candidate,
                fundamental=fundamental,
                narrative=narrative,
                regime=regime,
                conviction=conviction,
            )
            provenance = TradeProvenance(
                research_priority_id=priority_id,
                thematic_map_id=thematic_map_id,
                fundamental_analysis_id=fundamental_id,
                narrative_analysis_id=narrative_id,
                regime_state_id=regime_id,
            )
            trade = trade.model_copy_validate({"provenance": provenance})
            trade_id = save_schema(trade)
            trade_ideas_saved += 1

            constraint = check_portfolio_constraints(
                proposed_trade=trade,
                portfolio_state=None,
            )
            decision = _decision_label(conviction.rating)
            if decision == "accepted" and constraint.allowed:
                accepted_underlyings.append(candidate.ticker)
            else:
                rejected_underlyings.append(candidate.ticker)

            save_decision_log_entry(
                {
                    "cycle_id": cycle_id,
                    "candidate": candidate.ticker,
                    "decision": decision if constraint.allowed or decision == "rejected" else "rejected",
                    "conviction_rating": conviction.rating.value,
                    "rule_applied": conviction.rule_applied,
                    "weakest_link": conviction.weakest_link,
                    "summary": conviction.reasoning,
                    "trade_idea_id": trade_id,
                    "portfolio_constraint": constraint.model_dump(mode="json"),
                    "review_notes": "",
                }
            )
            decision_log_entries += 1

    return {
        "cycle_id": cycle_id,
        "regime_id": regime_id,
        "thematic_maps": thematic_maps,
        "candidates_considered": candidates_considered,
        "trade_ideas_saved": trade_ideas_saved,
        "accepted": len(accepted_underlyings),
        "rejected": len(rejected_underlyings),
        "decision_log_entries": decision_log_entries,
        "accepted_underlyings": accepted_underlyings,
        "rejected_underlyings": rejected_underlyings,
    }


if __name__ == "__main__":
    print(json.dumps(run_stub_research_cycle(), indent=2, sort_keys=True))
