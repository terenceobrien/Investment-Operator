"""Tests for SEC/Yahoo fundamental-data plumbing."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from src.agent_system.data import bundle, cache, sec
from src.agent_system.data.types import FundamentalDataBundle
from src.agent_system.data.yahoo import parse_yahoo_data


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_ROOT", tmp_path / "data_cache")


def test_ticker_to_cik_uses_mocked_sec_ticker_response(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"0": {"ticker": "AAPL", "cik_str": 320193}}

    monkeypatch.setattr(sec, "_REQUEST_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(sec.requests, "get", lambda *args, **kwargs: Response())

    assert sec.ticker_to_cik("AAPL", force_refresh=True) == "0000320193"


def test_parse_company_facts_handles_missing_tags_gracefully():
    raw = {
        "facts": {
            "us-gaap": {
                "Assets": {
                    "units": {"USD": [{"val": 125.0, "end": "2026-03-31"}]}
                }
            }
        }
    }

    facts = sec.parse_company_facts(raw)

    assert facts.total_assets == 125.0
    assert facts.revenue_ttm is None
    assert facts.free_cash_flow_ttm is None
    assert facts.total_debt is None
    assert facts.depreciation_amortization_ttm is None
    assert facts.ebitda_ttm is None


def test_parse_company_facts_computes_ttm_and_free_cash_flow():
    def quarterly(values):
        return [
            {
                "val": value,
                "start": f"2025-{month:02d}-01",
                "end": end,
                "frame": frame,
            }
            for value, month, end, frame in values
        ]

    raw = {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": quarterly(
                            [
                                (10, 1, "2025-03-31", "CY2025Q1"),
                                (11, 4, "2025-06-30", "CY2025Q2"),
                                (12, 7, "2025-09-30", "CY2025Q3"),
                                (13, 10, "2025-12-31", "CY2025Q4"),
                            ]
                        )
                    }
                },
                "NetCashProvidedByUsedInOperatingActivities": {
                    "units": {
                        "USD": quarterly(
                            [
                                (5, 1, "2025-03-31", "CY2025Q1"),
                                (5, 4, "2025-06-30", "CY2025Q2"),
                                (6, 7, "2025-09-30", "CY2025Q3"),
                                (6, 10, "2025-12-31", "CY2025Q4"),
                            ]
                        )
                    }
                },
                "PaymentsToAcquirePropertyPlantAndEquipment": {
                    "units": {
                        "USD": quarterly(
                            [
                                (1, 1, "2025-03-31", "CY2025Q1"),
                                (1, 4, "2025-06-30", "CY2025Q2"),
                                (2, 7, "2025-09-30", "CY2025Q3"),
                                (2, 10, "2025-12-31", "CY2025Q4"),
                            ]
                        )
                    }
                },
            }
        }
    }

    facts = sec.parse_company_facts(raw)

    assert facts.revenue_ttm == 46.0
    assert facts.operating_cash_flow_ttm == 22.0
    assert facts.capex_ttm == 6.0
    assert facts.free_cash_flow_ttm == 16.0
    assert facts.most_recent_quarter_end.isoformat() == "2025-12-31"


def test_parse_company_facts_extracts_da_and_computes_ebitda():
    def quarterly(values):
        return [
            {
                "val": value,
                "start": f"2025-{month:02d}-01",
                "end": end,
                "frame": frame,
            }
            for value, month, end, frame in values
        ]

    raw = {
        "facts": {
            "us-gaap": {
                "OperatingIncomeLoss": {
                    "units": {
                        "USD": quarterly(
                            [
                                (800, 1, "2025-03-31", "CY2025Q1"),
                                (850, 4, "2025-06-30", "CY2025Q2"),
                                (900, 7, "2025-09-30", "CY2025Q3"),
                                (950, 10, "2025-12-31", "CY2025Q4"),
                            ]
                        )
                    }
                },
                "DepreciationDepletionAndAmortization": {
                    "units": {
                        "USD": quarterly(
                            [
                                (350, 1, "2025-03-31", "CY2025Q1"),
                                (400, 4, "2025-06-30", "CY2025Q2"),
                                (450, 7, "2025-09-30", "CY2025Q3"),
                                (500, 10, "2025-12-31", "CY2025Q4"),
                            ]
                        )
                    }
                },
            }
        }
    }

    facts = sec.parse_company_facts(raw)

    assert facts.operating_income_ttm == 3500.0
    assert facts.depreciation_amortization_ttm == 1700.0
    assert facts.ebitda_ttm == 5200.0


def test_parse_company_facts_ebitda_none_when_da_tag_absent():
    raw = {
        "facts": {
            "us-gaap": {
                "OperatingIncomeLoss": {
                    "units": {
                        "USD": [
                            {
                                "val": 100.0,
                                "fp": "FY",
                                "start": "2025-01-01",
                                "end": "2025-12-31",
                            }
                        ]
                    }
                }
            }
        }
    }

    facts = sec.parse_company_facts(raw)

    assert facts.operating_income_ttm == 100.0
    assert facts.depreciation_amortization_ttm is None
    assert facts.ebitda_ttm is None


def test_parse_company_facts_prefers_current_tag_and_rolls_forward_ytd():
    raw = {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {"val": 25, "end": "2018-03-31", "frame": "CY2018Q1"}
                        ]
                    }
                },
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {
                        "USD": [
                            {
                                "val": 100,
                                "fp": "FY",
                                "start": "2024-10-01",
                                "end": "2025-09-30",
                            },
                            {
                                "val": 20,
                                "fp": "Q1",
                                "start": "2024-10-01",
                                "end": "2024-12-31",
                            },
                            {
                                "val": 30,
                                "fp": "Q1",
                                "start": "2025-10-01",
                                "end": "2025-12-31",
                            },
                        ]
                    }
                },
            }
        }
    }

    facts = sec.parse_company_facts(raw)

    assert facts.revenue_ttm == 110.0


def test_parse_company_facts_computes_historical_growth_and_margins():
    def annual(value, year):
        return {
            "val": value,
            "fp": "FY",
            "start": f"{year}-01-01",
            "end": f"{year}-12-31",
            "filed": f"{year + 1}-02-15",
        }

    raw = {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            annual(100.0, 2022),
                            annual(121.0, 2023),
                            annual(133.1, 2024),
                            annual(146.41, 2025),
                        ]
                    }
                },
                "GrossProfit": {"units": {"USD": [annual(73.205, 2025)]}},
                "OperatingIncomeLoss": {"units": {"USD": [annual(29.282, 2025)]}},
                "NetIncomeLoss": {"units": {"USD": [annual(14.641, 2025)]}},
            }
        }
    }

    facts = sec.parse_company_facts(raw)

    assert [r.revenue for r in facts.annual_revenue_history] == [
        146.41,
        133.1,
        121.0,
        100.0,
    ]
    assert facts.revenue_yoy_growth == pytest.approx(0.10)
    assert facts.revenue_3yr_cagr == pytest.approx(0.135, abs=0.001)
    assert facts.gross_margin == pytest.approx(0.50)
    assert facts.operating_margin == pytest.approx(0.20)
    assert facts.net_margin == pytest.approx(0.10)


def test_parse_company_facts_growth_fields_none_with_insufficient_history():
    raw = {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {
                                "val": 100.0,
                                "fp": "FY",
                                "start": "2025-01-01",
                                "end": "2025-12-31",
                            }
                        ]
                    }
                }
            }
        }
    }

    facts = sec.parse_company_facts(raw)

    assert len(facts.annual_revenue_history) == 1
    assert facts.revenue_yoy_growth is None
    assert facts.revenue_3yr_cagr is None


def test_parse_company_facts_margins_none_when_revenue_zero_or_missing():
    raw = {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {
                                "val": 0.0,
                                "fp": "FY",
                                "start": "2025-01-01",
                                "end": "2025-12-31",
                            }
                        ]
                    }
                },
                "GrossProfit": {
                    "units": {
                        "USD": [
                            {
                                "val": 50.0,
                                "fp": "FY",
                                "start": "2025-01-01",
                                "end": "2025-12-31",
                            }
                        ]
                    }
                },
            }
        }
    }

    facts = sec.parse_company_facts(raw)

    assert facts.gross_margin is None
    assert facts.operating_margin is None
    assert facts.net_margin is None


def test_parse_yahoo_data_handles_missing_keys_gracefully():
    values = parse_yahoo_data({})

    assert values["current_price"] is None
    assert values["mean_price_target"] is None
    assert values["analyst_count_buy"] is None
    assert values["sector"] is None
    assert values["industry"] is None
    assert values["is_etf"] is False


def test_parse_yahoo_data_extracts_sector_and_industry():
    values = parse_yahoo_data(
        {
            "currentPrice": 10.0,
            "sector": "Utilities",
            "industry": "Utilities - Regulated Electric",
        }
    )

    assert values["sector"] == "Utilities"
    assert values["industry"] == "Utilities - Regulated Electric"


def test_cache_get_returns_fresh_payload_and_none_when_stale():
    cache.cache_set("provider", "AAPL", {"price": 100})
    assert cache.cache_get("provider", "AAPL", timedelta(minutes=5)) == {
        "price": 100
    }

    path = cache.CACHE_ROOT / "provider" / "AAPL.json"
    path.write_text(
        json.dumps(
            {
                "written_at": (
                    datetime.now(timezone.utc) - timedelta(hours=1)
                ).isoformat(),
                "data": {"price": 50},
            }
        ),
        encoding="utf-8",
    )
    assert cache.cache_get("provider", "AAPL", timedelta(minutes=5)) is None


def test_get_fundamental_data_returns_bundle_when_both_sources_fail(monkeypatch):
    monkeypatch.setattr(bundle, "fetch_yahoo_data", lambda *args, **kwargs: {})
    monkeypatch.setattr(bundle, "fetch_earnings_history", lambda *args, **kwargs: [])
    monkeypatch.setattr(bundle, "ticker_to_cik", lambda *args, **kwargs: None)

    result = bundle.get_fundamental_data("NOPE")

    assert isinstance(result, FundamentalDataBundle)
    assert result.sec_fetch_success is False
    assert result.yahoo_fetch_success is False
    assert result.fetch_errors


def test_placeholder_yahoo_response_does_not_count_as_success(monkeypatch):
    monkeypatch.setattr(
        bundle,
        "fetch_yahoo_data",
        lambda *args, **kwargs: {"trailingPegRatio": None},
    )
    monkeypatch.setattr(bundle, "fetch_earnings_history", lambda *args, **kwargs: [])
    monkeypatch.setattr(bundle, "ticker_to_cik", lambda *args, **kwargs: None)

    result = bundle.get_fundamental_data("XXXFAKE")

    assert result.yahoo_fetch_success is False
    assert "Yahoo response contained no usable quote data" in result.fetch_errors


def test_yahoo_data_survives_sec_failure(monkeypatch):
    monkeypatch.setattr(
        bundle,
        "fetch_yahoo_data",
        lambda *args, **kwargs: {"quoteType": "EQUITY", "currentPrice": 42.5},
    )
    monkeypatch.setattr(bundle, "fetch_earnings_history", lambda *args, **kwargs: [])
    monkeypatch.setattr(bundle, "ticker_to_cik", lambda *args, **kwargs: None)

    result = bundle.get_fundamental_data("ONLYY")

    assert result.yahoo_fetch_success is True
    assert result.sec_fetch_success is False
    assert result.current_price == 42.5


def test_sec_data_survives_yahoo_failure(monkeypatch):
    monkeypatch.setattr(bundle, "fetch_yahoo_data", lambda *args, **kwargs: {})
    monkeypatch.setattr(bundle, "fetch_earnings_history", lambda *args, **kwargs: [])
    monkeypatch.setattr(bundle, "ticker_to_cik", lambda *args, **kwargs: "0000000001")
    monkeypatch.setattr(
        bundle,
        "fetch_submissions",
        lambda *args, **kwargs: {"cik": "1", "name": "SEC Only Corp"},
    )
    monkeypatch.setattr(
        bundle,
        "fetch_company_facts",
        lambda *args, **kwargs: {
            "entityName": "SEC Only Corp",
            "facts": {"us-gaap": {}},
        },
    )
    monkeypatch.setattr(bundle, "fetch_most_recent_filing", lambda *args, **kwargs: None)
    monkeypatch.setattr(bundle, "fetch_recent_8ks", lambda *args, **kwargs: [])

    result = bundle.get_fundamental_data("ONLYS")

    assert result.yahoo_fetch_success is False
    assert result.sec_fetch_success is True
    assert result.company_name == "SEC Only Corp"
    assert result.company_facts is not None


def test_etf_detection_skips_sec_fetches(monkeypatch):
    monkeypatch.setattr(
        bundle,
        "fetch_yahoo_data",
        lambda *args, **kwargs: {
            "quoteType": "ETF",
            "regularMarketPrice": 525.0,
        },
    )
    monkeypatch.setattr(bundle, "fetch_earnings_history", lambda *args, **kwargs: [])

    def _sec_should_not_run(*args, **kwargs):
        raise AssertionError("ETF path attempted SEC access")

    monkeypatch.setattr(bundle, "ticker_to_cik", _sec_should_not_run)

    result = bundle.get_fundamental_data("SPY")

    assert result.is_etf is True
    assert result.current_price == 525.0
    assert result.cik is None
    assert result.most_recent_10k is None


def test_foreign_issuer_uses_20f_when_10k_is_absent(monkeypatch):
    submissions = {
        "cik": "123456",
        "filings": {
            "recent": {
                "form": ["20-F"],
                "filingDate": ["2026-03-20"],
                "reportDate": ["2025-12-31"],
                "accessionNumber": ["0000123456-26-000001"],
                "primaryDocument": ["foreign-20f.htm"],
            }
        },
    }
    monkeypatch.setattr(
        sec,
        "_fetch_filing_text_with_metadata",
        lambda *args, **kwargs: ("Annual foreign filing text.", False, "primary_doc"),
    )

    filing = sec.fetch_most_recent_filing(submissions, ["10-K"])

    assert filing is not None
    assert filing.filing_type == "20-F"
    assert filing.period_of_report.isoformat() == "2025-12-31"
    assert "123456" in filing.primary_document_url


def test_filing_section_extraction_skips_table_of_contents_heading():
    text = (
        "Item 1A. Risk Factors 5 Item 7. Management's Discussion 21 "
        "Item 1A. Risk Factors Detailed risks in the filing body. "
        "Item 2. Properties "
        "Item 7. Management's Discussion and Analysis "
        "Detailed operating discussion in the filing body. Item 8. Financials"
    )

    extracted, method = sec._extract_relevant_sections(text)

    assert method == "primary_doc_sections"
    assert "Detailed risks in the filing body" in extracted
    assert "Detailed operating discussion in the filing body" in extracted
    assert "Risk Factors 5 Item 7" not in extracted


@pytest.mark.skipif(
    os.getenv("INTEGRATION_TESTS") != "1",
    reason="Set INTEGRATION_TESTS=1 to run provider integration tests.",
)
def test_integration_fetch_aapl():
    result = bundle.get_fundamental_data("AAPL")

    assert result.ticker == "AAPL"
    assert result.is_etf is False
    assert result.cik == "0000320193"
    assert result.current_price is not None


@pytest.mark.skipif(
    os.getenv("INTEGRATION_TESTS") != "1",
    reason="Set INTEGRATION_TESTS=1 to run provider integration tests.",
)
def test_integration_fetch_spy_skips_sec():
    result = bundle.get_fundamental_data("SPY")

    assert result.is_etf is True
    assert result.cik is None
    assert result.company_facts is None


@pytest.mark.skipif(
    os.getenv("INTEGRATION_TESTS") != "1",
    reason="Set INTEGRATION_TESTS=1 to run provider integration tests.",
)
def test_integration_fetch_powl():
    result = bundle.get_fundamental_data("POWL")

    assert result.ticker == "POWL"
    assert result.is_etf is False
    assert result.sec_fetch_success or result.yahoo_fetch_success


@pytest.mark.skipif(
    os.getenv("INTEGRATION_TESTS") != "1",
    reason="Set INTEGRATION_TESTS=1 to run provider integration tests.",
)
def test_integration_nonexistent_ticker_degrades_gracefully():
    result = bundle.get_fundamental_data("XXXFAKE")

    assert isinstance(result, FundamentalDataBundle)
    assert result.ticker == "XXXFAKE"
    assert result.fetch_errors
