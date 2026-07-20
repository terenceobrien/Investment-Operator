"""Pure-code financial-health screen over a FundamentalDataBundle."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from src.agent_system.data.types import FundamentalDataBundle
from src.agent_system.schemas.common import (
    AnalysisConviction,
    ConvictionRating,
    DerivedEvidence,
)
from src.agent_system.schemas.fundamental import (
    BusinessQuality,
    Crowdedness,
    Cyclicality,
    DifferMagnitude,
    EstimateRevisionTrend,
    EstimatesAndExpectations,
    Financials,
    FundamentalAnalysis,
    KeyMetric,
    Positioning,
)
from src.agent_system.schemas.fundamental_screen import (
    Archetype,
    FundamentalScreen,
    ScreenVerdict,
)
from src.agent_system.schemas.thematic import Candidate

logger = logging.getLogger("agent_system.rules.fundamental_screen")


@lru_cache(maxsize=1)
def load_screen_thresholds() -> dict:
    config_path = (
        Path(__file__).resolve().parents[1]
        / "config"
        / "screen_thresholds.yaml"
    )
    with config_path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError("screen_thresholds.yaml must contain a mapping")
    return data


def _safe_ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def _gt(value: float | None, threshold: float) -> bool | None:
    if value is None:
        return None
    return value > threshold


def _lt(value: float | None, threshold: float) -> bool | None:
    if value is None:
        return None
    return value < threshold


def _fmt_money(value: float | None) -> str:
    if value is None:
        return "n/a"
    abs_value = abs(value)
    if abs_value >= 1_000_000_000:
        return f"${value / 1_000_000_000:.1f}B"
    if abs_value >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    return f"${value:,.0f}"


def _leverage_measure_phrase(leverage_measure_used: str | None) -> str:
    if leverage_measure_used == "operating_income_proxy":
        return "EBITDA proxy (D&A unavailable)"
    return "EBITDA"


def _format_pct(value: float) -> str:
    return f"{value:.0%}"


_SCREEN_KEY_METRICS: tuple[tuple[str, str, str, float], ...] = (
    ("revenue_ttm", "revenue TTM", "$mm", 1 / 1_000_000),
    ("revenue_3yr_cagr", "revenue growth (3yr CAGR)", "%", 100),
    ("revenue_yoy_growth", "revenue growth (YoY)", "%", 100),
    ("ebitda_ttm", "EBITDA TTM", "$mm", 1 / 1_000_000),
    ("operating_income_ttm", "operating income TTM", "$mm", 1 / 1_000_000),
    ("operating_margin", "operating margin", "%", 100),
    ("net_margin", "net margin", "%", 100),
    ("free_cash_flow_ttm", "free cash flow TTM", "$mm", 1 / 1_000_000),
    ("operating_cash_flow_ttm", "operating cash flow TTM", "$mm", 1 / 1_000_000),
    ("total_debt", "total debt", "$mm", 1 / 1_000_000),
    ("debt_to_ebitda", "debt / EBITDA", "x", 1),
    ("debt_to_assets", "debt / assets", "ratio", 1),
    ("cash_and_equivalents", "cash and equivalents", "$mm", 1 / 1_000_000),
    ("stockholders_equity", "stockholders' equity", "$mm", 1 / 1_000_000),
    ("upside_to_target", "upside to target", "%", 100),
    ("buy_ratio", "buy rating ratio", "ratio", 1),
)


def _screen_key_metrics(screen: FundamentalScreen) -> list[KeyMetric]:
    key_metrics: list[KeyMetric] = []
    for source_key, label, unit, scale in _SCREEN_KEY_METRICS:
        raw_value = screen.metrics_used.get(source_key)
        if raw_value is None or isinstance(raw_value, bool):
            continue
        if not isinstance(raw_value, (int, float)):
            continue

        key_metrics.append(
            KeyMetric(
                metric=label,
                value=float(raw_value) * scale,
                unit=unit,
                vs_history="not assessed by deterministic screen",
                vs_peers="not assessed by deterministic screen",
                source=DerivedEvidence(
                    claim=f"{label} came from {screen.ticker} screen metrics.",
                    supports=True,
                    computation="FundamentalScreen.metrics_used",
                    upstream_claims=[f"{source_key}={raw_value}"],
                ),
            )
        )
    return key_metrics


def _select_growth_signal(
    *,
    revenue_3yr_cagr: float | None,
    revenue_yoy_growth: float | None,
    implausible_ceiling: float,
) -> tuple[float | None, str | None, bool, str | None]:
    available = [
        ("revenue_3yr_cagr", revenue_3yr_cagr),
        ("revenue_yoy_growth", revenue_yoy_growth),
    ]
    anomalous = [
        (name, value)
        for name, value in available
        if value is not None and value > implausible_ceiling
    ]
    growth_rate = None
    growth_measure_used = None
    for name, value in available:
        if value is not None and value <= implausible_ceiling:
            growth_rate = value
            growth_measure_used = name
            break

    data_quality_detail = None
    if anomalous:
        anomaly_text = ", ".join(
            f"{name}={_format_pct(value)}" for name, value in anomalous
        )
        data_quality_detail = (
            f"Revenue growth {anomaly_text} exceeds "
            f"{_format_pct(implausible_ceiling)} plausibility ceiling; treated "
            "as data artifact and disregarded for archetype classification. "
            "Verify underlying revenue history (possible divestiture, "
            "restatement, or base-year effect)."
        )
    return growth_rate, growth_measure_used, bool(anomalous), data_quality_detail


def _crowding(bundle: FundamentalDataBundle, thresholds: dict) -> tuple[bool, str | None, dict]:
    counts = [
        bundle.analyst_count_buy,
        bundle.analyst_count_hold,
        bundle.analyst_count_sell,
    ]
    buy_ratio = None
    upside_to_target = None
    if all(count is not None for count in counts):
        total = sum(int(count or 0) for count in counts)
        if total > 0:
            buy_ratio = int(bundle.analyst_count_buy or 0) / total
    if (
        bundle.mean_price_target is not None
        and bundle.current_price is not None
        and bundle.current_price > 0
    ):
        upside_to_target = (
            bundle.mean_price_target - bundle.current_price
        ) / bundle.current_price

    crowding_thresholds = thresholds["crowding"]
    flag = (
        buy_ratio is not None
        and upside_to_target is not None
        and buy_ratio >= float(crowding_thresholds["min_buy_ratio"])
        and upside_to_target <= float(crowding_thresholds["max_upside_to_target"])
    )
    detail = None
    if flag:
        detail = (
            f"Crowding flag: {buy_ratio:.0%} buy ratings and "
            f"{upside_to_target:.0%} upside to target."
        )
    return flag, detail, {
        "buy_ratio": buy_ratio,
        "upside_to_target": upside_to_target,
    }


def _base_screen(
    *,
    bundle: FundamentalDataBundle,
    archetype: Archetype,
    verdict: ScreenVerdict,
    reason: str,
    metrics_used: dict,
    crowding_flag: bool,
    crowding_detail: str | None,
    data_quality_flag: bool = False,
    data_quality_detail: str | None = None,
    data_was_sufficient: bool = True,
    notes: str | None = None,
) -> FundamentalScreen:
    return FundamentalScreen(
        created_at=datetime.now(timezone.utc),
        ticker=bundle.ticker,
        archetype=archetype,
        verdict=verdict,
        reason=reason,
        crowding_flag=crowding_flag,
        crowding_detail=crowding_detail,
        data_quality_flag=data_quality_flag,
        data_quality_detail=data_quality_detail,
        metrics_used=metrics_used,
        data_was_sufficient=data_was_sufficient,
        notes=notes,
    )


def screen_candidate(
    bundle: FundamentalDataBundle,
    thresholds: dict | None = None,
) -> FundamentalScreen:
    """
    Classify financial archetype and apply deterministic health checks.

    The screen never raises: sparse data and internal errors become PASS for
    manual review rather than silent elimination.
    """

    try:
        config = thresholds or load_screen_thresholds()
        crowding_flag, crowding_detail, crowding_metrics = _crowding(bundle, config)
        metrics_used: dict[str, Any] = {
            "is_etf": bundle.is_etf,
            **crowding_metrics,
        }

        if bundle.is_etf:
            return _base_screen(
                bundle=bundle,
                archetype=Archetype.ESTABLISHED,
                verdict=ScreenVerdict.PASS,
                reason="ETF - financial-health screen not applicable",
                metrics_used=metrics_used,
                crowding_flag=crowding_flag,
                crowding_detail=crowding_detail,
            )

        facts = bundle.company_facts
        if (
            facts is None
            or facts.revenue_ttm is None
            or (facts.net_income_ttm is None and facts.free_cash_flow_ttm is None)
        ):
            return _base_screen(
                bundle=bundle,
                archetype=Archetype.ESTABLISHED,
                verdict=ScreenVerdict.PASS,
                reason=(
                    "Insufficient financial data to screen; passing for manual review"
                ),
                metrics_used=metrics_used,
                crowding_flag=crowding_flag,
                crowding_detail=crowding_detail,
                data_was_sufficient=False,
            )

        notes: list[str] = []
        leverage_denominator = None
        leverage_measure_used = None
        if facts.ebitda_ttm is not None and facts.ebitda_ttm > 0:
            leverage_denominator = facts.ebitda_ttm
            leverage_measure_used = "ebitda"
        elif (
            facts.ebitda_ttm is None
            and facts.operating_income_ttm is not None
            and facts.operating_income_ttm > 0
        ):
            leverage_denominator = facts.operating_income_ttm
            leverage_measure_used = "operating_income_proxy"
            notes.append("EBITDA proxy used because D&A unavailable")
        else:
            notes.append("leverage check inconclusive")
        debt_to_ebitda = _safe_ratio(facts.total_debt, leverage_denominator)
        debt_to_assets = _safe_ratio(facts.total_debt, facts.total_assets)
        quarterly_burn = (
            -facts.operating_cash_flow_ttm / 4
            if facts.operating_cash_flow_ttm is not None
            and facts.operating_cash_flow_ttm < 0
            else None
        )
        cash_runway_quarters = (
            _safe_ratio(facts.cash_and_equivalents, quarterly_burn)
            if quarterly_burn is not None
            else None
        )
        distressed = config["distressed"]
        growth = config["growth"]
        established = config["established"]

        (
            growth_rate,
            growth_measure_used,
            data_quality_flag,
            data_quality_detail,
        ) = _select_growth_signal(
            revenue_3yr_cagr=facts.revenue_3yr_cagr,
            revenue_yoy_growth=facts.revenue_yoy_growth,
            implausible_ceiling=float(growth["implausible_growth_ceiling"]),
        )
        if data_quality_detail:
            notes.append(data_quality_detail)

        metrics_used.update(
            {
                "revenue_ttm": facts.revenue_ttm,
                "net_income_ttm": facts.net_income_ttm,
                "free_cash_flow_ttm": facts.free_cash_flow_ttm,
                "operating_cash_flow_ttm": facts.operating_cash_flow_ttm,
                "operating_income_ttm": facts.operating_income_ttm,
                "cash_and_equivalents": facts.cash_and_equivalents,
                "total_debt": facts.total_debt,
                "total_assets": facts.total_assets,
                "stockholders_equity": facts.stockholders_equity,
                "depreciation_amortization_ttm": (
                    facts.depreciation_amortization_ttm
                ),
                "ebitda_ttm": facts.ebitda_ttm,
                "leverage_measure_used": leverage_measure_used,
                "ebitda_proxy_operating_income_ttm": facts.operating_income_ttm,
                "debt_to_ebitda": debt_to_ebitda,
                "debt_to_assets": debt_to_assets,
                "revenue_growth": growth_rate,
                "growth_measure_used": growth_measure_used,
                "revenue_yoy_growth": facts.revenue_yoy_growth,
                "revenue_3yr_cagr": facts.revenue_3yr_cagr,
                "quarterly_burn": quarterly_burn,
                "cash_runway_quarters": cash_runway_quarters,
                "gross_margin": facts.gross_margin,
                "operating_margin": facts.operating_margin,
                "net_margin": facts.net_margin,
            }
        )

        if facts.stockholders_equity is not None and facts.stockholders_equity < 0:
            return _base_screen(
                bundle=bundle,
                archetype=Archetype.DISTRESSED,
                verdict=ScreenVerdict.ELIMINATE,
                reason="Distressed: negative stockholders' equity - ELIMINATE",
                metrics_used=metrics_used,
                crowding_flag=crowding_flag,
                crowding_detail=crowding_detail,
                data_quality_flag=data_quality_flag,
                data_quality_detail=data_quality_detail,
            )
        if (
            debt_to_ebitda is not None
            and leverage_denominator is not None
            and leverage_denominator > 0
            and debt_to_ebitda > float(distressed["debt_to_ebitda_ceiling"])
        ):
            leverage_phrase = _leverage_measure_phrase(leverage_measure_used)
            return _base_screen(
                bundle=bundle,
                archetype=Archetype.DISTRESSED,
                verdict=ScreenVerdict.ELIMINATE,
                reason=(
                    f"Distressed: debt/{leverage_phrase} {debt_to_ebitda:.1f}x "
                    f"above {float(distressed['debt_to_ebitda_ceiling']):.1f}x - ELIMINATE"
                ),
                metrics_used=metrics_used,
                crowding_flag=crowding_flag,
                crowding_detail=crowding_detail,
                data_quality_flag=data_quality_flag,
                data_quality_detail=data_quality_detail,
                notes="; ".join(notes) or None,
            )
        if (
            facts.operating_cash_flow_ttm is not None
            and facts.operating_cash_flow_ttm < 0
            and facts.cash_and_equivalents is not None
            and facts.total_debt is not None
            and facts.cash_and_equivalents < facts.total_debt
        ):
            return _base_screen(
                bundle=bundle,
                archetype=Archetype.DISTRESSED,
                verdict=ScreenVerdict.ELIMINATE,
                reason=(
                    "Distressed: negative operating cash flow and cash below "
                    "total debt - ELIMINATE"
                ),
                metrics_used=metrics_used,
                crowding_flag=crowding_flag,
                crowding_detail=crowding_detail,
                data_quality_flag=data_quality_flag,
                data_quality_detail=data_quality_detail,
            )

        is_unprofitable = (
            (facts.net_income_ttm is not None and facts.net_income_ttm < 0)
            or (facts.free_cash_flow_ttm is not None and facts.free_cash_flow_ttm < 0)
        )
        is_growth = (
            is_unprofitable
            and growth_rate is not None
            and growth_rate > float(growth["min_revenue_growth"])
            and debt_to_assets is not None
            and debt_to_assets < float(growth["max_debt_to_assets"])
        )

        if is_growth:
            if facts.operating_cash_flow_ttm is not None and facts.operating_cash_flow_ttm >= 0:
                runway_pass = True
            elif cash_runway_quarters is None:
                runway_pass = None
                notes.append("cash runway inconclusive")
            else:
                runway_pass = cash_runway_quarters > float(growth["min_cash_runway_quarters"])

            debt_pass = _lt(debt_to_assets, float(growth["max_debt_to_assets"]))
            growth_pass = _gt(growth_rate, float(growth["min_revenue_growth"]))
            if runway_pass is False:
                return _base_screen(
                    bundle=bundle,
                    archetype=Archetype.GROWTH,
                    verdict=ScreenVerdict.ELIMINATE,
                    reason=(
                        f"Growth: cash runway {cash_runway_quarters:.1f}q below "
                        f"{float(growth['min_cash_runway_quarters']):.1f}q minimum - ELIMINATE"
                    ),
                    metrics_used=metrics_used,
                    crowding_flag=crowding_flag,
                    crowding_detail=crowding_detail,
                    data_quality_flag=data_quality_flag,
                    data_quality_detail=data_quality_detail,
                )
            if debt_pass is False:
                return _base_screen(
                    bundle=bundle,
                    archetype=Archetype.GROWTH,
                    verdict=ScreenVerdict.ELIMINATE,
                    reason=(
                        f"Growth: debt/assets {debt_to_assets:.0%} above "
                        f"{float(growth['max_debt_to_assets']):.0%} maximum - ELIMINATE"
                    ),
                    metrics_used=metrics_used,
                    crowding_flag=crowding_flag,
                    crowding_detail=crowding_detail,
                    data_quality_flag=data_quality_flag,
                    data_quality_detail=data_quality_detail,
                )
            if growth_pass is False:
                return _base_screen(
                    bundle=bundle,
                    archetype=Archetype.GROWTH,
                    verdict=ScreenVerdict.ELIMINATE,
                    reason=(
                        f"Growth: revenue growth {growth_rate:.0%} below "
                        f"{float(growth['min_revenue_growth']):.0%} minimum - ELIMINATE"
                    ),
                    metrics_used=metrics_used,
                    crowding_flag=crowding_flag,
                    crowding_detail=crowding_detail,
                    data_quality_flag=data_quality_flag,
                    data_quality_detail=data_quality_detail,
                )
            reason = (
                f"Growth: revenue growth {growth_rate:.0%}, debt/assets "
                f"{debt_to_assets:.0%}, "
            )
            if runway_pass is True and cash_runway_quarters is not None:
                reason += f"cash runway {cash_runway_quarters:.1f}q - PASS"
            elif facts.operating_cash_flow_ttm is not None and facts.operating_cash_flow_ttm >= 0:
                reason += "operating cash flow positive - PASS"
            else:
                reason += "cash runway inconclusive - PASS for manual review"
            return _base_screen(
                bundle=bundle,
                archetype=Archetype.GROWTH,
                verdict=ScreenVerdict.PASS,
                reason=reason,
                metrics_used=metrics_used,
                crowding_flag=crowding_flag,
                crowding_detail=crowding_detail,
                data_quality_flag=data_quality_flag,
                data_quality_detail=data_quality_detail,
                notes="; ".join(notes) or None,
            )

        if facts.free_cash_flow_ttm is not None or facts.operating_cash_flow_ttm is not None:
            cash_generation_positive = (
                (facts.free_cash_flow_ttm is not None and facts.free_cash_flow_ttm > 0)
                or (
                    facts.operating_cash_flow_ttm is not None
                    and facts.operating_cash_flow_ttm > 0
                )
            )
            if not cash_generation_positive:
                return _base_screen(
                    bundle=bundle,
                    archetype=Archetype.ESTABLISHED,
                    verdict=ScreenVerdict.ELIMINATE,
                    reason="Established: no positive FCF or operating cash flow - ELIMINATE",
                    metrics_used=metrics_used,
                    crowding_flag=crowding_flag,
                    crowding_detail=crowding_detail,
                    data_quality_flag=data_quality_flag,
                    data_quality_detail=data_quality_detail,
                )
        else:
            notes.append("cash generation inconclusive")

        if (
            debt_to_ebitda is not None
            and leverage_denominator is not None
            and leverage_denominator > 0
            and debt_to_ebitda >= float(established["max_debt_to_ebitda"])
        ):
            leverage_phrase = _leverage_measure_phrase(leverage_measure_used)
            return _base_screen(
                bundle=bundle,
                archetype=Archetype.ESTABLISHED,
                verdict=ScreenVerdict.ELIMINATE,
                reason=(
                    f"Established: debt/{leverage_phrase} {debt_to_ebitda:.1f}x "
                    f"above {float(established['max_debt_to_ebitda']):.1f}x - ELIMINATE"
                ),
                metrics_used=metrics_used,
                crowding_flag=crowding_flag,
                crowding_detail=crowding_detail,
                data_quality_flag=data_quality_flag,
                data_quality_detail=data_quality_detail,
                notes="; ".join(notes) or None,
            )

        net_income_positive = (
            facts.net_income_ttm is not None and facts.net_income_ttm > 0
        )
        growth_enough = (
            growth_rate is not None
            and growth_rate > float(established["min_growth_if_unprofitable"])
        )
        if facts.net_income_ttm is not None and growth_rate is not None:
            if not (net_income_positive or growth_enough):
                return _base_screen(
                    bundle=bundle,
                    archetype=Archetype.ESTABLISHED,
                    verdict=ScreenVerdict.ELIMINATE,
                    reason=(
                        f"Established: unprofitable with revenue growth "
                        f"{growth_rate:.0%} below "
                        f"{float(established['min_growth_if_unprofitable']):.0%} - ELIMINATE"
                    ),
                    metrics_used=metrics_used,
                    crowding_flag=crowding_flag,
                    crowding_detail=crowding_detail,
                    data_quality_flag=data_quality_flag,
                    data_quality_detail=data_quality_detail,
                )
        elif facts.net_income_ttm is None or growth_rate is None:
            notes.append("profitability/growth check inconclusive")

        leverage_text = (
            f", leverage {debt_to_ebitda:.1f}x "
            f"{_leverage_measure_phrase(leverage_measure_used)}"
            if debt_to_ebitda is not None
            and leverage_denominator
            and leverage_denominator > 0
            else ""
        )
        reason = (
            f"Established: FCF {_fmt_money(facts.free_cash_flow_ttm)}"
            f"{leverage_text} - PASS"
        )
        return _base_screen(
            bundle=bundle,
            archetype=Archetype.ESTABLISHED,
            verdict=ScreenVerdict.PASS,
            reason=reason,
            metrics_used=metrics_used,
            crowding_flag=crowding_flag,
            crowding_detail=crowding_detail,
            data_quality_flag=data_quality_flag,
            data_quality_detail=data_quality_detail,
            notes="; ".join(notes) or None,
        )
    except Exception as exc:
        logger.warning("fundamental screen failed for %s: %s", bundle.ticker, exc)
        return FundamentalScreen(
            created_at=datetime.now(timezone.utc),
            ticker=bundle.ticker,
            archetype=Archetype.ESTABLISHED,
            verdict=ScreenVerdict.PASS,
            reason="Financial screen error; passing for manual review",
            metrics_used={"error": str(exc)},
            data_was_sufficient=False,
            notes=str(exc),
        )


def _bridge_screen_to_fundamental_conviction(
    screen: FundamentalScreen,
) -> ConvictionRating:
    """
    Map a passing FundamentalScreen to a conviction rating.

    The screen is a financial-health filter, not a fundamental analyst.
    It can honestly say "no disqualifier found" (MODERATE) or "passed but
    with concerns" (WEAK). It cannot honestly produce STRONG or EXCEPTIONAL
    - those require deeper analysis that the screen doesn't perform.
    """
    if screen.verdict != ScreenVerdict.PASS:
        return ConvictionRating.WEAK

    if screen.crowding_flag:
        return ConvictionRating.WEAK
    if screen.data_quality_flag:
        return ConvictionRating.WEAK
    if not screen.data_was_sufficient:
        return ConvictionRating.WEAK

    return ConvictionRating.MODERATE


def _bridge_screen_to_fundamental_justification(
    candidate: Candidate,
    screen: FundamentalScreen,
) -> str:
    rating = _bridge_screen_to_fundamental_conviction(screen)
    if rating == ConvictionRating.MODERATE:
        return (
            f"{candidate.ticker} screen passed cleanly with no crowding, "
            "data-quality, or sufficiency concerns. Bounded at MODERATE "
            "because the screen is a financial-health filter, not a full "
            f"fundamental analysis. Screen reason: {screen.reason}"
        )

    concerns = []
    if screen.verdict != ScreenVerdict.PASS:
        concerns.append("screen did not pass")
    if screen.crowding_flag:
        concerns.append("candidate carries crowding flag")
    if screen.data_quality_flag:
        concerns.append("data_quality flag set")
    if not screen.data_was_sufficient:
        concerns.append("data was insufficient for full evaluation")
    concern_text = "; ".join(concerns) or "screen bridge concern present"
    return (
        f"{candidate.ticker} screen passed but {concern_text}. Bounded at "
        "WEAK because the screen is a financial-health filter, not a full "
        f"fundamental analysis. Screen reason: {screen.reason}"
    )


def screen_to_minimal_fundamental_analysis(
    candidate: Candidate,
    screen: FundamentalScreen,
) -> FundamentalAnalysis:
    """
    Convert a PASS screen into a minimal FundamentalAnalysis-compatible object.

    This is a bridge for the pre-LLM fundamental phase: the screen is only a
    financial-health gate, so the analysis is intentionally explicit that it
    has not validated the full single-name thesis.
    """

    if screen.verdict != ScreenVerdict.PASS:
        raise ValueError("screen_to_minimal_fundamental_analysis requires a PASS screen")

    screen_evidence = DerivedEvidence(
        claim=f"{candidate.ticker} passed the deterministic financial-health screen.",
        supports=True,
        computation="screen_candidate over FundamentalDataBundle metrics",
        upstream_claims=[f"fundamental screen reason: {screen.reason}"],
    )
    bear_evidence = DerivedEvidence(
        claim=(
            "The financial-health screen is not a full fundamental analysis and "
            "may miss company-specific operating risks."
        ),
        supports=True,
        computation="phase 2.3.1 scope limitation",
        upstream_claims=["fundamental screen performs threshold checks only"],
    )

    balance_quality = 6.0
    cash_quality = 6.0
    if screen.archetype == Archetype.GROWTH:
        balance_quality = 6.5
        cash_quality = 5.8
    elif screen.archetype == Archetype.ESTABLISHED:
        balance_quality = 7.0
        cash_quality = 7.0

    if screen.data_was_sufficient is False:
        balance_quality = 5.0
        cash_quality = 5.0

    crowding = Crowdedness.CROWDED if screen.crowding_flag else Crowdedness.NORMAL
    conviction_rating = _bridge_screen_to_fundamental_conviction(screen)

    where_we_differ = (
        "The deterministic financial-health screen found no balance-sheet, "
        "cash-flow, or growth-archetype disqualifier, so the thematic variant "
        "view remains eligible for deeper fundamental validation."
    )
    if not screen.data_was_sufficient:
        where_we_differ = (
            "Financial data was too sparse for elimination; the candidate passes "
            "only for manual review and requires deeper fundamental validation."
        )

    return FundamentalAnalysis(
        ticker=candidate.ticker,
        thesis_statement=(
            f"{candidate.ticker} remains eligible for downstream research after "
            "passing the deterministic financial-health screen."
        ),
        business_quality=BusinessQuality(
            summary=(
                f"{candidate.name or candidate.ticker} is not qualitatively "
                "underwritten in this phase; the screen only checks financial "
                "health against archetype-aware thresholds."
            ),
            moat_assessment=(
                "Moat not assessed by the deterministic financial-health screen."
            ),
            moat_evidence=[],
            cyclicality=Cyclicality.HYBRID,
        ),
        financials=Financials(
            key_metrics=_screen_key_metrics(screen),
            balance_sheet_quality=balance_quality,
            cash_generation_quality=cash_quality,
            accounting_red_flags=[],
        ),
        estimates_and_expectations=EstimatesAndExpectations(
            consensus_summary=(
                "Consensus expectations were not independently assessed by the "
                "financial-health screen."
            ),
            revision_trend=EstimateRevisionTrend.STABLE,
            where_we_differ=where_we_differ,
            differ_magnitude=DifferMagnitude.MODEST,
            differ_evidence=[screen_evidence],
        ),
        positioning=Positioning(
            institutional_positioning=(
                screen.crowding_detail
                or "Crowding was not flagged by the available analyst-count data."
            ),
            crowdedness_assessment=crowding,
        ),
        steelman_bear_case=(
            "The bear case is that this deterministic screen is only a shallow "
            "financial-health gate; it may miss estimate risk, industry-specific "
            "deterioration, competitive pressure, accounting issues, or catalyst "
            "timing that a full fundamental agent must still analyze."
        ),
        bear_case_evidence=[bear_evidence],
        what_bear_case_misses=(
            "The screen does not claim the bear case is wrong; it only shows "
            "there is no deterministic financial-health reason to eliminate "
            "the candidate before deeper research."
        ),
        conviction=AnalysisConviction(
            rating=conviction_rating,
            justification=_bridge_screen_to_fundamental_justification(
                candidate,
                screen,
            ),
            primary_uncertainty=(
                "A full fundamental agent has not yet validated consensus, "
                "estimates, catalysts, or company-specific operating risks."
            ),
        ),
    )
