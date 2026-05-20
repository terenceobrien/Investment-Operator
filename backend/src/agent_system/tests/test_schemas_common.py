"""
Tests for agent_system.schemas.common.

These tests are also living documentation: each test name describes a
property of the schema layer, and the test body shows a minimal example.
When you're unsure how to construct one of these types, find the test that
exercises it.

Run with:
    pytest backend/src/agent_system/tests/test_schemas_common.py -v
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import HttpUrl, ValidationError

from src.agent_system.schemas.common import (
    BaseSchema,
    Catalyst,
    CatalystType,
    Conviction,
    ConvictionRating,
    DerivedEvidence,
    Evidence,
    EvidenceSourceType,
    Falsifier,
    FalsifierFrequency,
    FalsifierObservable,
    FalsifierStatus,
    FilingEvidence,
    FREDEvidence,
    InefficiencyArchetype,
    NewsEvidence,
    PositioningEvidence,
    PriceEvidence,
    archetype_from_taxonomy_id,
)
from pydantic import TypeAdapter

EvidenceAdapter = TypeAdapter(Evidence)


# ─────────────────────────────────────────────────────────────────────────────
# ConvictionRating — ordering and threshold checks
# ─────────────────────────────────────────────────────────────────────────────


class TestConvictionRating:
    def test_ranks_are_ordered(self):
        assert ConvictionRating.PASS.rank == 0
        assert ConvictionRating.WEAK.rank == 1
        assert ConvictionRating.MODERATE.rank == 2
        assert ConvictionRating.STRONG.rank == 3
        assert ConvictionRating.EXCEPTIONAL.rank == 4

    def test_at_least_works_for_threshold_checks(self):
        assert ConvictionRating.STRONG.at_least(ConvictionRating.MODERATE)
        assert ConvictionRating.STRONG.at_least(ConvictionRating.STRONG)
        assert not ConvictionRating.WEAK.at_least(ConvictionRating.STRONG)

    def test_string_values_are_stable(self):
        # Downstream storage uses these strings as enum values.
        # Changing them is a schema-breaking change.
        assert ConvictionRating.EXCEPTIONAL.value == "exceptional"
        assert ConvictionRating.PASS.value == "pass"


# ─────────────────────────────────────────────────────────────────────────────
# InefficiencyArchetype — sync with the taxonomy
# ─────────────────────────────────────────────────────────────────────────────


class TestInefficiencyArchetype:
    def test_contains_unknown_sentinel(self):
        assert InefficiencyArchetype.UNKNOWN.value == "unknown_unclassified"

    def test_contains_all_14_archetypes(self):
        # The v1 taxonomy has 14 numbered archetypes plus our UNKNOWN sentinel.
        # If you add a 15th archetype to inefficiency_taxonomy.py, this test
        # will fail and you'll know to update the expected count here.
        assert len(InefficiencyArchetype) == 15

    def test_contains_specific_known_archetype(self):
        # Spot-check a few that we explicitly depend on elsewhere.
        assert InefficiencyArchetype("narrative_fundamental_divergence")
        assert InefficiencyArchetype("speculative_bubble_mania")
        assert InefficiencyArchetype("regime_shift")

    def test_archetype_from_taxonomy_id_resolves_exact_id(self):
        result = archetype_from_taxonomy_id("narrative_fundamental_divergence")
        assert result == InefficiencyArchetype("narrative_fundamental_divergence")

    def test_archetype_from_taxonomy_id_returns_unknown_for_garbage(self):
        assert archetype_from_taxonomy_id("not a real archetype") == InefficiencyArchetype.UNKNOWN
        assert archetype_from_taxonomy_id(None) == InefficiencyArchetype.UNKNOWN
        assert archetype_from_taxonomy_id("") == InefficiencyArchetype.UNKNOWN


# ─────────────────────────────────────────────────────────────────────────────
# Immutability — frozen models reject mutation
# ─────────────────────────────────────────────────────────────────────────────


class TestImmutability:
    def test_evidence_cannot_be_mutated(self):
        ev = FREDEvidence(
            claim="10y yields rising",
            supports=True,
            series_id="DGS10",
            observation_date=datetime.now(timezone.utc),
            observation_value=4.5,
        )
        with pytest.raises(ValidationError):
            ev.claim = "different claim"

    def test_falsifier_cannot_be_mutated(self):
        f = Falsifier(
            condition="oil falls below $70 for 5 sessions",
            observable_in=FalsifierObservable.PRICE_ACTION,
            check_frequency=FalsifierFrequency.DAILY,
        )
        with pytest.raises(ValidationError):
            f.current_status = FalsifierStatus.TRIGGERED

    def test_model_copy_creates_modified_version(self):
        # Immutability doesn't mean you can never get a changed version —
        # you create a new one with model_copy(update=...).
        original = Falsifier(
            condition="oil falls below $70 for 5 sessions",
            observable_in=FalsifierObservable.PRICE_ACTION,
            check_frequency=FalsifierFrequency.DAILY,
        )
        updated = original.model_copy(
            update={"current_status": FalsifierStatus.TRIGGERED}
        )
        # Original is untouched, new one has the change.
        assert original.current_status == FalsifierStatus.NOT_TRIGGERED
        assert updated.current_status == FalsifierStatus.TRIGGERED


# ─────────────────────────────────────────────────────────────────────────────
# Extra fields rejected — catches typos in agent output
# ─────────────────────────────────────────────────────────────────────────────


class TestStrictValidation:
    def test_unknown_field_rejected(self):
        # Without extra="forbid", an LLM that emits a misspelled field name
        # would silently drop the data. With it, we catch the typo at parse.
        with pytest.raises(ValidationError):
            FREDEvidence(
                claim="10y yields rising",
                supports=True,
                series_id="DGS10",
                observation_date=datetime.now(timezone.utc),
                misspelled_field="should fail",  # type: ignore[call-arg]
            )


# ─────────────────────────────────────────────────────────────────────────────
# Numeric bounds — UnitInterval, Score0to10, Score0to100
# ─────────────────────────────────────────────────────────────────────────────


class TestNumericBounds:
    def test_positioning_percentile_must_be_in_unit_interval(self):
        # percentile_vs_history is a UnitInterval.
        with pytest.raises(ValidationError):
            PositioningEvidence(
                claim="cot net spec extreme long",
                supports=True,
                instrument="CL_F",
                metric="cot_net_spec_pct",
                value=42000.0,
                percentile_vs_history=1.5,  # invalid — > 1.0
                as_of=datetime.now(timezone.utc),
            )

    def test_positioning_percentile_at_bounds_is_ok(self):
        # 0.0 and 1.0 are both valid (inclusive bounds).
        ev_lo = PositioningEvidence(
            claim="cot net spec extreme short",
            supports=True,
            instrument="CL_F",
            metric="cot_net_spec_pct",
            value=-30000.0,
            percentile_vs_history=0.0,
            as_of=datetime.now(timezone.utc),
        )
        ev_hi = PositioningEvidence(
            claim="cot net spec extreme long",
            supports=True,
            instrument="CL_F",
            metric="cot_net_spec_pct",
            value=80000.0,
            percentile_vs_history=1.0,
            as_of=datetime.now(timezone.utc),
        )
        assert ev_lo.percentile_vs_history == 0.0
        assert ev_hi.percentile_vs_history == 1.0


# ─────────────────────────────────────────────────────────────────────────────
# Discriminated union — Evidence picks the right subclass
# ─────────────────────────────────────────────────────────────────────────────


class TestEvidenceDiscriminatedUnion:
    def test_dict_with_source_type_resolves_to_correct_subclass(self):
        # Simulates what happens when an agent emits JSON that gets validated.
        data = {
            "source_type": "fred",
            "claim": "10y yields rising",
            "supports": True,
            "series_id": "DGS10",
            "observation_date": "2026-05-19T00:00:00Z",
            "observation_value": 4.5,
        }
        ev = EvidenceAdapter.validate_python(data)
        assert isinstance(ev, FREDEvidence)
        assert ev.series_id == "DGS10"

    def test_missing_required_subclass_field_fails(self):
        # source_type=fred requires series_id. Without it, validation fails
        # even though the parent fields are all present.
        data = {
            "source_type": "fred",
            "claim": "10y yields rising",
            "supports": True,
            # series_id missing
            "observation_date": "2026-05-19T00:00:00Z",
        }
        with pytest.raises(ValidationError):
            EvidenceAdapter.validate_python(data)

    def test_news_evidence_with_url(self):
        data = {
            "source_type": "news",
            "claim": "Hormuz disruption escalating",
            "supports": True,
            "publisher": "Reuters",
            "title": "Tankers re-routing as Hormuz tensions rise",
            "url": "https://reuters.com/example",
            "published_at": "2026-05-18T14:30:00Z",
            "channel": "policy",
        }
        ev = EvidenceAdapter.validate_python(data)
        assert isinstance(ev, NewsEvidence)
        assert str(ev.url) == "https://reuters.com/example"
        assert ev.channel == "policy"

    def test_filing_evidence_requires_accession(self):
        with pytest.raises(ValidationError):
            EvidenceAdapter.validate_python(
                {
                    "source_type": "filing",
                    "claim": "Capex guidance raised",
                    "supports": True,
                    "cik": "0000789019",
                    # accession_number missing
                    "form_type": "10-Q",
                    "filed_at": "2026-04-25T16:00:00Z",
                }
            )

    def test_derived_evidence_requires_upstream_claims(self):
        # A derived claim with no upstream claims is exactly the failure
        # mode we want to prevent — agents asserting derivations without
        # showing their work.
        with pytest.raises(ValidationError):
            DerivedEvidence(
                claim="real yields are compressing growth multiples",
                supports=True,
                computation="growth_multiple = f(real_yield)",
                upstream_claims=[],  # empty list — invalid
            )

    def test_derived_evidence_with_upstream_claims_ok(self):
        ev = DerivedEvidence(
            claim="real yields are compressing growth multiples",
            supports=True,
            computation="growth_multiple = f(real_yield)",
            upstream_claims=[
                "10y real yields rose 40bps last month (FRED:DFII10)",
                "QQQ forward P/E compressed by 1.5 turns (price evidence)",
            ],
        )
        assert len(ev.upstream_claims) == 2


# ─────────────────────────────────────────────────────────────────────────────
# Falsifier — basic construction
# ─────────────────────────────────────────────────────────────────────────────


class TestFalsifier:
    def test_falsifier_defaults_to_not_triggered(self):
        f = Falsifier(
            condition="oil falls below $70 for 5 sessions",
            observable_in=FalsifierObservable.PRICE_ACTION,
            check_frequency=FalsifierFrequency.DAILY,
        )
        assert f.current_status == FalsifierStatus.NOT_TRIGGERED
        assert f.last_checked_at is None

    def test_falsifier_empty_condition_rejected(self):
        with pytest.raises(ValidationError):
            Falsifier(
                condition="",  # empty — invalid
                observable_in=FalsifierObservable.PRICE_ACTION,
                check_frequency=FalsifierFrequency.DAILY,
            )


# ─────────────────────────────────────────────────────────────────────────────
# Catalyst — date and ongoing validation
# ─────────────────────────────────────────────────────────────────────────────


class TestCatalyst:
    def test_dated_catalyst_ok(self):
        now = datetime.now(timezone.utc)
        c = Catalyst(
            event="Q3 earnings",
            catalyst_type=CatalystType.EARNINGS,
            earliest_date=now,
            latest_date=now + timedelta(days=3),
            asymmetry="+8% if beat and raise, -3% if in-line",
        )
        assert c.is_ongoing is False

    def test_latest_before_earliest_rejected(self):
        now = datetime.now(timezone.utc)
        with pytest.raises(ValidationError):
            Catalyst(
                event="Q3 earnings",
                catalyst_type=CatalystType.EARNINGS,
                earliest_date=now,
                latest_date=now - timedelta(days=3),  # before earliest — invalid
            )

    def test_ongoing_catalyst_ok(self):
        c = Catalyst(
            event="Strait of Hormuz tension persistence",
            catalyst_type=CatalystType.GEOPOLITICAL,
            is_ongoing=True,
        )
        assert c.earliest_date is None
        assert c.latest_date is None

    def test_ongoing_with_dates_rejected(self):
        # You don't get to set ongoing=True AND give dates. Pick one.
        now = datetime.now(timezone.utc)
        with pytest.raises(ValidationError):
            Catalyst(
                event="something",
                catalyst_type=CatalystType.STRUCTURAL,
                earliest_date=now,
                is_ongoing=True,
            )


# ─────────────────────────────────────────────────────────────────────────────
# Conviction — output of the rules engine
# ─────────────────────────────────────────────────────────────────────────────


class TestConviction:
    def test_basic_construction(self):
        c = Conviction(
            rating=ConvictionRating.STRONG,
            rule_applied="rule_exceptional_requires_all_strong",
            weakest_link="narrative",
            reasoning=(
                "Fundamental and regime alignment are exceptional, but narrative "
                "is only moderate. Capped at STRONG per rule."
            ),
        )
        assert c.rating == ConvictionRating.STRONG
        assert c.weakest_link == "narrative"

    def test_invalid_weakest_link_rejected(self):
        with pytest.raises(ValidationError):
            Conviction(
                rating=ConvictionRating.MODERATE,
                rule_applied="some_rule",
                weakest_link="invalid_dimension",  # not in the Literal set
                reasoning="...",
            )


# ─────────────────────────────────────────────────────────────────────────────
# BaseSchema — metadata fields
# ─────────────────────────────────────────────────────────────────────────────


class TestBaseSchema:
    def test_created_at_defaults_to_utc_now(self):
        f = Falsifier(
            condition="x",
            observable_in=FalsifierObservable.NEWS,
            check_frequency=FalsifierFrequency.DAILY,
        )
        assert f.created_at.tzinfo is not None  # timezone-aware

    def test_schema_version_is_set(self):
        f = Falsifier(
            condition="x",
            observable_in=FalsifierObservable.NEWS,
            check_frequency=FalsifierFrequency.DAILY,
        )
        assert f.schema_version  # non-empty

    def test_id_is_none_until_persisted(self):
        f = Falsifier(
            condition="x",
            observable_in=FalsifierObservable.NEWS,
            check_frequency=FalsifierFrequency.DAILY,
        )
        assert f.id is None