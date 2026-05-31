"""CLI for proposing, reviewing, and promoting macro research priorities."""
from __future__ import annotations

import argparse
import asyncio
import difflib
import sys
from pathlib import Path

from pydantic import ValidationError

from src.agent_system.agents.macro_agent import (
    MacroAgentValidationError,
    translate_to_priority,
)
from src.agent_system.macro import loader
from src.agent_system.orchestration.run_research_cycle import _select_regime_state
from src.agent_system.schemas.regime import ClarificationRequest, ResearchPriority


def _print_priority(priority: ResearchPriority, *, indent: str = "  ") -> None:
    print(
        f"{indent}- rank {priority.priority_rank} | "
        f"{priority.expected_edge_decay.value} | {priority.theme}"
    )
    print(f"{indent}  sub_questions: {len(priority.sub_questions)}")


def _print_clarification(item: dict) -> None:
    original = item.get("original_user_input") or item.get("original_input") or "(unknown)"
    print(f"  - input: {original}")
    print(f"    question: {item.get('question', '')}")
    options = item.get("suggested_options", []) or []
    if options:
        print("    suggested_options:")
        for option in options:
            print(f"      - {option}")


def _print_collection(
    priorities: list[ResearchPriority],
    clarifications: list[dict],
    *,
    label: str,
) -> None:
    print(f"{label}: {len(priorities)} priorit{'y' if len(priorities) == 1 else 'ies'}")
    for priority in priorities:
        _print_priority(priority)

    if clarifications:
        print()
        print(
            f"Clarifications: {len(clarifications)} "
            f"input{'s' if len(clarifications) != 1 else ''} need refinement"
        )
        for clarification in clarifications:
            _print_clarification(clarification)


async def _cmd_propose(args: argparse.Namespace) -> int:
    inputs_file = args.inputs_file or loader.default_inputs_file()
    try:
        inputs = loader.load_input_lines(inputs_file)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        print(
            f"Create it with one free-text input per line, or pass --inputs-file PATH.",
            file=sys.stderr,
        )
        return 1

    if not inputs:
        print(f"No inputs found in {inputs_file}", file=sys.stderr)
        return 1

    regime, regime_source, fallback_reason = _select_regime_state()
    print(f"Regime source: {regime_source}")
    if fallback_reason:
        print(f"Fallback reason: {fallback_reason}")

    priorities: list[ResearchPriority] = []
    clarifications: list[dict] = []
    enable_clarification = not args.no_clarification

    print(f"Running macro agent for {len(inputs)} input(s)")
    try:
        for idx, user_input in enumerate(inputs, 1):
            print(f"[{idx}/{len(inputs)}] {user_input[:100]}")
            result = await translate_to_priority(
                user_input=user_input,
                regime_state=regime,
                enable_clarification=enable_clarification,
            )
            if isinstance(result, ResearchPriority):
                priorities.append(result)
                print(f"    -> priority: {result.theme}")
            elif isinstance(result, ClarificationRequest):
                clarifications.append(loader.clarification_to_yaml_dict(user_input, result))
                print(f"    -> clarification: {result.question}")
            else:  # pragma: no cover - defensive guard for future return types
                raise MacroAgentValidationError(
                    f"Unexpected macro agent result type: {type(result).__name__}"
                )
    except (MacroAgentValidationError, ValueError, ValidationError) as exc:
        print(
            "Macro priority proposal failed; no proposed_priorities.yaml was written.",
            file=sys.stderr,
        )
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    output_path = loader.write_proposed_priorities(priorities, clarifications)
    print()
    print(f"Wrote proposed priorities to {output_path}")
    print()
    _print_collection(priorities, clarifications, label="Proposed")

    if clarifications:
        print()
        print(
            f"{len(clarifications)} input(s) need clarification. Refine inputs.txt "
            f"and re-run propose, OR run promote to commit the "
            f"{len(priorities)} priorities that succeeded."
        )

    low = len(inputs) * 0.30
    high = len(inputs) * 0.50
    print()
    print(f"Estimated LLM cost: ${low:.2f}-${high:.2f}")
    return 0


def _cmd_promote(args: argparse.Namespace) -> int:
    try:
        priorities, clarifications = loader.load_proposed_priorities()
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (ValueError, ValidationError) as exc:
        print(f"Proposed priorities failed validation; not promoted:\n{exc}", file=sys.stderr)
        return 1

    if not priorities:
        print(
            "No priorities to promote. proposed_priorities.yaml contains only "
            "clarifications or is empty.",
            file=sys.stderr,
        )
        return 1

    try:
        count, archive_path, comments_preserved = loader.promote_priorities(
            append=args.append
        )
    except (FileNotFoundError, ValueError, ValidationError) as exc:
        print(f"Promotion failed; current_regime.yaml was not updated:\n{exc}", file=sys.stderr)
        return 1

    mode = "appended to" if args.append else "replaced"
    print(f"Promoted {count} priorit{'y' if count == 1 else 'ies'}; {mode} seed_research_priorities.")
    print(f"Archived promoted snapshot to {archive_path}")
    if clarifications:
        print(f"Ignored {len(clarifications)} clarification(s); only priorities are promoted.")
    if not comments_preserved:
        print(
            "WARNING: ruamel.yaml is not available; PyYAML rewrote "
            "current_regime.yaml and may strip comments/formatting.",
            file=sys.stderr,
        )
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    if args.proposed:
        try:
            priorities, clarifications = loader.load_proposed_priorities()
        except FileNotFoundError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except (ValueError, ValidationError) as exc:
            print(f"Proposed priorities failed validation:\n{exc}", file=sys.stderr)
            return 1
        _print_collection(priorities, clarifications, label="Proposed")
        return 0

    try:
        priorities = loader.load_current_priorities()
    except (FileNotFoundError, ValueError, ValidationError) as exc:
        print(f"Could not load current priorities:\n{exc}", file=sys.stderr)
        return 1
    _print_collection(priorities, [], label="Current")
    return 0


def _cmd_diff(_args: argparse.Namespace) -> int:
    proposed_path = loader.proposed_priorities_path()
    if not proposed_path.exists():
        print(f"No proposed priorities file found at {proposed_path}", file=sys.stderr)
        return 1

    try:
        current_yaml = loader.current_priorities_as_yaml()
        priorities, _clarifications = loader.load_proposed_priorities(proposed_path)
    except (ValueError, ValidationError) as exc:
        print(f"Could not build diff:\n{exc}", file=sys.stderr)
        return 1

    proposed_yaml = loader._dump_yaml(
        {"priorities": [loader.priority_to_yaml_dict(p) for p in priorities]}
    )
    diff = difflib.unified_diff(
        current_yaml.splitlines(keepends=True),
        proposed_yaml.splitlines(keepends=True),
        fromfile="current seed_research_priorities",
        tofile=str(proposed_path),
    )
    sys.stdout.writelines(diff)
    return 0


def _build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Macro research-priority workflow.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    propose = subparsers.add_parser(
        "propose",
        help="Generate proposed ResearchPriority objects from inputs.txt.",
    )
    propose.add_argument(
        "--inputs-file",
        type=Path,
        default=None,
        help="Input file. Defaults to data/agent_system/priorities/inputs.txt.",
    )
    propose.add_argument(
        "--no-clarification",
        action="store_true",
        help="Force priority output instead of allowing ClarificationRequest responses.",
    )
    propose.set_defaults(func=lambda args: asyncio.run(_cmd_propose(args)))

    promote = subparsers.add_parser(
        "promote",
        help="Promote proposed priorities into current_regime.yaml.",
    )
    promote.add_argument(
        "--append",
        action="store_true",
        help="Append to seed_research_priorities instead of replacing them.",
    )
    promote.set_defaults(func=_cmd_promote)

    show = subparsers.add_parser("show", help="Show current or proposed priorities.")
    group = show.add_mutually_exclusive_group()
    group.add_argument("--proposed", action="store_true")
    group.add_argument("--current", action="store_true")
    show.set_defaults(func=_cmd_show)

    diff = subparsers.add_parser(
        "diff",
        help="Diff current seed priorities against proposed priorities.",
    )
    diff.set_defaults(func=_cmd_diff)
    return parser


def main() -> None:
    args = _build_argparser().parse_args()
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
