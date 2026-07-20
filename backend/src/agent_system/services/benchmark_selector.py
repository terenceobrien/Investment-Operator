"""Deterministic benchmark selection for single-name relative-value analysis."""
from __future__ import annotations

from src.agent_system.schemas.deep_fundamental import (
    BenchmarkSelection,
    CompanyProfile,
)


BenchmarkTuple = tuple[str, list[str], str]


TICKER_BENCHMARK_OVERRIDES: dict[str, BenchmarkTuple] = {
    "MSFT": ("QQQ", ["XLK", "SPY"], "mega-cap software/platform exposure"),
    "AAPL": ("QQQ", ["XLK", "SPY"], "mega-cap technology platform exposure"),
    "AMZN": ("QQQ", ["XLY", "SPY"], "mega-cap platform and consumer discretionary exposure"),
    "GOOGL": ("QQQ", ["XLK", "SPY"], "mega-cap technology platform exposure"),
    "META": ("QQQ", ["XLK", "SPY"], "mega-cap technology platform exposure"),
    "MU": ("SMH", ["SOXX", "QQQ"], "semiconductor memory exposure"),
    "NVDA": ("SMH", ["SOXX", "QQQ"], "semiconductor and AI chip exposure"),
    "AMD": ("SMH", ["SOXX", "QQQ"], "semiconductor and AI chip exposure"),
    "AVGO": ("SMH", ["SOXX", "QQQ"], "semiconductor and AI infrastructure exposure"),
    "JPM": ("XLF", ["KBE", "SPY"], "large bank exposure"),
    "BAC": ("XLF", ["KBE", "SPY"], "large bank exposure"),
    "C": ("XLF", ["KBE", "SPY"], "large bank exposure"),
    "WFC": ("XLF", ["KBE", "SPY"], "large bank exposure"),
    "UNH": ("XLV", ["SPY"], "managed care healthcare exposure"),
    "HUM": ("XLV", ["SPY"], "managed care healthcare exposure"),
    "ELV": ("XLV", ["SPY"], "managed care healthcare exposure"),
    "ETN": ("XLI", ["PAVE", "SPY"], "electrical infrastructure and industrial exposure"),
    "GEV": ("XLI", ["PAVE", "SPY"], "power equipment and industrial exposure"),
    "PWR": ("XLI", ["PAVE", "SPY"], "infrastructure services exposure"),
    "XOM": ("XLE", ["SPY"], "integrated energy exposure"),
    "CVX": ("XLE", ["SPY"], "integrated energy exposure"),
}


def select_benchmarks(
    ticker: str,
    company_profile: CompanyProfile | None = None,
    user_override: str | None = None,
) -> BenchmarkSelection:
    """Select a relevant benchmark ETF using deterministic ticker/profile rules."""

    clean_ticker = ticker.upper().strip()
    override = (user_override or "").upper().strip()
    if override:
        default_primary, default_secondary, default_reason = _deterministic_mapping(
            clean_ticker,
            company_profile,
        )
        secondary = _dedupe(
            benchmark
            for benchmark in [*default_secondary, default_primary]
            if benchmark != override
        )
        return BenchmarkSelection(
            primary_benchmark=override,
            secondary_benchmarks=secondary,
            benchmark_reason=(
                f"User override selected {override} as primary benchmark; "
                f"default rule would have used {default_primary} ({default_reason})."
            ),
            benchmark_source="user_override",
        )

    primary, secondary, reason = _deterministic_mapping(clean_ticker, company_profile)
    source = "deterministic_mapping" if clean_ticker in TICKER_BENCHMARK_OVERRIDES else (
        "profile_inferred" if company_profile is not None else "deterministic_mapping"
    )
    return BenchmarkSelection(
        primary_benchmark=primary,
        secondary_benchmarks=secondary,
        benchmark_reason=reason,
        benchmark_source=source,
    )


def _deterministic_mapping(
    ticker: str,
    company_profile: CompanyProfile | None,
) -> BenchmarkTuple:
    if ticker in TICKER_BENCHMARK_OVERRIDES:
        return TICKER_BENCHMARK_OVERRIDES[ticker]

    text = _profile_text(company_profile)
    if _contains_any(text, ("semiconductor", "semi", "memory", "dram", "nand", "ai chip", "gpu")):
        return "SMH", ["SOXX", "QQQ"], "profile indicates semiconductor or AI chip exposure"
    if _contains_any(text, ("bank", "banking", "financial services", "capital markets")):
        return "XLF", ["KBE", "SPY"], "profile indicates bank or financial exposure"
    if _contains_any(text, ("managed care", "pharma", "pharmaceutical", "medtech", "medical device", "healthcare", "health care")):
        return "XLV", ["SPY"], "profile indicates healthcare exposure"
    if _contains_any(text, ("electrical", "infrastructure", "industrial", "grid", "power equipment", "construction")):
        return "XLI", ["PAVE", "SPY"], "profile indicates industrial or infrastructure exposure"
    if _contains_any(text, ("energy", "oil", "gas", "exploration", "production", "integrated")):
        return "XLE", ["SPY"], "profile indicates energy exposure"
    if _contains_any(text, ("utility", "utilities", "regulated electric", "regulated gas")):
        return "XLU", ["SPY"], "profile indicates utilities exposure"
    if _contains_any(text, ("consumer discretionary", "consumer cyclical", "retail", "e-commerce", "automotive")):
        return "XLY", ["SPY"], "profile indicates consumer discretionary exposure"
    if _contains_any(text, ("consumer staples", "consumer defensive", "food", "beverage", "household products")):
        return "XLP", ["SPY"], "profile indicates consumer staples exposure"
    if _contains_any(text, ("technology", "software", "platform", "cloud", "internet", "saas")):
        return "QQQ", ["XLK", "SPY"], "profile indicates mega-cap technology/platform/software exposure"

    return "SPY", [], "no specific sector benchmark rule matched; using broad U.S. equity benchmark"


def _profile_text(company_profile: CompanyProfile | None) -> str:
    if company_profile is None:
        return ""
    parts = [
        company_profile.sector or "",
        company_profile.industry or "",
        company_profile.business_description or "",
        company_profile.business_model or "",
        *company_profile.revenue_model,
        *company_profile.margin_drivers,
        *company_profile.thematic_exposures,
        *company_profile.macro_sensitivities,
    ]
    return " ".join(parts).lower()


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _dedupe(values) -> list[str]:
    seen: set[str] = set()
    clean_values: list[str] = []
    for value in values:
        clean = str(value).upper().strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        clean_values.append(clean)
    return clean_values
