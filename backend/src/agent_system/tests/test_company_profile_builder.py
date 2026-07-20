from __future__ import annotations

import asyncio
from datetime import date

from src.agent_system.agents.company_profile_agent_prompts import (
    render_company_profile_input_context,
    render_financial_context_summary,
    render_research_context_summary,
)
from src.agent_system.schemas.deep_fundamental import (
    CompanyProfile,
    CompanySegment,
    DataConfidence,
    PeerCompany,
)
from src.agent_system.services import company_profile_builder


def test_company_profile_schema_has_source_metadata():
    profile = CompanyProfile(ticker="TEST")

    assert profile.profile_source == "llm_generated_unverified"
    assert profile.profile_confidence == DataConfidence.MEDIUM
    assert profile.profile_source_notes == []
    assert profile.profile_data_gaps == []


def test_company_profile_prompt_renderers_are_defensive():
    assert render_financial_context_summary(None) == "None supplied."
    assert render_research_context_summary(None) == "None supplied."

    rendered = render_company_profile_input_context(
        ticker="AAPL",
        company_name="Apple Inc.",
        financial_context={"ticker": "AAPL"},
        research_context=None,
        existing_profile=CompanyProfile(ticker="AAPL"),
        as_of_date=date(2026, 6, 28),
    )

    assert "AAPL" in rendered
    assert "Apple Inc." in rendered


def test_manual_seed_profile_is_labeled_manual():
    profile = company_profile_builder.build_company_profile("MU")

    assert profile.profile_source == "manual_seed"
    assert profile.profile_confidence == DataConfidence.HIGH
    assert any("static seed" in note.lower() for note in profile.profile_source_notes)


def test_minimal_fallback_when_no_seed_cache_or_llm(monkeypatch, tmp_path):
    monkeypatch.setattr(
        company_profile_builder,
        "COMPANY_PROFILE_CACHE_ROOT",
        tmp_path,
    )

    profile = company_profile_builder.build_company_profile(
        "NOSEEDTEST",
        use_llm_profile=False,
    )

    assert profile.ticker == "NOSEEDTEST"
    assert profile.profile_confidence == DataConfidence.LOW
    assert profile.profile_data_gaps


def test_async_generated_profile_is_cached(monkeypatch, tmp_path):
    monkeypatch.setattr(
        company_profile_builder,
        "COMPANY_PROFILE_CACHE_ROOT",
        tmp_path,
    )

    async def fake_generate_company_profile(**kwargs):
        return CompanyProfile(
            ticker=kwargs["ticker"],
            company_name="Apple Inc.",
            sector="Information Technology",
            industry="Consumer Electronics",
            business_description="Apple sells devices, software, and services.",
            business_model="Integrated hardware, software, and services ecosystem.",
            segments=[
                CompanySegment(
                    name="iPhone",
                    description="Smartphone products.",
                    key_drivers=["replacement cycle", "installed base"],
                )
            ],
            peer_group=[
                PeerCompany(ticker="MSFT", name="Microsoft", relevance="Mega-cap platform peer")
            ],
            thematic_exposures=["consumer tech", "services ecosystem"],
            macro_sensitivities=["consumer demand", "FX", "China exposure"],
            major_risks=["App Store regulation"],
            profile_source="llm_generated_unverified",
            profile_confidence=DataConfidence.MEDIUM,
            profile_as_of_date=date(2026, 6, 28),
            profile_source_notes=["fake generated profile"],
        )

    from src.agent_system.agents import company_profile_agent

    monkeypatch.setattr(
        company_profile_agent,
        "generate_company_profile",
        fake_generate_company_profile,
    )

    profile = asyncio.run(
        company_profile_builder.build_company_profile_async(
            "AAPL",
            use_llm_profile=True,
        )
    )
    cached = company_profile_builder.load_company_profile("AAPL")

    assert profile.company_name == "Apple Inc."
    assert cached is not None
    assert cached.company_name == "Apple Inc."
