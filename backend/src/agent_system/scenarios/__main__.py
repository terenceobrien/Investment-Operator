"""CLI for proposing, reviewing, and promoting scenario sets."""
from __future__ import annotations

import argparse
import asyncio
import difflib
import shutil
import sys

from pydantic import ValidationError

from src.agent_system.orchestration.run_research_cycle import _select_regime_state
from src.agent_system.scenarios.cli_helpers import (
    find_latest_trade_any_status,
    find_trade_by_ticker,
    schema_records_path,
)
from src.agent_system.scenarios.generator import propose_scenarios
from src.agent_system.scenarios.loader import (
    _scenario_set_to_yaml,
    archive_current_scenarios,
    current_path,
    load_current_scenarios,
    load_proposed_scenarios,
    proposed_path,
    write_scenario_set,
)
from src.agent_system.scenarios.scorer import score_trade_against_scenarios
from src.agent_system.scenarios.types import ScenarioSet
from src.agent_system.storage.repository import save_schema


def _print_summary(scenario_set: ScenarioSet) -> None:
    print(
        f"ScenarioSet: horizon={scenario_set.horizon_months}m "
        f"regime={scenario_set.regime_id_basis} generated_at={scenario_set.generated_at}"
    )
    for scenario in scenario_set.scenarios:
        print(f"  - {scenario.id}: {scenario.probability:.0%} | {scenario.label}")
        print(f"    {scenario.description}")


def _truncate(text: str, max_chars: int = 90) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


async def _cmd_propose(args: argparse.Namespace) -> int:
    regime, regime_source, _fallback_reason = _select_regime_state()
    print(f"Regime source: {regime_source}")
    scenario_set = await propose_scenarios(
        regime=regime,
        horizon_months=args.horizon_months,
        n_scenarios=args.n_scenarios,
    )
    write_scenario_set(proposed_path(), scenario_set)
    print(f"Wrote proposed scenarios to {proposed_path()}")
    _print_summary(scenario_set)
    return 0


def _cmd_promote(_args: argparse.Namespace) -> int:
    path = proposed_path()
    if not path.exists():
        print(f"No proposed scenario file found at {path}", file=sys.stderr)
        return 1
    try:
        proposed = load_proposed_scenarios()
    except (ValidationError, ValueError) as exc:
        print(f"Proposed scenarios failed validation; not promoted:\n{exc}", file=sys.stderr)
        return 1
    if proposed is None:
        print(f"Proposed scenario file is empty: {path}", file=sys.stderr)
        return 1

    archived = archive_current_scenarios()
    current_path().parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(current_path()))
    print(f"Promoted proposed scenarios to {current_path()}")
    if archived:
        print(f"Archived previous current scenarios to {archived}")
    _print_summary(proposed)
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    scenario_set = load_proposed_scenarios() if args.proposed else load_current_scenarios()
    which = "proposed" if args.proposed else "current"
    if scenario_set is None:
        print(f"No {which} scenario set found.")
        return 1
    _print_summary(scenario_set)
    return 0


def _cmd_diff(_args: argparse.Namespace) -> int:
    current = load_current_scenarios()
    proposed = load_proposed_scenarios()
    if current is None or proposed is None:
        print("Both current and proposed scenario sets are required for diff.")
        return 1
    current_lines = _scenario_set_to_yaml(current).splitlines(keepends=True)
    proposed_lines = _scenario_set_to_yaml(proposed).splitlines(keepends=True)
    diff = difflib.unified_diff(
        current_lines,
        proposed_lines,
        fromfile="current_scenarios.yaml",
        tofile="proposed_scenarios.yaml",
    )
    sys.stdout.writelines(diff)
    return 0


async def _cmd_score(args: argparse.Namespace) -> int:
    scenario_set = load_current_scenarios()
    if scenario_set is None:
        print(f"No current scenario set found at {current_path()}", file=sys.stderr)
        print("Run `python -m src.agent_system.scenarios promote` first.", file=sys.stderr)
        return 1

    records_path = schema_records_path()
    try:
        trade = find_trade_by_ticker(
            args.ticker,
            cycle_id=args.cycle_id,
            storage_path=records_path,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"Could not load TradeIdea records: {exc}", file=sys.stderr)
        return 1

    if trade is None:
        try:
            latest = find_latest_trade_any_status(
                args.ticker,
                cycle_id=args.cycle_id,
                storage_path=records_path,
            )
        except (FileNotFoundError, ValueError) as exc:
            print(f"Could not load TradeIdea records: {exc}", file=sys.stderr)
            return 1
        cycle_text = f" in cycle {args.cycle_id}" if args.cycle_id else ""
        if latest is not None and latest.expression is None:
            print(
                f"Latest TradeIdea for {args.ticker}{cycle_text} was rejected "
                "(expression=None), so it cannot be scenario-scored.",
                file=sys.stderr,
            )
            print(f"Rejection reason: {latest.rejection_reason}", file=sys.stderr)
        else:
            print(
                f"No accepted TradeIdea found for {args.ticker}{cycle_text} "
                f"in {records_path}",
                file=sys.stderr,
            )
        return 1

    if trade.expression is None:
        print(
            f"TradeIdea for {args.ticker} has expression=None and cannot be scored.",
            file=sys.stderr,
        )
        return 1

    regime, _regime_source, _fallback_reason = _select_regime_state()
    analysis = await score_trade_against_scenarios(trade, scenario_set, regime=regime)
    analysis_id = save_schema(analysis, schema_type="TradeScenarioAnalysis")

    primary = trade.expression.primary_instrument
    print()
    print(f"Trade: {trade.underlying}  id={trade.id or '(unpersisted)'}")
    print(
        f"Instrument: {primary.instrument_type.value} / {primary.direction.value} "
        f"/ {primary.description or primary.ticker}"
    )
    print(
        f"Conviction: {trade.combined_conviction.rating.value} "
        f"({trade.combined_conviction.rule_applied})"
    )
    print()
    print("Scenario scores:")
    print(
        f"{'scenario_id':<28} {'prob':>6} {'pnl':>8} "
        f"{'conf':<7} reasoning"
    )
    print("-" * 96)
    probabilities = {scenario.id: scenario.probability for scenario in scenario_set.scenarios}
    for score in analysis.scenario_scores:
        print(
            f"{score.scenario_id:<28} "
            f"{probabilities.get(score.scenario_id, 0.0):>6.0%} "
            f"{score.expected_pnl_pct:>8.1%} "
            f"{score.confidence:<7} "
            f"{_truncate(score.reasoning)}"
        )

    worst = min(analysis.scenario_scores, key=lambda score: score.expected_pnl_pct)
    best = max(analysis.scenario_scores, key=lambda score: score.expected_pnl_pct)
    print()
    print("Computed metrics:")
    print(f"  scenario-weighted expected_return: {analysis.expected_return:.1%}")
    print(f"  scenario_weight_source: {analysis.scenario_weight_source}")
    weights = ", ".join(
        f"{scenario_id}={weight:.0%}"
        for scenario_id, weight in analysis.scenario_weights_used.items()
    )
    print(f"  scenario_weights_used: {weights}")
    if analysis.scenario_weight_warning:
        print(f"  scenario_weight_warning: {analysis.scenario_weight_warning}")
    print(
        f"  worst_case_pnl_pct: {analysis.worst_case_pnl_pct:.1%} "
        f"({worst.scenario_id})"
    )
    print(
        f"  best_case_pnl_pct: {analysis.best_case_pnl_pct:.1%} "
        f"({best.scenario_id})"
    )
    print(
        f"  scenarios_positive: {analysis.scenarios_positive} "
        f"of {len(analysis.scenario_scores)}"
    )
    print(f"  robustness_score: {analysis.robustness_score:.3f}")
    print(f"  persisted_analysis_id: {analysis_id}")
    return 0


def _build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scenario set workflow.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    propose = subparsers.add_parser("propose", help="Generate proposed scenarios.")
    propose.add_argument("--horizon-months", type=int, default=6)
    propose.add_argument("--n-scenarios", type=int, default=4)
    propose.set_defaults(func=lambda args: asyncio.run(_cmd_propose(args)))

    promote = subparsers.add_parser("promote", help="Promote proposed to current.")
    promote.set_defaults(func=_cmd_promote)

    show = subparsers.add_parser("show", help="Show current or proposed scenarios.")
    group = show.add_mutually_exclusive_group()
    group.add_argument("--proposed", action="store_true")
    group.add_argument("--current", action="store_true")
    show.set_defaults(func=_cmd_show)

    diff = subparsers.add_parser("diff", help="Diff current and proposed scenarios.")
    diff.set_defaults(func=_cmd_diff)

    score = subparsers.add_parser("score", help="Score one TradeIdea against current scenarios.")
    score.add_argument("--ticker", required=True, help="TradeIdea underlying ticker to score.")
    score.add_argument("--cycle-id", default=None, help="Optional cycle_id filter.")
    score.set_defaults(func=lambda args: asyncio.run(_cmd_score(args)))
    return parser


def main() -> None:
    args = _build_argparser().parse_args()
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
