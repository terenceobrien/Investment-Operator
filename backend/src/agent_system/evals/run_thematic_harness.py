"""
Run the thematic agent against priorities from a previous macro harness
run, and persist outputs.

Usage from repo root:
    python -m src.agent_system.evals.run_thematic_harness --macro-run <macro_run_id>

    # or with options:
    python -m src.agent_system.evals.run_thematic_harness --macro-run <id> --filter user_
    python -m src.agent_system.evals.run_thematic_harness --macro-run <id> --dry-run

The --macro-run flag is REQUIRED. It points to a previous macro harness
output (e.g. macro_harness_20260523_212316). The thematic agent runs on
the priorities from that file, NOT on the original user inputs.

Why this design: cost predictability and iteration consistency. The macro
harness costs $2-3 per run; the thematic harness costs another $3-5. By
using existing macro outputs, the thematic agent can be iterated against
the same priorities across multiple runs, making iteration comparisons
clean.

If --macro-run is not specified, the harness lists available macro runs
and exits with a clear message. It does NOT silently run the macro agent.

Inputs that produced a clarification (not a priority) from the macro
agent are skipped with a logged note - the thematic agent has nothing
to work with for those.

Output is persisted to data/agent_system/thematic_agent_evals/run_<timestamp>.jsonl
with one line per input. Each line is a JSON object containing:
    - input_id (matches source macro input_id)
    - source_priority (full ResearchPriority embedded for self-contained scoring)
    - source_macro_run_id (link back to the originating macro run)
    - response_kind: "thematic_map" | "clarification" | "error"
    - response: the full ThematicMap or ClarificationRequest object
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
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.agent_system.agents.thematic_agent import (
    ThematicAgentValidationError,
    translate_priority_to_candidates,
)
from src.agent_system.orchestration.run_research_cycle import _select_regime_state
from src.agent_system.schemas.regime import (
    ClarificationRequest,
    ResearchPriority,
)
from src.agent_system.schemas.thematic import ThematicMap

logger = logging.getLogger("agent_system.evals.thematic_harness")

# Resolve against the backend application root so repo-root invocation via the
# `src` import shim reaches the same persisted macro runs used by the backend.
BACKEND_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MACRO_DIR = BACKEND_ROOT / "data/agent_system/macro_agent_evals"
DEFAULT_OUTPUT_DIR = BACKEND_ROOT / "data/agent_system/thematic_agent_evals"


def _list_available_macro_runs(macro_dir: Path) -> list[str]:
    """Return list of available macro run IDs (filenames without extension)."""
    if not macro_dir.exists():
        return []
    return sorted(
        [p.stem for p in macro_dir.glob("macro_harness_*.jsonl")],
        reverse=True,
    )


def _load_macro_priorities(macro_run_id: str, macro_dir: Path) -> list[dict]:
    """Load macro harness output and return entries that contain priorities."""
    path = macro_dir / f"{macro_run_id}.jsonl"
    if not path.exists():
        available = _list_available_macro_runs(macro_dir)
        msg = f"Macro run file not found: {path}\n\nAvailable runs:\n"
        for run in available:
            msg += f"  {run}\n"
        raise FileNotFoundError(msg)

    with path.open("r", encoding="utf-8") as f:
        records = [json.loads(line) for line in f if line.strip()]

    # A macro clarification or error leaves no priority to map to candidates.
    for record in records:
        if record.get("response_kind") != "priority":
            logger.info(
                "[skip] %s: macro response_kind=%s; no priority to map",
                record.get("input_id", "(unknown input)"),
                record.get("response_kind", "(missing)"),
            )
    return [r for r in records if r.get("response_kind") == "priority"]


async def run_one_input(
    macro_record: dict,
    regime_state,
    run_id: str,
    run_started_at: str,
    source_macro_run_id: str,
) -> dict:
    """
    Run the thematic agent on a single macro priority. Always returns a dict
    suitable for JSONL output - never raises. Errors are captured into the dict.
    """
    try:
        priority = ResearchPriority.model_validate(macro_record["response"])
    except Exception as e:
        return {
            "input_id": macro_record["input_id"],
            "source_priority": macro_record["response"],
            "source_macro_run_id": source_macro_run_id,
            "response_kind": "error",
            "response": None,
            "error": f"Failed to reconstruct ResearchPriority: {e}",
            "timing_ms": 0,
            "run_id": run_id,
            "run_started_at": run_started_at,
        }

    start = time.time()
    try:
        result = await translate_priority_to_candidates(
            priority=priority,
            regime_state=regime_state,
        )
        timing_ms = int((time.time() - start) * 1000)

        if isinstance(result, ThematicMap):
            return {
                "input_id": macro_record["input_id"],
                "source_priority": macro_record["response"],
                "source_macro_run_id": source_macro_run_id,
                "response_kind": "thematic_map",
                "response": result.model_dump(mode="json"),
                "error": None,
                "timing_ms": timing_ms,
                "run_id": run_id,
                "run_started_at": run_started_at,
            }
        if isinstance(result, ClarificationRequest):
            return {
                "input_id": macro_record["input_id"],
                "source_priority": macro_record["response"],
                "source_macro_run_id": source_macro_run_id,
                "response_kind": "clarification",
                "response": result.model_dump(mode="json"),
                "error": None,
                "timing_ms": timing_ms,
                "run_id": run_id,
                "run_started_at": run_started_at,
            }
        return {
            "input_id": macro_record["input_id"],
            "source_priority": macro_record["response"],
            "source_macro_run_id": source_macro_run_id,
            "response_kind": "error",
            "response": None,
            "error": f"Unexpected response type: {type(result).__name__}",
            "timing_ms": timing_ms,
            "run_id": run_id,
            "run_started_at": run_started_at,
        }
    except ThematicAgentValidationError as e:
        timing_ms = int((time.time() - start) * 1000)
        return {
            "input_id": macro_record["input_id"],
            "source_priority": macro_record["response"],
            "source_macro_run_id": source_macro_run_id,
            "response_kind": "error",
            "response": None,
            "error": f"ThematicAgentValidationError: {e}",
            "timing_ms": timing_ms,
            "run_id": run_id,
            "run_started_at": run_started_at,
        }
    except Exception as e:
        timing_ms = int((time.time() - start) * 1000)
        return {
            "input_id": macro_record["input_id"],
            "source_priority": macro_record["response"],
            "source_macro_run_id": source_macro_run_id,
            "response_kind": "error",
            "response": None,
            "error": f"{type(e).__name__}: {e}",
            "timing_ms": timing_ms,
            "run_id": run_id,
            "run_started_at": run_started_at,
        }


async def run_harness(
    macro_run_id: str,
    macro_dir: Path = DEFAULT_MACRO_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    filter_prefix: Optional[str] = None,
    dry_run: bool = False,
) -> dict:
    """
    Run the harness end-to-end and persist results.

    Args:
        macro_run_id: ID of the macro harness run whose priorities should be
            used as input (REQUIRED).
        macro_dir: Directory containing macro harness output JSONL files.
        output_dir: Directory where thematic JSONL output is written.
        filter_prefix: If provided, only run inputs whose ids match one of the
            comma-separated prefixes.
        dry_run: If True, load inputs but skip agent calls.
    """
    try:
        macro_records = _load_macro_priorities(macro_run_id, macro_dir)
    except FileNotFoundError as e:
        print(str(e))
        sys.exit(1)

    if filter_prefix:
        prefixes = [p.strip() for p in filter_prefix.split(",") if p.strip()]
        macro_records = [
            r
            for r in macro_records
            if any(r["input_id"].startswith(p) for p in prefixes)
        ]

    if not macro_records:
        print(
            f"No priorities found in {macro_run_id} "
            f"matching filter '{filter_prefix or '*'}'"
        )
        sys.exit(1)

    regime, regime_source, fallback_reason = _select_regime_state()

    run_started_at_dt = datetime.now(timezone.utc)
    run_id = f"thematic_harness_{run_started_at_dt.strftime('%Y%m%d_%H%M%S')}"
    run_started_at = run_started_at_dt.isoformat()

    if dry_run:
        print(f"[dry-run] Loaded {len(macro_records)} priorities from {macro_run_id}")
        print(f"[dry-run] Regime source: {regime_source}")
        print(f"[dry-run] Run ID would be: {run_id}")
        for record in macro_records:
            theme = record["response"]["theme"]
            print(f"  - {record['input_id']}: {theme[:80]}")
        return {
            "run_id": run_id,
            "dry_run": True,
            "count": len(macro_records),
            "regime_source": regime_source,
        }

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{run_id}.jsonl"

    results = []
    for idx, macro_record in enumerate(macro_records, 1):
        theme = macro_record["response"]["theme"]
        print(f"[{idx}/{len(macro_records)}] {macro_record['input_id']}: {theme[:60]}...")
        result = await run_one_input(
            macro_record=macro_record,
            regime_state=regime,
            run_id=run_id,
            run_started_at=run_started_at,
            source_macro_run_id=macro_run_id,
        )
        results.append(result)

        with output_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(result) + "\n")

        if result["response_kind"] == "thematic_map":
            candidate_count = len(result["response"]["candidates"])
            excluded_count = len(result["response"]["excluded"])
            print(f"    -> map ({candidate_count} candidates, {excluded_count} excluded)")
        elif result["response_kind"] == "clarification":
            question = result["response"]["question"]
            print(f"    -> clarification: {question[:80]}")
        else:
            print(f"    -> ERROR: {result['error']}")

    map_count = sum(1 for r in results if r["response_kind"] == "thematic_map")
    clarification_count = sum(
        1 for r in results if r["response_kind"] == "clarification"
    )
    error_count = sum(1 for r in results if r["response_kind"] == "error")
    total_ms = sum(r["timing_ms"] for r in results)

    summary = {
        "run_id": run_id,
        "source_macro_run_id": macro_run_id,
        "output_path": str(output_path),
        "regime_source": regime_source,
        "regime_fallback_reason": fallback_reason,
        "input_count": len(macro_records),
        "map_count": map_count,
        "clarification_count": clarification_count,
        "error_count": error_count,
        "total_ms": total_ms,
        "average_ms": total_ms // len(macro_records) if macro_records else 0,
    }

    print()
    print("-" * 60)
    print(f"Run complete: {run_id}")
    print(f"  Source macro run: {macro_run_id}")
    print(f"  Thematic maps: {map_count}")
    print(f"  Clarifications: {clarification_count}")
    print(f"  Errors: {error_count}")
    print(f"  Total time: {total_ms / 1000:.1f}s")
    print(f"  Average per input: {summary['average_ms']}ms")
    print(f"  Output: {output_path}")
    print()
    print("To score this run interactively:")
    print(f"  python -m src.agent_system.evals.score_thematic_harness {run_id}")
    print()

    return summary


def _build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the thematic agent against priorities from a macro harness run."
    )
    parser.add_argument(
        "--macro-run",
        type=str,
        required=False,
        default=None,
        help=(
            "ID of the macro harness run providing priorities "
            "(e.g. macro_harness_20260523_212316). REQUIRED."
        ),
    )
    parser.add_argument(
        "--macro-dir",
        type=Path,
        default=DEFAULT_MACRO_DIR,
        help="Directory with macro harness JSONL outputs.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for thematic JSONL output.",
    )
    parser.add_argument(
        "--filter",
        type=str,
        default=None,
        help=(
            "Only run inputs matching one of the comma-separated prefixes. "
            "Example: --filter user_01,user_06,draft_08 runs three specific "
            "inputs. Single prefix still works as before (--filter user_)."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Load inputs and regime state but skip agent calls.",
    )
    return parser


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = _build_argparser().parse_args()

    if args.macro_run is None:
        print("ERROR: --macro-run is required.\n")
        available = _list_available_macro_runs(args.macro_dir)
        if available:
            print("Available macro runs:")
            for run in available:
                print(f"  {run}")
            print()
            print("Use one of these with --macro-run, or run a new macro harness first.")
        else:
            print(f"No macro runs found in {args.macro_dir}.")
            print("Run a macro harness first:")
            print("  python -m src.agent_system.evals.run_macro_harness")
        sys.exit(1)

    asyncio.run(
        run_harness(
            macro_run_id=args.macro_run,
            macro_dir=args.macro_dir,
            output_dir=args.output_dir,
            filter_prefix=args.filter,
            dry_run=args.dry_run,
        )
    )


if __name__ == "__main__":
    main()
