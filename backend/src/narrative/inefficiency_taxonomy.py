"""
Compact inefficiency taxonomy for final narrative synthesis.

This module intentionally encodes the paper as a small prompt-friendly
classification registry, not as a document dump or retrieval system.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

INEFFICIENCY_TAXONOMY_VERSION = "v1"


INEFFICIENCY_TAXONOMY: List[Dict[str, Any]] = [
    {
        "id": "narrative_fundamental_divergence",
        "name": "Narrative-Fundamental Divergence",
        "definition": "Dominant market narrative materially diverges from observable fundamentals such as earnings, cash flows, credit quality, policy reality, macro data, or valuation anchors.",
        "core_cause": "Narrative epidemics, incentive-driven framing, and slow belief updating distort the relationship between story and reality.",
        "narrative_signature": ["story much better or worse than evidence", "dissenting evidence rationalized", "media or consensus framing dominates data"],
        "fundamental_signature": ["earnings, policy, macro, credit, or valuation evidence conflicts with the story"],
        "price_signature": ["price increasingly reflects story rather than reality", "valuation or price behavior detaches from evidence"],
        "typical_resolution": ["earnings, macro data, policy, or corporate events force story toward reality"],
        "false_positive_checks": ["do not classify if narrative, fundamentals, and price broadly align", "news tone alone is not enough"],
        "underlying_gap_types": ["positive_narrative_fundamental_divergence", "negative_narrative_fundamental_divergence"],
        "aliases": ["narrative divergence", "fundamental divergence", "story reality gap", "narrative-fundamental gap"],
    },
    {
        "id": "speculative_bubble_mania",
        "name": "Speculative Bubble / Mania",
        "definition": "Self-reinforcing upside narrative and extrapolative expectations push price far ahead of fundamentals.",
        "core_cause": "Extrapolation, FOMO, easy credit, and new-era storytelling create reflexive upside.",
        "narrative_signature": ["euphoric language", "new era framing", "unlimited TAM or paradigm shift claims"],
        "fundamental_signature": ["real development exists but valuation discipline breaks down"],
        "price_signature": ["parabolic or persistent outperformance", "outsized reaction to good news", "valuation far above anchors"],
        "typical_resolution": ["credit tightening", "narrative exhaustion", "shock or regulatory intervention"],
        "false_positive_checks": ["strong fundamentals plus reasonable price reaction is not a bubble", "momentum alone is not enough"],
        "underlying_gap_types": ["positive_narrative_fundamental_divergence"],
        "aliases": ["bubble", "mania", "speculative mania", "new era bubble", "valuation bubble"],
    },
    {
        "id": "panic_crash_forced_liquidation",
        "name": "Panic Crash / Forced Liquidation",
        "definition": "Fear, liquidity stress, margin calls, or forced selling pushes price below what fundamentals alone would justify.",
        "core_cause": "Leverage, VaR/risk controls, margin calls, and absent liquidity amplify fear.",
        "narrative_signature": ["catastrophic framing", "systemic comparisons", "bearish consensus extreme"],
        "fundamental_signature": ["fundamentals impaired less than price implies or policy backstop emerges"],
        "price_signature": ["indiscriminate selling", "volatility spike", "correlations rise", "gap-downs or liquidity air pockets"],
        "typical_resolution": ["seller exhaustion", "policy response", "value buyers absorb supply"],
        "false_positive_checks": ["genuine fundamental impairment may not be panic mispricing"],
        "underlying_gap_types": ["negative_narrative_fundamental_divergence", "price_fundamental_divergence"],
        "aliases": ["panic", "crash", "forced liquidation", "capitulation", "liquidation cascade"],
    },
    {
        "id": "post_earnings_announcement_drift",
        "name": "Post-Earnings Announcement Drift",
        "definition": "Market underreacts to earnings or guidance information, causing price to continue drifting in the direction of the surprise.",
        "core_cause": "Anchoring, limited attention, slow analyst revisions, and institutional inertia delay full repricing.",
        "narrative_signature": ["old company narrative updates slowly", "analyst revisions trail the surprise"],
        "fundamental_signature": ["earnings, guidance, margin, or revenue surprise appears sustainable"],
        "price_signature": ["initial reaction incomplete", "post-event trend persists", "follow-through after consolidation"],
        "typical_resolution": ["market digests results through revisions and portfolio adjustments over weeks"],
        "false_positive_checks": ["one-day earnings reaction alone is not PEAD without follow-through or underreaction evidence"],
        "underlying_gap_types": ["price_fundamental_divergence"],
        "aliases": ["pead", "earnings drift", "post earnings drift", "earnings underreaction"],
    },
    {
        "id": "momentum_trend_persistence",
        "name": "Momentum / Trend Persistence",
        "definition": "Narrative, fundamentals, and price reinforce each other, allowing a trend to persist longer than expected.",
        "core_cause": "Underreaction, herding, career risk, and slow diffusion of improving information reinforce winners.",
        "narrative_signature": ["narrative strengthens with price", "winners receive validation and upgrades"],
        "fundamental_signature": ["earnings, liquidity, or macro backdrop confirms the direction"],
        "price_signature": ["price leadership continues", "pullbacks are bought", "higher-timeframe trend intact"],
        "typical_resolution": ["trend exhausts when fundamentals weaken, crowding rises, or macro regime changes"],
        "false_positive_checks": ["do not call momentum an inefficiency if fully euphoric without continued confirmation"],
        "underlying_gap_types": ["unclear"],
        "aliases": ["momentum persistence", "trend persistence", "price momentum", "momentum regime"],
    },
    {
        "id": "value_mean_reversion",
        "name": "Value / Mean Reversion",
        "definition": "Price becomes overly depressed relative to normalized fundamentals, creating potential mean reversion if fundamentals stabilize.",
        "core_cause": "Excess pessimism, neglect, forced de-risking, or extrapolated bad news depresses valuation.",
        "narrative_signature": ["negative narrative", "low expectations", "less-bad news begins to matter"],
        "fundamental_signature": ["fundamentals stabilize or improve", "valuation discount to normalized anchors"],
        "price_signature": ["price lags fundamentals", "positive reaction to less-bad news", "mean reversion setup"],
        "typical_resolution": ["catalyst or improving data makes normalized value visible"],
        "false_positive_checks": ["cheap assets with deteriorating fundamentals can be value traps"],
        "underlying_gap_types": ["negative_narrative_fundamental_divergence", "price_fundamental_divergence"],
        "aliases": ["value", "mean reversion", "deep value", "value dislocation", "valuation reset"],
    },
    {
        "id": "volatility_risk_premium",
        "name": "Volatility Risk Premium",
        "definition": "Implied or expected risk becomes too high or too low relative to realized risk and event distribution.",
        "core_cause": "Fear, complacency, hedging demand, and event uncertainty distort volatility pricing.",
        "narrative_signature": ["fear or complacency in risk language", "event risk over- or under-emphasized"],
        "fundamental_signature": ["event distribution or realized risk differs from priced risk"],
        "price_signature": ["options or volatility pricing dislocated", "event premium fades or expands"],
        "typical_resolution": ["event passes, realized volatility confirms or refutes priced risk"],
        "false_positive_checks": ["do not classify if no volatility data or event-risk evidence is supplied"],
        "underlying_gap_types": ["price_narrative_divergence"],
        "aliases": ["vol risk premium", "volatility premium", "implied volatility dislocation", "event vol premium"],
    },
    {
        "id": "liquidity_crisis",
        "name": "Liquidity Crisis",
        "definition": "Liquidity constraints, funding stress, or market plumbing issues distort prices beyond fundamental value.",
        "core_cause": "Funding stress, market-maker withdrawal, collateral pressure, and balance-sheet limits impair price discovery.",
        "narrative_signature": ["liquidity or funding fear dominates", "market plumbing stress becomes central story"],
        "fundamental_signature": ["fundamental value not enough to explain price pressure"],
        "price_signature": ["forced selling", "widening spreads", "Treasury/dollar/liquidity stress", "market depth deterioration"],
        "typical_resolution": ["liquidity backstop, funding relief, or seller exhaustion restores price discovery"],
        "false_positive_checks": ["ordinary risk-off without liquidity stress is not a liquidity crisis"],
        "underlying_gap_types": ["price_fundamental_divergence", "cross_asset_divergence"],
        "aliases": ["funding stress", "liquidity stress", "market plumbing", "liquidity dislocation"],
    },
    {
        "id": "crowded_trade_positioning_extreme",
        "name": "Crowded Trade / Positioning Extreme",
        "definition": "A popular trade becomes vulnerable because expectations or positioning are one-sided; even good news may be sold if the bar is too high.",
        "core_cause": "Consensus positioning, benchmark pressure, and high expectations leave little marginal buyer/seller support.",
        "narrative_signature": ["consensus bullish or bearish story", "expectations high", "leadership narrative narrows"],
        "fundamental_signature": ["fundamentals may still be good but bar is elevated"],
        "price_signature": ["good news sold or bad news bought", "reversal despite supportive news", "leadership narrows"],
        "typical_resolution": ["positioning resets through sideways churn, reversal, or expectation reset"],
        "false_positive_checks": ["crowded does not mean wrong if fundamentals and price continue confirming"],
        "underlying_gap_types": ["positive_narrative_fundamental_divergence", "price_narrative_divergence"],
        "aliases": ["crowded trade", "crowded trade exhaustion", "expectation reset", "good news sold", "bad news bought", "positioning extreme"],
    },
    {
        "id": "information_cascade",
        "name": "Information Cascade",
        "definition": "Market participants adopt a belief because others appear to believe it, amplifying a narrative without independent evidence.",
        "core_cause": "Herding, reputational incentives, and social proof override independent evidence gathering.",
        "narrative_signature": ["same story echoed repeatedly", "thin original evidence base", "dissent ignored"],
        "fundamental_signature": ["independent hard evidence is sparse or ambiguous"],
        "price_signature": ["price validates the story reflexively", "moves extend despite limited new data"],
        "typical_resolution": ["new evidence, failed catalyst, or narrative fatigue breaks the cascade"],
        "false_positive_checks": ["widely shared views based on strong evidence are not cascades"],
        "underlying_gap_types": ["price_narrative_divergence"],
        "aliases": ["cascade", "herding cascade", "narrative cascade", "social proof trade"],
    },
    {
        "id": "regime_shift",
        "name": "Regime Shift",
        "definition": "A fundamental change in macro, policy, liquidity, earnings, or market structure causes old relationships or narratives to become obsolete.",
        "core_cause": "Policy, liquidity, inflation, credit, earnings, or market-structure change invalidates the prior playbook.",
        "narrative_signature": ["old playbook stops working", "narrative lags data or policy change"],
        "fundamental_signature": ["macro, policy, liquidity, earnings, or credit data shifts materially"],
        "price_signature": ["cross-asset relationships change", "prior winners and losers rotate"],
        "typical_resolution": ["market reprices to the new regime as evidence accumulates"],
        "false_positive_checks": ["one noisy data point is not a regime shift"],
        "underlying_gap_types": ["cross_asset_divergence", "price_fundamental_divergence"],
        "aliases": ["regime change", "macro regime shift", "policy regime shift", "rotation regime"],
    },
    {
        "id": "event_driven_mispricing",
        "name": "Event-Driven Mispricing",
        "definition": "A discrete event is overinterpreted, underinterpreted, or misunderstood by the market.",
        "core_cause": "Complex or bounded events create simplified narratives and temporary supply-demand distortions.",
        "narrative_signature": ["event framed simplistically", "market over- or under-interprets event implications"],
        "fundamental_signature": ["event has identifiable earnings, policy, litigation, M&A, geopolitical, or supply implications"],
        "price_signature": ["price move appears too large or small relative to event implications", "falsifier tied to event resolution"],
        "typical_resolution": ["deal, ruling, lock-up, policy action, earnings follow-up, or other event endpoint resolves uncertainty"],
        "false_positive_checks": ["do not classify without a clearly identifiable event"],
        "underlying_gap_types": ["price_narrative_divergence", "price_fundamental_divergence"],
        "aliases": ["event mispricing", "event-driven", "event overreaction", "event underreaction"],
    },
    {
        "id": "credit_equity_divergence",
        "name": "Credit / Equity Divergence",
        "definition": "Credit and equity markets send conflicting signals about risk, growth, or liquidity.",
        "core_cause": "Credit markets and equity markets process liquidity, default, and growth risks at different speeds.",
        "narrative_signature": ["equity story differs from credit-risk story", "credit specialists or equity investors disagree"],
        "fundamental_signature": ["credit quality, spreads, duration, or liquidity data conflicts with equity framing"],
        "price_signature": ["equities rally while credit weakens", "credit improves while equities stay pessimistic", "HYG/LQD/spreads disagree with SPY/QQQ"],
        "typical_resolution": ["equities catch down/up to credit signal or credit spreads converge to equity view"],
        "false_positive_checks": ["ETF noise or duration effects can produce false signals; confirm with spreads if available"],
        "underlying_gap_types": ["cross_asset_divergence"],
        "aliases": ["credit equity divergence", "credit/equity divergence", "credit-equity divergence", "credit leads equity", "spread equity divergence"],
    },
    {
        "id": "small_cap_neglect",
        "name": "Small-Cap / Neglect Premium",
        "definition": "Small or less-covered assets remain underpriced because attention, liquidity, or coverage is low despite improving fundamentals.",
        "core_cause": "Coverage gaps, institutional constraints, liquidity limits, and weak media attention delay discovery.",
        "narrative_signature": ["limited media coverage", "weak institutional attention", "absence of consensus narrative"],
        "fundamental_signature": ["fundamentals stabilize or improve", "quality/cash flow better than attention implies"],
        "price_signature": ["price lags larger peers", "thin episodic volume", "discovery catalyst possible"],
        "typical_resolution": ["coverage, institutional ownership, liquidity, catalyst, or acquisition closes neglect gap"],
        "false_positive_checks": ["small-cap underperformance may reflect real quality or liquidity risk, not neglect"],
        "underlying_gap_types": ["negative_narrative_fundamental_divergence"],
        "aliases": ["small cap neglect", "small-cap neglect", "neglect premium", "coverage gap", "attention neglect"],
    },
]


def _slug(value: str) -> str:
    value = value.lower().strip()
    value = value.replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return re.sub(r"_+", "_", value).strip("_")


def _alias_index() -> Dict[str, Dict[str, Any]]:
    idx: Dict[str, Dict[str, Any]] = {}
    for item in INEFFICIENCY_TAXONOMY:
        keys = [item["id"], item["name"], *item.get("aliases", [])]
        for key in keys:
            if key:
                idx[_slug(str(key))] = item
    return idx


def get_inefficiency_taxonomy_ids() -> List[str]:
    return [item["id"] for item in INEFFICIENCY_TAXONOMY]


def get_inefficiency_taxonomy_for_prompt() -> List[Dict[str, Any]]:
    prompt_fields = (
        "id",
        "name",
        "definition",
        "narrative_signature",
        "fundamental_signature",
        "price_signature",
        "typical_resolution",
        "false_positive_checks",
        "aliases",
    )
    return [{k: item[k] for k in prompt_fields if k in item} for item in INEFFICIENCY_TAXONOMY]


def normalize_archetype_id(value: Optional[str]) -> Optional[str]:
    normalized = normalize_archetype(value)
    return normalized["id"] if normalized else None


def normalize_archetype(value: Optional[str]) -> Optional[Dict[str, str]]:
    if not value:
        return None
    item = _alias_index().get(_slug(value))
    if not item:
        return None
    return {"id": item["id"], "name": item["name"]}
