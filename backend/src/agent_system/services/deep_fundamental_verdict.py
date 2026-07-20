from __future__ import annotations

from src.agent_system.schemas.deep_fundamental import (
    BasicScreenResult,
    CompanyProfile,
    CompetitivePositionAnalysis,
    DeepFundamentalLLMSynthesis,
    DeepSynthesisConfidence,
    DeepFundamentalScores,
    DeepFundamentalVerdict,
    FinancialTrendAnalysis,
    MarketExpectationAnalysis,
    PressureInflectionAnalysis,
    PressureType,
    RegimeSensitivityAnalysis,
    RelativePerformanceContext,
    ThemeContextPack,
    VariantView,
)


def build_deep_fundamental_scores(
    company_profile: CompanyProfile,
    financial_trend_analysis: FinancialTrendAnalysis,
    pressure_inflection_analysis: PressureInflectionAnalysis,
    competitive_position_analysis: CompetitivePositionAnalysis,
    regime_sensitivity_analysis: RegimeSensitivityAnalysis | None,
    market_expectation_analysis: MarketExpectationAnalysis,
    variant_view: VariantView,
    theme_context: ThemeContextPack | None = None,
    relative_performance_context: RelativePerformanceContext | None = None,
    llm_synthesis: DeepFundamentalLLMSynthesis | None = None,
) -> DeepFundamentalScores:
    business_quality = 50.0
    financial_health = 50.0
    competitive_position = 50.0
    earnings_inflection = 50.0
    regime_fit = 50.0 if regime_sensitivity_analysis else None
    valuation_setup = 50.0
    variant_strength = 0.0
    idiosyncratic_risk = 50.0

    # Business quality heuristics
    if company_profile.business_model:
        business_quality += 10
    if company_profile.segments:
        business_quality += 5
    if company_profile.thematic_exposures:
        business_quality += 5
    if company_profile.major_risks:
        profile_risks = classify_llm_risk_items(company_profile.major_risks)
        idiosyncratic_risk += min(
            10,
            len(profile_risks["business_idiosyncratic"]) * 2
            + len(profile_risks["balance_sheet"]) * 3,
        )
        idiosyncratic_risk += min(3, len(profile_risks["unknown"]))

    # Competitive heuristics
    if competitive_position_analysis.moat_sources:
        competitive_position += min(20, len(competitive_position_analysis.moat_sources) * 4)
    if competitive_position_analysis.competitive_threats:
        competitive_position -= min(10, len(competitive_position_analysis.competitive_threats) * 2)

    # Financial trend heuristics
    if financial_trend_analysis.red_flags:
        financial_health -= min(25, len(financial_trend_analysis.red_flags) * 5)
    if financial_trend_analysis.improving_indicators:
        financial_health += min(20, len(financial_trend_analysis.improving_indicators) * 4)
    indicator_text = " ".join(
        financial_trend_analysis.improving_indicators
        + financial_trend_analysis.deteriorating_indicators
        + financial_trend_analysis.red_flags
    ).lower()
    if "latest quarter revenue" in indicator_text or "run-rate is above ltm" in indicator_text:
        earnings_inflection += 6
    if "latest quarter gross margin is above ltm" in indicator_text:
        earnings_inflection += 5
    if "latest quarter operating margin is above ltm" in indicator_text:
        earnings_inflection += 5
    if "fcf conversion is lagging ebitda" in indicator_text:
        financial_health -= 4
        valuation_setup -= 3
    if "capex intensity is elevated" in indicator_text:
        financial_health -= 4
        valuation_setup -= 3

    # Pressure/inflection heuristics
    if pressure_inflection_analysis.inflection_catalysts:
        earnings_inflection += min(25, len(pressure_inflection_analysis.inflection_catalysts) * 5)
    if pressure_inflection_analysis.abatement_evidence:
        earnings_inflection += min(15, len(pressure_inflection_analysis.abatement_evidence) * 3)
    if pressure_inflection_analysis.pressure_type in {
        PressureType.CYCLICAL,
        PressureType.TEMPORARY_COST_PRESSURE,
        PressureType.MARKET_OVERREACTION,
    }:
        earnings_inflection += 5
    if pressure_inflection_analysis.pressure_type == PressureType.STRUCTURAL:
        earnings_inflection -= 20
        idiosyncratic_risk += 15

    # Regime heuristics
    if regime_sensitivity_analysis:
        if regime_sensitivity_analysis.scenario_impacts:
            positive = sum(
                1 for impact in regime_sensitivity_analysis.scenario_impacts
                if impact.impact == "positive"
            )
            negative = sum(
                1 for impact in regime_sensitivity_analysis.scenario_impacts
                if impact.impact == "negative"
            )
            regime_fit = 50 + (positive * 5) - (negative * 3)

    # Valuation / expectations heuristics
    if market_expectation_analysis.upside_already_priced is True:
        valuation_setup -= 15
    if market_expectation_analysis.downside_already_priced is True:
        valuation_setup += 10
    if market_expectation_analysis.market_mispricing_hypothesis:
        valuation_setup += 5
    if market_expectation_analysis.crowdedness_risk:
        valuation_setup -= 3

    # Variant view heuristics
    if variant_view.variant_view_strength == "strong":
        variant_strength = 85
    elif variant_view.variant_view_strength == "medium":
        variant_strength = 70
    elif variant_view.variant_view_strength == "weak":
        variant_strength = 55
    else:
        variant_strength = 20

    if variant_view.evidence_supporting_variant_view:
        variant_strength += min(10, len(variant_view.evidence_supporting_variant_view) * 2)

    if (
        theme_context is not None
        and theme_context.aggregate_theme_support_score is not None
    ):
        normalized_theme_score = _clamp(
            50 + (theme_context.aggregate_theme_support_score * 25)
        )
        if regime_fit is not None:
            regime_fit = (0.6 * regime_fit) + (0.4 * normalized_theme_score)
        else:
            regime_fit = normalized_theme_score

    if theme_context is not None and theme_context.theme_mapping is not None:
        mapped = theme_context.theme_mapping.mapped_themes
        if mapped:
            avg_confidence = sum(item.confidence for item in mapped) / len(mapped)
            if avg_confidence >= 0.65:
                variant_strength += 5

        if theme_context.negative_drivers:
            valuation_setup -= min(8, len(theme_context.negative_drivers) * 1.5)

    if llm_synthesis is not None:
        if llm_synthesis.variant_view_strength == "strong":
            variant_strength += 5
        elif llm_synthesis.variant_view_strength == "none":
            variant_strength = min(variant_strength, 45)

        if llm_synthesis.key_risks:
            risk_categories = classify_llm_risk_items(llm_synthesis.key_risks)
            idiosyncratic_risk += _llm_idiosyncratic_risk_penalty(risk_categories)
            valuation_setup -= min(
                8,
                2 * len(risk_categories["valuation_expectations"])
                + len(risk_categories["technical_positioning"]),
            )
            if regime_fit is not None:
                regime_fit -= min(
                    6,
                    1.5 * len(risk_categories["macro_theme"])
                    + len(risk_categories["cycle"]),
                )
            financial_health -= min(
                5,
                2 * len(risk_categories["balance_sheet"]),
            )

    # Clamp components
    business_quality = _clamp(business_quality)
    financial_health = _clamp(financial_health)
    competitive_position = _clamp(competitive_position)
    earnings_inflection = _clamp(earnings_inflection)
    regime_fit = _clamp(regime_fit) if regime_fit is not None else None
    valuation_setup = _clamp(valuation_setup)
    variant_strength = _clamp(variant_strength)
    idiosyncratic_risk = _clamp(idiosyncratic_risk)
    relative_strength = _relative_strength_score(
        relative_performance_context,
        financial_health=financial_health,
        earnings_inflection=earnings_inflection,
        variant_strength=variant_strength,
    )

    # Weighted score.
    # Note: idiosyncratic risk is subtracted because higher risk score is worse.
    weighted_inputs = [
        (business_quality, 0.15),
        (financial_health, 0.12),
        (competitive_position, 0.15),
        (earnings_inflection, 0.18),
        (valuation_setup, 0.15),
        (relative_strength, 0.12),
        (variant_strength, 0.18),
        (100 - idiosyncratic_risk, 0.07),
    ]

    if regime_fit is not None:
        weighted_inputs.append((regime_fit, 0.12))

    total_weight = sum(weight for _, weight in weighted_inputs)
    final_score = sum(score * weight for score, weight in weighted_inputs) / total_weight

    # Caps to prevent false precision.
    stale_financial_context = any(
        "stale" in flag.lower()
        for flag in financial_trend_analysis.red_flags
    )
    cyclical_or_high_beta = _profile_is_cyclical_or_high_beta(company_profile)
    if stale_financial_context:
        final_score = min(final_score, 65 if llm_synthesis is None else 68)
        if cyclical_or_high_beta:
            final_score = min(final_score, 64 if llm_synthesis is None else 66)

    if variant_view.variant_view_strength == "none":
        final_score = min(final_score, 62)

    if not variant_view.required_confirming_evidence:
        final_score = min(final_score, 70)

    if idiosyncratic_risk >= 80:
        final_score = min(final_score, 68)

    if llm_synthesis is not None:
        adjustment = max(-10.0, min(10.0, llm_synthesis.suggested_score_adjustment))
        final_score += adjustment

        if llm_synthesis.confidence == DeepSynthesisConfidence.LOW:
            final_score = min(final_score, 70)

        if llm_synthesis.qualitative_conviction == "reject":
            deterministic_strength = (
                financial_health >= 75
                and (regime_fit is not None and regime_fit >= 70)
            )
            if not deterministic_strength:
                final_score = min(final_score, 62)

    return DeepFundamentalScores(
        business_quality=business_quality,
        financial_health=financial_health,
        competitive_position=competitive_position,
        earnings_inflection_potential=earnings_inflection,
        regime_fit=regime_fit,
        valuation_setup=valuation_setup,
        relative_strength_benchmark_alpha=relative_strength,
        variant_perception_strength=variant_strength,
        idiosyncratic_risk=idiosyncratic_risk,
        final_underwriting_score=_clamp(final_score),
    )


def determine_deep_fundamental_verdict(
    scores: DeepFundamentalScores,
    basic_screen_result: BasicScreenResult | None,
    financial_trend_analysis: FinancialTrendAnalysis,
    pressure_inflection_analysis: PressureInflectionAnalysis,
    variant_view: VariantView,
    llm_synthesis: DeepFundamentalLLMSynthesis | None = None,
) -> tuple[DeepFundamentalVerdict, bool, str | None]:
    score = scores.final_underwriting_score

    screen_override = False
    screen_override_rationale = None
    watchlist_floor_rationale = (
        "Constructive LLM synthesis with medium/high confidence and adequate "
        "business/financial quality floors verdict at watchlist rather than reject."
        if _constructive_watchlist_floor(scores, llm_synthesis)
        else None
    )

    # Reject if there is no real variant view.
    if variant_view.variant_view_strength == "none":
        if watchlist_floor_rationale:
            return DeepFundamentalVerdict.WATCHLIST, False, watchlist_floor_rationale
        if basic_screen_result and basic_screen_result.passed:
            return (
                DeepFundamentalVerdict.OVERRIDE_SCREEN_ACCEPT_TO_REJECT,
                True,
                "Basic screen passed, but no variant view was established. Passing metrics alone are not enough for underwriting.",
            )

        return DeepFundamentalVerdict.REJECT, False, None

    # Possible override of a failed basic screen.
    if basic_screen_result and not basic_screen_result.passed:
        if (
            scores.earnings_inflection_potential >= 70
            and scores.variant_perception_strength >= 65
            and pressure_inflection_analysis.pressure_type
            in {
                PressureType.CYCLICAL,
                PressureType.TEMPORARY_COST_PRESSURE,
                PressureType.MACRO_DRIVEN,
                PressureType.MARKET_OVERREACTION,
            }
        ):
            screen_override = True
            screen_override_rationale = (
                "Basic screen failed, but deep underwriting found a plausible temporary/cyclical pressure "
                "with identifiable inflection catalysts and a valid variant view."
            )

            if score >= 75:
                return DeepFundamentalVerdict.OVERRIDE_SCREEN_REJECT, True, screen_override_rationale

            return DeepFundamentalVerdict.WATCHLIST, True, screen_override_rationale

    # Possible override of a passed screen.
    if basic_screen_result and basic_screen_result.passed:
        if scores.variant_perception_strength < 50 or scores.idiosyncratic_risk >= 80:
            if watchlist_floor_rationale:
                return DeepFundamentalVerdict.WATCHLIST, False, watchlist_floor_rationale
            return (
                DeepFundamentalVerdict.OVERRIDE_SCREEN_ACCEPT_TO_REJECT,
                True,
                "Basic screen passed, but deep underwriting found weak variant perception or elevated idiosyncratic risk.",
            )

    # Standard verdicts
    if (
        score >= 82
        and scores.variant_perception_strength >= 75
        and variant_view.variant_view_strength == "strong"
        and scores.financial_health >= 65
        and scores.valuation_setup >= 55
        and scores.idiosyncratic_risk < 75
    ):
        return DeepFundamentalVerdict.STRONG_ACCEPT, screen_override, screen_override_rationale

    if (
        score >= 72
        and scores.variant_perception_strength >= 60
        and variant_view.variant_view_strength in {"medium", "strong"}
    ):
        return DeepFundamentalVerdict.ACCEPT_WITH_CAVEATS, screen_override, screen_override_rationale

    if score >= 60:
        return DeepFundamentalVerdict.WATCHLIST, screen_override, screen_override_rationale

    if watchlist_floor_rationale:
        return DeepFundamentalVerdict.WATCHLIST, False, watchlist_floor_rationale

    return DeepFundamentalVerdict.REJECT, screen_override, screen_override_rationale


RiskCategoryMap = dict[str, list[str]]


def classify_llm_risk_items(risks: list[str]) -> RiskCategoryMap:
    categories: RiskCategoryMap = {
        "business_idiosyncratic": [],
        "balance_sheet": [],
        "valuation_expectations": [],
        "macro_theme": [],
        "cycle": [],
        "technical_positioning": [],
        "unknown": [],
    }
    keyword_map = [
        (
            "balance_sheet",
            (
                "leverage",
                "debt",
                "liquidity",
                "refinancing",
                "covenant",
                "cash burn",
            ),
        ),
        (
            "business_idiosyncratic",
            (
                "execution",
                "capacity constraint",
                "management",
                "product",
                "customer concentration",
                "supplier",
                "technology transition",
                "operational",
                "backlog conversion",
            ),
        ),
        (
            "valuation_expectations",
            (
                "valuation",
                "multiple",
                "expectations",
                "priced in",
                "forward p/e",
                "ev/ebitda",
                "price-to-sales",
                "price-to-book",
                "estimate",
                "peak earnings",
            ),
        ),
        (
            "macro_theme",
            (
                "rates",
                "fed",
                "construction",
                "industrial capex",
                "data center capex",
                "ai capex",
                "grid spending",
                "input cost",
                "china",
                "export restrictions",
                "global growth",
            ),
        ),
        (
            "cycle",
            (
                "memory pricing",
                "dram",
                "nand",
                "cycle",
                "cyclical",
                "inventory",
                "supply additions",
                "supply discipline",
            ),
        ),
        (
            "technical_positioning",
            (
                "momentum",
                "drawdown",
                "crowded",
                "positioning",
                "52-week high",
                "high beta",
                "reversal",
            ),
        ),
    ]

    for risk in risks:
        clean = risk.strip() if isinstance(risk, str) else str(risk).strip()
        if not clean:
            continue
        lowered = clean.lower()
        matched = False
        for category, keywords in keyword_map:
            if any(keyword in lowered for keyword in keywords):
                categories[category].append(clean)
                matched = True
                break
        if not matched:
            categories["unknown"].append(clean)
    return categories


def _llm_idiosyncratic_risk_penalty(categories: RiskCategoryMap) -> float:
    penalty = 0.0
    penalty += min(12, 3 * len(categories["business_idiosyncratic"]))
    penalty += min(10, 4 * len(categories["balance_sheet"]))
    penalty += min(5, len(categories["unknown"]))
    non_idiosyncratic = (
        len(categories["valuation_expectations"])
        + len(categories["macro_theme"])
        + len(categories["cycle"])
        + len(categories["technical_positioning"])
    )
    penalty += min(5, 0.75 * non_idiosyncratic)
    return penalty


def _constructive_watchlist_floor(
    scores: DeepFundamentalScores,
    llm_synthesis: DeepFundamentalLLMSynthesis | None,
) -> bool:
    if llm_synthesis is None:
        return False
    return (
        llm_synthesis.qualitative_conviction == "constructive"
        and llm_synthesis.confidence
        in {DeepSynthesisConfidence.MEDIUM, DeepSynthesisConfidence.HIGH}
        and scores.business_quality >= 65
        and scores.financial_health >= 50
        and scores.final_underwriting_score >= 56
        and scores.idiosyncratic_risk < 85
    )


def _relative_strength_score(
    relative_performance_context: RelativePerformanceContext | None,
    *,
    financial_health: float,
    earnings_inflection: float,
    variant_strength: float,
) -> float:
    if relative_performance_context is None:
        return 50.0

    raw_score = relative_performance_context.score_0_to_100
    label = relative_performance_context.overall_label
    if raw_score is None or label == "insufficient_data":
        return 50.0

    score = float(raw_score)
    primary = relative_performance_context.primary_metrics
    trend = primary.relative_trend if primary is not None else None

    strong_or_improving_fundamentals = (
        financial_health >= 65
        or earnings_inflection >= 65
        or variant_strength >= 65
    )
    weak_fundamentals = financial_health < 50 and earnings_inflection < 55

    if label == "confirmed_relative_leader":
        score = max(score, 70)
    elif label == "defensive_relative_outperformer":
        score = max(score, 62)
    elif label == "improving_relative_inflection":
        score = max(score, 56 if strong_or_improving_fundamentals else 50)
    elif label == "deteriorating_relative_laggard":
        if strong_or_improving_fundamentals and trend == "improving":
            score = max(score, 45)
        elif weak_fundamentals:
            score -= 8
        else:
            score = min(score, 45)
    elif label == "benchmark_like":
        if strong_or_improving_fundamentals and trend == "improving":
            score = max(score, 54)
        else:
            score = max(45, min(score, 55))

    return _clamp(score)


def _profile_is_cyclical_or_high_beta(company_profile: CompanyProfile) -> bool:
    text = " ".join(
        [
            company_profile.industry or "",
            company_profile.business_model or "",
            *company_profile.revenue_model,
            *company_profile.margin_drivers,
            *company_profile.macro_sensitivities,
            *company_profile.major_risks,
        ]
    ).lower()
    return any(
        keyword in text
        for keyword in (
            "cycle",
            "cyclical",
            "memory",
            "semiconductor",
            "commodity",
            "inventory",
            "pricing",
            "high beta",
            "capex",
        )
    )


def _clamp(value: float, low: float = 0, high: float = 100) -> float:
    return max(low, min(high, float(value)))
