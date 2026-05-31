"""
Interactive scoring CLI for macro agent harness outputs.

Usage from repo root:
    python -m src.agent_system.evals.score_macro_harness <run_id>

    # or to score only specific inputs:
    python -m src.agent_system.evals.score_macro_harness <run_id> --filter user_

Scoring is per-rule 0/1/2 plus three calibration items plus freeform notes
plus an overall verdict.

Scores are persisted to data/agent_system/macro_agent_evals/<run_id>_scored.jsonl
alongside the harness output. The scoring CLI is idempotent — re-running
it after scoring a subset will resume from where you left off.

You can quit mid-session with 'q' or Ctrl+C; partial scores are preserved.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_OUTPUT_DIR = Path("data/agent_system/macro_agent_evals")


# Rubric definition. Each tuple is (key, label, description).
RULES_RUBRIC = [
    ("MA-1", "Narrowing", "Theme is meaningfully more specific than the input"),
    (
        "MA-2",
        "Regime-grounded rationale",
        "Rationale cites specific regime elements (layer scores, drivers, falsifiers, forward context)",
    ),
    (
        "MA-3",
        "Edge hypothesis",
        "Articulates a specific mispricing, not just 'this is relevant'",
    ),
    (
        "MA-4",
        "Answerable sub-questions",
        "Each sub-question is a research task with available data",
    ),
    ("MA-5", "No duplication", "Doesn't duplicate existing priorities on the regime"),
    (
        "MA-6",
        "Pragmatic-bearish bias",
        "Bullish framings reframed with discipline, not echoed",
    ),
    (
        "MA-7",
        "Clarification gate",
        "Clarifies only when genuinely ambiguous; doesn't refuse work",
    ),
    (
        "MA-8",
        "Priority rank honesty",
        "priority_rank reflects how regime-aligned and sharp the input was",
    ),
    (
        "MA-9",
        "Horizon inference",
        "expected_edge_decay is defensible given the thesis nature",
    ),
    (
        "MA-10",
        "Schema validity",
        "Output passes all schema constraints (length, bounds, etc.)",
    ),
    (
        "MA-11",
        "Forward context",
        "References Fed path, breakevens, catalysts where relevant",
    ),
    (
        "MA-12",
        "Topic extraction",
        "User's directional framing reframed into topic; agent's view not user's",
    ),
]

CALIBRATION_RUBRIC = [
    ("voice_match", "Voice match", "Sounds like how the user would write a priority"),
    (
        "conviction_calibration",
        "Conviction calibration",
        "priority_rank value feels honest in retrospect",
    ),
    (
        "horizon_calibration",
        "Horizon calibration",
        "expected_edge_decay choice feels defensible",
    ),
]


def load_harness_output(run_id: str, output_dir: Path) -> list[dict]:
    path = output_dir / f"{run_id}.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"Harness output not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_existing_scores(run_id: str, output_dir: Path) -> dict[str, dict]:
    """Load existing scores keyed by input_id."""
    path = output_dir / f"{run_id}_scored.jsonl"
    if not path.exists():
        return {}
    existing = {}
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                record = json.loads(line)
                existing[record["input_id"]] = record
    return existing


def append_score(run_id: str, output_dir: Path, score_record: dict) -> None:
    path = output_dir / f"{run_id}_scored.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(score_record) + "\n")


def display_output(output: dict) -> None:
    """Render a harness output cleanly for review."""
    print()
    print("=" * 78)
    print(f"INPUT: {output['input_id']}  [{output['input_category']}]")
    print("─" * 78)
    print(f"Text: {output['input_text']}")
    if output.get("input_expected_behavior_notes"):
        print()
        print("Expected behavior notes:")
        for line in output["input_expected_behavior_notes"].strip().split("\n"):
            print(f"  {line}")
    print()
    print("─" * 78)
    print(f"RESPONSE: {output['response_kind']}")
    print("─" * 78)

    if output["response_kind"] == "priority":
        r = output["response"]
        print(f"Theme: {r['theme']}")
        print()
        print("Rationale:")
        for line in _wrap(r["rationale"], 76):
            print(f"  {line}")
        print()
        print("Edge hypothesis:")
        for line in _wrap(r["edge_hypothesis"], 76):
            print(f"  {line}")
        print()
        print("Sub-questions:")
        for sq in r["sub_questions"]:
            for i, line in enumerate(_wrap(sq, 74)):
                prefix = "  - " if i == 0 else "    "
                print(f"{prefix}{line}")
        print()
        print(f"priority_rank: {r['priority_rank']}")
        print(f"expected_edge_decay: {r['expected_edge_decay']}")
    elif output["response_kind"] == "clarification":
        r = output["response"]
        print(f"Question: {r['question']}")
        print()
        print("Suggested options:")
        for opt in r["suggested_options"]:
            print(f"  - {opt}")
        print()
        print(f"Reasoning: {r['reasoning']}")
    elif output["response_kind"] == "error":
        print(f"ERROR: {output['error']}")

    print()


def _wrap(text: str, width: int) -> list[str]:
    """Simple word-wrap for display."""
    import textwrap

    return textwrap.wrap(text, width=width) or [""]


def prompt_score(label: str, description: str) -> int | None:
    """Prompt for a 0/1/2 score. Returns None if user quits."""
    while True:
        print(f"  {label}: {description}")
        raw = input(
            "    [0=clearly fails, 1=partial, 2=clearly passes, s=skip, q=quit]: "
        ).strip().lower()
        if raw == "q":
            return None
        if raw == "s":
            return -1
        if raw in ("0", "1", "2"):
            return int(raw)
        print("    invalid input, try again")


def prompt_verdict() -> str | None:
    """Prompt for overall verdict. Returns None if user quits."""
    while True:
        raw = input(
            "  Overall verdict [a=accept, i=iterate, r=reject, q=quit]: "
        ).strip().lower()
        if raw == "q":
            return None
        if raw in ("a", "accept"):
            return "accept"
        if raw in ("i", "iterate"):
            return "iterate"
        if raw in ("r", "reject"):
            return "reject"
        print("    invalid input, try again")


def prompt_notes() -> str | None:
    """Prompt for freeform notes (multiline ok via single line input)."""
    print("  Notes (press enter to skip, type 'q' to quit):")
    raw = input("  > ").strip()
    if raw.lower() == "q":
        return None
    return raw


def score_one(output: dict) -> dict | None:
    """Score one harness output interactively. Returns None if user quits."""
    display_output(output)

    if output["response_kind"] == "error":
        print("Output errored; skipping rubric. Add a note describing what went wrong.")
        notes = prompt_notes()
        if notes is None:
            return None
        return {
            "input_id": output["input_id"],
            "run_id": output["run_id"],
            "errored": True,
            "error": output["error"],
            "notes": notes,
            "scored_at": datetime.now(timezone.utc).isoformat(),
        }

    print("Score each rule [0=fails, 1=partial, 2=passes, s=skip rule, q=quit]")
    print()

    rule_scores = {}
    print("Contract rules:")
    for key, label, description in RULES_RUBRIC:
        score = prompt_score(label, description)
        if score is None:
            return None
        rule_scores[key] = score

    print()
    print("Calibration:")
    calibration_scores = {}
    for key, label, description in CALIBRATION_RUBRIC:
        score = prompt_score(label, description)
        if score is None:
            return None
        calibration_scores[key] = score

    print()
    notes = prompt_notes()
    if notes is None:
        return None

    print()
    verdict = prompt_verdict()
    if verdict is None:
        return None

    return {
        "input_id": output["input_id"],
        "input_category": output["input_category"],
        "run_id": output["run_id"],
        "rule_scores": rule_scores,
        "calibration_scores": calibration_scores,
        "verdict": verdict,
        "notes": notes,
        "scored_at": datetime.now(timezone.utc).isoformat(),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Interactively score macro agent harness outputs."
    )
    parser.add_argument("run_id", help="Harness run ID to score.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory with harness output JSONL files.",
    )
    parser.add_argument(
        "--filter",
        type=str,
        default=None,
        help="Only score inputs whose id starts with this prefix.",
    )
    parser.add_argument(
        "--rescore",
        action="store_true",
        help="Re-score inputs that already have scores (default: skip).",
    )
    args = parser.parse_args()

    outputs = load_harness_output(args.run_id, args.output_dir)
    existing_scores = load_existing_scores(args.run_id, args.output_dir)

    if args.filter:
        outputs = [o for o in outputs if o["input_id"].startswith(args.filter)]

    if not args.rescore:
        outputs = [o for o in outputs if o["input_id"] not in existing_scores]

    if not outputs:
        print("Nothing to score. All inputs in this run are already scored.")
        print("To re-score, pass --rescore.")
        return

    print(f"Scoring {len(outputs)} outputs from run {args.run_id}")
    print("(Press Ctrl+C or type 'q' at any prompt to quit; progress is saved.)")

    for idx, output in enumerate(outputs, 1):
        print()
        print(f"╔{'═' * 76}╗")
        print(f"║ {idx} of {len(outputs)}  —  {output['input_id']:<60} ║")
        print(f"╚{'═' * 76}╝")

        try:
            score_record = score_one(output)
        except KeyboardInterrupt:
            print()
            print("Interrupted. Partial scores saved.")
            return

        if score_record is None:
            print("Quit requested. Partial scores saved.")
            return

        append_score(args.run_id, args.output_dir, score_record)
        print(f"  ✓ scored ({score_record['verdict']})")

    print()
    print(f"Done. All {len(outputs)} outputs scored.")
    print(f"Scores at: {args.output_dir / f'{args.run_id}_scored.jsonl'}")


if __name__ == "__main__":
    main()
