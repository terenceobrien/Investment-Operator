"""Map companies to macro-forecast theme IDs.

The public API is shaped so an LLM classifier can later choose from the
forecast-provided theme catalog. For now, mapping is deterministic and only
returns theme IDs that exist in the supplied catalog.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from src.agent_system.schemas.deep_fundamental import (
    CompanyProfile,
    DataConfidence,
    RejectedThemeMapping,
    ThemeCatalogItem,
    ThemeFitType,
    ThemeMappingItem,
    ThemeMappingResult,
)


FIT_WEIGHTS = {
    ThemeFitType.PRIMARY: 1.0,
    ThemeFitType.SECONDARY: 0.7,
    ThemeFitType.PARTIAL: 0.45,
    ThemeFitType.INDIRECT: 0.25,
    ThemeFitType.NONE: 0.0,
}


THEME_MAPPING_ROOT = (
    Path(__file__).resolve().parents[4] / "data" / "theme_mappings"
)


THEME_MAPPING_STOPWORDS = {
    "and",
    "or",
    "the",
    "a",
    "an",
    "of",
    "to",
    "in",
    "for",
    "with",
    "quality",
    "growth",
    "cash",
    "assets",
    "real",
    "power",
    "high",
    "infrastructure",
    "duration",
    "short",
    "long",
    "small",
    "large",
}


KEYWORD_RULES: list[dict[str, object]] = [
    {
        "company": {"memory", "dram", "nand", "hbm", "storage"},
        "theme": {"memory", "semis", "semiconductor", "storage"},
        "fit": ThemeFitType.PRIMARY,
        "confidence": 0.88,
        "rationale": "Company text directly references memory/storage semiconductor economics.",
    },
    {
        "company": {"semiconductor", "semis", "chip", "chips", "ai server", "hbm"},
        "theme": {"semiconductor", "semis", "quality ai", "high beta ai"},
        "fit": ThemeFitType.SECONDARY,
        "confidence": 0.68,
        "rationale": "Company has semiconductor or AI-server exposure relevant to this macro theme.",
    },
    {
        "company": {
            "grid",
            "power",
            "electrification",
            "electrical",
            "data center power",
            "utility",
        },
        "theme": {"grid", "power", "infrastructure", "electrification"},
        "fit": ThemeFitType.PRIMARY,
        "confidence": 0.9,
        "rationale": "Company text directly references grid, power, or electrification demand.",
    },
    {
        "company": {
            "cash flow",
            "free cash flow",
            "profitable",
            "quality",
            "resilient",
            "resilience",
            "pricing power",
            "margin resilience",
        },
        "theme": {"quality", "compounders", "cash flow"},
        "fit": ThemeFitType.PARTIAL,
        "confidence": 0.52,
        "rationale": "Company text points to quality, pricing power, or cash-flow resilience.",
    },
    {
        "company": {"healthcare", "pharma", "biotech", "medtech", "medical"},
        "theme": {"healthcare", "pharma", "biotech", "medtech", "defensive"},
        "fit": ThemeFitType.PRIMARY,
        "confidence": 0.88,
        "rationale": "Company sector or industry directly matches healthcare defensives.",
    },
    {
        "company": {"oil", "crude", "natural gas"},
        "theme": {"energy", "oil", "commodity", "commodities"},
        "fit": ThemeFitType.PRIMARY,
        "confidence": 0.86,
        "rationale": "Company text directly references oil, gas, or energy exposure.",
    },
    {
        "company": {"commodities", "real assets", "gold", "miners", "metals"},
        "theme": {"commodity", "commodities", "real assets", "gold", "miners"},
        "fit": ThemeFitType.PRIMARY,
        "confidence": 0.84,
        "rationale": "Company text directly references commodities or real assets.",
    },
    {
        "company": {"small cap", "regional bank", "high leverage", "domestic cyclicals"},
        "theme": {"small", "small_caps", "regional", "cyclical"},
        "fit": ThemeFitType.SECONDARY,
        "confidence": 0.62,
        "rationale": "Company text resembles small-cap or domestic cyclical exposure.",
    },
    {
        "company": {"duration", "long-duration", "software", "unprofitable growth"},
        "theme": {"duration", "software", "growth"},
        "fit": ThemeFitType.SECONDARY,
        "confidence": 0.6,
        "rationale": "Company text has duration-sensitive growth exposure.",
    },
    {
        "company": {"cash", "short duration", "bills", "carry"},
        "theme": {"cash", "short", "duration", "carry"},
        "fit": ThemeFitType.INDIRECT,
        "confidence": 0.4,
        "rationale": "Company text has indirect cash or short-duration linkage.",
    },
    {
        "company": {
            "ai infrastructure",
            "cloud ai",
            "ai software",
            "ai platform",
            "ai devices",
            "ai device",
            "ai semiconductor",
            "ai monetization",
            "data center",
            "hyperscaler",
            "accelerator",
        },
        "theme": {"quality ai"},
        "fit": ThemeFitType.PARTIAL,
        "confidence": 0.5,
        "rationale": "Company text references AI or data-center demand tied to this theme.",
    },
]


def build_theme_mapping_for_ticker(
    ticker: str,
    company_profile: CompanyProfile,
    theme_catalog: list[ThemeCatalogItem],
    refresh: bool = False,
    use_llm: bool = False,
) -> ThemeMappingResult:
    if not refresh:
        cached = load_theme_mapping_result(ticker)
        if cached is not None and "exposure-gated-v2" in (cached.mapping_summary or ""):
            valid_ids = {item.theme_id for item in theme_catalog}
            cached_mapped = [
                item for item in cached.mapped_themes if item.theme_id in valid_ids
            ]
            if cached_mapped:
                return cached.model_copy(update={"mapped_themes": cached_mapped})

    if not theme_catalog:
        return ThemeMappingResult(
            ticker=ticker.upper().strip(),
            mapping_summary="No macro forecast theme catalog was available.",
            data_confidence=DataConfidence.LOW,
            source="none",
        )

    mapped: list[ThemeMappingItem] = []
    rejected: list[RejectedThemeMapping] = []

    for theme in theme_catalog:
        score, fit, reasons = _score_theme_match(company_profile, theme)
        if score >= 0.35:
            mapped.append(
                ThemeMappingItem(
                    theme_id=theme.theme_id,
                    theme_label=theme.label,
                    fit=fit,
                    confidence=min(1.0, score),
                    rationale="; ".join(reasons),
                )
            )
        elif score >= 0.2:
            rejected.append(
                RejectedThemeMapping(
                    theme_id=theme.theme_id,
                    theme_label=theme.label,
                    reason="Rejected: keyword overlap did not imply economic exposure.",
                )
            )

    mapped = sorted(
        mapped,
        key=lambda item: (FIT_WEIGHTS[item.fit], item.confidence),
        reverse=True,
    )

    source = "deterministic_fallback"
    summary = (
        f"Mapped {len(mapped)} of {len(theme_catalog)} available macro-forecast themes "
        "using deterministic exposure-gated-v2 keyword/semantic fallback."
    )
    if not mapped and _is_bank_profile(company_profile):
        summary += (
            " No active macro theme cleanly maps to diversified banks / "
            "credit-cycle financials."
        )
    if use_llm:
        summary += " LLM mapping requested, but no standard LLM client is wired here yet."

    confidence = DataConfidence.MEDIUM if mapped else DataConfidence.LOW
    result = ThemeMappingResult(
        ticker=ticker.upper().strip(),
        mapped_themes=mapped,
        rejected_themes=rejected[:10],
        mapping_summary=summary,
        data_confidence=confidence,
        source=source,
    )
    save_theme_mapping_result(result)
    return result


def save_theme_mapping_result(result: ThemeMappingResult) -> Path:
    THEME_MAPPING_ROOT.mkdir(parents=True, exist_ok=True)
    path = THEME_MAPPING_ROOT / f"{result.ticker.upper()}.json"
    path.write_text(result.model_dump_json(indent=2))
    return path


def load_theme_mapping_result(ticker: str) -> ThemeMappingResult | None:
    path = THEME_MAPPING_ROOT / f"{ticker.upper().strip()}.json"
    if not path.exists():
        return None
    try:
        return ThemeMappingResult.model_validate_json(path.read_text())
    except Exception:
        return None


def _score_theme_match(
    company_profile: CompanyProfile,
    theme: ThemeCatalogItem,
) -> tuple[float, ThemeFitType, list[str]]:
    company_text = _company_text(company_profile)
    theme_text = f"{theme.theme_id} {theme.label or ''}".lower().replace("_", " ")
    theme_tokens = _tokens(theme_text)
    company_tokens = _tokens(company_text)

    reasons: list[str] = []
    score = 0.0
    fit = ThemeFitType.NONE
    rule_matched = False

    allowed, rejection_reason = _passes_economic_theme_gate(
        company_profile,
        company_text,
        theme_text,
    )
    if not allowed:
        return 0.2, ThemeFitType.NONE, [rejection_reason]

    overlap = theme_tokens & company_tokens
    if overlap:
        overlap_score = min(0.18, len(overlap) * 0.04)
        score += overlap_score
        if len(overlap) >= 2:
            fit = _max_fit(fit, ThemeFitType.PARTIAL)
        reasons.append(f"Shared terms: {', '.join(sorted(overlap)[:5])}.")

    for rule in KEYWORD_RULES:
        company_keywords = rule["company"]
        theme_keywords = rule["theme"]
        assert isinstance(company_keywords, set)
        assert isinstance(theme_keywords, set)

        if not _contains_any(company_text, company_keywords):
            continue
        if not _contains_any(theme_text, theme_keywords):
            continue

        rule_fit = rule["fit"]
        rule_confidence = rule["confidence"]
        rule_rationale = rule["rationale"]
        assert isinstance(rule_fit, ThemeFitType)
        assert isinstance(rule_confidence, float)
        assert isinstance(rule_rationale, str)
        score = max(score, rule_confidence)
        fit = _max_fit(fit, rule_fit)
        reasons.append(rule_rationale)
        rule_matched = True

    direct_core_exposure = _has_direct_core_exposure(company_profile, theme_text)
    if not rule_matched and score >= 0.35:
        score = 0.2
        fit = ThemeFitType.NONE
        reasons.append("Rejected: keyword overlap did not imply economic exposure.")
    elif rule_matched and not direct_core_exposure:
        if fit == ThemeFitType.PRIMARY:
            fit = ThemeFitType.SECONDARY
            reasons.append(
                "Fit reduced because direct revenue/business-model exposure "
                "is not explicit in the company profile."
            )
        if score > 0.4:
            score = 0.4
            reasons.append(
                "Confidence capped because mapping appears indirect rather "
                "than direct company economics."
            )

    if score > 0.55 and not _explicit_theme_exposure(company_profile, theme_text):
        score = 0.55
        reasons.append(
            "Confidence capped because deterministic mapping lacks explicit "
            "company thematic exposure confirmation."
        )

    if not reasons:
        reasons.append("No direct semantic match to company economics.")

    if fit == ThemeFitType.NONE and score >= 0.35:
        fit = ThemeFitType.PARTIAL
    return score, fit, _dedupe(reasons)


def _passes_economic_theme_gate(
    company_profile: CompanyProfile,
    company_text: str,
    theme_text: str,
) -> tuple[bool, str]:
    if _theme_has(theme_text, {"grid", "power infrastructure", "electrification"}):
        required = {
            "grid",
            "utility equipment",
            "electrical equipment",
            "power infrastructure",
            "data center power",
            "transformer",
            "switchgear",
            "electrification",
            "transmission",
            "distribution",
        }
        return _gate(company_text, required, "grid/power infrastructure")

    if _theme_has(theme_text, {"memory", "memory semis"}):
        required = {
            "dram",
            "nand",
            "hbm",
            "memory semiconductor",
            "storage semiconductor",
        }
        return _gate(company_text, required, "memory semiconductor")

    if _theme_has(theme_text, {"high beta ai semis", "semis", "semiconductor"}):
        if _has_direct_semiconductor_supplier_economics(company_text):
            return True, ""
        if _is_semiconductor_customer_or_internal_designer(company_text):
            return False, (
                "Rejected: company appears to use or design chips for its own "
                "ecosystem, not sell high-beta semiconductor supplier exposure."
            )
        return False, (
            "Rejected: keyword overlap did not imply direct semiconductor "
            "supplier economics."
        )

    if _theme_has(theme_text, {"quality ex ai", "quality cash flow", "cash flow", "compounder"}):
        required = {
            "durable cash flow",
            "free cash flow",
            "high margins",
            "recurring revenue",
            "defensive quality",
            "quality compounder",
            "pricing power",
            "cash generation",
            "fee income",
        }
        return _gate(company_text, required, "quality/cash-flow")

    if _theme_has(theme_text, {"quality ai"}):
        required = {
            "ai infrastructure",
            "cloud ai",
            "ai software",
            "ai platform",
            "ai devices",
            "ai device",
            "ai semiconductor",
            "ai monetization",
            "data center ai",
            "hyperscaler",
        }
        return _gate(company_text, required, "AI economic exposure")

    if _theme_has(theme_text, {"cash short duration", "short duration", "cash"}):
        required = {
            "cash-like",
            "short-duration bond",
            "treasury bills",
            "money market",
            "cash vehicle",
            "carry instrument",
            "short duration etf",
        }
        return _gate(company_text, required, "cash/short-duration instrument")

    if _theme_has(theme_text, {"commodities", "real assets", "oil", "energy"}):
        if _is_financial_intermediary_profile(company_profile):
            return False, (
                "Rejected: commodities trading, real-estate lending, or asset "
                "management exposure at a bank does not create direct "
                "commodity/real-asset economics."
            )
        if _has_direct_commodity_or_real_asset_economics(company_text):
            return True, ""
        return False, (
            "Rejected: keyword overlap did not imply direct commodity or "
            "real-asset exposure."
        )

    if _theme_has(theme_text, {"small caps", "small cap", "small_caps"}):
        ticker = company_profile.ticker.upper()
        required = {
            "small cap etf",
            "small-cap etf",
            "small cap",
            "small-cap",
            "regional bank",
            "domestic small cap",
        }
        if ticker in {"IWM", "IJR", "VB", "SCHA"}:
            return True, ""
        return _gate(company_text, required, "small-cap")

    if _theme_has(theme_text, {"long duration growth", "duration growth"}):
        required = {
            "unprofitable growth",
            "high-multiple growth",
            "long-duration growth",
            "software growth",
            "biotech",
            "rate-sensitive growth",
        }
        return _gate(company_text, required, "long-duration growth")

    return True, ""


def _theme_has(theme_text: str, concepts: set[str]) -> bool:
    return any(concept in theme_text for concept in concepts)


def _gate(
    company_text: str,
    required_terms: set[str],
    label: str,
) -> tuple[bool, str]:
    if _contains_any(company_text, required_terms):
        return True, ""
    return False, (
        f"Rejected: keyword overlap did not imply economic exposure to {label} theme."
    )


def _has_direct_semiconductor_supplier_economics(company_text: str) -> bool:
    direct_terms = {
        "semiconductor manufacturer",
        "semiconductor supplier",
        "chip manufacturer",
        "chip supplier",
        "fabless semiconductor",
        "merchant semiconductor",
        "sells semiconductors",
        "semiconductor revenue",
        "revenue from semiconductors",
        "ai accelerator supplier",
        "gpu supplier",
        "gpu manufacturer",
        "memory supplier",
        "dram",
        "nand",
        "hbm",
        "foundry",
        "semiconductor equipment",
        "networking semiconductor",
        "server semiconductor",
        "server semis",
    }
    return _contains_any(company_text, direct_terms)


def _is_semiconductor_customer_or_internal_designer(company_text: str) -> bool:
    excluded_terms = {
        "consumer electronics",
        "device company",
        "devices",
        "hardware oem",
        "consumer electronics oem",
        "cloud customer",
        "software company",
        "uses semiconductors",
        "custom chips",
        "custom silicon",
        "apple silicon",
        "internal product ecosystem",
        "designs custom chips",
        "designs chips for its own",
    }
    return _contains_any(company_text, excluded_terms)


def _has_direct_commodity_or_real_asset_economics(company_text: str) -> bool:
    direct_terms = {
        "oil and gas producer",
        "oil producer",
        "gas producer",
        "exploration and production",
        " e&p",
        "refiner",
        "refining",
        "midstream operator",
        "pipeline operator",
        "commodity producer",
        "metals producer",
        "mining company",
        "gold miner",
        "copper miner",
        "real estate investment trust",
        " reit",
        "property owner",
        "infrastructure asset owner",
        "timber",
        "farmland",
        "owns real assets",
        "direct commodity revenue",
        "natural resources producer",
    }
    return _contains_any(company_text, direct_terms)


def _is_financial_intermediary_profile(company_profile: CompanyProfile) -> bool:
    text = " ".join(
        [
            company_profile.sector or "",
            company_profile.industry or "",
            company_profile.business_description or "",
            company_profile.business_model or "",
        ]
    ).lower()
    return _contains_any(
        text,
        {
            "bank",
            "banks",
            "broker",
            "dealer",
            "asset manager",
            "asset management",
            "wealth management",
            "investment banking",
            "diversified financial",
        },
    )


def _is_bank_profile(company_profile: CompanyProfile) -> bool:
    text = f"{company_profile.sector or ''} {company_profile.industry or ''} {company_profile.business_model or ''}".lower()
    return _contains_any(text, {"bank", "banks", "diversified banks", "banking"})


def _has_direct_core_exposure(
    company_profile: CompanyProfile,
    theme_text: str,
) -> bool:
    core_text = " ".join(
        [
            company_profile.business_description or "",
            company_profile.business_model or "",
            " ".join(company_profile.revenue_model),
            " ".join(company_profile.thematic_exposures),
        ]
    ).lower()
    if not core_text:
        return False
    if _theme_has(theme_text, {"high beta ai semis", "semis", "semiconductor"}):
        return _has_direct_semiconductor_supplier_economics(core_text)
    if _theme_has(theme_text, {"commodities", "real assets", "oil", "energy"}):
        return _has_direct_commodity_or_real_asset_economics(core_text)
    allowed, _reason = _passes_economic_theme_gate(
        company_profile,
        core_text,
        theme_text,
    )
    if allowed and theme_text:
        return True
    theme_tokens = _tokens(theme_text)
    core_tokens = _tokens(core_text)
    return len(theme_tokens & core_tokens) >= 1


def _explicit_theme_exposure(
    company_profile: CompanyProfile,
    theme_text: str,
) -> bool:
    exposure_text = " ".join(
        company_profile.thematic_exposures
        + company_profile.macro_sensitivities
    ).lower()
    if not exposure_text:
        return False
    theme_tokens = _tokens(theme_text)
    exposure_tokens = _tokens(exposure_text)
    return len(theme_tokens & exposure_tokens) >= 1


def _company_text(company_profile: CompanyProfile) -> str:
    pieces: list[str] = [
        company_profile.company_name or "",
        company_profile.sector or "",
        company_profile.industry or "",
        company_profile.business_description or "",
        company_profile.business_model or "",
    ]
    for segment in company_profile.segments:
        pieces.extend([segment.name, segment.description or ""])
        pieces.extend(segment.key_drivers)
    pieces.extend(company_profile.revenue_model)
    pieces.extend(company_profile.margin_drivers)
    pieces.extend(company_profile.thematic_exposures)
    pieces.extend(company_profile.macro_sensitivities)
    pieces.extend(company_profile.major_risks)
    return " ".join(pieces).lower()


def _tokens(value: str) -> set[str]:
    cleaned = "".join(char.lower() if char.isalnum() else " " for char in value)
    return {
        token for token in cleaned.split()
        if len(token) > 2 and token not in THEME_MAPPING_STOPWORDS
    }


def _contains_any(text: str, terms: Iterable[str]) -> bool:
    tokens = _tokens(text)
    for term in terms:
        clean = term.lower().strip()
        if not clean:
            continue
        if " " in clean or "-" in clean:
            if clean in text:
                return True
            continue
        if clean in tokens:
            return True
    return False


def _max_fit(left: ThemeFitType, right: ThemeFitType) -> ThemeFitType:
    return left if FIT_WEIGHTS[left] >= FIT_WEIGHTS[right] else right


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value not in seen:
            deduped.append(value)
            seen.add(value)
    return deduped
