"""CompanyProfile builder with manual, cached, LLM, and fallback paths."""
from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path
from typing import Any

from src.agent_system.schemas.deep_fundamental import (
    CompanyProfile,
    DataConfidence,
    FundamentalContextPack,
)
from src.agent_system.services.deep_fundamental_builders import (
    COMPANY_KNOWLEDGE,
    build_company_profile as build_static_company_profile,
)
from src.agent_system.paths import company_profiles_dir


COMPANY_PROFILE_CACHE_ROOT = company_profiles_dir(create=False)


async def build_company_profile_async(
    ticker: str,
    *,
    financial_context: FundamentalContextPack | None = None,
    research_context: Any | None = None,
    use_llm_profile: bool = True,
    refresh_profile: bool = False,
) -> CompanyProfile:
    """Build a CompanyProfile, using manual seed first unless refreshed."""

    clean_ticker = ticker.upper().strip()
    if not clean_ticker:
        raise ValueError("ticker cannot be empty")

    if not refresh_profile:
        manual = _manual_seed_profile(clean_ticker)
        if manual is not None:
            return manual

        cached = load_company_profile(clean_ticker)
        if cached is not None:
            return cached

    if use_llm_profile:
        from src.agent_system.agents.company_profile_agent import (
            generate_company_profile,
        )

        profile = await generate_company_profile(
            ticker=clean_ticker,
            financial_context=financial_context,
            research_context=research_context,
            existing_profile=_minimal_profile(clean_ticker),
            as_of_date=date.today(),
        )
        save_company_profile(profile)
        return profile

    return _minimal_profile(clean_ticker)


def build_company_profile(
    ticker: str,
    *,
    financial_context: FundamentalContextPack | None = None,
    research_context: Any | None = None,
    use_llm_profile: bool = True,
    refresh_profile: bool = False,
) -> CompanyProfile:
    """
    Synchronous convenience wrapper.

    The default is cache/manual/minimal only, preserving cheap deterministic
    runs. If use_llm_profile=True is requested from sync code, this wrapper
    uses asyncio.run and should not be called from an existing event loop.
    """

    if use_llm_profile:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                build_company_profile_async(
                    ticker,
                    financial_context=financial_context,
                    research_context=research_context,
                    use_llm_profile=True,
                    refresh_profile=refresh_profile,
                )
            )
        raise RuntimeError(
            "build_company_profile cannot run live LLM profile generation "
            "inside an existing event loop. Use build_company_profile_async."
        )

    clean_ticker = ticker.upper().strip()
    if not clean_ticker:
        raise ValueError("ticker cannot be empty")

    if not refresh_profile:
        manual = _manual_seed_profile(clean_ticker)
        if manual is not None:
            return manual
        cached = load_company_profile(clean_ticker)
        if cached is not None:
            return cached

    return _minimal_profile(clean_ticker)


def save_company_profile(profile: CompanyProfile) -> Path:
    COMPANY_PROFILE_CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    path = _profile_cache_path(profile.ticker)
    path.write_text(profile.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_company_profile(ticker: str) -> CompanyProfile | None:
    path = _profile_cache_path(ticker)
    if not path.exists():
        return None
    try:
        return CompanyProfile.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _profile_cache_path(ticker: str) -> Path:
    return COMPANY_PROFILE_CACHE_ROOT / f"{ticker.upper().strip()}.json"


def _manual_seed_profile(ticker: str) -> CompanyProfile | None:
    if ticker.upper().strip() not in COMPANY_KNOWLEDGE:
        return None
    profile = build_static_company_profile(ticker)
    notes = [
        "Company profile from internal static seed.",
        *profile.profile_source_notes,
    ]
    return profile.model_copy(
        update={
            "profile_source": "manual_seed",
            "profile_confidence": DataConfidence.HIGH,
            "profile_as_of_date": profile.profile_as_of_date or date.today(),
            "profile_source_notes": _dedupe_preserve_order(notes),
        }
    )


def _minimal_profile(ticker: str) -> CompanyProfile:
    return CompanyProfile(
        ticker=ticker.upper().strip(),
        business_description="Company profile not yet available.",
        profile_source="llm_generated_unverified",
        profile_confidence=DataConfidence.LOW,
        profile_as_of_date=date.today(),
        profile_source_notes=[
            "Minimal fallback profile only; no manual seed, cached profile, "
            "or LLM-generated profile was used."
        ],
        profile_data_gaps=[
            "Business model",
            "Segments",
            "Peers",
            "Macro sensitivities",
            "Theme exposures",
        ],
    )


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        clean = value.strip() if isinstance(value, str) else str(value).strip()
        if not clean:
            continue
        key = clean.lower().rstrip(".!?:;").strip()
        if key in seen:
            continue
        seen.add(key)
        result.append(clean)
    return result
