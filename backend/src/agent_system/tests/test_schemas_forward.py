"""
Tests for agent_system.schemas.forward.

Forward context is optional macro metadata, but when present it must still be
strictly validated and immutable like the rest of the agent-system schemas.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.agent_system.schemas.forward import (
    FedPathReading,
    ForwardContext,
    InflationExpectations,
    MarketEvent,
    PredictionMarketReading,
)


def _fed_path_reading() -> FedPathReading:
    return FedPathReading(
        meeting_date="2026-06-17",
        prob_cut_50=0.02,
        prob_cut_25=0.18,
        prob_hold=0.70,
        prob_hike_25=0.09,
        prob_hike_50=0.01,
        source="CME FedWatch as of 2026-05-19",
    )


def _market_event() -> MarketEvent:
    return MarketEvent(
        name="FOMC June Meeting",
        date="2026-06-17",
        category="fed",
        significance="high",
        notes="Market pricing 70% hold.",
    )


def _prediction_market_reading() -> PredictionMarketReading:
    return PredictionMarketReading(
        contract_id="kalshi-fed-june-hold",
        question="Will the Federal Reserve hold rates at the June meeting?",
        current_probability=0.70,
        volume_usd=125000.0,
        source="kalshi",
        as_of=datetime.now(timezone.utc),
        notes="Illustrative contract reading.",
    )


class TestFedPathReading:
    def test_construction(self):
        reading = _fed_path_reading()
        assert reading.meeting_date == "2026-06-17"
        assert reading.prob_hold == 0.70

    def test_probabilities_sum_validation(self):
        with pytest.raises(ValidationError):
            FedPathReading(
                meeting_date="2026-06-17",
                prob_cut_50=0.25,
                prob_cut_25=0.25,
                prob_hold=0.25,
                prob_hike_25=0.25,
                prob_hike_50=0.25,
                source="CME FedWatch as of 2026-05-19",
            )

    def test_date_format(self):
        with pytest.raises(ValidationError):
            FedPathReading(
                meeting_date="2026/06/17",
                prob_cut_50=0.02,
                prob_cut_25=0.18,
                prob_hold=0.70,
                prob_hike_25=0.09,
                prob_hike_50=0.01,
                source="CME FedWatch as of 2026-05-19",
            )


class TestInflationExpectations:
    def test_all_fields(self):
        snapshot = InflationExpectations(
            breakeven_2y=2.6,
            breakeven_5y=2.45,
            breakeven_10y=2.35,
            forward_5y5y=2.25,
            as_of=datetime.now(timezone.utc),
            trend_30d="rising",
            notes="5y breakeven up 30bps in 30 days",
        )
        assert snapshot.trend_30d == "rising"

    def test_all_none(self):
        snapshot = InflationExpectations(as_of=datetime.now(timezone.utc))
        assert snapshot.breakeven_5y is None

    def test_partial_fields(self):
        snapshot = InflationExpectations(
            breakeven_5y=2.45,
            as_of=datetime.now(timezone.utc),
        )
        assert snapshot.breakeven_5y == 2.45
        assert snapshot.forward_5y5y is None


class TestMarketEvent:
    def test_construction(self):
        event = _market_event()
        assert event.category == "fed"

    def test_date_format(self):
        with pytest.raises(ValidationError):
            MarketEvent(
                name="FOMC June Meeting",
                date="06-17-2026",
                category="fed",
                significance="high",
            )

    def test_category_enum_bounds(self):
        with pytest.raises(ValidationError):
            MarketEvent(
                name="FOMC June Meeting",
                date="2026-06-17",
                category="central_bank",
                significance="high",
            )

    def test_significance_enum_bounds(self):
        with pytest.raises(ValidationError):
            MarketEvent(
                name="FOMC June Meeting",
                date="2026-06-17",
                category="fed",
                significance="urgent",
            )


class TestPredictionMarketReading:
    def test_construction(self):
        reading = _prediction_market_reading()
        assert reading.current_probability == 0.70

    def test_unit_interval_bounds(self):
        with pytest.raises(ValidationError):
            PredictionMarketReading(
                contract_id="kalshi-fed-june-hold",
                question="Will the Federal Reserve hold rates at the June meeting?",
                current_probability=1.2,
                volume_usd=125000.0,
                source="kalshi",
                as_of=datetime.now(timezone.utc),
            )


class TestForwardContext:
    def test_composition(self):
        context = ForwardContext(
            fed_path=[_fed_path_reading()],
            inflation_expectations=InflationExpectations(
                breakeven_5y=2.45,
                as_of=datetime.now(timezone.utc),
            ),
            upcoming_catalysts=[_market_event()],
            prediction_market_signals=[_prediction_market_reading()],
            as_of=datetime.now(timezone.utc),
            data_quality_notes="All sources present in fixture.",
        )
        assert len(context.fed_path) == 1
        assert context.upcoming_catalysts[0].name == "FOMC June Meeting"

    def test_max_length_constraints(self):
        with pytest.raises(ValidationError):
            ForwardContext(
                fed_path=[_fed_path_reading()] * 9,
                as_of=datetime.now(timezone.utc),
            )
        with pytest.raises(ValidationError):
            ForwardContext(
                upcoming_catalysts=[_market_event()] * 31,
                as_of=datetime.now(timezone.utc),
            )
        with pytest.raises(ValidationError):
            ForwardContext(
                prediction_market_signals=[_prediction_market_reading()] * 21,
                as_of=datetime.now(timezone.utc),
            )

    @pytest.mark.parametrize(
        "obj",
        [
            _fed_path_reading(),
            InflationExpectations(as_of=datetime.now(timezone.utc)),
            _market_event(),
            _prediction_market_reading(),
            ForwardContext(as_of=datetime.now(timezone.utc)),
        ],
    )
    def test_all_forward_schemas_are_frozen(self, obj):
        with pytest.raises(ValidationError):
            obj.created_at = datetime.now(timezone.utc)
