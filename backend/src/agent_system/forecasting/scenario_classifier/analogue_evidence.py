"""Live analogue evidence for the behavioral scenario posterior.

The live path uses only point-in-time observable neighbor labels: a neighbor's
forward recession outcome is usable only after the full horizon has resolved
before the query date. The shrunk share is an a-priori regularizer, not fitted;
thin or low-weight match sets move toward the unconditional eligible-query base
rate and therefore make the analogue-implied mixture converge back toward the
BVAR distribution.
"""
from __future__ import annotations

import argparse
import copy
import sys
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
import yaml

from src.agent_system.forecasting.behavioral_scenarios_loader import (
    default_behavioral_scenarios_path,
    load_behavioral_scenarios,
)
from src.agent_system.forecasting.scenario_classifier.analogue_matcher import (
    AnalogueMatch,
    DEFAULT_FORWARD_BUFFER_QUARTERS,
    DEFAULT_THRESHOLD_PERCENTILE,
    DEFAULT_TREND_WEIGHT,
    AnalogueMatcherError,
    default_library_path,
    load_directional_feature_library,
    match_analogues,
)
from src.agent_system.forecasting.scenario_classifier.directional_features import (
    LIBRARY_FILENAME,
    load_directional_feature_cache,
)
from src.agent_system.forecasting.scenario_classifier.forward_outcomes import (
    DEFAULT_HORIZON_QUARTERS,
    DEFAULT_MIN_POOL,
    DEFAULT_PRIOR_STRENGTH,
    MODE_PIT,
    compute_neighbor_recession_share,
    eligible_query_dates,
    pit_candidate_pool_size,
    shrink_neighbor_share,
)
from src.agent_system.forecasting.scenario_classifier.nber_dates import (
    NBER_PEAKS,
    NBER_RECESSION_QUARTERS,
    parse_quarter,
    recession_within,
)


STATE_SCORED = "scored"
STATE_UNPRECEDENTED = "unprecedented_state"
STATE_INSUFFICIENT_POOL = "insufficient_pool"
REBUILD_COMMAND = (
    "PYTHONPATH=backend python3 -m "
    "src.agent_system.forecasting.scenario_classifier.directional_features "
    "build-library --start 1975Q1 --end {end_quarter}"
)
COHERENCE_TOLERANCE = 1e-6
MIXTURE_COHERENCE_TOLERANCE = 1e-9
MIXTURE_EPSILON = 1e-9
MIXTURE_NUMERICAL_FLOOR = 0.001
TOP_MATCH_LIMIT = 10
YAML_TOP_MATCH_LIMIT = 5
LOW_ONSET_LAG_EFFECTIVE_N = 8.0
TIMING_LOW_N_EFFECTIVE_N = 4.0


class AnalogueEvidenceError(RuntimeError):
    """Raised when analogue evidence cannot be computed without hiding gaps."""


@dataclass(frozen=True)
class AnalogueEvidenceConfig:
    trailing_window_quarters: int
    prior_strength: float
    horizon_quarters: int
    min_pool: int
    stress_advisory_threshold: float
    mixture_alpha: float
    survival_conditioning: bool
    scenario_recession_membership: dict[str, bool]
    source_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AnalogueTopMatch:
    neighbor_quarter: str
    distance: float
    kernel_weight: float
    resolved: bool
    recession_bound: bool | None
    onset_lag_quarters: int | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AnalogueWindowState:
    quarter: str
    state: str
    share: float | None
    share_raw: float | None
    n_matches: int
    evaluable_neighbor_count: int
    dropped_unresolved_count: int
    kernel_weight_sum: float
    pit_candidate_pool_size: int
    elapsed_quarters: int | None = None
    spent_mass: float | None = None
    remaining_mass: float | None = None
    conditioned_share: float | None = None
    no_timing_evidence: bool = False
    timing_low_n: bool = False
    top_matches: tuple[AnalogueTopMatch, ...] = ()
    onset_lag_distribution: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["top_matches"] = [match.to_dict() for match in self.top_matches]
        return payload


@dataclass(frozen=True)
class AnalogueEvidence:
    query_date: str
    current_state: str
    spot_share: float | None
    trailing_max: float | None
    window_states: tuple[AnalogueWindowState, ...]
    base_rate: float
    kernel_weight_sum: float
    stress_advisory: bool
    config_snapshot: dict[str, Any]
    trailing_max_quarter: str | None = None
    trailing_max_onset_lag_distribution: dict[str, Any] | None = None
    trailing_max_unconditioned: float | None = None
    trailing_max_conditioned: float | None = None
    s_used: float | None = None
    s_source: str | None = None
    binding_quarter: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_date": self.query_date,
            "current_state": self.current_state,
            "spot_share": self.spot_share,
            "trailing_max": self.trailing_max,
            "trailing_max_unconditioned": self.trailing_max_unconditioned,
            "trailing_max_conditioned": self.trailing_max_conditioned,
            "s_used": self.s_used,
            "s_source": self.s_source,
            "binding_quarter": self.binding_quarter,
            "window_states": [state.to_dict() for state in self.window_states],
            "base_rate": self.base_rate,
            "kernel_weight_sum": self.kernel_weight_sum,
            "stress_advisory": self.stress_advisory,
            "config_snapshot": self.config_snapshot,
            "trailing_max_quarter": self.trailing_max_quarter,
            "trailing_max_onset_lag_distribution": self.trailing_max_onset_lag_distribution,
        }


def default_analogue_evidence_config_path() -> Path:
    return default_behavioral_scenarios_path().parent / "analogue_evidence.yaml"


def load_analogue_evidence_config(
    path: str | Path | Mapping[str, Any] | None = None,
    *,
    behavioral_scenarios_path: str | Path | None = None,
) -> AnalogueEvidenceConfig:
    """Load and validate the analogue evidence config against the taxonomy."""

    if path is None:
        source_path = default_analogue_evidence_config_path()
        payload = _read_yaml_mapping(source_path)
        source_text: str | None = str(source_path)
    elif isinstance(path, Mapping):
        payload = dict(path)
        source_text = None
    else:
        source_path = Path(path)
        payload = _read_yaml_mapping(source_path)
        source_text = str(source_path)

    required = {
        "trailing_window_quarters",
        "prior_strength",
        "horizon_quarters",
        "min_pool",
        "stress_advisory_threshold",
        "mixture_alpha",
        "survival_conditioning",
        "scenario_recession_membership",
    }
    missing = sorted(required - set(payload))
    if missing:
        raise AnalogueEvidenceError(f"analogue evidence config missing keys: {missing}")

    scenarios = load_behavioral_scenarios(behavioral_scenarios_path)
    taxonomy_ids = tuple(scenarios.keys())
    membership = _validated_membership_map(
        payload["scenario_recession_membership"],
        expected_scenario_ids=taxonomy_ids,
    )
    prior_strength = _positive_float(payload["prior_strength"], "prior_strength")
    if abs(prior_strength - DEFAULT_PRIOR_STRENGTH) > COHERENCE_TOLERANCE:
        raise AnalogueEvidenceError(
            "analogue_evidence.yaml prior_strength must match "
            f"forward_outcomes default {DEFAULT_PRIOR_STRENGTH}; got {prior_strength}"
        )

    return AnalogueEvidenceConfig(
        trailing_window_quarters=_positive_int(
            payload["trailing_window_quarters"],
            "trailing_window_quarters",
        ),
        prior_strength=prior_strength,
        horizon_quarters=_positive_int(payload["horizon_quarters"], "horizon_quarters"),
        min_pool=_positive_int(payload["min_pool"], "min_pool"),
        stress_advisory_threshold=_probability(
            payload["stress_advisory_threshold"],
            "stress_advisory_threshold",
        ),
        mixture_alpha=_open_probability(payload["mixture_alpha"], "mixture_alpha"),
        survival_conditioning=_strict_bool(
            payload["survival_conditioning"],
            "survival_conditioning",
        ),
        scenario_recession_membership=membership,
        source_path=source_text,
    )


def assert_directional_feature_library_current(
    library: str | Path | pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Load the directional library and hard-error if it lags the classifier cache."""

    try:
        frame = load_directional_feature_library(library)
    except AnalogueMatcherError as exc:
        end_quarter = _effective_classifier_cache_max_text(fallback="latest-cache-quarter")
        raise AnalogueEvidenceError(
            f"{exc}; rebuild with: {REBUILD_COMMAND.format(end_quarter=end_quarter)}"
        ) from exc

    library_max = max(frame["_as_of_period"])
    cache_max = _effective_classifier_cache_max()
    if library_max < cache_max:
        raise AnalogueEvidenceError(
            "directional feature library is stale relative to the classifier cache: "
            f"library max={library_max}, classifier cache max={cache_max}. Rebuild with: "
            f"{REBUILD_COMMAND.format(end_quarter=cache_max)}"
        )
    if library_max > cache_max:
        raise AnalogueEvidenceError(
            "directional feature library is ahead of the classifier cache: "
            f"library max={library_max}, classifier cache max={cache_max}. Rebuild the "
            "classifier cache and then rebuild directional features."
        )
    return frame


def compute_analogue_base_rate(
    library: str | Path | pd.DataFrame | None = None,
    *,
    horizon: int = DEFAULT_HORIZON_QUARTERS,
    min_pool: int = DEFAULT_MIN_POOL,
    forward_buffer_quarters: int = DEFAULT_FORWARD_BUFFER_QUARTERS,
) -> float:
    """Compute the eligible-query unconditional recession-forward base rate."""

    horizon_q = _positive_int(horizon, "horizon")
    min_pool_count = _positive_int(min_pool, "min_pool")
    buffer = _positive_int(forward_buffer_quarters, "forward_buffer_quarters")
    frame = load_directional_feature_library(library)
    periods = list(frame["_as_of_period"])
    max_known = max(periods)
    outcomes: list[float] = []
    for query in eligible_query_dates(
        frame,
        horizon=horizon_q,
        forward_buffer_quarters=buffer,
    ):
        if pit_candidate_pool_size(periods, query, buffer) < min_pool_count:
            continue
        outcomes.append(
            float(recession_within(query, horizon_q, max_known_quarter=max_known))
        )
    if not outcomes:
        raise AnalogueEvidenceError(
            f"no min-pool eligible dates for analogue base rate; "
            f"horizon={horizon_q}, min_pool={min_pool_count}"
        )
    base_rate = float(np.mean(outcomes))
    if not 0.0 < base_rate < 1.0:
        raise AnalogueEvidenceError(
            f"analogue base rate must be inside (0, 1) for mixture reporting; got {base_rate}"
        )
    return base_rate


def compute_analogue_evidence(
    query_date: pd.Period | str | None = None,
    *,
    config: AnalogueEvidenceConfig | Mapping[str, Any] | str | Path | None = None,
    library: str | Path | pd.DataFrame | None = None,
    validate_library_current: bool = True,
) -> AnalogueEvidence:
    """Compute live PIT-observable analogue evidence for one query quarter."""

    evidence_config = _coerce_config(config)
    frame = (
        assert_directional_feature_library_current(library)
        if validate_library_current
        else load_directional_feature_library(library)
    )
    periods = list(frame["_as_of_period"])
    min_period = min(periods)
    max_period = max(periods)
    query = max_period if query_date is None else parse_quarter(query_date)
    if query not in set(periods):
        raise AnalogueEvidenceError(
            f"query date {query} is not in directional feature library; "
            f"available range {min_period}..{max_period}"
        )
    window_start = query - (evidence_config.trailing_window_quarters - 1)
    if window_start < min_period:
        raise AnalogueEvidenceError(
            f"analogue evidence window {window_start}..{query} starts before "
            f"library range {min_period}..{max_period}"
        )
    window = tuple(pd.period_range(window_start, query, freq="Q"))
    missing_window = [str(period) for period in window if period not in set(periods)]
    if missing_window:
        raise AnalogueEvidenceError(
            f"directional feature library is missing window quarter(s): {missing_window}"
        )

    base_rate = compute_analogue_base_rate(
        frame,
        horizon=evidence_config.horizon_quarters,
        min_pool=evidence_config.min_pool,
    )
    raw_states = tuple(
        _score_window_quarter(
            period,
            frame=frame,
            periods=periods,
            max_known=max_period,
            base_rate=base_rate,
            config=evidence_config,
        )
        for period in window
    )
    states = _apply_survival_conditioning_to_window(
        raw_states,
        current_query=query,
    )
    scored_shares = [
        float(state.share)
        for state in states
        if state.state == STATE_SCORED and state.share is not None
    ]
    conditioned_shares = [
        float(state.conditioned_share)
        for state in states
        if state.state == STATE_SCORED and state.conditioned_share is not None
    ]
    trailing_max_unconditioned = max(scored_shares) if scored_shares else None
    trailing_max_conditioned = max(conditioned_shares) if conditioned_shares else None
    if evidence_config.survival_conditioning:
        s_used = trailing_max_conditioned
        s_source = "survival_conditioned_trailing_max"
        binding_attr = "conditioned_share"
    else:
        s_used = trailing_max_unconditioned
        s_source = "unconditioned_trailing_max"
        binding_attr = "share"

    binding_state: AnalogueWindowState | None = None
    if s_used is not None:
        binding_state = next(
            state
            for state in states
            if state.state == STATE_SCORED
            and getattr(state, binding_attr) is not None
            and float(getattr(state, binding_attr)) == float(s_used)
        )
    binding_quarter = binding_state.quarter if binding_state is not None else None
    trailing_max_onset_lag_distribution = (
        copy.deepcopy(binding_state.onset_lag_distribution)
        if binding_state is not None
        else None
    )
    current = states[-1]
    spot_share = float(current.share) if current.state == STATE_SCORED and current.share is not None else None
    stress_advisory = bool(
        current.state == STATE_UNPRECEDENTED
        and s_used is not None
        and s_used >= evidence_config.stress_advisory_threshold
    )
    current_state = current.state
    return AnalogueEvidence(
        query_date=str(query),
        current_state=current_state,
        spot_share=spot_share,
        trailing_max=float(s_used) if s_used is not None else None,
        window_states=states,
        base_rate=base_rate,
        kernel_weight_sum=float(current.kernel_weight_sum),
        stress_advisory=stress_advisory,
        config_snapshot=evidence_config.to_dict(),
        trailing_max_quarter=binding_quarter,
        trailing_max_onset_lag_distribution=trailing_max_onset_lag_distribution,
        trailing_max_unconditioned=(
            float(trailing_max_unconditioned)
            if trailing_max_unconditioned is not None
            else None
        ),
        trailing_max_conditioned=(
            float(trailing_max_conditioned)
            if trailing_max_conditioned is not None
            else None
        ),
        s_used=float(s_used) if s_used is not None else None,
        s_source=s_source if s_used is not None else "full_window_abstention",
        binding_quarter=binding_quarter,
    )


def onset_lag_distribution(
    match_set: tuple[AnalogueMatch, ...] | list[AnalogueMatch],
    query_date: pd.Period | str,
    *,
    horizon_quarters: int = DEFAULT_HORIZON_QUARTERS,
    max_known_quarter: pd.Period | str | None = None,
) -> dict[str, Any]:
    """Summarize resolved recession-bound analogue timing to the next NBER peak."""

    query = parse_quarter(query_date)
    horizon = _positive_int(horizon_quarters, "horizon_quarters")
    max_known = parse_quarter(max_known_quarter) if max_known_quarter is not None else query
    lag_weights = {lag: 0.0 for lag in range(0, horizon + 1)}
    recession_bound_weight = 0.0
    recession_bound_count = 0
    unresolved_count = 0
    unresolved_weight = 0.0
    benign_resolved_count = 0
    in_recession_count = 0
    in_recession_weight = 0.0
    peak_at_match_count = 0
    peak_at_match_weight = 0.0

    for match in match_set:
        neighbor = parse_quarter(match.analogue_date)
        weight = _nonnegative_float(match.kernel_weight, "match.kernel_weight")
        if neighbor + horizon > query:
            unresolved_count += 1
            unresolved_weight += weight
            continue
        if neighbor + horizon > max_known:
            raise AnalogueEvidenceError(
                f"cannot compute onset-lag distribution for {query}: neighbor "
                f"{neighbor} horizon ends at {neighbor + horizon}, beyond max_known={max_known}"
            )
        recession_bound = recession_within(
            neighbor,
            horizon,
            max_known_quarter=max_known,
        )
        if not recession_bound:
            benign_resolved_count += 1
            continue

        recession_bound_count += 1
        recession_bound_weight += weight
        if neighbor in NBER_RECESSION_QUARTERS:
            if neighbor in NBER_PEAKS:
                peak_at_match_count += 1
                peak_at_match_weight += weight
            else:
                in_recession_count += 1
                in_recession_weight += weight
            lag_weights[0] += weight
            continue

        lag = _first_peak_lag_after(neighbor, horizon)
        if lag is None:
            raise AnalogueEvidenceError(
                f"neighbor {neighbor} is recession-bound over {horizon}Q but no "
                "subsequent NBER peak was found inside the horizon"
            )
        lag_weights[lag] += weight

    histogram_weight_sum = float(sum(lag_weights.values()))
    positive_lag_weight_sum = float(
        sum(weight for lag, weight in lag_weights.items() if lag > 0)
    )
    if histogram_weight_sum > 0.0:
        histogram = {
            str(lag): float(weight / histogram_weight_sum)
            for lag, weight in lag_weights.items()
        }
    else:
        histogram = {str(lag): 0.0 for lag in lag_weights}

    if positive_lag_weight_sum > 0.0:
        weighted_mean_lag = float(
            sum(float(lag) * weight for lag, weight in lag_weights.items() if lag > 0)
            / positive_lag_weight_sum
        )
        weighted_median_lag = float(
            _weighted_median_lag(
                {lag: weight for lag, weight in lag_weights.items() if lag > 0},
                positive_lag_weight_sum,
            )
        )
    else:
        weighted_mean_lag = None
        weighted_median_lag = None

    return {
        "horizon_quarters": int(horizon),
        "histogram": histogram,
        "weighted_mean_lag": weighted_mean_lag,
        "weighted_median_lag": weighted_median_lag,
        "weighted_mean_lag_excluding_lag0": weighted_mean_lag,
        "weighted_median_lag_excluding_lag0": weighted_median_lag,
        "effective_n": float(recession_bound_weight),
        "low_n": bool(recession_bound_weight < LOW_ONSET_LAG_EFFECTIVE_N),
        "low_n_threshold": LOW_ONSET_LAG_EFFECTIVE_N,
        "histogram_weight_sum": histogram_weight_sum,
        "positive_lag_weight_sum": positive_lag_weight_sum,
        "lag0_kernel_weight": float(lag_weights[0]),
        "resolved_recession_bound_count": int(recession_bound_count),
        "benign_resolved_count": int(benign_resolved_count),
        "unresolved_count": int(unresolved_count),
        "unresolved_kernel_weight": float(unresolved_weight),
        "in_recession_at_match": {
            "count": int(in_recession_count),
            "kernel_weight": float(in_recession_weight),
        },
        "peak_at_match": {
            "count": int(peak_at_match_count),
            "kernel_weight": float(peak_at_match_weight),
        },
    }


def conditional_timing_summary(
    distribution: Mapping[str, Any],
    *,
    current_query: pd.Period | str,
    trailing_max_quarter: pd.Period | str,
    share_shrunk: float,
) -> dict[str, Any]:
    """Compute remaining onset timing conditional on no onset since the max signal."""

    return _conditional_timing(
        distribution,
        current_query=parse_quarter(current_query),
        trailing_max_quarter=parse_quarter(trailing_max_quarter),
        share_shrunk=share_shrunk,
    )


def apply_analogue_mixture(
    bvar_soft: Mapping[str, float],
    evidence: AnalogueEvidence,
    alpha: float,
) -> tuple[dict[str, float], dict[str, Any]]:
    """Mix BVAR soft probabilities with analogue-implied recession-group mass."""

    membership = _membership_from_evidence(evidence)
    before = validate_probability_taxonomy_coherence(
        bvar_soft,
        membership.keys(),
        stage="bvar_soft",
        tolerance=MIXTURE_COHERENCE_TOLERANCE,
    )
    mixture_alpha = _open_probability(alpha, "mixture_alpha")
    if evidence.s_used is None and evidence.trailing_max is None:
        after = dict(before)
        report = _mixture_report(
            before=before,
            analogue_implied=dict(before),
            mixed_pre_floor=dict(before),
            after=after,
            evidence=evidence,
            membership=membership,
            alpha=mixture_alpha,
            alpha_effective=0.0,
            applied=False,
            reason="full_window_abstention",
            floor_applied={scenario_id: False for scenario_id in before},
        )
        return after, report

    s = _probability(
        evidence.s_used if evidence.s_used is not None else evidence.trailing_max,
        "evidence.s_used",
    )
    _open_probability(evidence.base_rate, "evidence.base_rate")
    recession_ids = [scenario_id for scenario_id, is_member in membership.items() if is_member]
    other_ids = [scenario_id for scenario_id, is_member in membership.items() if not is_member]
    if not recession_ids or not other_ids:
        raise AnalogueEvidenceError(
            "scenario_recession_membership must contain at least one recession "
            "scenario and one non-recession scenario"
        )
    group_mass_rec = float(sum(before[scenario_id] for scenario_id in recession_ids))
    group_mass_nonrec = float(sum(before[scenario_id] for scenario_id in other_ids))
    analogue_implied: dict[str, float] = {}
    for scenario_id in recession_ids:
        if group_mass_rec > MIXTURE_EPSILON:
            analogue_implied[scenario_id] = float(s * before[scenario_id] / group_mass_rec)
        else:
            analogue_implied[scenario_id] = float(s / len(recession_ids))
    for scenario_id in other_ids:
        if group_mass_nonrec > MIXTURE_EPSILON:
            analogue_implied[scenario_id] = float((1.0 - s) * before[scenario_id] / group_mass_nonrec)
        else:
            analogue_implied[scenario_id] = float((1.0 - s) / len(other_ids))
    _assert_probability_sum(
        analogue_implied,
        "analogue_implied",
        tolerance=MIXTURE_COHERENCE_TOLERANCE,
    )

    mixed_pre_floor = {
        scenario_id: float((1.0 - mixture_alpha) * before[scenario_id] + mixture_alpha * analogue_implied[scenario_id])
        for scenario_id in before
    }
    _assert_probability_sum(
        mixed_pre_floor,
        "mixed_pre_floor",
        tolerance=MIXTURE_COHERENCE_TOLERANCE,
    )
    floor_applied = {
        scenario_id: mixed_pre_floor[scenario_id] < MIXTURE_NUMERICAL_FLOOR
        for scenario_id in before
    }
    floored = {
        scenario_id: max(MIXTURE_NUMERICAL_FLOOR, mixed_pre_floor[scenario_id])
        for scenario_id in before
    }
    denominator = float(sum(floored.values()))
    if not np.isfinite(denominator) or denominator <= 0.0:
        raise AnalogueEvidenceError(
            f"analogue mixture produced invalid floor normalization denominator: {denominator}"
        )
    after = {
        scenario_id: float(value / denominator)
        for scenario_id, value in floored.items()
    }
    after = validate_probability_taxonomy_coherence(
        after,
        membership.keys(),
        stage="post_analogue",
        tolerance=MIXTURE_COHERENCE_TOLERANCE,
    )
    report = _mixture_report(
        before=before,
        analogue_implied=analogue_implied,
        mixed_pre_floor=mixed_pre_floor,
        after=after,
        evidence=evidence,
        membership=membership,
        alpha=mixture_alpha,
        alpha_effective=mixture_alpha,
        applied=True,
        reason="trailing_max_linear_mixture",
        floor_applied=floor_applied,
    )
    return after, report


def apply_analogue_tilt(
    probabilities: Mapping[str, float],
    evidence: AnalogueEvidence,
) -> tuple[dict[str, float], dict[str, Any]]:
    """Retired probability path retained as a fail-loud compatibility stub."""

    raise AnalogueEvidenceError(
        "apply_analogue_tilt is retired by the two_source_v1 rewire; "
        "use apply_analogue_mixture(bvar_soft, evidence, alpha)."
    )


def validate_probability_taxonomy_coherence(
    probabilities: Mapping[str, float],
    scenario_ids: Any,
    *,
    stage: str,
    tolerance: float = COHERENCE_TOLERANCE,
) -> dict[str, float]:
    """Hard-error if probabilities and taxonomy ids desync."""

    expected = {str(scenario_id) for scenario_id in scenario_ids}
    actual = {str(scenario_id) for scenario_id in probabilities}
    if actual != expected:
        raise AnalogueEvidenceError(
            f"{stage} probability/taxonomy desync: "
            f"missing={sorted(expected - actual)} unknown={sorted(actual - expected)}"
        )
    clean: dict[str, float] = {}
    for scenario_id, value in probabilities.items():
        number = _nonnegative_float(value, f"{stage}.{scenario_id}")
        clean[str(scenario_id)] = number
    total = float(sum(clean.values()))
    if abs(total - 1.0) > tolerance:
        raise AnalogueEvidenceError(
            f"{stage} probabilities must sum to 1.0 within {tolerance}; got {total:.12f}"
        )
    return clean


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except Exception as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Live analogue evidence for behavioral scenario posteriors."
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)
    evidence = subparsers.add_parser("evidence")
    evidence.add_argument("--date", default=None, help="Query quarter, e.g. 2026Q2.")
    evidence.add_argument(
        "--library",
        default=None,
        help=f"Directional feature library CSV; defaults to {default_library_path()}.",
    )
    evidence.add_argument(
        "--config",
        default=None,
        help=f"Analogue evidence config; defaults to {default_analogue_evidence_config_path()}.",
    )
    evidence.set_defaults(func=_cmd_evidence)
    return parser


def _cmd_evidence(args: argparse.Namespace) -> int:
    evidence = compute_analogue_evidence(
        query_date=args.date,
        config=args.config,
        library=args.library,
    )
    _print_evidence(evidence, library=args.library)
    return 0


def _score_window_quarter(
    query: pd.Period,
    *,
    frame: pd.DataFrame,
    periods: list[pd.Period],
    max_known: pd.Period,
    base_rate: float,
    config: AnalogueEvidenceConfig,
) -> AnalogueWindowState:
    pool_size = pit_candidate_pool_size(
        periods,
        query,
        DEFAULT_FORWARD_BUFFER_QUARTERS,
    )
    if pool_size < config.min_pool:
        return _window_state(
            query,
            state=STATE_INSUFFICIENT_POOL,
            pit_candidate_pool_size_value=pool_size,
        )

    try:
        match_result = match_analogues(
            query,
            w=DEFAULT_TREND_WEIGHT,
            threshold_percentile=DEFAULT_THRESHOLD_PERCENTILE,
            forward_buffer_quarters=DEFAULT_FORWARD_BUFFER_QUARTERS,
            library=frame,
        )
    except AnalogueMatcherError as exc:
        if "no point-in-time candidates" in str(exc):
            raise AnalogueEvidenceError(
                f"pool-size inconsistency for {query}: pool_size={pool_size}"
            ) from exc
        raise

    if not match_result.matches:
        return _window_state(
            query,
            state=STATE_UNPRECEDENTED,
            pit_candidate_pool_size_value=pool_size,
        )

    top_matches = _top_matches_for_window(
        match_result.matches,
        query=query,
        horizon=config.horizon_quarters,
        max_known=max_known,
        limit=TOP_MATCH_LIMIT,
    )
    onset_distribution = onset_lag_distribution(
        match_result.matches,
        query,
        horizon_quarters=config.horizon_quarters,
        max_known_quarter=max_known,
    )
    share_info = compute_neighbor_recession_share(
        match_result.matches,
        query=query,
        horizon=config.horizon_quarters,
        max_known_quarter=max_known,
        mode=MODE_PIT,
    )
    share_raw = float(share_info["share_raw"])
    kernel_weight_sum = float(share_info["kernel_weight_sum"])
    evaluable_count = int(share_info["evaluable_neighbor_count"])
    if pd.isna(share_raw) or evaluable_count <= 0:
        raise AnalogueEvidenceError(
            f"{query} has {len(match_result.matches)} analogue matches but no "
            "PIT-resolved neighbor labels; "
            f"dropped_unresolved_count={int(share_info['dropped_unresolved_count'])}"
        )
    share = shrink_neighbor_share(
        share_raw,
        kernel_weight_sum,
        base_rate=base_rate,
        prior_strength=config.prior_strength,
    )
    return AnalogueWindowState(
        quarter=str(query),
        state=STATE_SCORED,
        share=float(share),
        share_raw=share_raw,
        n_matches=int(len(match_result.matches)),
        evaluable_neighbor_count=evaluable_count,
        dropped_unresolved_count=int(share_info["dropped_unresolved_count"]),
        kernel_weight_sum=kernel_weight_sum,
        pit_candidate_pool_size=pool_size,
        top_matches=top_matches,
        onset_lag_distribution=onset_distribution,
    )


def _window_state(
    quarter: pd.Period,
    *,
    state: str,
    pit_candidate_pool_size_value: int,
) -> AnalogueWindowState:
    return AnalogueWindowState(
        quarter=str(quarter),
        state=state,
        share=None,
        share_raw=None,
        n_matches=0,
        evaluable_neighbor_count=0,
        dropped_unresolved_count=0,
        kernel_weight_sum=0.0,
        pit_candidate_pool_size=int(pit_candidate_pool_size_value),
    )


def _top_matches_for_window(
    matches: tuple[AnalogueMatch, ...] | list[AnalogueMatch],
    *,
    query: pd.Period,
    horizon: int,
    max_known: pd.Period,
    limit: int,
) -> tuple[AnalogueTopMatch, ...]:
    horizon_q = _positive_int(horizon, "horizon")
    rows: list[AnalogueTopMatch] = []
    for match in sorted(
        matches,
        key=lambda item: (-float(item.kernel_weight), float(item.distance), item.analogue_date),
    )[:limit]:
        neighbor = parse_quarter(match.analogue_date)
        resolved = bool(neighbor + horizon_q <= query)
        recession_bound: bool | None = None
        onset_lag: int | None = None
        if resolved:
            if neighbor + horizon_q > max_known:
                raise AnalogueEvidenceError(
                    f"resolved top match {neighbor} for {query} extends beyond "
                    f"known history: horizon end {neighbor + horizon_q}, max_known={max_known}"
                )
            recession_bound = bool(
                recession_within(
                    neighbor,
                    horizon_q,
                    max_known_quarter=max_known,
                )
            )
            if recession_bound:
                onset_lag = _onset_lag_for_neighbor(neighbor, horizon_q)
        rows.append(
            AnalogueTopMatch(
                neighbor_quarter=str(neighbor),
                distance=float(match.distance),
                kernel_weight=float(match.kernel_weight),
                resolved=resolved,
                recession_bound=recession_bound,
                onset_lag_quarters=onset_lag,
            )
        )
    return tuple(rows)


def _onset_lag_for_neighbor(neighbor: pd.Period, horizon: int) -> int | None:
    if neighbor in NBER_RECESSION_QUARTERS:
        return 0 if neighbor in NBER_PEAKS else None
    return _first_peak_lag_after(neighbor, horizon)


def _first_peak_lag_after(neighbor: pd.Period, horizon: int) -> int | None:
    for peak in sorted(NBER_PEAKS):
        if peak <= neighbor:
            continue
        lag = _quarter_distance(peak, neighbor)
        if 1 <= lag <= horizon:
            return int(lag)
    return None


def _quarter_distance(later: pd.Period, earlier: pd.Period) -> int:
    return int(later.ordinal - earlier.ordinal)


def _weighted_median_lag(lag_weights: Mapping[int, float], total_weight: float) -> int:
    midpoint = total_weight / 2.0
    cumulative = 0.0
    for lag in sorted(lag_weights):
        cumulative += float(lag_weights[lag])
        if cumulative >= midpoint:
            return int(lag)
    return int(max(lag_weights))


def _apply_survival_conditioning_to_window(
    states: tuple[AnalogueWindowState, ...],
    *,
    current_query: pd.Period,
) -> tuple[AnalogueWindowState, ...]:
    conditioned_states: list[AnalogueWindowState] = []
    for state in states:
        elapsed = _quarter_distance(current_query, parse_quarter(state.quarter))
        if state.state != STATE_SCORED or state.share is None:
            conditioned_states.append(replace(state, elapsed_quarters=int(elapsed)))
            continue

        distribution = (
            copy.deepcopy(state.onset_lag_distribution)
            if state.onset_lag_distribution is not None
            else None
        )
        effective_n = (
            _nonnegative_float(distribution.get("effective_n"), "effective_n")
            if isinstance(distribution, Mapping)
            and distribution.get("effective_n") is not None
            else 0.0
        )
        if not isinstance(distribution, Mapping) or effective_n <= 0.0:
            conditioned_states.append(
                replace(
                    state,
                    elapsed_quarters=int(elapsed),
                    conditioned_share=float(state.share),
                    no_timing_evidence=True,
                    timing_low_n=False,
                )
            )
            continue

        timing = _conditional_timing(
            distribution,
            current_query=current_query,
            trailing_max_quarter=parse_quarter(state.quarter),
            share_shrunk=float(state.share),
        )
        distribution["conditional_timing"] = timing
        conditioned_states.append(
            replace(
                state,
                elapsed_quarters=int(elapsed),
                spent_mass=float(timing["spent_mass"]),
                remaining_mass=float(timing["remaining_mass"]),
                conditioned_share=float(timing["conditional_share"]),
                no_timing_evidence=False,
                timing_low_n=bool(effective_n < TIMING_LOW_N_EFFECTIVE_N),
                onset_lag_distribution=dict(distribution),
            )
        )
    return tuple(conditioned_states)


def _conditional_timing(
    distribution: Mapping[str, Any],
    *,
    current_query: pd.Period,
    trailing_max_quarter: pd.Period,
    share_shrunk: float,
) -> dict[str, Any]:
    elapsed = _quarter_distance(current_query, trailing_max_quarter)
    if elapsed < 0:
        raise AnalogueEvidenceError(
            f"trailing-max quarter {trailing_max_quarter} is after current query {current_query}"
        )
    histogram = distribution.get("histogram")
    if not isinstance(histogram, Mapping):
        raise AnalogueEvidenceError("onset-lag distribution is missing histogram")
    horizon = _positive_int(distribution.get("horizon_quarters", DEFAULT_HORIZON_QUARTERS), "horizon_quarters")
    share = _probability(share_shrunk, "share_shrunk")
    if share >= 1.0 - 1e-9:
        raise AnalogueEvidenceError(
            f"share_shrunk must be < 1 - 1e-9 for conditional timing; got {share}"
        )
    if elapsed == 0:
        spent_mass = 0.0
        remaining_mass = 1.0
    else:
        spent_mass = float(
            sum(
                float(histogram.get(str(lag), 0.0))
                for lag in range(0, min(elapsed, horizon) + 1)
            )
        )
        remaining_mass = float(
            sum(
                float(histogram.get(str(lag), 0.0))
                for lag in range(elapsed + 1, horizon + 1)
            )
        )
    denominator = 1.0 - share * spent_mass
    if denominator <= 0.0:
        raise AnalogueEvidenceError(
            f"conditional_timing denominator must be positive; got {denominator}"
        )
    conditional_share = float((share * remaining_mass) / denominator)
    return {
        "elapsed_quarters": int(elapsed),
        "spent_mass": spent_mass,
        "remaining_mass": remaining_mass,
        "conditional_share": conditional_share,
        "share_shrunk": share,
        "formula": "(share_shrunk * remaining_mass) / (1 - share_shrunk * spent_mass)",
    }


def _mixture_report(
    *,
    before: Mapping[str, float],
    analogue_implied: Mapping[str, float],
    mixed_pre_floor: Mapping[str, float],
    after: Mapping[str, float],
    evidence: AnalogueEvidence,
    membership: Mapping[str, bool],
    alpha: float,
    alpha_effective: float,
    applied: bool,
    reason: str,
    floor_applied: Mapping[str, bool],
) -> dict[str, Any]:
    per_scenario = {
        scenario_id: {
            "bvar_soft": float(before[scenario_id]),
            "analogue_implied": float(analogue_implied[scenario_id]),
            "mixed_pre_floor": float(mixed_pre_floor[scenario_id]),
            "final": float(after[scenario_id]),
            "delta": float(after[scenario_id] - before[scenario_id]),
            "floor_applied": bool(floor_applied.get(scenario_id, False)),
        }
        for scenario_id in before
    }
    recession_ids = [scenario_id for scenario_id, is_member in membership.items() if is_member]
    other_ids = [scenario_id for scenario_id, is_member in membership.items() if not is_member]
    return {
        "enabled": True,
        "applied": bool(applied),
        "reason": reason,
        "combination": "linear_mixture",
        "numerical_floor": MIXTURE_NUMERICAL_FLOOR,
        "floor_note": "Uniform numerical floor applied after mixing and renormalized; not a judgmental scenario floor.",
        "alpha": float(alpha),
        "alpha_effective": float(alpha_effective),
        "s": evidence.s_used if evidence.s_used is not None else evidence.trailing_max,
        "s_source": evidence.s_source,
        "b": float(evidence.base_rate),
        "membership_groups": {
            "recession": recession_ids,
            "non_recession": other_ids,
        },
        "stress_advisory": bool(evidence.stress_advisory),
        "abstention_state": evidence.current_state if evidence.s_used is None else None,
        "evidence": _evidence_summary(evidence),
        "bvar_soft": {key: float(value) for key, value in before.items()},
        "analogue_implied": {key: float(value) for key, value in analogue_implied.items()},
        "mixed_pre_floor": {key: float(value) for key, value in mixed_pre_floor.items()},
        "probabilities_before": {key: float(value) for key, value in before.items()},
        "probabilities_after": {key: float(value) for key, value in after.items()},
        "floor_applied": {key: bool(value) for key, value in floor_applied.items()},
        "per_scenario": per_scenario,
        "movement_total_abs": float(
            sum(abs(row["delta"]) for row in per_scenario.values())
        ),
    }


def disabled_analogue_evidence_report(
    probabilities: Mapping[str, float],
) -> dict[str, Any]:
    """Return a visible no-op report for A/B runs with analogue evidence disabled."""

    clean = {str(key): float(value) for key, value in probabilities.items()}
    return {
        "enabled": False,
        "applied": False,
        "reason": "analogue_evidence_disabled",
        "combination": "linear_mixture",
        "alpha": 0.0,
        "alpha_effective": 0.0,
        "probabilities_before": dict(clean),
        "probabilities_after": dict(clean),
        "bvar_soft": dict(clean),
        "analogue_implied": dict(clean),
        "mixed_pre_floor": dict(clean),
        "per_scenario": {
            key: {
                "bvar_soft": value,
                "analogue_implied": value,
                "mixed_pre_floor": value,
                "final": value,
                "delta": 0.0,
                "floor_applied": False,
            }
            for key, value in clean.items()
        },
        "floor_applied": {key: False for key in clean},
        "movement_total_abs": 0.0,
        "stress_advisory": False,
    }


def compact_top_match_strings(
    state: AnalogueWindowState | Mapping[str, Any],
    *,
    limit: int = YAML_TOP_MATCH_LIMIT,
) -> tuple[str, ...]:
    """Render a window state's top matches as compact human-readable strings."""

    if isinstance(state, AnalogueWindowState):
        matches = [match.to_dict() for match in state.top_matches]
    else:
        matches = list(state.get("top_matches") or [])
    rows: list[str] = []
    for match in matches[:limit]:
        if not isinstance(match, Mapping):
            continue
        quarter = str(match.get("neighbor_quarter") or match.get("analogue_date") or "unknown")
        weight = _finite_float(match.get("kernel_weight", 0.0), "kernel_weight")
        resolved = bool(match.get("resolved", False))
        recession_bound = match.get("recession_bound")
        if not resolved:
            label = "unresolved"
        elif recession_bound is True:
            label = "rec"
        elif recession_bound is False:
            label = "benign"
        else:
            label = "unknown"
        lag = match.get("onset_lag_quarters")
        lag_text = "" if lag is None else f", lag {int(lag)}"
        rows.append(f"{quarter} (w={weight:.2f}, {label}{lag_text})")
    return tuple(rows)


def compact_analogue_report_for_yaml(
    report: Mapping[str, Any] | None,
    *,
    fan_artifact_path: str | None = None,
) -> dict[str, Any]:
    """Compact the analogue report for current-regime YAML handoff readability."""

    if report is None:
        return {}
    payload = copy.deepcopy(dict(report))
    evidence = payload.get("evidence")
    if isinstance(evidence, Mapping):
        compact_evidence = {
            key: copy.deepcopy(evidence.get(key))
            for key in (
                "query_date",
                "current_state",
                "spot_share",
                "trailing_max",
                "trailing_max_unconditioned",
                "trailing_max_conditioned",
                "s_used",
                "s_source",
                "binding_quarter",
                "trailing_max_quarter",
                "base_rate",
                "kernel_weight_sum",
                "stress_advisory",
            )
            if key in evidence
        }
        window_states = []
        for state in evidence.get("window_states") or []:
            if not isinstance(state, Mapping):
                continue
            state_distribution = state.get("onset_lag_distribution")
            conditional_timing = None
            if isinstance(state_distribution, Mapping):
                conditional_timing = copy.deepcopy(
                    state_distribution.get("conditional_timing")
                )
            window_states.append(
                {
                    "quarter": state.get("quarter"),
                    "state": state.get("state"),
                    "share": state.get("share"),
                    "share_raw": state.get("share_raw"),
                    "n_matches": state.get("n_matches"),
                    "evaluable_neighbor_count": state.get("evaluable_neighbor_count"),
                    "dropped_unresolved_count": state.get("dropped_unresolved_count"),
                    "kernel_weight_sum": state.get("kernel_weight_sum"),
                    "pit_candidate_pool_size": state.get("pit_candidate_pool_size"),
                    "elapsed_quarters": state.get("elapsed_quarters"),
                    "spent_mass": state.get("spent_mass"),
                    "remaining_mass": state.get("remaining_mass"),
                    "conditioned_share": state.get("conditioned_share"),
                    "no_timing_evidence": state.get("no_timing_evidence"),
                    "timing_low_n": state.get("timing_low_n"),
                    "conditional_timing": conditional_timing,
                    "top_matches": list(compact_top_match_strings(state)),
                }
            )
        compact_evidence["window_states"] = window_states
        trailing_distribution = evidence.get("trailing_max_onset_lag_distribution")
        if isinstance(trailing_distribution, Mapping):
            compact_evidence["trailing_max_onset_lag_distribution"] = {
                "horizon_quarters": trailing_distribution.get("horizon_quarters"),
                "histogram": copy.deepcopy(trailing_distribution.get("histogram")),
                "weighted_mean_lag": trailing_distribution.get("weighted_mean_lag"),
                "weighted_median_lag": trailing_distribution.get("weighted_median_lag"),
                "weighted_mean_lag_excluding_lag0": trailing_distribution.get(
                    "weighted_mean_lag_excluding_lag0"
                ),
                "weighted_median_lag_excluding_lag0": trailing_distribution.get(
                    "weighted_median_lag_excluding_lag0"
                ),
                "effective_n": trailing_distribution.get("effective_n"),
                "low_n": trailing_distribution.get("low_n"),
                "positive_lag_weight_sum": trailing_distribution.get(
                    "positive_lag_weight_sum"
                ),
                "lag0_kernel_weight": trailing_distribution.get("lag0_kernel_weight"),
                "in_recession_at_match": copy.deepcopy(
                    trailing_distribution.get("in_recession_at_match")
                ),
                "peak_at_match": copy.deepcopy(trailing_distribution.get("peak_at_match")),
                "conditional_timing": copy.deepcopy(
                    trailing_distribution.get("conditional_timing")
                ),
            }
        if fan_artifact_path:
            compact_evidence["analogue_fan_artifact_path"] = fan_artifact_path
        payload["evidence"] = compact_evidence
    if "analogue_fan" in payload:
        payload["analogue_fan"] = {
            "artifact_path": fan_artifact_path or payload.get("analogue_fan_artifact_path"),
            "note": "Full analogue fan arrays are stored in the JSON artifact, not embedded in current-regime YAML.",
        }
    elif fan_artifact_path:
        payload["analogue_fan_artifact_path"] = fan_artifact_path
    return payload


def _evidence_summary(evidence: AnalogueEvidence) -> dict[str, Any]:
    return {
        "query_date": evidence.query_date,
        "current_state": evidence.current_state,
        "spot_share": evidence.spot_share,
        "trailing_max": evidence.trailing_max,
        "trailing_max_unconditioned": evidence.trailing_max_unconditioned,
        "trailing_max_conditioned": evidence.trailing_max_conditioned,
        "s_used": evidence.s_used,
        "s_source": evidence.s_source,
        "binding_quarter": evidence.binding_quarter,
        "base_rate": evidence.base_rate,
        "kernel_weight_sum": evidence.kernel_weight_sum,
        "stress_advisory": evidence.stress_advisory,
        "trailing_max_quarter": evidence.trailing_max_quarter,
        "trailing_max_onset_lag_distribution": evidence.trailing_max_onset_lag_distribution,
        "window_states": [state.to_dict() for state in evidence.window_states],
    }


def _assert_probability_sum(
    probabilities: Mapping[str, float],
    stage: str,
    *,
    tolerance: float,
) -> None:
    total = float(sum(float(value) for value in probabilities.values()))
    if abs(total - 1.0) > tolerance:
        raise AnalogueEvidenceError(
            f"{stage} probabilities must sum to 1.0 within {tolerance}; got {total:.12f}"
        )


def _coerce_config(
    config: AnalogueEvidenceConfig | Mapping[str, Any] | str | Path | None,
) -> AnalogueEvidenceConfig:
    if isinstance(config, AnalogueEvidenceConfig):
        return config
    return load_analogue_evidence_config(config)


def _membership_from_evidence(evidence: AnalogueEvidence) -> dict[str, bool]:
    raw = evidence.config_snapshot.get("scenario_recession_membership")
    if not isinstance(raw, Mapping):
        raise AnalogueEvidenceError("evidence config_snapshot is missing scenario_recession_membership")
    return {str(key): _strict_bool(value, f"scenario_recession_membership.{key}") for key, value in raw.items()}


def _validated_membership_map(
    value: Any,
    *,
    expected_scenario_ids: tuple[str, ...],
) -> dict[str, bool]:
    if not isinstance(value, Mapping):
        raise AnalogueEvidenceError("scenario_recession_membership must be a mapping")
    actual = {str(key) for key in value}
    expected = set(expected_scenario_ids)
    if actual != expected:
        raise AnalogueEvidenceError(
            "scenario_recession_membership must exactly match behavioral_scenarios.yaml; "
            f"missing={sorted(expected - actual)} unknown={sorted(actual - expected)}"
        )
    return {
        scenario_id: _strict_bool(
            value[scenario_id],
            f"scenario_recession_membership.{scenario_id}",
        )
        for scenario_id in expected_scenario_ids
    }


def _effective_classifier_cache_max() -> pd.Period:
    cache = load_directional_feature_cache()
    latest_by_variable = {
        variable: series.index.max()
        for variable, series in cache.histories.items()
    }
    if not latest_by_variable:
        raise AnalogueEvidenceError("classifier cache produced no directional histories")
    return min(latest_by_variable.values())


def _effective_classifier_cache_max_text(*, fallback: str) -> str:
    try:
        return str(_effective_classifier_cache_max())
    except Exception:
        return fallback


def _read_yaml_mapping(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise AnalogueEvidenceError(f"analogue evidence config not found: {path}")
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise AnalogueEvidenceError(f"could not parse YAML {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise AnalogueEvidenceError(f"{path} must contain a YAML mapping")
    return payload


def _positive_int(value: Any, name: str) -> int:
    try:
        integer = int(value)
    except (TypeError, ValueError) as exc:
        raise AnalogueEvidenceError(f"{name} must be an integer; got {value!r}") from exc
    if integer < 1:
        raise AnalogueEvidenceError(f"{name} must be at least 1; got {value!r}")
    return integer


def _positive_float(value: Any, name: str) -> float:
    number = _finite_float(value, name)
    if number <= 0.0:
        raise AnalogueEvidenceError(f"{name} must be positive; got {value!r}")
    return number


def _nonnegative_float(value: Any, name: str) -> float:
    number = _finite_float(value, name)
    if number < 0.0:
        raise AnalogueEvidenceError(f"{name} must be non-negative; got {value!r}")
    return number


def _finite_float(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise AnalogueEvidenceError(f"{name} must be numeric; got {value!r}") from exc
    if not np.isfinite(number):
        raise AnalogueEvidenceError(f"{name} must be finite; got {value!r}")
    return number


def _probability(value: Any, name: str) -> float:
    number = _finite_float(value, name)
    if not 0.0 <= number <= 1.0:
        raise AnalogueEvidenceError(f"{name} must be in [0, 1]; got {value!r}")
    return number


def _open_probability(value: Any, name: str) -> float:
    number = _probability(value, name)
    if not 0.0 < number < 1.0:
        raise AnalogueEvidenceError(f"{name} must be inside (0, 1); got {value!r}")
    return number


def _strict_bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise AnalogueEvidenceError(f"{name} must be true/false; got {value!r}")
    return bool(value)


def _fmt(value: Any) -> str:
    if value is None:
        return "None"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not np.isfinite(number):
        return "n/a"
    return f"{number:.6f}"


def _print_evidence(evidence: AnalogueEvidence, *, library: str | Path | None) -> None:
    print("Directional Analogue Evidence")
    print(f"query_date: {evidence.query_date}")
    print(f"library: {library or default_library_path()}")
    print(f"config: {evidence.config_snapshot.get('source_path') or '(mapping)'}")
    print(f"current_state: {evidence.current_state}")
    print(f"spot_share_shrunk: {_fmt(evidence.spot_share)}")
    print(f"trailing_max_unconditioned: {_fmt(evidence.trailing_max_unconditioned)}")
    print(f"trailing_max_conditioned: {_fmt(evidence.trailing_max_conditioned)}")
    print(f"s_used: {_fmt(evidence.s_used)}")
    print(f"s_source: {evidence.s_source or 'n/a'}")
    print(f"binding_quarter: {evidence.binding_quarter or 'n/a'}")
    print(f"trailing_max_shrunk: {_fmt(evidence.trailing_max)}")
    print(f"trailing_max_quarter: {evidence.trailing_max_quarter or 'n/a'}")
    print(f"base_rate: {_fmt(evidence.base_rate)}")
    print(f"kernel_weight_sum_current: {_fmt(evidence.kernel_weight_sum)}")
    print(f"stress_advisory: {evidence.stress_advisory}")
    print("settings:")
    for key in (
        "trailing_window_quarters",
        "prior_strength",
        "horizon_quarters",
        "min_pool",
        "stress_advisory_threshold",
        "mixture_alpha",
        "survival_conditioning",
    ):
        print(f"  {key}: {evidence.config_snapshot[key]}")
    print("scenario_recession_membership:")
    for scenario_id, is_member in evidence.config_snapshot["scenario_recession_membership"].items():
        print(f"  {scenario_id}: {bool(is_member)}")
    print("window_states:")
    print(
        f"  {'quarter':<8} {'state':<22} {'shrunk':>10} {'raw':>10} "
        f"{'cond':>10} {'spent':>8} {'remain':>8} {'elapsed':>7} "
        f"{'matches':>8} {'evaluable':>10} {'dropped':>8} {'kernel_wt':>10} {'pool':>6}"
    )
    for state in evidence.window_states:
        print(
            f"  {state.quarter:<8} {state.state:<22} {_fmt(state.share):>10} "
            f"{_fmt(state.share_raw):>10} {_fmt(state.conditioned_share):>10} "
            f"{_fmt(state.spent_mass):>8} {_fmt(state.remaining_mass):>8} "
            f"{str(state.elapsed_quarters):>7} {state.n_matches:>8} "
            f"{state.evaluable_neighbor_count:>10} {state.dropped_unresolved_count:>8} "
            f"{state.kernel_weight_sum:>10.6f} {state.pit_candidate_pool_size:>6}"
        )
        if state.state == STATE_SCORED:
            flags = []
            if state.no_timing_evidence:
                flags.append("no_timing_evidence")
            if state.timing_low_n:
                flags.append("timing_low_n")
            if flags:
                print(f"    flags: {', '.join(flags)}")
        if state.top_matches:
            print("    top_matches:")
            print(
                f"      {'neighbor':<8} {'weight':>10} {'distance':>10} "
                f"{'resolved':>9} {'recession':>10} {'lag':>5}"
            )
            for match in state.top_matches:
                recession = (
                    "null"
                    if match.recession_bound is None
                    else ("true" if match.recession_bound else "false")
                )
                lag = "null" if match.onset_lag_quarters is None else str(match.onset_lag_quarters)
                print(
                    f"      {match.neighbor_quarter:<8} {match.kernel_weight:>10.6f} "
                    f"{match.distance:>10.6f} {str(match.resolved):>9} "
                    f"{recession:>10} {lag:>5}"
                )
        if state.onset_lag_distribution:
            dist = state.onset_lag_distribution
            print("    onset_lag_distribution:")
            print(
                f"      effective_n: {_fmt(dist.get('effective_n'))} "
                f"low_n: {bool(dist.get('low_n'))} "
                f"mean_lag_ex_lag0: {_fmt(dist.get('weighted_mean_lag_excluding_lag0'))} "
                f"median_lag_ex_lag0: {_fmt(dist.get('weighted_median_lag_excluding_lag0'))}"
            )
            hist = dist.get("histogram") if isinstance(dist, Mapping) else {}
            if isinstance(hist, Mapping):
                hist_text = ", ".join(
                    f"{lag}:{_fmt(value)}" for lag, value in hist.items()
                )
                print(f"      histogram: {hist_text}")
            in_recession = dist.get("in_recession_at_match") or {}
            peak_at_match = dist.get("peak_at_match") or {}
            print(
                "      in_recession_at_match: "
                f"count={in_recession.get('count', 0)} "
                f"weight={_fmt(in_recession.get('kernel_weight', 0.0))}; "
                "peak_at_match: "
                f"count={peak_at_match.get('count', 0)} "
                f"weight={_fmt(peak_at_match.get('kernel_weight', 0.0))}"
            )
            conditional = dist.get("conditional_timing")
            if isinstance(conditional, Mapping):
                print("      conditional_timing:")
                print(
                    "        "
                    f"elapsed={conditional.get('elapsed_quarters')} "
                    f"spent={_fmt(conditional.get('spent_mass'))} "
                    f"remaining={_fmt(conditional.get('remaining_mass'))} "
                    f"conditional_share={_fmt(conditional.get('conditional_share'))}"
                )


if __name__ == "__main__":
    raise SystemExit(main())
