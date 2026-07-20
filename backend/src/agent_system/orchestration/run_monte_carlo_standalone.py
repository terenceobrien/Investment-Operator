"""Run Monte Carlo simulation from persisted cycle artifacts only."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.agent_system.orchestration.run_research_cycle import _run_monte_carlo
from src.agent_system.paths import cycles_dir
from src.agent_system.scenarios.types import (
    DEFAULT_SCENARIO_PRIORS,
    TradeScenarioAnalysis,
)
from src.agent_system.schemas.macro_forecast import MacroForecastResult
from src.agent_system.schemas.monte_carlo import MonteCarloPathResult
from src.agent_system.schemas.portfolio_plan import PortfolioPlan
from src.agent_system.schemas.trade import TradeIdea
from src.agent_system.services.scenario_translation import (
    translate_scenario_probabilities,
)
from src.agent_system.storage.repository import _read_jsonl, _schema_records_path


BACKEND_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MACRO_FORECAST_PATH = (
    BACKEND_ROOT
    / "data"
    / "agent_system"
    / "reports"
    / "macro_forecasts"
    / "macro_forecast_2026-06-05.json"
)


def _parse_created_at(value: Any) -> datetime:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            pass
    return datetime.min.replace(tzinfo=timezone.utc)


def _schema_rows(schema_type: str) -> list[dict[str, Any]]:
    return [
        row
        for row in _read_jsonl(_schema_records_path())
        if row.get("schema_type") == schema_type
        and isinstance(row.get("payload_json"), dict)
    ]


def _latest_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    return max(
        rows,
        key=lambda row: _parse_created_at(
            row.get("created_at")
            or row.get("payload_json", {}).get("created_at")
        ),
    )


def _load_portfolio_plan(cycle_id: str) -> PortfolioPlan:
    matches = [
        row
        for row in _schema_rows("PortfolioPlan")
        if row["payload_json"].get("cycle_id") == cycle_id
    ]
    row = _latest_row(matches)
    if row is None:
        raise FileNotFoundError(
            f"PortfolioPlan for cycle_id={cycle_id!r} was not found in "
            f"{_schema_records_path()}."
        )
    return PortfolioPlan.model_validate(row["payload_json"])


def _load_scenario_analyses(trade_ids: set[str]) -> list[TradeScenarioAnalysis]:
    analyses: list[TradeScenarioAnalysis] = []
    for row in _schema_rows("TradeScenarioAnalysis"):
        payload = row["payload_json"]
        if payload.get("trade_id") not in trade_ids:
            continue
        try:
            analyses.append(TradeScenarioAnalysis.model_validate(payload))
        except Exception:
            continue
    missing = trade_ids - {analysis.trade_id for analysis in analyses}
    if missing:
        raise FileNotFoundError(
            "Missing TradeScenarioAnalysis records for trade_id(s): "
            + ", ".join(sorted(missing))
        )
    return analyses


def _load_trade_ideas(trade_ids: set[str]) -> list[TradeIdea]:
    by_id: dict[str, tuple[datetime, TradeIdea]] = {}
    for row in _schema_rows("TradeIdea"):
        payload = row["payload_json"]
        trade_id = payload.get("id") or row.get("id")
        if trade_id not in trade_ids:
            continue
        try:
            trade = TradeIdea.model_validate(payload)
        except Exception:
            continue
        created_at = _parse_created_at(row.get("created_at") or payload.get("created_at"))
        current = by_id.get(str(trade_id))
        if current is None or created_at >= current[0]:
            by_id[str(trade_id)] = (created_at, trade)
    missing = trade_ids - set(by_id)
    if missing:
        raise FileNotFoundError(
            "Missing TradeIdea records for trade_id(s): "
            + ", ".join(sorted(missing))
        )
    return [by_id[trade_id][1] for trade_id in sorted(trade_ids)]


def _load_macro_scenario_probabilities() -> dict[str, float]:
    try:
        payload = json.loads(DEFAULT_MACRO_FORECAST_PATH.read_text(encoding="utf-8"))
        result = MacroForecastResult.model_validate(payload)
        probabilities = (
            result.scenario_probabilities_blended
            or (
                result.historical_calibration.blended_scenario_probabilities
                if result.historical_calibration is not None
                else None
            )
        )
        if probabilities:
            return translate_scenario_probabilities(
                {
                    scenario_id: float(value)
                    for scenario_id, value in probabilities.items()
                }
            )
        print(
            "Warning: macro forecast blended scenario probabilities unavailable; "
            "using DEFAULT_SCENARIO_PRIORS.",
            file=sys.stderr,
        )
    except Exception as exc:
        print(
            "Warning: failed to load macro forecast probabilities from "
            f"{DEFAULT_MACRO_FORECAST_PATH}: {exc}; using DEFAULT_SCENARIO_PRIORS.",
            file=sys.stderr,
        )
    return translate_scenario_probabilities(dict(DEFAULT_SCENARIO_PRIORS))


def _positive_trade_ids(plan: PortfolioPlan) -> set[str]:
    return {
        decision.trade_id
        for decision in plan.trade_decisions
        if decision.decision != "rejected_portfolio"
        and decision.final_size_pct > 0
    }


def _pct(value: float, *, signed: bool = False, digits: int = 1) -> str:
    sign = "+" if signed and value >= 0 else ""
    return f"{sign}{value:.{digits}%}"


def _print_result(
    *,
    cycle_id: str,
    n_paths: int,
    result: MonteCarloPathResult,
) -> None:
    print("═══ MONTE CARLO SIMULATION ═══")
    print(f"Cycle: {cycle_id}")
    print(f"Paths: {n_paths:,}")
    print(f"Assumption confidence: {result.assumption_confidence}")
    print()
    print("PORTFOLIO")
    print(f"  Expected return:      {_pct(result.portfolio_expected_return, signed=True)}")
    print(f"  Median return:        {_pct(result.portfolio_median_return, signed=True)}")
    print(
        f"  P10 / P90:           {_pct(result.portfolio_p10, signed=True)} / "
        f"{_pct(result.portfolio_p90, signed=True)}"
    )
    print(f"  Prob of loss:         {_pct(result.portfolio_prob_loss, digits=0)}")
    print(f"  Prob of >5% loss:     {_pct(result.portfolio_prob_loss_5pct, digits=0)}")
    print(f"  Prob of >10% loss:    {_pct(result.portfolio_prob_loss_10pct, digits=0)}")
    print(f"  Expected shortfall:   {_pct(result.portfolio_expected_shortfall_5pct, signed=True)}")
    print(f"  Best scenario:        {result.portfolio_best_scenario}")
    print(f"  Worst scenario:       {result.portfolio_worst_scenario}")
    print()
    print("SCENARIO BREAKDOWN")
    for scenario_id, mean_return in result.per_scenario_mean_return.items():
        count = result.scenarios_sampled.get(scenario_id, 0)
        print(f"  {scenario_id:<24} {_pct(mean_return, signed=True):>8}   (drawn {count:,} paths)")
    print()
    print("THEME CONCENTRATION")
    for theme, size in sorted(result.theme_concentration.items()):
        print(f"  {theme:<28} {_pct(size):>8}")
    print()
    print("PER-TICKER")
    print("  Ticker   Median    P10      P90    ProbLoss  PortContr  TailContr  WorstScen")
    for ticker in sorted(result.ticker_median_returns):
        print(
            f"  {ticker:<7} "
            f"{_pct(result.ticker_median_returns[ticker], signed=True):>7} "
            f"{_pct(result.ticker_p10[ticker], signed=True):>8} "
            f"{_pct(result.ticker_p90[ticker], signed=True):>8} "
            f"{_pct(result.ticker_prob_loss[ticker], digits=0):>8} "
            f"{_pct(result.ticker_portfolio_contribution[ticker], signed=True, digits=2):>10} "
            f"{_pct(result.ticker_tail_contribution[ticker], signed=True, digits=2):>10} "
            f"{result.ticker_worst_scenario[ticker]}"
        )
    print()
    print("DIVERGENCE WARNINGS")
    if result.divergence_warnings:
        for warning in result.divergence_warnings:
            print(f"  {warning}")
    else:
        print("  None")


def _recent_cycle_ids(limit: int = 5) -> list[str]:
    root = cycles_dir()
    candidates = [
        item for item in root.iterdir()
        if item.is_dir() and (item / "status.json").exists()
    ]
    candidates.sort(key=lambda path: (path / "status.json").stat().st_mtime, reverse=True)
    return [path.name for path in candidates[:limit]]


def _print_missing_cycle_id_usage() -> None:
    print(
        "Usage: python3 -m src.agent_system.orchestration.run_monte_carlo_standalone "
        "--cycle-id <cycle_id> [--n-paths 10000]"
    )
    recent = _recent_cycle_ids()
    if recent:
        print()
        print("Most recent cycle IDs:")
        for cycle_id in recent:
            print(f"  {cycle_id}")


def run_for_cycle(cycle_id: str, n_paths: int) -> MonteCarloPathResult:
    plan = _load_portfolio_plan(cycle_id)
    trade_ids = _positive_trade_ids(plan)
    if not trade_ids:
        raise ValueError(f"Cycle {cycle_id!r} has no positive-size portfolio trades.")
    scenario_analyses = _load_scenario_analyses(trade_ids)
    trades = _load_trade_ideas(trade_ids)
    probabilities = _load_macro_scenario_probabilities()
    os.chdir(BACKEND_ROOT.parent)
    return _run_monte_carlo(
        plan=plan,
        accepted_trades=trades,
        scenario_analyses=scenario_analyses,
        macro_scenario_probabilities=probabilities,
        cycle_id=cycle_id,
        n_paths=n_paths,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run Monte Carlo from persisted agent-system cycle artifacts.",
        add_help=True,
    )
    parser.add_argument("--cycle-id", default=None, help="Completed cycle id to load.")
    parser.add_argument("--n-paths", type=int, default=10_000, help="Number of paths.")
    args = parser.parse_args(argv)

    if not args.cycle_id:
        _print_missing_cycle_id_usage()
        return 2

    try:
        result = run_for_cycle(args.cycle_id, args.n_paths)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    _print_result(cycle_id=args.cycle_id, n_paths=args.n_paths, result=result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
