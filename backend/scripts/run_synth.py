"""
scripts/run_synth.py

End-to-end runner for Pipeline B: loads RSS/local sources, assembles the
narrative bundle, optionally loads the prior snapshot, and calls the LLM
synthesis step.  Use --dry-run to validate the bundle without making an
LLM call.

Usage (from repo root):
    python backend/scripts/run_synth.py --dry-run
    python backend/scripts/run_synth.py --lookback-hours 48
    python backend/scripts/run_synth.py --no-prior --sources-csv path/to/sources.csv

Environment:
    Requires OPENAI_API_KEY (for live synthesis; not needed with --dry-run).
    Reads .env from the repo root if present.
"""
from __future__ import annotations

import argparse
import collections
import json
import logging
import sys
from pathlib import Path
from typing import List

# ---------------------------------------------------------------------------
# Path setup — must happen before any src.* imports.
# backend/ must be on sys.path for `src.*` style imports.
# backend/src/ must also be present for `narrative.*` style imports used
# internally by enrich/article_fetch.py and cleaning.py.
# ---------------------------------------------------------------------------
_repo_root = Path(__file__).resolve().parents[2]
_backend_dir = _repo_root / "backend"
_backend_src_dir = _backend_dir / "src"

for _p in (_backend_src_dir, _backend_dir):
    _ps = str(_p)
    if _ps not in sys.path:
        sys.path.insert(0, _ps)

# Load .env before importing application modules so env vars are available.
# Tries python-dotenv first; falls back to a lightweight manual parser so
# the script works without installing python-dotenv.
def _load_env_file(path: Path) -> None:
    """Minimal .env loader: KEY=VALUE lines, strips quotes, skips comments."""
    import os
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as _fh:
        for _line in _fh:
            _line = _line.strip()
            if not _line or _line.startswith("#") or "=" not in _line:
                continue
            _key, _, _val = _line.partition("=")
            _key = _key.strip()
            _val = _val.strip().strip("\"'")
            if _key and _key not in os.environ:
                os.environ[_key] = _val

try:
    from dotenv import load_dotenv
    # Try repo-root .env then backend/.env
    load_dotenv(_repo_root / ".env")
    load_dotenv(_backend_dir / ".env")
except ImportError:
    # Fall back to manual loader
    _load_env_file(_repo_root / ".env")
    _load_env_file(_backend_dir / ".env")

# ---------------------------------------------------------------------------
# Application imports (after path setup)
# ---------------------------------------------------------------------------
from src.data.price_context import build_multi_timeframe_price_context_sync  # noqa: E402
from src.narrative.bundle import build_narrative_bundle  # noqa: E402
from src.narrative.source_loader import load_sources_from_csv  # noqa: E402
from src.narrative.synth import (  # noqa: E402
    extract_tickers_from_items,
    load_latest_narrative_snapshot,
    save_narrative_snapshot,
    synthesize_narrative_state,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("run_synth")

# ---------------------------------------------------------------------------
# Watchlist — placeholder; wire to user config in a later task
# ---------------------------------------------------------------------------
DEFAULT_WATCH_TICKERS = ["SPY", "QQQ", "IWM", "TLT", "HYG", "VIX"]

DEFAULT_SOURCES_CSV = _backend_dir / "config" / "narrative_sources.csv"
SNAPSHOTS_DIR = _repo_root / "data" / "snapshots"


def _channel_counts(items: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = collections.defaultdict(int)
    for it in items:
        ch = (it.get("channel") or "unknown").lower()
        counts[ch] += 1
    return dict(counts)


def _source_counts(items: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = collections.defaultdict(int)
    for it in items:
        src = it.get("source") or "unknown"
        counts[src] += 1
    return dict(counts)


def _avg_word_count(items: list[dict]) -> float:
    wcs = [
        (it.get("raw") or {}).get("word_count") or 0
        for it in items
        if (it.get("raw") or {}).get("extraction_success")
    ]
    return round(sum(wcs) / len(wcs), 1) if wcs else 0.0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Pipeline B narrative synthesis",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--lookback-hours",
        type=int,
        default=36,
        help="Hours of history to pull from each source",
    )
    parser.add_argument(
        "--sources-csv",
        type=Path,
        default=DEFAULT_SOURCES_CSV,
        help="Path to narrative_sources.csv",
    )
    parser.add_argument(
        "--no-prior",
        action="store_true",
        help="Skip loading the prior narrative snapshot",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Fetch + assemble the bundle and print a summary, "
            "but skip the LLM synthesis call and snapshot save"
        ),
    )
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # 1. Load sources
    # ------------------------------------------------------------------
    logger.info("Loading sources from %s", args.sources_csv)
    try:
        source_specs = load_sources_from_csv(args.sources_csv)
    except Exception as exc:
        logger.error("Failed to load sources CSV: %s", exc)
        sys.exit(1)

    enabled_names = [meta["Source Name"] for _, meta in source_specs]
    logger.info("%d enabled source(s): %s", len(enabled_names), ", ".join(enabled_names))

    # ------------------------------------------------------------------
    # 2. Build bundle
    # ------------------------------------------------------------------
    logger.info(
        "Assembling bundle (lookback=%dh, tickers=%s) …",
        args.lookback_hours,
        DEFAULT_WATCH_TICKERS,
    )
    try:
        bundle = build_narrative_bundle(
            watch_tickers=DEFAULT_WATCH_TICKERS,
            sources=source_specs,
            lookback_hours=args.lookback_hours,
        )
    except ImportError as exc:
        logger.error("Bundle assembly failed — missing dependency: %s", exc)
        sys.exit(1)
    except Exception as exc:
        logger.error("Bundle assembly failed: %s", exc, exc_info=True)
        sys.exit(1)

    bundle_dict = bundle.to_dict()
    items = bundle_dict.get("items") or []
    channel_cts = _channel_counts(items)
    source_cts = _source_counts(items)
    avg_wc = _avg_word_count(items)

    logger.info("Bundle assembled: %d total items", len(items))
    for ch, n in sorted(channel_cts.items()):
        logger.info("  channel=%-18s %3d items", ch, n)

    # Flag sources with zero items
    zero_item_sources = [
        meta["Source Name"]
        for _, meta in source_specs
        if source_cts.get(meta["Source Name"], 0) == 0
    ]
    if zero_item_sources:
        logger.warning(
            "Zero items from %d source(s) — check URLs / lookback window: %s",
            len(zero_item_sources),
            ", ".join(zero_item_sources),
        )

    if args.dry_run:
        print("\n" + "=" * 72)
        print("DRY RUN — bundle summary (no LLM call, no snapshot saved)")
        print("=" * 72)
        print(f"  asof_utc        : {bundle_dict.get('asof_utc')}")
        print(f"  total items     : {len(items)}")
        print(f"  lookback_hours  : {args.lookback_hours}")
        print(f"  avg word count  : {avg_wc} (enriched items only)")
        print("\n  Items by channel:")
        for ch, n in sorted(channel_cts.items()):
            print(f"    {ch:<20} {n:>4}")
        print("\n  Items by source (top 20):")
        for src, n in sorted(source_cts.items(), key=lambda x: -x[1])[:20]:
            print(f"    {src:<40} {n:>4}")
        print("\n  Zero-item sources:")
        if zero_item_sources:
            for s in zero_item_sources:
                print(f"    !! {s}")
        else:
            print("    (none — all sources returned at least 1 item)")
        print("\n  Sample items (first 3):")
        for it in items[:3]:
            print(
                f"    [{it.get('channel')}] {it.get('source')} | "
                f"{it.get('title', '')[:80]}"
            )
        print("=" * 72)
        return

    # ------------------------------------------------------------------
    # 3. Load prior snapshot (optional)
    # ------------------------------------------------------------------
    prior_state: dict | None = None
    if not args.no_prior:
        prior_date, prior_state = load_latest_narrative_snapshot(
            base_dir=SNAPSHOTS_DIR
        )
        if prior_state:
            logger.info("Loaded prior snapshot from %s", prior_date)
        else:
            logger.info("No prior snapshot found — proceeding cold")

    # ------------------------------------------------------------------
    # 4. Build price context (with derived single-name tickers)
    # ------------------------------------------------------------------
    # Extract company tickers mentioned in bundle items so single-name
    # returns (e.g. LLY, MRK, GOOGL) are included in the price_ledger.
    raw_items = bundle_dict.get("items") or []
    derived_tickers = extract_tickers_from_items(raw_items, max_tickers=20)
    if derived_tickers:
        logger.info("Derived %d single-name ticker(s): %s", len(derived_tickers), derived_tickers)

    # Combine default watchlist + derived tickers, preserving order, deduped
    _seen_watch: set[str] = set()
    combined_watch: List[str] = []
    for t in DEFAULT_WATCH_TICKERS + derived_tickers:
        if t not in _seen_watch:
            _seen_watch.add(t)
            combined_watch.append(t)

    logger.info("Building multi-timeframe price context (%d tickers) …", len(combined_watch))
    price_context = build_multi_timeframe_price_context_sync(
        watch_tickers=combined_watch,
    )
    pc_errors = price_context.get("errors") or []
    if pc_errors:
        logger.warning(
            "price_context returned with %d error(s): %s",
            len(pc_errors),
            pc_errors,
        )
    else:
        logger.info(
            "price_context OK — %d cross_asset, %d sectors, %d single_names, "
            "%d relationships, horizons=%s",
            len(price_context.get("cross_asset") or []),
            len(price_context.get("sectors") or []),
            len(price_context.get("single_names") or []),
            len(price_context.get("relationships") or []),
            price_context.get("horizons"),
        )

    # ------------------------------------------------------------------
    # 5. Synthesize
    # ------------------------------------------------------------------
    logger.info("Calling synthesize_narrative_state …")
    try:
        result = synthesize_narrative_state(
            bundle=bundle_dict,
            market_state_summary=None,
            market_moves=None,
            prior_state=prior_state,
            lookback_hours=args.lookback_hours,
            price_context=price_context,
        )
    except Exception as exc:
        logger.error("Synthesis failed: %s", exc, exc_info=True)
        sys.exit(1)

    # ------------------------------------------------------------------
    # 6. Save snapshot
    # ------------------------------------------------------------------
    snapshot_path = save_narrative_snapshot(result, base_dir=SNAPSHOTS_DIR)
    logger.info("Snapshot saved to %s", snapshot_path)

    # ------------------------------------------------------------------
    # 7. Print summary
    # ------------------------------------------------------------------
    meta = result.get("_meta") or {}
    print("\n" + "=" * 72)
    print("Synthesis complete")
    print("=" * 72)
    print(f"  snapshot        : {snapshot_path}")
    print(f"  total items     : {meta.get('total_items_in_bundle')}")
    print(f"  items → LLM     : {meta.get('items_selected_for_llm')}")
    print(f"  prior snapshot  : {meta.get('prior_snapshot_found')}")
    summary = result.get("one_paragraph_summary") or ""
    if summary:
        print(f"\n  Summary:\n    {summary[:400]}")
    print("=" * 72)


if __name__ == "__main__":
    main()
