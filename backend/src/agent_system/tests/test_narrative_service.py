from __future__ import annotations

from datetime import date

import pytest

from src.agent_system import narrative_service as service
from src.narrative.schema import (
    DominantNarrative,
    EvidenceItem,
    ExecutiveSnapshot,
    InefficiencyMapItem,
    NarrativeStateV1,
)
from src.narrative.synth import save_narrative_snapshot
from src.narrative.ticker_profiles import normalize_ticker


TODAY = date(2026, 6, 5)


def _narrative(
    title: str,
    *,
    tickers: list[str],
    stance: str = "mixed",
    confidence: int = 70,
    evidence_titles: list[str] | None = None,
    takeaways: list[str] | None = None,
) -> DominantNarrative:
    return DominantNarrative(
        title=title,
        stance=stance,
        confidence=confidence,
        why_now=f"{title} why now",
        takeaways=takeaways or ["PRICE: price is confirming the narrative."],
        tickers=tickers,
        evidence=[
            EvidenceItem(channel="news", source="fixture", title=title)
            for title in (evidence_titles or [])
        ],
    )


def _state(
    narratives: list[DominantNarrative],
    *,
    subject: str = "SPY",
    inefficiencies: list[InefficiencyMapItem] | None = None,
    price_confirmation: str = "Confirming",
) -> dict:
    return NarrativeStateV1(
        asof_utc=f"{TODAY.isoformat()}T10:00:00+00:00",
        dominant_narratives=narratives,
        executive_snapshot=ExecutiveSnapshot(price_confirmation=price_confirmation),
        inefficiency_map=inefficiencies or [],
    ).model_dump(mode="json") | {"_meta": {"subject": {"ticker": subject}}}


def _write_snapshot(
    tmp_path,
    *,
    subject: str,
    snapshot_date: date = TODAY,
    narratives: list[DominantNarrative],
    inefficiencies: list[InefficiencyMapItem] | None = None,
    price_confirmation: str = "Confirming",
) -> None:
    save_narrative_snapshot(
        _state(
            narratives,
            subject=subject,
            inefficiencies=inefficiencies,
            price_confirmation=price_confirmation,
        ),
        tmp_path,
        snapshot_date.isoformat(),
        subject_key=subject,
    )


@pytest.fixture
def service_tmp(monkeypatch, tmp_path):
    monkeypatch.setattr(service, "SNAPSHOT_DIR", tmp_path)
    monkeypatch.setattr(service, "_today_utc", lambda: TODAY)
    return tmp_path


def _patch_sector_map(monkeypatch, mapping: dict[str, str]) -> None:
    original = service.get_ticker_profile

    def fake_profile(ticker):
        normalized = normalize_ticker(ticker)
        if normalized in mapping:
            return {
                "ticker": normalized,
                "name": normalized,
                "sector_etf": mapping[normalized],
                "company_aliases": [normalized],
            }
        return original(ticker)

    monkeypatch.setattr(service, "get_ticker_profile", fake_profile)


def test_get_ticker_narrative_high_coverage(service_tmp):
    _write_snapshot(
        service_tmp,
        subject="SPY",
        narratives=[
            _narrative("AI leadership", tickers=["NVDA"], evidence_titles=["NVDA guidance"]),
            _narrative("Semis momentum", tickers=["NVDA", "AAPL"]),
        ],
    )

    result = service.get_ticker_narrative("NVDA")

    assert result.coverage_quality == "high"
    assert result.dominant_narrative_title == "AI leadership"
    assert result.snapshot_subject == "SPY"


def test_get_ticker_narrative_medium_coverage(service_tmp):
    _write_snapshot(
        service_tmp,
        subject="SPY",
        narratives=[_narrative("Single mention", tickers=["AAPL"], evidence_titles=[])],
    )

    result = service.get_ticker_narrative("AAPL")

    assert result.coverage_quality == "medium"
    assert result.dominant_narrative_title == "Single mention"


def test_get_ticker_narrative_absent(service_tmp):
    _write_snapshot(
        service_tmp,
        subject="SPY",
        narratives=[_narrative("Broad market", tickers=["SPY"])],
    )

    result = service.get_ticker_narrative("AMZN")

    assert result.coverage_quality == "absent"
    assert result.ticker == "AMZN"
    assert result.sector_etf is not None


def test_get_ticker_narrative_stale(service_tmp):
    _write_snapshot(
        service_tmp,
        subject="SPY",
        snapshot_date=date(2026, 6, 2),
        narratives=[_narrative("Stale AI", tickers=["MSFT"])],
    )

    result = service.get_ticker_narrative("MSFT")

    assert result.is_stale is True
    assert result.coverage_quality == "medium"


def test_snapshot_selection_prefers_more_prominent(service_tmp):
    _write_snapshot(
        service_tmp,
        subject="SPY",
        narratives=[_narrative("SPY AI", tickers=["NVDA"], confidence=90)],
    )
    _write_snapshot(
        service_tmp,
        subject="QQQ",
        narratives=[
            _narrative(
                "QQQ AI",
                tickers=["NVDA"],
                confidence=80,
                evidence_titles=["Nvidia NVDA evidence item"],
            )
        ],
    )

    result = service.get_ticker_narrative("NVDA")

    assert result.snapshot_subject == "QQQ"
    assert result.dominant_narrative_title == "QQQ AI"


def test_get_sector_narrative_aggregates_tickers(service_tmp, monkeypatch):
    _patch_sector_map(
        monkeypatch,
        {"AMZN": "XLY", "TSLA": "XLY", "HD": "XLY", "LOW": "XLY"},
    )
    _write_snapshot(
        service_tmp,
        subject="SPY",
        narratives=[_narrative("Consumer discretionary", tickers=["AMZN", "TSLA", "HD", "LOW"])],
    )

    result = service.get_sector_narrative("XLY")

    assert result.coverage_quality == "high"
    assert result.sector_ticker_count == 4
    assert result.sector_tickers_in_narrative == ["AMZN", "TSLA", "HD", "LOW"]


def test_divergence_stance_opposite(service_tmp, monkeypatch):
    _patch_sector_map(monkeypatch, {"AAA": "XLY", "BBB": "XLY", "CCC": "XLY"})
    _write_snapshot(
        service_tmp,
        subject="SPY",
        narratives=[
            _narrative("Ticker upside", tickers=["AAA"], stance="risk_on", evidence_titles=["AAA"]),
            _narrative("Sector pressure", tickers=["BBB", "CCC"], stance="risk_off"),
        ],
    )

    signal = service.detect_ticker_sector_divergence("AAA")

    assert signal is not None
    assert signal.divergence_type == "stance_opposite"
    assert signal.ticker_stance == "risk_on"
    assert signal.sector_stance == "risk_off"


def test_divergence_idiosyncratic_story(service_tmp, monkeypatch):
    _patch_sector_map(
        monkeypatch,
        {
            "AAA": "XLY",
            "BBB": "XLY",
            "CCC": "XLY",
            "NVDA": "SMH",
            "MSFT": "XLK",
            "META": "XLC",
            "GLD": "GLD",
        },
    )
    _write_snapshot(
        service_tmp,
        subject="SPY",
        narratives=[
            _narrative(
                "Cross-sector AI basket",
                tickers=["AAA", "NVDA", "MSFT", "META", "GLD"],
                evidence_titles=["AAA joins AI basket"],
            ),
            _narrative("Sector base", tickers=["BBB", "CCC"], stance="mixed"),
        ],
    )

    signal = service.detect_ticker_sector_divergence("AAA")

    assert signal is not None
    assert signal.divergence_type == "idiosyncratic_story"


def test_divergence_no_signal_when_insufficient_data(service_tmp, monkeypatch):
    _patch_sector_map(monkeypatch, {"AAA": "XLY", "BBB": "XLY", "CCC": "XLY"})
    _write_snapshot(
        service_tmp,
        subject="SPY",
        narratives=[
            _narrative("Weak ticker", tickers=["AAA"], confidence=25),
            _narrative("Sector base", tickers=["BBB", "CCC"], confidence=70),
        ],
    )

    assert service.detect_ticker_sector_divergence("AAA") is None


def test_no_snapshots_returns_absent(service_tmp):
    result = service.get_ticker_narrative("NVDA")

    assert result.coverage_quality == "absent"
    assert result.ticker == "NVDA"
    assert service.get_market_narrative_state() is None
