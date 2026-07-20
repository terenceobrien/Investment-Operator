"""Priority-aware existing-position filter for conviction-stage candidates."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.agent_system.schemas.common import Conviction, ConvictionRating
from src.agent_system.schemas.regime import ResearchPriority
from src.agent_system.schemas.thematic import Candidate
from src.agent_system.services.held_position_registry import HeldPositionRecord
from src.agent_system.services.scenario_compatibility import scenarios_compatible
from src.state.config_loader import EXISTING_POSITION_FILTER_PARAMS


class ExistingPositionVerdict(Enum):
    NONE = "none"
    SAME_PRIORITY_HELD = "same_priority_held"
    SAME_PRIORITY_WATCHING = "same_priority_watching"
    SAME_PRIORITY_RECENTLY_CLOSED = "same_priority_recently_closed"
    CROSS_HYPOTHESIS_CONFIRMING = "cross_hypothesis_confirming"
    CROSS_HYPOTHESIS_TENSION = "cross_hypothesis_tension"


@dataclass(frozen=True)
class ExistingPositionFilterConfig:
    enabled: bool = True
    same_priority_demotion_tiers: int = 1
    same_priority_recently_closed_window_days: int = 30
    scenario_compatibility_threshold: float = 0.0
    surface_cross_hypothesis_flags: bool = True


@dataclass(frozen=True)
class ExistingPositionCheck:
    ticker: str
    verdict: ExistingPositionVerdict
    rationale: str
    held_record: HeldPositionRecord
    conviction_before: ConvictionRating
    conviction_after: ConvictionRating
    scenario_correlation: float | None = None

    def as_candidate_payload(self) -> dict[str, object]:
        return {
            "ticker": self.ticker,
            "verdict": self.verdict.value,
            "rationale": self.rationale,
            "held_cycle_id": self.held_record.cycle_id,
            "held_status": self.held_record.status,
            "held_priority_id": self.held_record.priority_id,
            "held_priority_label": self.held_record.priority_label,
            "held_priority_scenarios": list(self.held_record.priority_scenarios),
            "closed_reason": self.held_record.closed_reason,
            "days_since_close": self.held_record.days_since_close,
            "conviction_before": self.conviction_before.value,
            "conviction_after": self.conviction_after.value,
            "scenario_correlation": self.scenario_correlation,
        }


@dataclass(frozen=True)
class ExistingPositionFilterApplication:
    candidate: Candidate
    conviction: Conviction
    checks: list[ExistingPositionCheck]


def existing_position_filter_config() -> ExistingPositionFilterConfig:
    params = EXISTING_POSITION_FILTER_PARAMS
    return ExistingPositionFilterConfig(
        enabled=bool(params["existing_position_filter.enabled"]),
        same_priority_demotion_tiers=int(params["existing_position_filter.same_priority_demotion_tiers"]),
        same_priority_recently_closed_window_days=int(
            params["existing_position_filter.same_priority_recently_closed_window_days"]
        ),
        scenario_compatibility_threshold=float(
            params["existing_position_filter.scenario_compatibility_threshold"]
        ),
        surface_cross_hypothesis_flags=bool(
            params["existing_position_filter.surface_cross_hypothesis_flags"]
        ),
    )


def _normalized_label(value: str | None) -> str:
    return " ".join((value or "").strip().lower().split())


def _priority_identity(priority: ResearchPriority) -> str | None:
    return priority.source_theme_id or priority.id


def _same_priority(candidate_priority: ResearchPriority, held_record: HeldPositionRecord) -> bool:
    candidate_id = _priority_identity(candidate_priority)
    if candidate_id and held_record.priority_id == candidate_id:
        return True
    candidate_label = _normalized_label(candidate_priority.theme)
    held_label = _normalized_label(held_record.priority_label)
    return bool(candidate_label and held_label and candidate_label == held_label)


def classify_candidate_vs_held(
    candidate_priority: ResearchPriority,
    held_record: HeldPositionRecord,
) -> tuple[ExistingPositionVerdict, str]:
    """Return the held-position verdict and human-readable rationale."""

    other_priority = held_record.priority_label or held_record.priority_id or "unknown hypothesis"
    if _same_priority(candidate_priority, held_record):
        if held_record.status == "open":
            return (
                ExistingPositionVerdict.SAME_PRIORITY_HELD,
                f"Already held under this hypothesis (cycle {held_record.cycle_id}).",
            )
        if held_record.status == "watching":
            return (
                ExistingPositionVerdict.SAME_PRIORITY_WATCHING,
                f"Already watching under this hypothesis (cycle {held_record.cycle_id}).",
            )
        return (
            ExistingPositionVerdict.SAME_PRIORITY_RECENTLY_CLOSED,
            (
                "Recently closed under same hypothesis "
                f"({held_record.closed_reason or 'unknown reason'}, "
                f"{held_record.days_since_close if held_record.days_since_close is not None else '?'}d ago)."
            ),
        )

    candidate_scenarios = list(candidate_priority.source_scenario_ids or [])
    held_scenarios = list(held_record.priority_scenarios or [])
    if not candidate_scenarios or not held_scenarios:
        return ExistingPositionVerdict.NONE, "No comparable scenario-driver metadata."

    config = existing_position_filter_config()
    compatible, score = scenarios_compatible(
        candidate_scenarios,
        held_scenarios,
        threshold=config.scenario_compatibility_threshold,
    )
    if compatible:
        return (
            ExistingPositionVerdict.CROSS_HYPOTHESIS_CONFIRMING,
            (
                f"Cross-hypothesis confirming: also surfaced under {other_priority} "
                f"(cycle {held_record.cycle_id}); scenario correlation {score:+.2f}."
            ),
        )
    return (
        ExistingPositionVerdict.CROSS_HYPOTHESIS_TENSION,
        (
            f"Cross-hypothesis tension: surfaced under contradictory hypothesis {other_priority} "
            f"(cycle {held_record.cycle_id}); scenario correlation {score:+.2f}."
        ),
    )


def _demote_rating(rating: ConvictionRating, tiers: int) -> ConvictionRating:
    rank = max(0, rating.rank - max(0, tiers))
    for candidate in ConvictionRating:
        if candidate.rank == rank:
            return candidate
    return ConvictionRating.PASS


def _truncate(value: str, max_length: int) -> str:
    if len(value) <= max_length:
        return value
    return value[: max_length - 3].rstrip() + "..."


def apply_existing_position_filter(
    *,
    candidate: Candidate,
    priority: ResearchPriority,
    conviction: Conviction,
    held_records: list[HeldPositionRecord],
) -> ExistingPositionFilterApplication:
    """Apply priority-aware held-position checks to one candidate."""

    config = existing_position_filter_config()
    if not config.enabled or not held_records:
        return ExistingPositionFilterApplication(candidate=candidate, conviction=conviction, checks=[])

    raw_verdicts: list[tuple[ExistingPositionVerdict, str, HeldPositionRecord, float | None]] = []
    for held_record in held_records:
        verdict, rationale = classify_candidate_vs_held(priority, held_record)
        if verdict == ExistingPositionVerdict.NONE:
            continue
        if verdict in {
            ExistingPositionVerdict.CROSS_HYPOTHESIS_CONFIRMING,
            ExistingPositionVerdict.CROSS_HYPOTHESIS_TENSION,
        } and not config.surface_cross_hypothesis_flags:
            continue
        correlation = None
        if priority.source_scenario_ids and held_record.priority_scenarios:
            _, correlation = scenarios_compatible(
                list(priority.source_scenario_ids),
                list(held_record.priority_scenarios),
                threshold=config.scenario_compatibility_threshold,
            )
        raw_verdicts.append((verdict, rationale, held_record, correlation))

    if not raw_verdicts:
        return ExistingPositionFilterApplication(candidate=candidate, conviction=conviction, checks=[])

    demotion_verdicts = {
        ExistingPositionVerdict.SAME_PRIORITY_HELD,
        ExistingPositionVerdict.SAME_PRIORITY_WATCHING,
    }
    should_demote = any(verdict in demotion_verdicts for verdict, _, _, _ in raw_verdicts)
    new_rating = conviction.rating
    if should_demote:
        new_rating = _demote_rating(conviction.rating, config.same_priority_demotion_tiers)

    checks = [
        ExistingPositionCheck(
            ticker=candidate.ticker,
            verdict=verdict,
            rationale=rationale,
            held_record=held_record,
            conviction_before=conviction.rating,
            conviction_after=new_rating,
            scenario_correlation=correlation,
        )
        for verdict, rationale, held_record, correlation in raw_verdicts
    ]
    candidate_with_verdicts = candidate.model_copy_validate(
        {
            "existing_position_verdicts": [
                check.as_candidate_payload()
                for check in checks
            ]
        }
    )

    if new_rating == conviction.rating and not checks:
        return ExistingPositionFilterApplication(
            candidate=candidate_with_verdicts,
            conviction=conviction,
            checks=checks,
        )

    notes = " ".join(check.rationale for check in checks)
    rule_applied = conviction.rule_applied
    if should_demote:
        rule_applied = _truncate(f"{rule_applied}+existing_position_filter", 200)
    updated_conviction = conviction.model_copy_validate(
        {
            "rating": new_rating,
            "rule_applied": rule_applied,
            "reasoning": _truncate(
                f"{conviction.reasoning} Existing position filter: {notes}",
                2000,
            ),
        }
    )
    return ExistingPositionFilterApplication(
        candidate=candidate_with_verdicts,
        conviction=updated_conviction,
        checks=checks,
    )


def format_existing_position_filter_report(checks: list[ExistingPositionCheck]) -> str | None:
    if not checks:
        return None

    groups: dict[ExistingPositionVerdict, list[ExistingPositionCheck]] = {}
    for check in checks:
        groups.setdefault(check.verdict, []).append(check)

    lines = [
        "Existing Position Filter Results",
        "--------------------------------",
        "",
        "Demoted (same-hypothesis repeats):",
    ]
    demoted = groups.get(ExistingPositionVerdict.SAME_PRIORITY_HELD, []) + groups.get(
        ExistingPositionVerdict.SAME_PRIORITY_WATCHING,
        [],
    )
    if demoted:
        for check in demoted:
            lines.append(
                f"  {check.ticker}: {check.conviction_before.value.upper()} -> "
                f"{check.conviction_after.value.upper()}. {check.rationale}"
            )
    else:
        lines.append("  (none)")

    lines.extend(["", "Cross-hypothesis confirming signals:"])
    confirming = groups.get(ExistingPositionVerdict.CROSS_HYPOTHESIS_CONFIRMING, [])
    if confirming:
        for check in confirming:
            lines.append(
                f"  {check.ticker}: {check.conviction_after.value.upper()} conviction. "
                f"{check.rationale} Cross-validation suggests robust positioning."
            )
    else:
        lines.append("  (none)")

    lines.extend(["", "Cross-hypothesis tension signals:"])
    tension = groups.get(ExistingPositionVerdict.CROSS_HYPOTHESIS_TENSION, [])
    if tension:
        for check in tension:
            lines.append(
                f"  {check.ticker}: {check.conviction_after.value.upper()} conviction. "
                f"{check.rationale} Verify which thesis this trade is actually expressing."
            )
    else:
        lines.append("  (none)")

    lines.extend(["", "Recently closed (verify thesis):"])
    recently_closed = groups.get(ExistingPositionVerdict.SAME_PRIORITY_RECENTLY_CLOSED, [])
    if recently_closed:
        for check in recently_closed:
            lines.append(
                f"  {check.ticker}: {check.conviction_after.value.upper()} conviction. {check.rationale}"
            )
    else:
        lines.append("  (none)")

    return "\n".join(lines)
