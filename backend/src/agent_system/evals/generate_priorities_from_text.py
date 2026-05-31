"""
Generate seed ResearchPriority YAML blocks from free-text user inputs.

This is a small eval/ops utility, not a new agent. It reuses the same
free-text-to-ResearchPriority converter used by the macro harness:
``translate_to_priority`` from ``src.agent_system.agents.macro_agent``.

Usage:
    # Generate priority blocks from the four sample inputs:
    python -m src.agent_system.evals.generate_priorities_from_text \
        --inputs-file src/agent_system/evals/sample_inputs.txt \
        --out /tmp/new_priorities.yaml

    # Then paste the contents of /tmp/new_priorities.yaml into the
    # seed_research_priorities list in src/agent_system/config/current_regime.yaml,
    # replacing or appending to the existing entries.

Blank lines and lines starting with "#" in the inputs file are ignored.
The default YAML output matches the seed_research_priorities field shape in
current_regime.yaml; the regime adapter fills supporting_evidence for seed
priorities when it loads the YAML.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Iterable, Literal

import yaml

from src.agent_system.agents.macro_agent import translate_to_priority
from src.agent_system.orchestration.run_research_cycle import _select_regime_state
from src.agent_system.schemas.regime import ClarificationRequest, ResearchPriority


OutputFormat = Literal["yaml", "json"]


class _FoldedString(str):
    """Marker type for readable block-style YAML strings."""


class _PriorityYamlDumper(yaml.SafeDumper):
    """Safe dumper with folded multiline-friendly prose scalars."""

    def increase_indent(self, flow: bool = False, indentless: bool = False):
        return super().increase_indent(flow=flow, indentless=False)


def _represent_folded_string(
    dumper: yaml.SafeDumper,
    data: _FoldedString,
) -> yaml.nodes.ScalarNode:
    return dumper.represent_scalar("tag:yaml.org,2002:str", str(data), style=">")


_PriorityYamlDumper.add_representer(_FoldedString, _represent_folded_string)


def load_input_lines(path: Path) -> list[str]:
    """Load non-blank, non-comment free-text inputs from a text file."""
    lines: list[str] = []
    with path.open("r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            lines.append(line)
    return lines


async def convert_text_to_priority(
    text: str,
    regime_state=None,
) -> ResearchPriority:
    """
    Convert one free-text input to a ResearchPriority via the macro-agent path.

    The macro harness permits ClarificationRequest responses. This utility is
    meant to produce pasteable seed priorities, so a clarification is reported
    as an error for that input rather than serialized.
    """
    if regime_state is None:
        regime_state, _regime_source, _fallback_reason = _select_regime_state()

    result = await translate_to_priority(
        user_input=text,
        regime_state=regime_state,
    )
    if isinstance(result, ResearchPriority):
        return result
    if isinstance(result, ClarificationRequest):
        raise RuntimeError(
            "Macro converter returned a clarification instead of a priority "
            f"for input {text!r}: {result.question}"
        )
    raise RuntimeError(
        f"Macro converter returned unexpected type {type(result).__name__} "
        f"for input {text!r}"
    )


async def convert_inputs_to_priorities(
    inputs: Iterable[str],
    regime_state=None,
) -> list[ResearchPriority]:
    """Convert all input strings to ResearchPriority objects sequentially."""
    if regime_state is None:
        regime_state, regime_source, _fallback_reason = _select_regime_state()
        print(f"Regime source: {regime_source}", file=sys.stderr)

    priorities: list[ResearchPriority] = []
    input_list = list(inputs)
    for idx, text in enumerate(input_list, 1):
        print(f"[{idx}/{len(input_list)}] {text[:80]}", file=sys.stderr)
        priority = await convert_text_to_priority(text, regime_state=regime_state)
        priorities.append(priority)
        print(f"    -> {priority.theme}", file=sys.stderr)
    return priorities


def priority_to_seed_dict(priority: ResearchPriority) -> dict:
    """
    Convert a ResearchPriority into current_regime.yaml seed field shape.

    current_regime.yaml seed priorities omit schema metadata and
    supporting_evidence; the adapter attaches a seed-derived evidence record
    when loading them.
    """
    return {
        "theme": priority.theme,
        "rationale": _FoldedString(priority.rationale),
        "edge_hypothesis": _FoldedString(priority.edge_hypothesis),
        "sub_questions": list(priority.sub_questions),
        "priority_rank": priority.priority_rank,
        "expected_edge_decay": priority.expected_edge_decay.value,
    }


def render_priorities(
    priorities: Iterable[ResearchPriority],
    *,
    output_format: OutputFormat = "yaml",
) -> str:
    """Render priorities as pasteable seed YAML or JSON."""
    seed_payload = [priority_to_seed_dict(priority) for priority in priorities]
    if output_format == "json":
        # Strip YAML marker subclasses before JSON encoding.
        json_ready = [
            {
                key: str(value) if isinstance(value, _FoldedString) else value
                for key, value in item.items()
            }
            for item in seed_payload
        ]
        return json.dumps(json_ready, indent=2) + "\n"
    if output_format == "yaml":
        return yaml.dump(
            seed_payload,
            Dumper=_PriorityYamlDumper,
            sort_keys=False,
            allow_unicode=False,
            width=88,
        )
    raise ValueError(f"unsupported output format: {output_format!r}")


def _build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate current_regime.yaml seed ResearchPriority blocks from "
            "free-text user inputs."
        )
    )
    parser.add_argument(
        "--inputs-file",
        type=Path,
        required=True,
        help="Text file with one free-text input per line.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output path. Defaults to stdout.",
    )
    parser.add_argument(
        "--format",
        choices=("yaml", "json"),
        default="yaml",
        help="Output format. YAML is suitable for current_regime.yaml paste.",
    )
    return parser


async def _run(args: argparse.Namespace) -> int:
    inputs = load_input_lines(args.inputs_file)
    if not inputs:
        print(f"No inputs found in {args.inputs_file}", file=sys.stderr)
        return 1

    priorities = await convert_inputs_to_priorities(inputs)
    rendered = render_priorities(priorities, output_format=args.format)

    if args.out is None:
        sys.stdout.write(rendered)
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")
        print(f"Wrote {len(priorities)} priority blocks to {args.out}", file=sys.stderr)
    return 0


def main() -> None:
    args = _build_argparser().parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
