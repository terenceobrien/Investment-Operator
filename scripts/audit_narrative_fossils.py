#!/usr/bin/env python3
"""Audit backend references to the retired narrative scenario taxonomy."""
from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path


NARRATIVE_SCENARIO_IDS = (
    "reopening_soft_landing",
    "sticky_late_cycle_ai",
    "oil_inflation_tail",
    "late_cycle_risk_off",
    "ai_capex_rollover",
)
SEARCH_PATTERNS = tuple(
    [(term, re.compile(re.escape(term))) for term in NARRATIVE_SCENARIO_IDS]
    + [
        ("narrative_v0", re.compile(re.escape("narrative_v0"))),
        ("src.analysis.analogues", re.compile(r"\bsrc\.analysis\.analogues\b")),
        (
            "src.analysis.rolling_composite",
            re.compile(r"\bsrc\.analysis\.rolling_composite\b"),
        ),
        ("analysis.analogues", re.compile(r"(?<!src\.)\banalysis\.analogues\b")),
        (
            "analysis.rolling_composite",
            re.compile(r"(?<!src\.)\banalysis\.rolling_composite\b"),
        ),
        ("from .analogues import", re.compile(r"\bfrom\s+\.analogues\s+import\b")),
        (
            "from .rolling_composite import",
            re.compile(r"\bfrom\s+\.rolling_composite\s+import\b"),
        ),
    ]
)
TEXT_SUFFIXES = {
    ".cfg",
    ".csv",
    ".json",
    ".md",
    ".py",
    ".txt",
    ".yaml",
    ".yml",
}
SKIP_DIRS = {
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
}


@dataclass(frozen=True)
class FossilHit:
    file: str
    line: int
    matched: str
    classification: str
    justification: str


def default_search_roots(repo_root: Path) -> tuple[Path, ...]:
    backend = repo_root / "backend"
    roots = [
        backend / "src",
        backend / "config",
        backend / "scripts",
    ]
    for path in backend.rglob("*"):
        if not path.is_dir():
            continue
        lower_name = path.name.lower()
        if "prompt" in lower_name or "template" in lower_name:
            roots.append(path)
    seen: set[Path] = set()
    out: list[Path] = []
    for root in roots:
        if root.exists() and root not in seen:
            seen.add(root)
            out.append(root)
    return tuple(out)


def collect_hits(repo_root: Path) -> list[FossilHit]:
    hits: list[FossilHit] = []
    for root in default_search_roots(repo_root):
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
            for line_number, line in enumerate(lines, 1):
                matched_terms = [
                    label
                    for label, pattern in SEARCH_PATTERNS
                    if pattern.search(line)
                ]
                if not matched_terms:
                    continue
                context = "\n".join(
                    lines[max(0, line_number - 4): min(len(lines), line_number + 3)]
                )
                for term in matched_terms:
                    classification, justification = classify_hit(
                        path.relative_to(repo_root),
                        line,
                        context,
                        term,
                    )
                    hits.append(
                        FossilHit(
                            file=path.relative_to(repo_root).as_posix(),
                            line=line_number,
                            matched=term,
                            classification=classification,
                            justification=justification,
                        )
                    )
    return hits


def classify_hit(
    relative_path: Path,
    line: str,
    context: str,
    matched: str,
) -> tuple[str, str]:
    path_text = relative_path.as_posix()
    lower_path = path_text.lower()
    lower_context = f"{line}\n{context}".lower()
    if "/tests/" in lower_path:
        return (
            "test_fixture",
            "Test coverage intentionally preserves behavior or reader compatibility around the retired taxonomy.",
        )
    if "/fixtures/" in lower_path or "/output/" in lower_path:
        return (
            "historical_artifact",
            "Stored fixture or generated artifact reference, not an executable forecast path.",
        )
    if lower_path.endswith("scenario_translation.py"):
        return (
            "live_code_path",
            "Legitimate Monte Carlo boundary translating legacy narrative inputs into behavioral IDs.",
        )
    if lower_path.endswith("current_regime_export.py"):
        if "retired" in lower_context or "two_source_v1" in lower_context:
            return (
                "dead_code",
                "Fail-loud retired handoff stub retained only to direct callers to the two_source_v1 path.",
            )
        return (
            "reader_compat",
            "Label/display compatibility for older current-regime artifacts.",
        )
    if "schema" in lower_path or "literal" in lower_context or "old artifact" in lower_context:
        return (
            "reader_compat",
            "Reader compatibility surface for old artifacts; not a newly produced probability path.",
        )
    if "retired" in lower_context or "legacy" in lower_context or "two_source_v1" in lower_context:
        return (
            "dead_code",
            "Surrounding code marks this path as legacy or fail-loud after the two_source_v1 rewire.",
        )
    if lower_path.startswith("backend/src/analysis/"):
        return (
            "dead_code",
            "Legacy daily analogue implementation retained outside the live behavioral macro probability path.",
        )
    if "precompute" in lower_path or "label_narrative" in lower_path:
        return (
            "dead_code",
            "Legacy narrative precompute script, not part of the live forecast assembly path.",
        )
    return (
        "live_code_path",
        "Backend executable code still references a retired narrative marker and needs owner review.",
    )


def render_markdown(hits: list[FossilHit]) -> str:
    lines = [
        "# Narrative Fossil Audit",
        "",
        "Backend-only scan for retired narrative scenario IDs, `narrative_v0`, and legacy daily analogue imports.",
        "",
        "| File | Line | Matched String | Classification | Justification |",
        "| --- | ---: | --- | --- | --- |",
    ]
    for hit in sorted(hits, key=lambda item: (item.file, item.line, item.matched)):
        lines.append(
            "| "
            + " | ".join(
                (
                    _escape_md(hit.file),
                    str(hit.line),
                    f"`{_escape_md(hit.matched)}`",
                    hit.classification,
                    _escape_md(hit.justification),
                )
            )
            + " |"
        )
    if not hits:
        lines.append("| none | 0 | `none` | dead_code | No backend fossils found. |")
    lines.append("")
    return "\n".join(lines)


def write_report(repo_root: Path, hits: list[FossilHit]) -> Path:
    path = repo_root / "data" / "agent_system" / "reports" / "audits" / "narrative_fossil_audit.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(hits), encoding="utf-8")
    return path


def _escape_md(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        default=Path(__file__).resolve().parents[1],
        type=Path,
        help="Repository root; defaults to the parent of scripts/.",
    )
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()
    hits = collect_hits(repo_root)
    report_path = write_report(repo_root, hits)
    print(f"wrote {report_path}")
    print(f"hits: {len(hits)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
