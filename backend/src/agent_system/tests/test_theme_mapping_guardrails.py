from __future__ import annotations

from src.agent_system.schemas.deep_fundamental import (
    CompanyProfile,
    CompanySegment,
    PeerCompany,
    ThemeCatalogItem,
)
from src.agent_system.services.theme_mapping_agent import (
    build_theme_mapping_for_ticker,
)


def _catalog() -> list[ThemeCatalogItem]:
    return [
        ThemeCatalogItem(theme_id="memory_semis", label="Memory semiconductors"),
        ThemeCatalogItem(theme_id="high_beta_ai_semis", label="High beta AI semis"),
        ThemeCatalogItem(theme_id="grid_power_infrastructure", label="Grid power infrastructure"),
        ThemeCatalogItem(theme_id="quality_ai", label="Quality AI"),
        ThemeCatalogItem(theme_id="quality_ex_ai_cash_flow", label="Quality ex-AI cash flow"),
        ThemeCatalogItem(theme_id="commodities_real_assets", label="Commodities real assets"),
        ThemeCatalogItem(theme_id="small_caps", label="Small caps"),
    ]


def test_aapl_does_not_overmatch_semis_or_grid(monkeypatch, tmp_path):
    from src.agent_system.services import theme_mapping_agent

    monkeypatch.setattr(theme_mapping_agent, "THEME_MAPPING_ROOT", tmp_path)
    profile = CompanyProfile(
        ticker="AAPL",
        company_name="Apple Inc.",
        sector="Information Technology",
        industry="Consumer Electronics",
        business_description=(
            "Apple sells consumer devices, software, services, and designs "
            "Apple Silicon custom chips for its own product ecosystem."
        ),
        business_model=(
            "Integrated hardware, software, and services ecosystem; Apple "
            "does not sell semiconductors externally."
        ),
        thematic_exposures=["AI devices", "services ecosystem", "quality cash flow"],
        macro_sensitivities=["consumer demand", "FX", "China exposure"],
        margin_drivers=["services mix", "gross margin"],
    )

    result = build_theme_mapping_for_ticker("AAPL", profile, _catalog(), refresh=True)
    mapped_ids = {item.theme_id for item in result.mapped_themes}

    assert "memory_semis" not in mapped_ids
    assert "high_beta_ai_semis" not in mapped_ids
    assert "grid_power_infrastructure" not in mapped_ids
    assert "small_caps" not in mapped_ids
    assert "commodities_real_assets" not in mapped_ids
    assert "quality_ai" in mapped_ids


def test_jpm_does_not_overmatch_small_caps_or_commodities(monkeypatch, tmp_path):
    from src.agent_system.services import theme_mapping_agent

    monkeypatch.setattr(theme_mapping_agent, "THEME_MAPPING_ROOT", tmp_path)
    profile = CompanyProfile(
        ticker="JPM",
        company_name="JPMorgan Chase & Co.",
        sector="Financials",
        industry="Diversified Banks",
        business_description="JPMorgan Chase is a large global bank.",
        business_model=(
            "Banking, payments, investment banking, commodities trading, "
            "real estate lending, and asset management."
        ),
        thematic_exposures=["quality financials", "capital markets activity"],
        macro_sensitivities=["rates", "yield curve", "credit cycle", "deposit beta"],
        margin_drivers=["net interest income", "fee income", "credit costs"],
    )

    result = build_theme_mapping_for_ticker("JPM", profile, _catalog(), refresh=True)
    mapped_ids = {item.theme_id for item in result.mapped_themes}

    assert "small_caps" not in mapped_ids
    assert "commodities_real_assets" not in mapped_ids
    assert "grid_power_infrastructure" not in mapped_ids
    assert "memory_semis" not in mapped_ids


def test_mu_and_etn_keep_direct_theme_mappings(monkeypatch, tmp_path):
    from src.agent_system.services import theme_mapping_agent

    monkeypatch.setattr(theme_mapping_agent, "THEME_MAPPING_ROOT", tmp_path)
    mu = CompanyProfile(
        ticker="MU",
        company_name="Micron Technology",
        industry="Semiconductors / Memory",
        business_description="Micron manufactures DRAM, NAND, HBM, and storage semiconductors.",
        thematic_exposures=["memory semiconductors", "HBM", "AI infrastructure"],
        macro_sensitivities=["AI capex", "memory pricing cycle"],
    )
    etn = CompanyProfile(
        ticker="ETN",
        company_name="Eaton",
        industry="Electrical Equipment",
        business_description="Eaton sells electrical equipment, switchgear, transformers, and data center power infrastructure.",
        thematic_exposures=["grid modernization", "electrification", "data center power"],
        macro_sensitivities=["industrial capex", "data center capex"],
        margin_drivers=["pricing power", "free cash flow"],
    )

    mu_ids = {
        item.theme_id
        for item in build_theme_mapping_for_ticker("MU", mu, _catalog(), refresh=True).mapped_themes
    }
    etn_ids = {
        item.theme_id
        for item in build_theme_mapping_for_ticker("ETN", etn, _catalog(), refresh=True).mapped_themes
    }

    assert "memory_semis" in mu_ids
    assert "high_beta_ai_semis" in mu_ids
    assert "grid_power_infrastructure" in etn_ids
    assert "quality_ex_ai_cash_flow" in etn_ids
