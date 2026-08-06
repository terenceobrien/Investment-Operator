"""
Interactive scoring CLI for thematic agent harness outputs.

Usage from repo root:
    python -m src.agent_system.evals.score_thematic_harness <run_id>

    # or to score only specific inputs:
    python -m src.agent_system.evals.score_thematic_harness <run_id> --filter user_

Scoring is map-level: each map gets one score per contract rule (TA-1
through TA-20), plus calibration items, plus freeform notes, plus an
overall verdict. Per-candidate scoring is not supported in v1 - if
specific candidates need detailed evaluation, capture observations in
the freeform notes field.

Scores are persisted to data/agent_system/thematic_agent_evals/<run_id>_scored.jsonl
alongside the harness output. The scoring CLI is idempotent - re-running
it after scoring a subset will resume from where you left off.

You can quit mid-session with 'q' or Ctrl+C; partial scores are preserved.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.agent_system.paths import thematic_agent_evals_dir

DEFAULT_OUTPUT_DIR = thematic_agent_evals_dir(create=False)


# Rubric definition. Each tuple is (key, label, description).
RULES_RUBRIC = [
    (
        "TA-1",
        "Priority-implied candidates",
        "Candidates fit the priority's specific thesis, not just sector-adjacent",
    ),
    (
        "TA-2",
        "Preliminary variant strength",
        "variant_strength reflects preliminary hypothesis, not validated edge",
    ),
    (
        "TA-3",
        "Substantive fields",
        "thematic_fit, consensus_view, potential_variant_view all populated "
        "meaningfully (empty variant + UNCLEAR is OK)",
    ),
    (
        "TA-4",
        "Consensus grounding",
        "Consensus claims grounded in regime/priority or qualified as priors",
    ),
    (
        "TA-5",
        "Auditable selection",
        "mapping_logic substantive, excluded has 2-3+ entries with reasons, "
        "universe_considered set",
    ),
    (
        "TA-6",
        "Sub-questions covered",
        "Candidate set collectively addresses the priority's sub_questions",
    ),
    (
        "TA-7",
        "Regime alignment as metadata",
        "Doesn't filter out regime-contrarian candidates if priority is contrarian",
    ),
    (
        "TA-8",
        "No duplication",
        "Candidates don't redundantly express same thesis with different tickers",
    ),
    (
        "TA-9",
        "Candidate count appropriate",
        "5-15 candidates, count reflects how many distinct thesis-angles exist",
    ),
    ("TA-10", "Schema validity", "Output passed schema validation"),
    ("TA-11", "Real tickers only", "No invented or hallucinated tickers"),
    (
        "TA-12",
        "Appropriate clarification gate",
        "Returns clarification only when priority is genuinely insufficient",
    ),
    (
        "TA-13",
        "Theme tags meaningful",
        "Each candidate has 1-3 specific theme_tags, not generic",
    ),
    (
        "TA-14",
        "Fit strength reflects real tie",
        "fit_strength values reflect actual fit, no inflation",
    ),
    (
        "TA-15",
        "Fit and variant strength independent",
        "fit_strength and variant_strength move independently, not coupled",
    ),
    (
        "TA-16",
        "Research depth calibrated",
        "DEEP/STANDARD/SHALLOW distributed based on candidate quality, "
        "not all STANDARD",
    ),
    (
        "TA-17",
        "Catalysts add information",
        "Per-candidate catalysts are name-specific, not duplicates of regime macros",
    ),
    (
        "TA-18",
        "priority_rank calibrated",
        "Ranks distributed meaningfully across candidates, not flat",
    ),
    (
        "TA-19",
        "Forward context engaged",
        "Long-duration single-name candidates address Fed-path tension; "
        "cross-asset candidates address forward-path conditions where variant "
        "view depends on them",
    ),
    (
        "TA-20",
        "Unique priority_rank",
        "Each candidate has a unique rank within the map (1 to 15)",
    ),
]

CALIBRATION_RUBRIC = [
    ("voice_match", "Voice match", "Sounds like how the user would describe candidates"),
    (
        "candidate_diversity",
        "Candidate diversity",
        "Map captures meaningfully distinct expressions of the thesis",
    ),
    (
        "mapping_logic_quality",
        "Mapping logic quality",
        "Explains selection clearly; not generic",
    ),
    (
        "exclusions_quality",
        "Exclusions quality",
        "Excluded entries are specific and informative, not boilerplate",
    ),
    (
        "actionable_research",
        "Actionable research",
        "Map represents research you would actually act on",
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


def _wrap(text: str, width: int) -> list[str]:
    """Simple word-wrap for display."""
    import textwrap

    return textwrap.wrap(text, width=width) or [""]


def display_output(output: dict) -> None:
    """Render a thematic harness output cleanly for review."""
    print()
    print("=" * 78)
    print(f"INPUT: {output['input_id']}")
    print(f"Source macro run: {output['source_macro_run_id']}")
    print("-" * 78)

    source_priority = output.get("source_priority", {})
    print(f"PRIORITY: {source_priority.get('theme', '(no theme)')}")
    print()
    print("Edge hypothesis:")
    for line in _wrap(source_priority.get("edge_hypothesis", ""), 76):
        print(f"  {line}")
    print()

    print("-" * 78)
    print(f"RESPONSE: {output['response_kind']}")
    print("-" * 78)

    if output["response_kind"] == "thematic_map":
        response = output["response"]
        print("Mapping logic:")
        for line in _wrap(response.get("mapping_logic", ""), 76):
            print(f"  {line}")
        print()
        print(f"Universe considered: {response.get('universe_considered', 0)}")
        print(f"Candidates: {len(response.get('candidates', []))}")
        print(f"Excluded: {len(response.get('excluded', []))}")
        print()

        print("Candidates:")
        for candidate in sorted(
            response.get("candidates", []),
            key=lambda item: item.get("priority_rank", 99),
        ):
            ticker = candidate.get("ticker", "?")
            rank = candidate.get("priority_rank", "?")
            fit = candidate.get("fit_strength", 0)
            variant_strength = candidate.get("variant_strength", "?")
            depth = candidate.get("recommended_research_depth", "?")
            tags = ",".join(candidate.get("theme_tags", []))
            print(
                f"  [#{rank}] {ticker:<6} fit={fit:.2f} "
                f"variant={variant_strength:<8} depth={depth:<8} [{tags}]"
            )
            fit_text = candidate.get("thematic_fit", "")
            if fit_text:
                for line in _wrap(fit_text, 70):
                    print(f"       fit: {line}")
            consensus_view = candidate.get("consensus_view", "")
            if consensus_view:
                for line in _wrap(consensus_view, 70):
                    print(f"       consensus: {line}")
            variant_view = candidate.get("potential_variant_view", "")
            if variant_view:
                for line in _wrap(variant_view, 70):
                    print(f"       variant: {line}")
            else:
                print("       variant: (empty, UNCLEAR)")
            print()

        if response.get("excluded"):
            print("Excluded:")
            for exclusion in response["excluded"]:
                ticker = exclusion.get("ticker", "?")
                reason = exclusion.get("reason", "")
                print(f"  {ticker}: {reason[:120]}")

    elif output["response_kind"] == "clarification":
        response = output["response"]
        print(f"Question: {response.get('question', '')}")
        print()
        print("Suggested options:")
        for option in response.get("suggested_options", []):
            print(f"  - {option}")
        print()
        print(f"Reasoning: {response.get('reasoning', '')}")
    elif output["response_kind"] == "error":
        print(f"ERROR: {output['error']}")

    print()


def prompt_score(label: str, description: str) -> Optional[int]:
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


def prompt_verdict() -> Optional[str]:
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


def prompt_notes() -> Optional[str]:
    """Prompt for freeform notes."""
    print("  Notes (press enter to skip, type 'q' to quit):")
    raw = input("  > ").strip()
    if raw.lower() == "q":
        return None
    return raw


def score_one(output: dict) -> Optional[dict]:
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
        "source_priority_theme": output.get("source_priority", {}).get("theme", ""),
        "run_id": output["run_id"],
        "rule_scores": rule_scores,
        "calibration_scores": calibration_scores,
        "verdict": verdict,
        "notes": notes,
        "scored_at": datetime.now(timezone.utc).isoformat(),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Interactively score thematic agent harness outputs."
    )
    parser.add_argument("run_id", help="Thematic harness run ID to score.")
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
        help=(
            "Only run inputs matching one of the comma-separated prefixes. "
            "Example: --filter user_01,user_06,draft_08 runs three specific "
            "inputs. Single prefix still works as before (--filter user_)."
        ),
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
        prefixes = [p.strip() for p in args.filter.split(",") if p.strip()]
        outputs = [
            o
            for o in outputs
            if any(o["input_id"].startswith(p) for p in prefixes)
        ]

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
        print(f"+{'-' * 76}+")
        print(f"| {idx} of {len(outputs)}  -  {output['input_id']:<60} |")
        print(f"+{'-' * 76}+")

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
        score_label = score_record.get("verdict", "error noted")
        print(f"  scored ({score_label})")

    print()
    print(f"Done. All {len(outputs)} outputs scored.")
    print(f"Scores at: {args.output_dir / f'{args.run_id}_scored.jsonl'}")


if __name__ == "__main__":
    main()
