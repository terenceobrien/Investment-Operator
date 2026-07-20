"""
Diagnostic script: figure out why seed_research_priorities entries in
current_regime.yaml aren't being picked up by the cycle.

Usage:
    cd /Users/terenceobrien/AI_Financial_Operator/backend
    python3 diagnose_priorities.py

The script searches for current_regime.yaml in common locations, loads it,
prints what's there, then tries to build ResearchPriority objects through
the actual adapter function. Any failure gets a clear message.
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path


def find_yaml() -> Path | None:
    """Search common locations for current_regime.yaml."""
    candidates = [
        Path("src/agent_system/config/current_regime.yaml"),
        Path("src/agent_system/regime/current_regime.yaml"),
        Path("src/agent_system/current_regime.yaml"),
        Path("data/agent_system/current_regime.yaml"),
        Path("config/current_regime.yaml"),
        Path("current_regime.yaml"),
    ]
    for path in candidates:
        if path.exists():
            return path

    # Fallback: scan the whole repo
    print("Not found in standard locations. Scanning repository...")
    for found in Path(".").rglob("current_regime.yaml"):
        # Skip the dated reports directory
        if "reports/macro_forecasts" in str(found):
            continue
        return found
    return None


def main() -> int:
    print("=" * 72)
    print("STEP 1: Find current_regime.yaml")
    print("=" * 72)
    path = find_yaml()
    if path is None:
        print("FAIL: could not locate current_regime.yaml anywhere")
        print()
        print("Run this from the terminal to find it:")
        print("  find . -name 'current_regime.yaml' -not -path '*/reports/*'")
        return 1
    print(f"Found: {path.resolve()}")
    print()

    print("=" * 72)
    print("STEP 2: Load the YAML")
    print("=" * 72)
    try:
        import yaml
    except ImportError:
        print("FAIL: PyYAML not installed in this environment")
        return 1

    try:
        with path.open() as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        print(f"FAIL: YAML parse error: {exc}")
        print()
        print("The file has a syntax problem. Look for:")
        print("  - Tabs (YAML requires spaces)")
        print("  - Misaligned indentation")
        print("  - Missing colons after keys")
        print("  - Unquoted strings containing colons or special characters")
        return 1
    print(f"YAML parsed successfully. Top-level keys: {list(data.keys()) if isinstance(data, dict) else type(data).__name__}")
    print()

    print("=" * 72)
    print("STEP 3: Check seed_research_priorities key")
    print("=" * 72)
    if not isinstance(data, dict):
        print(f"FAIL: top-level YAML is not a dict, it's {type(data).__name__}")
        return 1

    items = data.get("seed_research_priorities")
    if items is None:
        print("FAIL: 'seed_research_priorities' key is missing or null")
        print()
        print(f"Available top-level keys: {list(data.keys())}")
        return 1
    if not isinstance(items, list):
        print(f"FAIL: 'seed_research_priorities' should be a list, it's {type(items).__name__}")
        return 1

    print(f"Found {len(items)} entries under seed_research_priorities")
    print()

    print("=" * 72)
    print("STEP 4: Show each entry's structure")
    print("=" * 72)
    for i, item in enumerate(items, 1):
        print(f"--- Entry {i} ---")
        if not isinstance(item, dict):
            print(f"  NOT A DICT: {type(item).__name__}")
            print(f"  Raw value: {item!r}")
            continue
        print(f"  Keys present: {sorted(item.keys())}")
        for key, value in item.items():
            preview = repr(value)
            if len(preview) > 100:
                preview = preview[:97] + "..."
            print(f"    {key}: {preview}")
        print()

    print("=" * 72)
    print("STEP 5: Try to build ResearchPriority objects via adapter")
    print("=" * 72)
    try:
        from src.agent_system.adapters.regime import _build_seed_research_priorities
    except ImportError as exc:
        print(f"FAIL: cannot import _build_seed_research_priorities: {exc}")
        print()
        print("Are you running from the backend directory?")
        print(f"Current directory: {Path.cwd()}")
        return 1

    try:
        priorities = _build_seed_research_priorities(items)
    except Exception as exc:
        print(f"FAIL during build: {type(exc).__name__}: {exc}")
        print()
        print("Full traceback:")
        traceback.print_exc()
        print()
        print("This is the most useful error to diagnose. The traceback above")
        print("usually points to the specific field that failed validation.")
        return 1

    print(f"Successfully built {len(priorities)} ResearchPriority objects")
    print()
    for p in priorities:
        print(f"  rank {p.priority_rank}: {p.theme[:90]}")
        print(f"    expected_edge_decay: {p.expected_edge_decay}")
        print(f"    edge_hypothesis ({len(p.edge_hypothesis)} chars): {p.edge_hypothesis[:90]}...")
        print()

    print("=" * 72)
    print("STEP 6: Mismatch check")
    print("=" * 72)
    if len(priorities) != len(items):
        print(f"MISMATCH: {len(items)} YAML entries but {len(priorities)} built priorities")
        print("Some entries were silently dropped. Check the adapter function to")
        print("see if it filters anything.")
    else:
        print(f"All {len(items)} YAML entries built into priorities. The adapter is")
        print("working. If the cycle still isn't using them, the issue is downstream:")
        print()
        print("  - Possible cause A: the cycle is being invoked via run_cycle_with_inputs")
        print("    which uses LLM-generated priorities and bypasses the YAML.")
        print("  - Possible cause B: a different current_regime.yaml is being read at")
        print("    runtime than the one this script found. Confirm with:")
        print("      python3 -c 'from src.agent_system.adapters import regime; import inspect; print(inspect.getfile(regime))'")
        print("  - Possible cause C: a stale Python cache or .pyc file. Try:")
        print("      find . -name '__pycache__' -type d -exec rm -rf {} +")

    return 0


if __name__ == "__main__":
    sys.exit(main())