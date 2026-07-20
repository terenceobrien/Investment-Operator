from __future__ import annotations

from datetime import date
from typing import Any

from src.agent_system.schemas.deep_fundamental import (
    BasicScreenResult,
    CompanyProfile,
    CompanySegment,
    CompetitivePositionAnalysis,
    FalsificationFramework,
    FundamentalContextPack,
    FinancialTrendAnalysis,
    MacroContextPack,
    MarketExpectationAnalysis,
    PeerCompany,
    PressureInflectionAnalysis,
    PressureType,
    RegimeSensitivityAnalysis,
    ScenarioImpact,
    ThemeContextPack,
    VariantView,
    VariantViewDirection,
)


# ---------------------------------------------------------------------
# v1 static/semi-static company knowledge
# ---------------------------------------------------------------------
# This is intentionally simple. It lets the agent produce non-TODO output
# before you wire filings, financial APIs, earnings transcripts, peer data,
# and LLM synthesis.
#
# Later, replace this with:
# - SEC filing ingestion
# - company profile cache
# - yfinance / FMP / Polygon / Intrinio data
# - transcript/news retrieval
# - peer mapping database
# ---------------------------------------------------------------------

COMPANY_KNOWLEDGE: dict[str, dict[str, Any]] = {
    "MU": {
        "company_name": "Micron Technology",
        "sector": "Information Technology",
        "industry": "Semiconductors / Memory",
        "business_description": (
            "Micron is a memory and storage semiconductor company with exposure "
            "to DRAM, NAND, data center, PC, mobile, automotive, industrial, and AI-related demand."
        ),
        "business_model": (
            "Cyclical semiconductor manufacturer whose revenue and margins are driven by memory pricing, "
            "bit demand, supply discipline, technology transitions, utilization, and mix toward higher-value products."
        ),
        "segments": [
            {
                "name": "Compute and Networking",
                "description": "Memory products for data center, client, graphics, and networking applications.",
                "key_drivers": ["AI server demand", "HBM adoption", "DRAM pricing", "cloud capex"],
            },
            {
                "name": "Mobile",
                "description": "Memory and storage products for smartphones and mobile devices.",
                "key_drivers": ["smartphone unit demand", "content per device", "NAND pricing"],
            },
            {
                "name": "Embedded",
                "description": "Memory and storage for automotive, industrial, and consumer applications.",
                "key_drivers": ["auto electronics content", "industrial demand", "inventory cycles"],
            },
            {
                "name": "Storage",
                "description": "NAND and SSD products.",
                "key_drivers": ["enterprise SSD demand", "NAND pricing", "data center storage capex"],
            },
        ],
        "revenue_model": [
            "DRAM bit shipments",
            "NAND bit shipments",
            "average selling prices",
            "product mix",
            "AI/HBM demand",
        ],
        "cost_drivers": [
            "wafer costs",
            "fab utilization",
            "technology node transitions",
            "capex intensity",
            "depreciation",
        ],
        "margin_drivers": [
            "DRAM pricing",
            "NAND pricing",
            "HBM mix",
            "supply discipline",
            "utilization rates",
        ],
        "peer_group": [
            {"ticker": "SSNLF", "name": "Samsung Electronics", "relevance": "Large global memory competitor"},
            {"ticker": "000660.KS", "name": "SK Hynix", "relevance": "Major DRAM/HBM competitor"},
            {"ticker": "WDC", "name": "Western Digital", "relevance": "NAND/storage peer"},
        ],
        "thematic_exposures": [
            "AI infrastructure",
            "HBM",
            "memory pricing cycle",
            "data center capex",
            "semiconductor supply discipline",
        ],
        "macro_sensitivities": [
            "AI capex",
            "global growth",
            "inventory cycle",
            "rates/multiple compression",
            "China demand",
        ],
        "major_risks": [
            "memory pricing downturn",
            "supply additions",
            "AI capex slowdown",
            "China/export restrictions",
            "high capex and cyclicality",
        ],
    },
    "ETN": {
        "company_name": "Eaton",
        "sector": "Industrials",
        "industry": "Electrical Equipment / Power Management",
        "business_description": (
            "Eaton is a power management company exposed to electrical equipment, data centers, "
            "grid modernization, commercial buildings, aerospace, vehicles, and industrial end markets."
        ),
        "business_model": (
            "Diversified industrial with meaningful electrical equipment exposure. Revenue is driven by "
            "electrification, data center power demand, backlog conversion, pricing, and industrial/aerospace cycles."
        ),
        "segments": [
            {
                "name": "Electrical Americas",
                "description": "Electrical products and systems for commercial, industrial, utility, and data center customers.",
                "key_drivers": ["data center demand", "grid spending", "commercial construction", "pricing"],
            },
            {
                "name": "Electrical Global",
                "description": "Electrical equipment and systems outside the Americas.",
                "key_drivers": ["global electrification", "industrial demand", "energy transition"],
            },
            {
                "name": "Aerospace",
                "description": "Hydraulic, fuel, motion control, and electrical systems for aerospace markets.",
                "key_drivers": ["aircraft production", "aftermarket demand", "defense spending"],
            },
        ],
        "revenue_model": [
            "equipment sales",
            "systems integration",
            "aftermarket/services",
            "project backlog conversion",
        ],
        "cost_drivers": [
            "raw materials",
            "labor",
            "supply chain",
            "manufacturing capacity",
        ],
        "margin_drivers": [
            "pricing power",
            "volume leverage",
            "mix toward electrical/data center",
            "supply chain normalization",
        ],
        "peer_group": [
            {"ticker": "GEV", "name": "GE Vernova", "relevance": "Power/grid infrastructure peer"},
            {"ticker": "PWR", "name": "Quanta Services", "relevance": "Grid and electrical infrastructure peer"},
            {"ticker": "EMR", "name": "Emerson Electric", "relevance": "Industrial automation/electrical peer"},
            {"ticker": "ROK", "name": "Rockwell Automation", "relevance": "Industrial automation peer"},
        ],
        "thematic_exposures": [
            "AI data center power demand",
            "electrification",
            "grid modernization",
            "industrial infrastructure",
            "reshoring",
        ],
        "macro_sensitivities": [
            "rates",
            "industrial capex",
            "data center capex",
            "commodity input costs",
            "construction cycle",
        ],
        "major_risks": [
            "valuation compression",
            "data center capex slowdown",
            "industrial slowdown",
            "capacity constraints",
            "execution risk",
        ],
    },
}


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        clean = value.strip() if isinstance(value, str) else str(value).strip()
        if not clean:
            continue
        key = clean.lower().rstrip(".!?:;").strip()
        if key in seen:
            continue
        deduped.append(clean)
        seen.add(key)
    return deduped


def build_company_profile(ticker: str) -> CompanyProfile:
    data = COMPANY_KNOWLEDGE.get(ticker.upper(), {})

    segments = [
        CompanySegment(
            name=segment.get("name", "Unknown segment"),
            description=segment.get("description"),
            revenue_share_estimate=segment.get("revenue_share_estimate"),
            profit_share_estimate=segment.get("profit_share_estimate"),
            key_drivers=segment.get("key_drivers", []),
        )
        for segment in data.get("segments", [])
    ]

    peers = [
        PeerCompany(
            ticker=peer.get("ticker"),
            name=peer.get("name", "Unknown peer"),
            relevance=peer.get("relevance"),
        )
        for peer in data.get("peer_group", [])
    ]

    return CompanyProfile(
        ticker=ticker.upper(),
        company_name=data.get("company_name"),
        sector=data.get("sector"),
        industry=data.get("industry"),
        profile_source="manual_seed" if data else "llm_generated_unverified",
        profile_confidence=(
            "high" if data else "low"
        ),
        profile_as_of_date=date.today(),
        profile_source_notes=(
            ["Company profile from internal static seed."]
            if data
            else ["Static company profile is unavailable for this ticker."]
        ),
        profile_data_gaps=(
            []
            if data
            else [
                "Business model",
                "Segments",
                "Peers",
                "Macro sensitivities",
                "Theme exposures",
            ]
        ),
        business_description=data.get(
            "business_description",
            "Company profile not yet available in static knowledge base.",
        ),
        business_model=data.get("business_model"),
        segments=segments,
        revenue_model=data.get("revenue_model", []),
        cost_drivers=data.get("cost_drivers", []),
        margin_drivers=data.get("margin_drivers", []),
        key_customers=data.get("key_customers", []),
        key_suppliers=data.get("key_suppliers", []),
        peer_group=peers,
        thematic_exposures=data.get("thematic_exposures", []),
        macro_sensitivities=data.get("macro_sensitivities", []),
        major_risks=data.get("major_risks", []),
    )


def build_financial_trend_analysis(
    ticker: str,
    basic_screen_result: BasicScreenResult | None = None,
    fundamental_context: FundamentalContextPack | None = None,
) -> FinancialTrendAnalysis:
    quarterly_pack = (
        fundamental_context.quarterly_financial_trend
        if fundamental_context
        else None
    )
    if quarterly_pack is not None and quarterly_pack.latest_quarter is not None:
        improving_indicators: list[str] = []
        deteriorating_indicators: list[str] = []
        red_flags: list[str] = []

        direction_labels = [
            ("Revenue growth", quarterly_pack.revenue_trend_8q),
            ("Gross margin", quarterly_pack.gross_margin_trend_8q),
            ("Operating margin", quarterly_pack.operating_margin_trend_8q),
            ("Free cash flow", quarterly_pack.fcf_trend_8q),
            ("Leverage", quarterly_pack.leverage_trend_8q),
        ]
        for label, direction in direction_labels:
            if direction == "improving":
                improving_indicators.append(f"{label} is improving on trailing 8Q data.")
            elif direction == "deteriorating":
                deteriorating_indicators.append(f"{label} is deteriorating on trailing 8Q data.")

        flag_map = {
            "latest_quarter_revenue_accelerating_yoy": "Latest quarter revenue is accelerating year over year.",
            "latest_quarter_gross_margin_above_ltm": "Latest quarter gross margin is above LTM.",
            "latest_quarter_operating_margin_above_ltm": "Latest quarter operating margin is above LTM.",
            "latest_quarter_fcf_margin_above_ltm": "Latest quarter FCF margin is above LTM.",
            "latest_quarter_revenue_run_rate_above_ltm": "Latest quarter revenue run-rate is above LTM.",
            "gross_margin_expanding_sequentially": "Gross margin is expanding sequentially.",
            "operating_margin_expanding_sequentially": "Operating margin is expanding sequentially.",
            "leverage_improving": "Leverage is improving.",
        }
        for flag, label in flag_map.items():
            if flag in quarterly_pack.inflection_flags:
                improving_indicators.append(label)

        if "fcf_conversion_lagging_ebitda" in quarterly_pack.inflection_flags:
            deteriorating_indicators.append(
                "FCF conversion is lagging EBITDA, likely due to capex or working capital."
            )
        if "capex_intensity_elevated" in quarterly_pack.inflection_flags:
            red_flags.append("Capex intensity is elevated versus revenue.")
        if quarterly_pack.financial_context_stale:
            red_flags.append("Financial data is stale for current underwriting.")
        red_flags.extend(quarterly_pack.staleness_warnings)

        latest = quarterly_pack.latest_quarter
        if latest.operating_margin is not None and latest.operating_margin < 0:
            red_flags.append("Latest quarter operating margin is negative.")
        if latest.free_cash_flow is not None and latest.free_cash_flow < 0:
            red_flags.append("Latest quarter free cash flow is negative.")
        if latest.net_debt_to_ebitda is not None and latest.net_debt_to_ebitda > 4:
            red_flags.append("Latest quarter net debt to EBITDA is elevated above 4.0x.")

        screen_result_context = (
            "Financial trend analysis generated from quarterly-first "
            "fundamental context pack."
        )
        if quarterly_pack.latest_period_end_date is not None:
            screen_result_context += (
                f" Latest financial period ended "
                f"{quarterly_pack.latest_period_end_date.isoformat()}."
            )
        if basic_screen_result is not None:
            screen_result_context += (
                " The basic financial screen passed."
                if basic_screen_result.passed
                else " The basic financial screen failed."
            )

        return FinancialTrendAnalysis(
            revenue_growth_trend=quarterly_pack.revenue_trend_8q,
            gross_margin_trend=quarterly_pack.gross_margin_trend_8q,
            operating_margin_trend=quarterly_pack.operating_margin_trend_8q,
            fcf_trend=quarterly_pack.fcf_trend_8q,
            leverage_trend=quarterly_pack.leverage_trend_8q,
            improving_indicators=_dedupe_preserve_order(improving_indicators),
            deteriorating_indicators=_dedupe_preserve_order(deteriorating_indicators),
            red_flags=_dedupe_preserve_order(red_flags),
            screen_result_context=screen_result_context,
            why_screen_may_be_wrong=(
                "For cyclical or inflection names, latest-quarter and LTM "
                "data should dominate annual fiscal-year data. The basic "
                "screen should be interpreted in context of current trend "
                "direction, cyclicality, and whether weak metrics are "
                "improving or deteriorating."
            ),
        )

    trend_snapshot = (
        fundamental_context.financial_trend if fundamental_context else None
    )
    if trend_snapshot is not None and trend_snapshot.latest is not None:
        latest = trend_snapshot.latest
        improving_indicators: list[str] = []
        deteriorating_indicators: list[str] = []
        red_flags: list[str] = []

        direction_labels = [
            ("Revenue growth", trend_snapshot.revenue_growth_direction),
            ("Operating margin", trend_snapshot.margin_direction),
            ("Free cash flow", trend_snapshot.fcf_direction),
            ("Leverage", trend_snapshot.leverage_direction),
        ]
        for label, direction in direction_labels:
            if direction == "improving":
                improving_indicators.append(f"{label} is improving.")
            elif direction == "deteriorating":
                deteriorating_indicators.append(f"{label} is deteriorating.")

        if (
            latest.operating_margin is not None
            and latest.operating_margin < 0
        ):
            red_flags.append("Latest operating margin is negative.")
        if (
            latest.free_cash_flow is not None
            and latest.free_cash_flow < 0
        ):
            red_flags.append("Latest free cash flow is negative.")
        if (
            latest.net_debt_to_ebitda is not None
            and latest.net_debt_to_ebitda > 4
        ):
            red_flags.append("Net debt to EBITDA is elevated above 4.0x.")

        screen_result_context = (
            "Financial trend analysis generated from fundamental context pack."
        )
        if basic_screen_result is not None:
            screen_result_context += (
                " The basic financial screen passed."
                if basic_screen_result.passed
                else " The basic financial screen failed."
            )

        return FinancialTrendAnalysis(
            revenue_growth_trend=trend_snapshot.revenue_growth_direction,
            operating_margin_trend=trend_snapshot.margin_direction,
            fcf_trend=trend_snapshot.fcf_direction,
            leverage_trend=trend_snapshot.leverage_direction,
            improving_indicators=improving_indicators,
            deteriorating_indicators=deteriorating_indicators,
            red_flags=red_flags,
            screen_result_context=screen_result_context,
            why_screen_may_be_wrong=(
                "The basic screen should be interpreted in context of trend direction, "
                "cyclicality, and whether weak metrics are improving or deteriorating."
            ),
        )

    if basic_screen_result is None:
        return FinancialTrendAnalysis(
            screen_result_context=(
                "No basic fundamental screen result was provided. "
                "Deep analysis should be treated as incomplete until financial metrics are attached."
            ),
            why_screen_may_be_wrong=(
                "Cannot evaluate whether the basic screen is misleading because no screen result was provided."
            ),
        )

    failed = basic_screen_result.failed_metrics
    passed = basic_screen_result.passed_metrics

    red_flags = list(failed)
    improving_indicators = list(passed)

    if basic_screen_result.passed:
        context = (
            "The basic financial screen passed. Deep underwriting should still test whether the pass is misleading "
            "because of valuation, cyclicality, customer concentration, margin quality, or regime-specific risk."
        )
        why_wrong = (
            "A passing screen may still be too lenient if current financial strength reflects peak-cycle earnings, "
            "temporary pricing power, or a fully priced narrative."
        )
    else:
        context = (
            "The basic financial screen failed. Deep underwriting should determine whether the failure reflects "
            "structural weakness or temporary/cyclical pressure."
        )
        why_wrong = (
            "A failed screen may be too harsh if weak margins, cash flow, or growth are temporarily depressed "
            "and there is credible evidence of an earnings inflection."
        )

    return FinancialTrendAnalysis(
        improving_indicators=improving_indicators,
        deteriorating_indicators=failed,
        red_flags=red_flags,
        screen_result_context=context,
        why_screen_may_be_wrong=why_wrong,
    )


def build_pressure_inflection_analysis(
    ticker: str,
    company_profile: CompanyProfile,
    financial_trend_analysis: FinancialTrendAnalysis,
    fundamental_context: FundamentalContextPack | None = None,
    macro_context: dict[str, Any] | None = None,
    theme_context: dict[str, Any] | None = None,
) -> PressureInflectionAnalysis:
    exposures = set(company_profile.thematic_exposures + company_profile.macro_sensitivities)
    margin_drivers = set(company_profile.margin_drivers)

    recent_pressure_points: list[str] = []
    recent_strength_points: list[str] = []
    likely_causes: list[str] = []
    abatement_evidence: list[str] = []
    inflection_catalysts: list[str] = []
    key_timing_questions: list[str] = []

    pressure_type = PressureType.UNKNOWN
    cyclical_vs_structural = "Insufficient data to determine whether recent pressure is cyclical or structural."

    if ticker.upper() == "MU":
        recent_pressure_points.extend(
            [
                "Memory remains structurally cyclical, and reported financials can deteriorate sharply during downcycles.",
                "High capex intensity and supply additions can pressure free cash flow and margins.",
                "The stock is sensitive to AI capex expectations and memory pricing assumptions.",
            ]
        )
        recent_strength_points.extend(
            [
                "AI server demand and HBM mix can materially improve revenue quality and margins.",
                "Supply discipline across memory producers can support pricing recovery.",
            ]
        )
        likely_causes.extend(
            [
                "DRAM/NAND pricing cycle",
                "AI/HBM demand mix",
                "inventory normalization",
                "capacity discipline",
            ]
        )
        abatement_evidence.extend(
            [
                "Improving DRAM pricing would support gross margin recovery.",
                "Rising HBM mix would suggest the company is shifting toward higher-value demand.",
                "Inventory normalization would reduce pressure from oversupply conditions.",
            ]
        )
        inflection_catalysts.extend(
            [
                "HBM revenue acceleration",
                "positive memory pricing revisions",
                "upward earnings estimate revisions",
                "continued hyperscaler AI capex strength",
            ]
        )
        key_timing_questions.extend(
            [
                "Are DRAM and NAND prices continuing to improve?",
                "Is HBM demand translating into sustainable margin expansion?",
                "Are hyperscaler AI capex plans still rising or starting to flatten?",
            ]
        )
        pressure_type = PressureType.CYCLICAL
        cyclical_vs_structural = (
            "For MU, weak financial periods are often cyclical rather than permanently structural. "
            "The key underwriting question is whether AI/HBM demand and memory supply discipline are strong enough "
            "to turn a cyclical recovery into a higher-quality earnings inflection."
        )

    elif ticker.upper() == "ETN":
        recent_pressure_points.extend(
            [
                "Industrial and electrical equipment names can be vulnerable to valuation compression if rates rise.",
                "Data center optimism may already be partially priced into the stock.",
                "Supply chain, labor, and input costs can pressure margins if pricing does not offset inflation.",
            ]
        )
        recent_strength_points.extend(
            [
                "Data center power demand, electrification, and grid modernization provide strong secular demand support.",
                "Backlog conversion and pricing can support revenue and margin resilience.",
            ]
        )
        likely_causes.extend(
            [
                "AI data center power demand",
                "electrification capex",
                "industrial infrastructure spending",
                "pricing and backlog conversion",
            ]
        )
        abatement_evidence.extend(
            [
                "Sustained backlog strength would support future revenue visibility.",
                "Stable or expanding margins would indicate pricing power is offsetting input cost pressure.",
            ]
        )
        inflection_catalysts.extend(
            [
                "continued data center order growth",
                "margin expansion from electrical mix",
                "grid/electrification spending acceleration",
            ]
        )
        key_timing_questions.extend(
            [
                "Is data center demand still accelerating or merely remaining strong?",
                "Are margins expanding despite input and labor cost pressure?",
                "Is valuation still reasonable versus forward earnings revisions?",
            ]
        )
        pressure_type = PressureType.MACRO_DRIVEN
        cyclical_vs_structural = (
            "For ETN, the fundamental setup appears more secular than purely cyclical, but the stock can still be "
            "pressured by rates, valuation, and any slowdown in data center or industrial capex expectations."
        )

    else:
        if "oil" in " ".join(exposures).lower() or "commodity" in " ".join(exposures).lower():
            likely_causes.append("commodity/input cost sensitivity")
            pressure_type = PressureType.MACRO_DRIVEN

        if margin_drivers:
            key_timing_questions.append(
                f"Are key margin drivers improving: {', '.join(sorted(margin_drivers))}?"
            )

    quarterly_pack = (
        fundamental_context.quarterly_financial_trend
        if fundamental_context
        else None
    )
    price_snapshot = fundamental_context.price_snapshot if fundamental_context else None
    if quarterly_pack is not None and quarterly_pack.inflection_flags:
        flags = set(quarterly_pack.inflection_flags)
        if "latest_quarter_revenue_accelerating_yoy" in flags:
            recent_strength_points.append("Latest quarter revenue is accelerating year over year.")
            inflection_catalysts.append("latest-quarter revenue acceleration")
        if "latest_quarter_revenue_run_rate_above_ltm" in flags:
            recent_strength_points.append("Latest quarter revenue run-rate is above LTM.")
            inflection_catalysts.append("latest-quarter revenue run-rate above LTM")
        if "latest_quarter_gross_margin_above_ltm" in flags:
            abatement_evidence.append("Latest quarter gross margin is above LTM.")
            inflection_catalysts.append("latest-quarter gross margin above LTM")
        if "latest_quarter_operating_margin_above_ltm" in flags:
            abatement_evidence.append("Latest quarter operating margin is above LTM.")
            inflection_catalysts.append("latest-quarter operating margin above LTM")
        if "gross_margin_expanding_sequentially" in flags:
            abatement_evidence.append("Gross margin is expanding sequentially.")
        if "operating_margin_expanding_sequentially" in flags:
            abatement_evidence.append("Operating margin is expanding sequentially.")
        if "latest_quarter_fcf_margin_above_ltm" in flags:
            abatement_evidence.append("Latest quarter FCF margin is above LTM.")
        if "leverage_improving" in flags:
            recent_strength_points.append("Leverage is improving in the latest quarterly data.")
        if "fcf_conversion_lagging_ebitda" in flags:
            recent_pressure_points.append(
                "FCF conversion is lagging EBITDA, so accounting inflection needs cash-flow confirmation."
            )
        if "capex_intensity_elevated" in flags:
            recent_pressure_points.append(
                "Capex intensity is elevated, which can mute free-cash-flow conversion."
            )
        if "financial_data_stale" in flags:
            recent_pressure_points.append(
                "Financial data is stale; current price may reflect newer information."
            )
        if (
            price_snapshot is not None
            and (
                (price_snapshot.return_1m is not None and abs(price_snapshot.return_1m) > 0.20)
                or (price_snapshot.return_3m is not None and abs(price_snapshot.return_3m) > 0.40)
            )
        ):
            recent_pressure_points.append(
                "Large recent price move raises expectations/peak-cycle risk relative to latest financials."
            )
        if pressure_type == PressureType.UNKNOWN:
            pressure_type = PressureType.CYCLICAL
        cyclical_vs_structural = (
            "Quarterly-first context shows active inflection signals. "
            "Underwriting should separate latest-quarter/LTM acceleration from "
            "annual through-cycle averages and test whether the improvement is "
            "durable or already priced."
        )

    return PressureInflectionAnalysis(
        recent_pressure_points=_dedupe_preserve_order(recent_pressure_points),
        recent_strength_points=_dedupe_preserve_order(recent_strength_points),
        likely_causes=_dedupe_preserve_order(likely_causes),
        pressure_type=pressure_type,
        cyclical_vs_structural_assessment=cyclical_vs_structural,
        abatement_evidence=_dedupe_preserve_order(abatement_evidence),
        inflection_catalysts=_dedupe_preserve_order(inflection_catalysts),
        margin_recovery_potential=(
            "Potentially meaningful if the identified pressure points are temporary and pricing/mix improves."
            if abatement_evidence
            else None
        ),
        demand_recovery_potential=(
            "Dependent on whether the relevant end-market drivers continue improving."
            if inflection_catalysts
            else None
        ),
        earnings_inflection_potential=(
            "Requires confirmation through margins, revenue acceleration, and estimate revisions."
            if inflection_catalysts
            else None
        ),
        key_timing_questions=key_timing_questions,
    )


def build_competitive_position_analysis(
    ticker: str,
    company_profile: CompanyProfile,
) -> CompetitivePositionAnalysis:
    moat_sources: list[str] = []
    advantages: list[str] = []
    threats: list[str] = []

    if ticker.upper() == "MU":
        moat_sources = [
            "advanced manufacturing capability",
            "scale in memory production",
            "technology execution",
            "customer qualification for high-performance memory",
        ]
        advantages = [
            "direct exposure to HBM and AI memory demand",
            "operating leverage to memory pricing recovery",
        ]
        threats = [
            "Samsung and SK Hynix competition",
            "memory supply additions",
            "pricing cyclicality",
        ]
        summary = (
            "MU has strong cyclical leverage and strategic exposure to AI memory, but competitive position depends "
            "heavily on technology execution, HBM share, and industry supply discipline."
        )

    elif ticker.upper() == "ETN":
        moat_sources = [
            "scale in electrical equipment",
            "installed base",
            "distribution and customer relationships",
            "mission-critical power management expertise",
        ]
        advantages = [
            "direct exposure to data center power demand",
            "strong positioning in electrification and grid modernization",
            "pricing power in critical infrastructure categories",
        ]
        threats = [
            "valuation risk",
            "competition from other electrical and grid equipment providers",
            "industrial capex slowdown",
        ]
        summary = (
            "ETN has strong competitive positioning as an electrical infrastructure compounder with data center "
            "and electrification exposure, but valuation and capex-cycle risk need to be underwritten carefully."
        )

    else:
        summary = (
            "Competitive position requires further peer and filing analysis. Static knowledge base does not yet "
            "contain enough company-specific information."
        )

    return CompetitivePositionAnalysis(
        peer_group=company_profile.peer_group,
        moat_sources=moat_sources,
        competitive_advantages=advantages,
        competitive_threats=threats,
        competitive_position_summary=summary,
    )


def _dedupe_scenario_impacts(
    impacts: list[ScenarioImpact],
) -> list[ScenarioImpact]:
    seen: set[tuple[str, str]] = set()
    deduped: list[ScenarioImpact] = []

    for impact in impacts:
        key = (impact.scenario_name, impact.impact)
        if key not in seen:
            deduped.append(impact)
            seen.add(key)

    return deduped


def _coerce_macro_context(
    macro_context: MacroContextPack | dict[str, Any] | None,
) -> MacroContextPack | None:
    if macro_context is None:
        return None
    if isinstance(macro_context, MacroContextPack):
        return macro_context
    if isinstance(macro_context, dict):
        try:
            return MacroContextPack.model_validate(macro_context)
        except Exception:
            return None
    return None


def _coerce_theme_context(
    theme_context: ThemeContextPack | dict[str, Any] | None,
) -> ThemeContextPack | None:
    if theme_context is None:
        return None
    if isinstance(theme_context, ThemeContextPack):
        return theme_context
    if isinstance(theme_context, dict):
        try:
            return ThemeContextPack.model_validate(theme_context)
        except Exception:
            return None
    return None


def build_regime_sensitivity_analysis(
    ticker: str,
    company_profile: CompanyProfile,
    macro_context: MacroContextPack | dict[str, Any] | None = None,
    theme_context: ThemeContextPack | dict[str, Any] | None = None,
) -> RegimeSensitivityAnalysis | None:
    if macro_context is None and theme_context is None and not company_profile.macro_sensitivities:
        return None

    scenario_impacts: list[ScenarioImpact] = []
    macro_pack = _coerce_macro_context(macro_context)
    theme_pack = _coerce_theme_context(theme_context)

    for sensitivity in company_profile.macro_sensitivities:
        lower = sensitivity.lower()

        if "ai" in lower or "capex" in lower:
            scenario_impacts.append(
                ScenarioImpact(
                    scenario_name="AI capex acceleration",
                    impact="positive",
                    rationale="Company appears positively exposed to sustained or accelerating AI/data center capex.",
                    sensitivity_level="high",
                )
            )
            scenario_impacts.append(
                ScenarioImpact(
                    scenario_name="AI capex rollover",
                    impact="negative",
                    rationale="A slowdown in AI/data center capex would likely pressure growth expectations and valuation.",
                    sensitivity_level="high",
                )
            )

        if "rate" in lower:
            scenario_impacts.append(
                ScenarioImpact(
                    scenario_name="Rates remain elevated",
                    impact="negative",
                    rationale="Higher rates can pressure valuation multiples and financing-sensitive demand.",
                    sensitivity_level="medium",
                )
            )

        if "global growth" in lower or "industrial" in lower:
            scenario_impacts.append(
                ScenarioImpact(
                    scenario_name="Global growth slows",
                    impact="negative",
                    rationale="Slower macro growth would likely pressure cyclical demand.",
                    sensitivity_level="medium",
                )
            )

    if theme_pack is not None:
        if theme_pack.positive_drivers:
            scenario_impacts.append(
                ScenarioImpact(
                    scenario_name="Macro-supported mapped themes",
                    impact="positive",
                    rationale=theme_pack.positive_drivers[0],
                    sensitivity_level="medium",
                )
            )
        if theme_pack.negative_drivers:
            scenario_impacts.append(
                ScenarioImpact(
                    scenario_name="Macro-penalized mapped themes",
                    impact="negative",
                    rationale=theme_pack.negative_drivers[0],
                    sensitivity_level="medium",
                )
            )
        if theme_pack.mixed_drivers:
            scenario_impacts.append(
                ScenarioImpact(
                    scenario_name="Mixed mapped-theme macro signals",
                    impact="mixed",
                    rationale=theme_pack.mixed_drivers[0],
                    sensitivity_level="medium",
                )
            )

        aggregate = theme_pack.aggregate_theme_support_score
        if aggregate is not None and aggregate > 0.25:
            scenario_impacts.append(
                ScenarioImpact(
                    scenario_name="Aggregate mapped-theme support",
                    impact="positive",
                    rationale=(
                        f"Mapped macro themes have positive aggregate support score "
                        f"of {aggregate:.2f}."
                    ),
                    sensitivity_level="medium",
                )
            )
        elif aggregate is not None and aggregate < -0.25:
            scenario_impacts.append(
                ScenarioImpact(
                    scenario_name="Aggregate mapped-theme pressure",
                    impact="negative",
                    rationale=(
                        f"Mapped macro themes have negative aggregate support score "
                        f"of {aggregate:.2f}."
                    ),
                    sensitivity_level="medium",
                )
            )

    if macro_pack is not None:
        macro_signal_text = " ".join(
            " ".join(
                str(value or "")
                for value in (
                    signal.label,
                    signal.signal,
                    signal.level_status,
                    signal.trend_status,
                    signal.notes,
                )
            )
            for signal in macro_pack.top_macro_signals
        ).lower()

        if (
            any("rate" in item.lower() for item in company_profile.macro_sensitivities)
            and any(term in macro_signal_text for term in ("fed", "rate", "hike", "hold", "elevated"))
        ):
            scenario_impacts.append(
                ScenarioImpact(
                    scenario_name="Rates remain elevated",
                    impact="negative",
                    rationale=(
                        "Macro forecast signals mention rate or Fed pressure, which can weigh on "
                        "valuation-sensitive companies."
                    ),
                    sensitivity_level="medium",
                )
            )

        if (
            any("ai" in item.lower() or "capex" in item.lower() for item in company_profile.macro_sensitivities + company_profile.thematic_exposures)
            and theme_pack is not None
            and any(
                term in " ".join(theme_pack.positive_drivers).lower()
                for term in ("ai", "data center", "capex")
            )
        ):
            scenario_impacts.append(
                ScenarioImpact(
                    scenario_name="AI/data-center macro support",
                    impact="positive",
                    rationale="Mapped theme drivers include positive AI/data-center macro support.",
                    sensitivity_level="high",
                )
            )

        if (
            any(
                term in item.lower()
                for item in company_profile.macro_sensitivities
                for term in ("oil", "commodity", "inflation")
            )
            and any(term in macro_signal_text for term in ("oil", "commodity", "inflation"))
        ):
            scenario_impacts.append(
                ScenarioImpact(
                    scenario_name="Oil/inflation macro sensitivity",
                    impact="mixed",
                    rationale=(
                        "Macro forecast signals mention oil, commodities, or inflation; "
                        "ticker-level impact depends on whether this is revenue beta or input-cost pressure."
                    ),
                    sensitivity_level="medium",
                )
            )

    scenario_impacts = _dedupe_scenario_impacts(scenario_impacts)
    aggregate_theme_score = (
        theme_pack.aggregate_theme_support_score if theme_pack is not None else None
    )
    if aggregate_theme_score is not None and aggregate_theme_score > 0:
        upside_scenario = (
            "Macro forecast supports the company's mapped themes, improving the odds that "
            "top-down backdrop reinforces ticker-level execution."
        )
        downside_scenario = (
            "The main downside is that positive mapped-theme support fades or becomes crowded "
            "before ticker fundamentals confirm."
        )
    elif aggregate_theme_score is not None and aggregate_theme_score < 0:
        upside_scenario = (
            "Upside requires company-specific execution to overcome weak macro support for mapped themes."
        )
        downside_scenario = (
            "Macro forecast currently penalizes mapped themes, creating top-down pressure on growth "
            "expectations or valuation."
        )
    else:
        upside_scenario = "Macro/theme backdrop reinforces the company's highest-quality revenue and margin drivers."
        downside_scenario = "Macro/theme backdrop deteriorates in a way that pressures growth expectations, margins, or valuation."

    return RegimeSensitivityAnalysis(
        current_regime_fit=_summarize_regime_fit(company_profile, macro_context, theme_context),
        scenario_impacts=scenario_impacts,
        ai_capex_sensitivity=(
            "High" if any("AI" in item or "ai" in item for item in company_profile.macro_sensitivities + company_profile.thematic_exposures) else None
        ),
        rate_sensitivity=(
            "Medium to high" if any("rate" in item.lower() for item in company_profile.macro_sensitivities) else None
        ),
        upside_scenario=upside_scenario,
        downside_scenario=downside_scenario,
        regime_fit_summary=_build_regime_fit_summary(macro_pack, theme_pack),
    )


def _summarize_regime_fit(
    company_profile: CompanyProfile,
    macro_context: MacroContextPack | dict[str, Any] | None,
    theme_context: ThemeContextPack | dict[str, Any] | None,
) -> str:
    exposures = company_profile.thematic_exposures + company_profile.macro_sensitivities
    theme_pack = _coerce_theme_context(theme_context)

    if theme_pack is not None:
        selected = ", ".join(theme_pack.selected_theme_ids) or "none"
        score = theme_pack.aggregate_theme_support_score
        score_text = f"{score:.2f}" if score is not None else "n/a"
        return (
            "Company mapped to macro forecast themes "
            f"({selected}) with aggregate theme support score {score_text}. "
            f"Known exposures: {', '.join(exposures)}."
        )

    if macro_context:
        return (
            "Company has macro sensitivities that should be tested against provided macro context. "
            f"Known sensitivities: {', '.join(company_profile.macro_sensitivities)}."
        )

    return (
        "No explicit macro/theme context was provided. Regime fit is inferred from static company sensitivities: "
        f"{', '.join(exposures)}."
    )


def _build_regime_fit_summary(
    macro_context: MacroContextPack | None,
    theme_context: ThemeContextPack | None,
) -> str:
    parts = ["Regime sensitivity combines static exposure mapping with macro/theme context when provided."]
    if macro_context is not None:
        scenarios = [
            scenario.label or scenario.scenario_id
            for scenario in macro_context.top_scenarios[:3]
        ]
        signals = [
            signal.label or signal.input_id
            for signal in macro_context.top_macro_signals[:3]
        ]
        if scenarios:
            parts.append(f"Top scenarios: {', '.join(scenarios)}.")
        if signals:
            parts.append(f"Top macro signals: {', '.join(signals)}.")
    if theme_context is not None and theme_context.theme_fit_summary:
        parts.append(theme_context.theme_fit_summary)
    return " ".join(parts)


def build_market_expectation_analysis(
    ticker: str,
    company_profile: CompanyProfile,
    financial_trend_analysis: FinancialTrendAnalysis,
    pressure_inflection_analysis: PressureInflectionAnalysis,
) -> MarketExpectationAnalysis:
    if ticker.upper() == "MU":
        return MarketExpectationAnalysis(
            narrative_consensus=(
                "Market narrative likely centers on memory cycle recovery, HBM demand, AI infrastructure exposure, "
                "and the sustainability of pricing/margin improvement."
            ),
            implied_expectations=(
                "The stock likely embeds expectations for continued memory pricing recovery and AI/HBM demand strength."
            ),
            market_mispricing_hypothesis=(
                "Potential mispricing exists if the market underestimates the durability of HBM-driven mix improvement "
                "or over-penalizes MU for historical memory cyclicality."
            ),
            upside_already_priced=None,
            downside_already_priced=None,
            crowdedness_risk="AI semiconductor exposure can become crowded, increasing drawdown risk if capex expectations weaken.",
            expectation_summary=(
                "The key expectation question is whether MU is still being valued like a cyclical memory name "
                "or increasingly like a strategic AI infrastructure supplier."
            ),
        )

    if ticker.upper() == "ETN":
        return MarketExpectationAnalysis(
            narrative_consensus=(
                "Market narrative likely centers on data center power demand, electrification, grid modernization, "
                "and industrial infrastructure."
            ),
            implied_expectations=(
                "The stock may already price in a meaningful amount of secular data center and electrification upside."
            ),
            market_mispricing_hypothesis=(
                "Potential mispricing exists if the market underestimates the duration of electrical backlog growth "
                "or the margin uplift from mix shift, but valuation risk is material."
            ),
            upside_already_priced=None,
            downside_already_priced=None,
            crowdedness_risk="High-quality AI infrastructure beneficiaries can become consensus longs.",
            expectation_summary=(
                "The key expectation question is whether earnings revisions can continue to outrun valuation expectations."
            ),
        )

    return MarketExpectationAnalysis(
        narrative_consensus="Current market narrative requires news, price action, and estimate revision ingestion.",
        implied_expectations="Cannot infer implied expectations with high confidence in v1.",
        market_mispricing_hypothesis="No strong mispricing hypothesis generated yet.",
        expectation_summary="Market expectation analysis is incomplete until valuation and price data are wired.",
    )


def build_variant_view(
    ticker: str,
    company_profile: CompanyProfile,
    financial_trend_analysis: FinancialTrendAnalysis,
    pressure_inflection_analysis: PressureInflectionAnalysis,
    competitive_position_analysis: CompetitivePositionAnalysis,
    market_expectation_analysis: MarketExpectationAnalysis,
    user_supplied_thesis: str | None = None,
    macro_context: MacroContextPack | dict[str, Any] | None = None,
    theme_context: ThemeContextPack | dict[str, Any] | None = None,
) -> VariantView:
    evidence: list[str] = []
    why_market_may_be_wrong: list[str] = []
    confirming: list[str] = []
    risks: list[str] = []
    theme_pack = _coerce_theme_context(theme_context)

    if user_supplied_thesis:
        consensus = "Consensus view not independently established in v1."
        helix_view = f"User-supplied thesis to underwrite: {user_supplied_thesis}"
        strength = "medium"
        direction = VariantViewDirection.TWO_SIDED
    elif ticker.upper() == "MU":
        consensus = (
            "MU is viewed as a cyclical memory company with upside tied to memory pricing recovery and AI/HBM demand."
        )
        helix_view = (
            "The possible variant view is that AI/HBM mix improvement may make the current earnings cycle higher quality "
            "than a normal memory rebound, creating more durable margin and earnings upside than the market assumes."
        )
        evidence = pressure_inflection_analysis.abatement_evidence + pressure_inflection_analysis.inflection_catalysts
        why_market_may_be_wrong = [
            "The market may over-anchor to historical memory cyclicality.",
            "The market may underestimate the margin impact of HBM mix.",
            "The market may underprice supply discipline if producers remain rational.",
        ]
        confirming = [
            "HBM revenue growth continues to accelerate.",
            "DRAM pricing remains firm.",
            "Gross margin expands faster than expected.",
            "Earnings estimates continue revising upward.",
        ]
        risks = [
            "AI capex expectations weaken.",
            "Memory supply additions pressure pricing.",
            "HBM competition limits margin upside.",
            "The stock already prices in the recovery.",
        ]
        strength = "medium"
        direction = VariantViewDirection.BULLISH

    elif ticker.upper() == "ETN":
        consensus = (
            "ETN is viewed as a high-quality electrical infrastructure beneficiary of data center demand and electrification."
        )
        helix_view = (
            "The possible variant view is that electrical demand from data centers, grid modernization, and electrification "
            "can sustain above-trend growth and margin resilience for longer than traditional industrial-cycle models imply."
        )
        evidence = pressure_inflection_analysis.recent_strength_points + pressure_inflection_analysis.inflection_catalysts
        why_market_may_be_wrong = [
            "The market may underestimate the duration of data center electrical demand.",
            "The market may underappreciate backlog quality and pricing power.",
        ]
        confirming = [
            "Data center orders remain strong.",
            "Electrical margins continue expanding.",
            "Backlog conversion supports revenue visibility.",
            "Earnings revisions remain positive.",
        ]
        risks = [
            "Valuation already reflects much of the secular upside.",
            "Data center capex expectations slow.",
            "Rates rise and pressure industrial multiples.",
        ]
        strength = "medium"
        direction = VariantViewDirection.BULLISH

    else:
        consensus = "Consensus view not available in v1."
        helix_view = (
            "No strong variant view generated yet. Additional company, financial, peer, valuation, and news data required."
        )
        risks = ["Insufficient information to establish variant perception."]
        strength = "none"
        direction = VariantViewDirection.NONE

    if theme_pack is not None and theme_pack.selected_theme_ids:
        theme_list = ", ".join(theme_pack.selected_theme_ids[:4])
        theme_sentence = (
            f" Macro forecast mapping identifies {theme_list} as relevant themes; "
            "ticker-level underwriting should test whether the company is a clean expression of that support."
        )
        helix_view = f"{helix_view}{theme_sentence}" if helix_view else theme_sentence
        evidence.extend(theme_pack.positive_drivers[:4])
        risks.extend(theme_pack.negative_drivers[:4])
        if (
            theme_pack.aggregate_theme_support_score is not None
            and theme_pack.aggregate_theme_support_score < 0
        ):
            risks.append(
                f"Mapped macro themes have negative aggregate support "
                f"({theme_pack.aggregate_theme_support_score:.2f})."
            )

    return VariantView(
        consensus_view=consensus,
        helix_variant_view=helix_view,
        variant_view_direction=direction,
        evidence_supporting_variant_view=evidence,
        why_market_may_be_wrong=why_market_may_be_wrong,
        required_confirming_evidence=confirming,
        risks_to_variant_view=risks,
        variant_view_strength=strength,
    )


def build_falsification_framework(
    ticker: str,
    company_profile: CompanyProfile,
    pressure_inflection_analysis: PressureInflectionAnalysis,
    regime_sensitivity_analysis: RegimeSensitivityAnalysis | None,
    variant_view: VariantView,
) -> FalsificationFramework:
    fundamental: list[str] = []
    macro: list[str] = []
    valuation: list[str] = []
    timing: list[str] = []
    technical: list[str] = []
    triggers: list[str] = []
    metrics: list[str] = []

    if ticker.upper() == "MU":
        fundamental = [
            "Gross margin fails to expand despite claimed pricing/mix improvement.",
            "HBM growth fails to translate into earnings upside.",
            "Inventory or supply commentary points to renewed oversupply.",
        ]
        macro = [
            "Hyperscaler AI capex expectations roll over.",
            "Global semiconductor demand weakens materially.",
        ]
        valuation = [
            "Multiple expansion outpaces estimate revisions and eliminates upside asymmetry.",
        ]
        timing = [
            "Expected memory pricing recovery fails to appear within the target horizon.",
        ]
        technical = [
            "Stock materially underperforms semiconductor peers despite positive memory pricing data.",
        ]
        triggers = [
            "Negative earnings revision cycle resumes.",
            "Management guides to weaker pricing or weaker HBM demand.",
            "Semiconductor capex narrative deteriorates.",
        ]
        metrics = [
            "DRAM pricing",
            "NAND pricing",
            "HBM revenue/mix",
            "gross margin",
            "capex",
            "inventory",
            "earnings revisions",
        ]

    elif ticker.upper() == "ETN":
        fundamental = [
            "Electrical backlog growth slows materially.",
            "Margins stop expanding despite strong end-market demand.",
            "Pricing power weakens relative to input/labor costs.",
        ]
        macro = [
            "Data center capex expectations roll over.",
            "Rates rise enough to pressure industrial multiples.",
            "Industrial capex slows sharply.",
        ]
        valuation = [
            "Valuation expands without corresponding upward estimate revisions.",
        ]
        timing = [
            "Backlog conversion fails to support earnings growth over the target horizon.",
        ]
        technical = [
            "Stock underperforms industrial/electrical peers despite intact macro theme.",
        ]
        triggers = [
            "Order growth decelerates.",
            "Electrical margins disappoint.",
            "Data center commentary weakens.",
        ]
        metrics = [
            "orders",
            "backlog",
            "electrical segment margin",
            "data center demand commentary",
            "earnings revisions",
            "forward multiple",
        ]

    else:
        fundamental = [
            "Company fails to show evidence supporting the proposed variant view."
        ]
        triggers = [
            "Rerun deep fundamental analysis when financial, peer, valuation, and news data are available."
        ]
        metrics = [
            "revenue growth",
            "gross margin",
            "operating margin",
            "free cash flow",
            "leverage",
            "earnings revisions",
        ]

    return FalsificationFramework(
        fundamental_falsifiers=fundamental,
        macro_falsifiers=macro,
        valuation_falsifiers=valuation,
        timing_falsifiers=timing,
        technical_or_price_falsifiers=technical,
        monitoring_triggers=triggers,
        key_metrics_to_watch=metrics,
        falsification_summary=(
            "Thesis should be downgraded if key financial, macro, valuation, or timing assumptions fail to confirm."
        ),
    )
