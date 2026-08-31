"""
Generate and approve manual ResearchPriority entries from free-text theses.

This is a small eval/ops utility, not a new agent. It reuses the same
free-text-to-ResearchPriority converter used by the macro harness:
``translate_to_priority`` from ``src.agent_system.agents.macro_agent``.

Usage:
    # Generate one priority from a file, review it, then choose whether to append
    # it to data/agent_system/priorities/manual_research_priorities.yaml:
    python -m src.agent_system.evals.generate_priorities_from_text \
        /tmp/manual_thesis.txt

    # Generate-only batch rendering remains available for inspection:
    python -m src.agent_system.evals.generate_priorities_from_text \
        --inputs-file src/agent_system/evals/sample_inputs.txt \
        --out /tmp/generated_priorities.yaml

Blank lines and lines starting with "#" in the inputs file are ignored.
The default append target is the HELIX_DATA_ROOT-aware manual priority queue.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Literal

import yaml

from src.agent_system.agents.macro_agent import (
    MacroAgentValidationError,
    translate_to_priority,
)
from src.agent_system.forecasting.macro_scenario_source import (
    MANUAL_RESEARCH_PRIORITIES_FILENAME,
    MANUAL_RESEARCH_PRIORITY_SOURCE,
    MANUAL_RESEARCH_PRIORITIES_SOURCE_MACRO_FORECAST_ID,
    default_manual_research_priorities_path,
    load_manual_research_priorities,
)
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


class PriorityGenerationError(RuntimeError):
    """Raised when thesis text cannot be converted into a valid priority."""

    def __init__(
        self,
        message: str,
        *,
        raw_output: str | None = None,
        validation_error: str | None = None,
    ) -> None:
        super().__init__(message)
        self.raw_output = raw_output
        self.validation_error = validation_error or message


class ManualPriorityAppendError(RuntimeError):
    """Raised when an approved manual priority cannot be persisted safely."""


def _extract_raw_output(exc: BaseException) -> str | None:
    """Best-effort raw-output extraction from current/future LLM errors."""

    seen: set[int] = set()
    cursor: BaseException | None = exc
    while cursor is not None and id(cursor) not in seen:
        seen.add(id(cursor))
        for attr in ("raw_output", "raw_response", "response_text", "raw"):
            value = getattr(cursor, attr, None)
            if isinstance(value, str) and value.strip():
                return value
        cursor = cursor.__cause__ or cursor.__context__
    return None


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

    try:
        result = await translate_to_priority(
            user_input=text,
            regime_state=regime_state,
        )
    except MacroAgentValidationError as exc:
        raise PriorityGenerationError(
            f"Macro converter failed to produce a valid ResearchPriority for input {text!r}: {exc}",
            raw_output=_extract_raw_output(exc),
            validation_error=str(exc),
        ) from exc
    if isinstance(result, ResearchPriority):
        return result
    if isinstance(result, ClarificationRequest):
        raise PriorityGenerationError(
            "Macro converter returned a clarification instead of a priority "
            f"for input {text!r}: {result.question}",
            raw_output=result.model_dump_json(indent=2),
            validation_error=result.question,
        )
    raise PriorityGenerationError(
        f"Macro converter returned unexpected type {type(result).__name__} "
        f"for input {text!r}",
        raw_output=str(result),
        validation_error=f"unexpected result type {type(result).__name__}",
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


def _plain_json_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        payload = value.model_dump(mode="json")
    elif isinstance(value, dict):
        payload = dict(value)
    else:
        raise TypeError(f"cannot serialize value of type {type(value).__name__}")
    return {key: item for key, item in payload.items() if item is not None}


def _evidence_to_manual_dict(evidence: Any) -> dict[str, Any]:
    payload = _plain_json_dict(evidence)
    for metadata_key in ("schema_version", "created_at", "id"):
        payload.pop(metadata_key, None)
    return payload


def priority_to_manual_dict(
    priority: ResearchPriority,
    *,
    source_thesis_text: str,
    approved_by: str | None = None,
    approved_at: datetime | None = None,
) -> dict[str, Any]:
    """Convert an approved priority into manual_research_priorities.yaml shape."""

    approved_at = approved_at or datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "theme": priority.theme,
        "rationale": _FoldedString(priority.rationale),
        "edge_hypothesis": _FoldedString(priority.edge_hypothesis),
        "sub_questions": list(priority.sub_questions),
        "priority_rank": priority.priority_rank,
        "expected_edge_decay": priority.expected_edge_decay.value,
        "supporting_evidence": [
            _evidence_to_manual_dict(evidence)
            for evidence in priority.supporting_evidence
        ],
        "source": MANUAL_RESEARCH_PRIORITY_SOURCE,
        "source_macro_forecast_id": MANUAL_RESEARCH_PRIORITIES_SOURCE_MACRO_FORECAST_ID,
        "source_thesis_text": _FoldedString(source_thesis_text),
        "approved_at": approved_at.isoformat(),
    }
    if approved_by:
        payload["approved_by"] = approved_by
    if priority.source_theme_id:
        payload["source_theme_id"] = priority.source_theme_id
    if priority.source_scenario_ids:
        payload["source_scenario_ids"] = list(priority.source_scenario_ids)
    return payload


def _render_manual_entry(entry: dict[str, Any]) -> str:
    rendered = yaml.dump(
        [entry],
        Dumper=_PriorityYamlDumper,
        sort_keys=False,
        allow_unicode=False,
        width=88,
    )
    return "".join(f"  {line}" if line.strip() else line for line in rendered.splitlines(True))


def _manual_yaml_payload_count(path: Path) -> tuple[str, list[Any]]:
    if not path.exists():
        return "priorities:\n", []
    text = path.read_text(encoding="utf-8")
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ManualPriorityAppendError(
            f"Manual research priorities file is invalid YAML: {path}: {exc}"
        ) from exc
    if raw is None:
        return "priorities:\n", []
    if not isinstance(raw, dict):
        raise ManualPriorityAppendError(
            f"Manual research priorities file must contain a mapping with 'priorities': {path}"
        )
    items = raw.get("priorities")
    if items is None:
        raise ManualPriorityAppendError(
            f"Manual research priorities file missing required field 'priorities': {path}"
        )
    if not isinstance(items, list):
        raise ManualPriorityAppendError(
            f"Manual research priorities field must be a list: {path}.priorities"
        )
    if not items:
        return "priorities:\n", []
    return text, list(items)


def _next_priority_rank(items: list[Any]) -> int:
    ranks: list[int] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        raw_rank = item.get("priority_rank")
        try:
            ranks.append(int(raw_rank))
        except (TypeError, ValueError):
            continue
    return max(ranks, default=0) + 1


def append_manual_priority(
    priority: ResearchPriority,
    source_text: str,
    approved_by: str | None = None,
    *,
    path: str | Path | None = None,
) -> list[ResearchPriority]:
    """
    Append an approved priority to the manual queue with atomic round-trip validation.

    The manual queue is append-only from this helper's perspective. Existing
    bytes are preserved as a prefix; the new entry is rendered and appended to
    the ``priorities`` list, then validated through
    ``load_manual_research_priorities`` before the atomic rename.
    """

    target = Path(path).expanduser() if path is not None else default_manual_research_priorities_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    existing_text, existing_items = _manual_yaml_payload_count(target)
    next_rank = _next_priority_rank(existing_items)
    prepared = priority.model_copy_validate(
        update={
            "priority_rank": next_rank,
            "source": MANUAL_RESEARCH_PRIORITY_SOURCE,
            "source_macro_forecast_id": MANUAL_RESEARCH_PRIORITIES_SOURCE_MACRO_FORECAST_ID,
            "source_thesis_text": source_text,
            "approved_by": approved_by,
            "approved_at": datetime.now(timezone.utc),
        }
    )
    entry = priority_to_manual_dict(
        prepared,
        source_thesis_text=source_text,
        approved_by=approved_by,
        approved_at=prepared.approved_at,
    )
    separator = "" if existing_text.endswith("\n") else "\n"
    new_text = f"{existing_text}{separator}{_render_manual_entry(entry)}"
    tmp_path = target.with_name(f".{target.name}.tmp")
    tmp_path.write_text(new_text, encoding="utf-8")
    try:
        loaded = load_manual_research_priorities(tmp_path)
    except Exception as exc:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise ManualPriorityAppendError(
            f"Round-trip validation failed for appended manual priority file {target}: {exc}"
        ) from exc
    os.replace(tmp_path, target)
    return loaded


def replace_manual_priority(
    priority: ResearchPriority,
    source_text: str,
    approved_by: str | None = None,
    *,
    path: str | Path | None = None,
) -> list[ResearchPriority]:
    """
    Replace the manual queue with one approved priority.

    This is the production approval behavior: the manual priority file is the
    current operator-selected priority, not a historical backlog. The file is
    still written through a temp file, validated by ``load_manual_research_priorities``,
    and then atomically swapped into place.
    """

    target = Path(path).expanduser() if path is not None else default_manual_research_priorities_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    prepared = priority.model_copy_validate(
        update={
            "priority_rank": 1,
            "source": MANUAL_RESEARCH_PRIORITY_SOURCE,
            "source_macro_forecast_id": MANUAL_RESEARCH_PRIORITIES_SOURCE_MACRO_FORECAST_ID,
            "source_thesis_text": source_text,
            "approved_by": approved_by,
            "approved_at": datetime.now(timezone.utc),
        }
    )
    entry = priority_to_manual_dict(
        prepared,
        source_thesis_text=source_text,
        approved_by=approved_by,
        approved_at=prepared.approved_at,
    )
    new_text = f"priorities:\n{_render_manual_entry(entry)}"
    tmp_path = target.with_name(f".{target.name}.tmp")
    tmp_path.write_text(new_text, encoding="utf-8")
    try:
        loaded = load_manual_research_priorities(tmp_path)
    except Exception as exc:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise ManualPriorityAppendError(
            f"Round-trip validation failed for replaced manual priority file {target}: {exc}"
        ) from exc
    os.replace(tmp_path, target)
    return loaded


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
            "Generate a manual ResearchPriority from free text and optionally "
            "append it to manual_research_priorities.yaml."
        )
    )
    parser.add_argument(
        "input_file",
        nargs="?",
        type=Path,
        help="File containing one free-text thesis. Defaults to stdin.",
    )
    parser.add_argument(
        "--inputs-file",
        type=Path,
        default=None,
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
        help="Generate-only output format when --out or --no-persist is used.",
    )
    parser.add_argument(
        "--no-persist",
        action="store_true",
        help="Generate and print priorities without prompting to append them.",
    )
    parser.add_argument(
        "--manual-path",
        type=Path,
        default=None,
        help="Override manual_research_priorities.yaml path for append mode.",
    )
    return parser


async def _run(args: argparse.Namespace) -> int:
    if args.inputs_file is not None:
        inputs = load_input_lines(args.inputs_file)
    elif args.input_file is not None:
        thesis = args.input_file.read_text(encoding="utf-8").strip()
        inputs = [thesis] if thesis else []
    else:
        thesis = sys.stdin.read().strip()
        inputs = [thesis] if thesis else []
    if not inputs:
        source = args.inputs_file or args.input_file or "stdin"
        print(f"No inputs found in {source}", file=sys.stderr)
        return 1

    try:
        priorities = await convert_inputs_to_priorities(inputs)
    except PriorityGenerationError as exc:
        print(f"Priority generation failed: {exc.validation_error}", file=sys.stderr)
        if exc.raw_output:
            print("Raw model output:", file=sys.stderr)
            print(exc.raw_output, file=sys.stderr)
        return 1
    rendered = render_priorities(priorities, output_format=args.format)

    if args.out is None:
        sys.stdout.write(rendered)
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")
        print(f"Wrote {len(priorities)} priority blocks to {args.out}", file=sys.stderr)
    if args.out is not None or args.no_persist:
        return 0

    if len(priorities) != 1:
        print(
            "Append mode requires exactly one generated priority. "
            "Use --out or --no-persist for batch generation.",
            file=sys.stderr,
        )
        return 1
    answer = input("Append this priority to manual_research_priorities.yaml? [y/N] ").strip().lower()
    if answer not in {"y", "yes"}:
        print("Not appended.", file=sys.stderr)
        return 0
    appended = append_manual_priority(
        priorities[0],
        inputs[0],
        approved_by="cli",
        path=args.manual_path,
    )
    target = args.manual_path or default_manual_research_priorities_path()
    print(
        f"Appended priority to {target}; manual priority count={len(appended)}",
        file=sys.stderr,
    )
    return 0


def main() -> None:
    args = _build_argparser().parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
