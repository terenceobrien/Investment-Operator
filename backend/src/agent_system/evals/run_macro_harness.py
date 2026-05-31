"""
Run the macro agent against all test inputs and persist outputs.

Usage from repo root:
    python -m src.agent_system.evals.run_macro_harness

    # or with options:
    python -m src.agent_system.evals.run_macro_harness --inputs-file <path>
    python -m src.agent_system.evals.run_macro_harness --dry-run
    python -m src.agent_system.evals.run_macro_harness --filter user_

The runner ALWAYS uses the real OpenAI API. There is no mock path here —
this harness exists specifically to evaluate real agent behavior. Cost
per full run (15 inputs) is roughly $0.50-2.00 depending on model.

Output is persisted to data/agent_system/macro_agent_evals/run_<timestamp>.jsonl
with one line per input. Each line is a JSON object containing:
    - input_id, input_text, input_category
    - input_expected_behavior_notes (from the YAML)
    - response_kind: "priority" | "clarification" | "error"
    - response: the full ResearchPriority or ClarificationRequest object
    - error: error message if response_kind == "error"
    - timing_ms: wall-clock duration of the agent call
    - run_id: shared across all inputs in this harness run
    - run_started_at: timestamp at run start
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

from src.agent_system.agents.macro_agent import (
    MacroAgentValidationError,
    translate_to_priority,
)
from src.agent_system.orchestration.run_research_cycle import _select_regime_state
from src.agent_system.schemas.regime import (
    ClarificationRequest,
    ResearchPriority,
)

logger = logging.getLogger("agent_system.evals.macro_harness")

DEFAULT_INPUTS_PATH = Path(__file__).parent / "macro_agent_inputs.yaml"
DEFAULT_OUTPUT_DIR = Path("data/agent_system/macro_agent_evals")


async def run_one_input(
    input_record: dict,
    regime_state,
    run_id: str,
    run_started_at: str,
) -> dict:
    """
    Run the agent on a single input. Always returns a dict suitable for
    JSONL output — never raises. Errors are captured into the dict.
    """
    start = time.time()
    try:
        result = await translate_to_priority(
            user_input=input_record["text"],
            regime_state=regime_state,
        )
        timing_ms = int((time.time() - start) * 1000)

        if isinstance(result, ResearchPriority):
            return _result_record(
                input_record=input_record,
                response_kind="priority",
                response=result.model_dump(mode="json"),
                error=None,
                timing_ms=timing_ms,
                run_id=run_id,
                run_started_at=run_started_at,
            )
        elif isinstance(result, ClarificationRequest):
            return _result_record(
                input_record=input_record,
                response_kind="clarification",
                response=result.model_dump(mode="json"),
                error=None,
                timing_ms=timing_ms,
                run_id=run_id,
                run_started_at=run_started_at,
            )
        else:
            return _result_record(
                input_record=input_record,
                response_kind="error",
                response=None,
                error=f"Unexpected response type: {type(result).__name__}",
                timing_ms=timing_ms,
                run_id=run_id,
                run_started_at=run_started_at,
            )
    except MacroAgentValidationError as e:
        timing_ms = int((time.time() - start) * 1000)
        return _result_record(
            input_record=input_record,
            response_kind="error",
            response=None,
            error=f"MacroAgentValidationError: {e}",
            timing_ms=timing_ms,
            run_id=run_id,
            run_started_at=run_started_at,
        )
    except Exception as e:
        timing_ms = int((time.time() - start) * 1000)
        return _result_record(
            input_record=input_record,
            response_kind="error",
            response=None,
            error=f"{type(e).__name__}: {e}",
            timing_ms=timing_ms,
            run_id=run_id,
            run_started_at=run_started_at,
        )


async def run_harness(
    inputs_path: Path = DEFAULT_INPUTS_PATH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    filter_prefix: Optional[str] = None,
    dry_run: bool = False,
) -> dict:
    """
    Run the harness end-to-end and persist results.

    Args:
        inputs_path: Path to the YAML test inputs file.
        output_dir: Directory where JSONL output is written.
        filter_prefix: If provided, only run inputs whose id starts with this.
        dry_run: If True, load and validate inputs but skip agent calls.

    Returns:
        Summary dict with run_id, output_path, counts, and timing info.
    """
    with inputs_path.open("r", encoding="utf-8") as f:
        inputs_data = yaml.safe_load(f)
    inputs = inputs_data.get("inputs", [])

    if filter_prefix:
        inputs = [i for i in inputs if i["id"].startswith(filter_prefix)]

    if not inputs:
        return {"error": "no inputs to run", "count": 0}

    regime, regime_source, fallback_reason = _select_regime_state()

    run_started_at_dt = datetime.now(timezone.utc)
    run_id = f"macro_harness_{run_started_at_dt.strftime('%Y%m%d_%H%M%S')}"
    run_started_at = run_started_at_dt.isoformat()

    if dry_run:
        print(f"[dry-run] Loaded {len(inputs)} inputs")
        print(f"[dry-run] Regime source: {regime_source}")
        print(f"[dry-run] Run ID would be: {run_id}")
        for i in inputs:
            print(f"  - {i['id']}: {i['text'][:80]}...")
        return {
            "run_id": run_id,
            "dry_run": True,
            "count": len(inputs),
            "regime_source": regime_source,
        }

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{run_id}.jsonl"

    results = []
    for idx, input_record in enumerate(inputs, 1):
        print(
            f"[{idx}/{len(inputs)}] Running: "
            f"{input_record['id']} - {input_record['text'][:60]}..."
        )
        result = await run_one_input(
            input_record=input_record,
            regime_state=regime,
            run_id=run_id,
            run_started_at=run_started_at,
        )
        results.append(result)
        with output_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(result) + "\n")

        if result["response_kind"] == "priority":
            theme = result["response"]["theme"]
            rank = result["response"]["priority_rank"]
            print(f"    → priority (rank {rank}): {theme[:80]}")
        elif result["response_kind"] == "clarification":
            question = result["response"]["question"]
            print(f"    → clarification: {question[:80]}")
        else:
            print(f"    → ERROR: {result['error']}")

    priority_count = sum(1 for r in results if r["response_kind"] == "priority")
    clarification_count = sum(
        1 for r in results if r["response_kind"] == "clarification"
    )
    error_count = sum(1 for r in results if r["response_kind"] == "error")
    total_ms = sum(r["timing_ms"] for r in results)

    summary = {
        "run_id": run_id,
        "output_path": str(output_path),
        "regime_source": regime_source,
        "regime_fallback_reason": fallback_reason,
        "input_count": len(inputs),
        "priority_count": priority_count,
        "clarification_count": clarification_count,
        "error_count": error_count,
        "total_ms": total_ms,
        "average_ms": total_ms // len(inputs) if inputs else 0,
    }

    print()
    print("─" * 60)
    print(f"Run complete: {run_id}")
    print(f"  priorities: {priority_count}")
    print(f"  clarifications: {clarification_count}")
    print(f"  errors: {error_count}")
    print(f"  total time: {total_ms / 1000:.1f}s")
    print(f"  average per input: {summary['average_ms']}ms")
    print(f"  output: {output_path}")
    print()
    print("To score this run interactively:")
    print(f"  python -m src.agent_system.evals.score_macro_harness {run_id}")
    print()

    return summary


def _result_record(
    *,
    input_record: dict,
    response_kind: str,
    response: dict | None,
    error: str | None,
    timing_ms: int,
    run_id: str,
    run_started_at: str,
) -> dict:
    return {
        "input_id": input_record["id"],
        "input_text": input_record["text"],
        "input_category": input_record["category"],
        "input_expected_behavior_notes": input_record.get(
            "expected_behavior_notes", ""
        ),
        "response_kind": response_kind,
        "response": response,
        "error": error,
        "timing_ms": timing_ms,
        "run_id": run_id,
        "run_started_at": run_started_at,
    }


def _build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the macro agent against test inputs and persist outputs."
    )
    parser.add_argument(
        "--inputs-file",
        type=Path,
        default=DEFAULT_INPUTS_PATH,
        help="Path to test inputs YAML file.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for JSONL output.",
    )
    parser.add_argument(
        "--filter",
        type=str,
        default=None,
        help="Only run inputs whose id starts with this prefix.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Load inputs and regime state but skip agent calls.",
    )
    return parser


def main():
    args = _build_argparser().parse_args()
    asyncio.run(
        run_harness(
            inputs_path=args.inputs_file,
            output_dir=args.output_dir,
            filter_prefix=args.filter,
            dry_run=args.dry_run,
        )
    )


if __name__ == "__main__":
    main()
