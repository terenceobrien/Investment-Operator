from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------
# This script lives in:
#   REPO_ROOT/scripts/run_deep_fundamental.py
#
# Backend imports live in:
#   REPO_ROOT/backend/src/...
#
# By adding BACKEND_ROOT to sys.path, imports should work like:
#   from src.agent_system...
# ---------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _load_env_files() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(REPO_ROOT / ".env")
        load_dotenv(REPO_ROOT / ".env.local")
        load_dotenv(BACKEND_ROOT / ".env", override=True)
        return
    except Exception:
        pass

    for path in (REPO_ROOT / ".env", REPO_ROOT / ".env.local", BACKEND_ROOT / ".env"):
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            clean = line.strip()
            if not clean or clean.startswith("#") or "=" not in clean:
                continue
            key, value = clean.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and (path == BACKEND_ROOT / ".env" or key not in os.environ):
                os.environ[key] = value


_load_env_files()


from src.agent_system.schemas.deep_fundamental import DeepFundamentalInputMode
from src.agent_system.services.deep_fundamental_agent import (
    build_deep_fundamental_report,
    build_deep_fundamental_report_async,
)
from src.agent_system.storage.repository import (
    load_latest_deep_fundamental_report,
    save_deep_fundamental_report,
)


TRANSCRIPT_DIR_CANDIDATE_NAMES = (
    "{ticker}_transcript.txt",
    "{ticker}_latest_transcript.txt",
    "{ticker}.txt",
    "{lower}_transcript.txt",
    "{lower}_latest_transcript.txt",
    "{lower}.txt",
)


@dataclass
class TranscriptResolution:
    paths_by_ticker: dict[str, list[str]] = field(default_factory=dict)
    source_by_ticker: dict[str, str] = field(default_factory=dict)
    warnings_by_ticker: dict[str, list[str]] = field(default_factory=dict)


def resolve_transcript_paths(
    args: argparse.Namespace,
    tickers: list[str],
) -> TranscriptResolution:
    clean_tickers = [ticker.upper().strip() for ticker in tickers if ticker.strip()]
    ticker_set = set(clean_tickers)
    resolution = TranscriptResolution(
        paths_by_ticker={ticker: [] for ticker in clean_tickers},
        warnings_by_ticker={ticker: [] for ticker in clean_tickers},
    )

    if len(clean_tickers) > 1 and (args.transcript_path or args.transcript_paths):
        raise ValueError(
            "`--transcript-path` is ambiguous for multi-ticker runs. "
            "Use `--transcript-map` or `--transcript-dir`."
        )

    mapped_paths = _parse_transcript_map(args.transcript_map or [], ticker_set)
    for ticker, path in mapped_paths.items():
        resolution.paths_by_ticker[ticker] = [path]
        resolution.source_by_ticker[ticker] = "transcript_map"

    if args.transcript_dir:
        transcript_dir = Path(args.transcript_dir).expanduser()
        if not transcript_dir.is_dir():
            raise ValueError(f"`--transcript-dir` is not a directory: {transcript_dir}")
        for ticker in clean_tickers:
            if resolution.paths_by_ticker[ticker]:
                continue
            selected_path, warning = _resolve_transcript_dir_file(
                transcript_dir,
                ticker,
            )
            if selected_path:
                resolution.paths_by_ticker[ticker] = [selected_path]
                resolution.source_by_ticker[ticker] = "transcript_dir"
            else:
                resolution.warnings_by_ticker[ticker].append(
                    f"No manual transcript found in transcript directory for {ticker}."
                )
            if warning:
                resolution.warnings_by_ticker[ticker].append(warning)

    if len(clean_tickers) == 1:
        ticker = clean_tickers[0]
        if not resolution.paths_by_ticker[ticker]:
            fallback_paths = []
            if args.transcript_path:
                fallback_paths.append(args.transcript_path)
            fallback_paths.extend(args.transcript_paths or [])
            if fallback_paths:
                resolution.paths_by_ticker[ticker] = [
                    _validate_existing_path(path, "--transcript-path")
                    for path in fallback_paths
                ]
                resolution.source_by_ticker[ticker] = "transcript_path"

    return resolution


def _parse_transcript_map(
    entries: list[str],
    ticker_set: set[str],
) -> dict[str, str]:
    mapped_paths: dict[str, str] = {}
    for entry in entries:
        if "=" not in entry:
            raise ValueError(
                "Malformed `--transcript-map` entry. Expected TICKER=/path/to/file."
            )
        raw_ticker, raw_path = entry.split("=", 1)
        ticker = raw_ticker.upper().strip()
        if not ticker:
            raise ValueError("Malformed `--transcript-map` entry with empty ticker.")
        if ticker not in ticker_set:
            raise ValueError(
                f"`--transcript-map` includes {ticker}, which is not in `--tickers`."
            )
        if ticker in mapped_paths:
            raise ValueError(f"Duplicate `--transcript-map` entry for {ticker}.")
        mapped_paths[ticker] = _validate_existing_path(raw_path, f"--transcript-map {ticker}")
    return mapped_paths


def parse_benchmark_map(
    entries: list[str],
    ticker_set: set[str],
) -> dict[str, str]:
    mapped_benchmarks: dict[str, str] = {}
    for entry in entries:
        if "=" not in entry:
            raise ValueError(
                "Malformed `--benchmark-map` entry. Expected TICKER=BENCHMARK."
            )
        raw_ticker, raw_benchmark = entry.split("=", 1)
        ticker = raw_ticker.upper().strip()
        benchmark = raw_benchmark.upper().strip()
        if not ticker or not benchmark:
            raise ValueError(
                "Malformed `--benchmark-map` entry with empty ticker or benchmark."
            )
        if ticker not in ticker_set:
            raise ValueError(
                f"`--benchmark-map` includes {ticker}, which is not in `--tickers`."
            )
        if ticker in mapped_benchmarks:
            raise ValueError(f"Duplicate `--benchmark-map` entry for {ticker}.")
        mapped_benchmarks[ticker] = benchmark
    return mapped_benchmarks


def resolve_benchmark_overrides(
    args: argparse.Namespace,
    tickers: list[str],
) -> dict[str, str]:
    ticker_set = set(tickers)
    overrides = parse_benchmark_map(args.benchmark_map or [], ticker_set)
    if args.benchmark:
        if len(tickers) != 1:
            raise ValueError(
                "`--benchmark` is only allowed for single-ticker runs. "
                "Use `--benchmark-map TICKER=BENCHMARK` for multi-ticker runs."
            )
        ticker = tickers[0]
        if ticker in overrides:
            raise ValueError(
                f"Benchmark override supplied twice for {ticker}; use either "
                "`--benchmark` or `--benchmark-map`, not both."
            )
        overrides[ticker] = args.benchmark.upper().strip()
    return overrides


def _resolve_transcript_dir_file(
    transcript_dir: Path,
    ticker: str,
) -> tuple[str | None, str | None]:
    lower = ticker.lower()
    candidates: list[Path] = []
    seen: set[Path] = set()
    for template in TRANSCRIPT_DIR_CANDIDATE_NAMES:
        path = _find_case_preserving_child(
            transcript_dir,
            template.format(ticker=ticker, lower=lower),
        )
        if path and path not in seen:
            candidates.append(path)
            seen.add(path)

    if not candidates:
        return None, None

    selected = max(candidates, key=lambda path: path.stat().st_mtime)
    warning = None
    if len(candidates) > 1:
        warning = (
            f"Multiple transcript files found for {ticker}; selected newest: "
            f"{selected}."
        )
    return str(selected.resolve()), warning


def _find_case_preserving_child(directory: Path, name: str) -> Path | None:
    direct = directory / name
    if not direct.is_file():
        return None
    try:
        for child in directory.iterdir():
            if child.name == name and child.is_file():
                return child
        for child in directory.iterdir():
            if child.name.lower() == name.lower() and child.is_file():
                return child
    except OSError:
        return direct
    return direct


def _validate_existing_path(path: str, source_label: str) -> str:
    clean_path = Path(path).expanduser()
    if not clean_path.is_file():
        raise ValueError(f"{source_label} path does not exist: {clean_path}")
    return str(clean_path.resolve())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run standalone or routed deep fundamental underwriting."
    )

    parser.add_argument(
        "--tickers",
        nargs="+",
        required=True,
        help="Ticker symbols to analyze, e.g. MU ETN UAL",
    )

    parser.add_argument(
        "--horizon",
        default="6m",
        help="Investment horizon, e.g. 1m, 3m, 6m, 1y",
    )

    parser.add_argument(
        "--mode",
        choices=[mode.value for mode in DeepFundamentalInputMode],
        default=DeepFundamentalInputMode.STANDALONE.value,
        help="Run mode: standalone or routed_cycle",
    )

    parser.add_argument(
        "--cycle-id",
        default=None,
        help="Optional cycle ID when running inside a research cycle.",
    )

    parser.add_argument(
        "--candidate-id",
        default=None,
        help="Optional candidate ID when running inside a research cycle.",
    )

    parser.add_argument(
        "--trade-id",
        default=None,
        help="Optional trade ID if linked to an accepted/proposed trade.",
    )

    parser.add_argument(
        "--thesis",
        default=None,
        help="Optional user-supplied thesis or research angle.",
    )

    parser.add_argument(
        "--macro-forecast-path",
        default=None,
        help="Optional path to an existing macro forecast JSON.",
    )

    parser.add_argument(
        "--refresh-theme-mapping",
        action="store_true",
        help="Rebuild ticker-to-theme mapping instead of using a cached mapping.",
    )

    parser.add_argument(
        "--no-theme-mapping",
        action="store_true",
        help="Extract macro context but skip ticker-to-theme mapping.",
    )

    parser.add_argument(
        "--benchmark",
        default=None,
        help="Primary benchmark override for a single-ticker run, e.g. SMH.",
    )

    parser.add_argument(
        "--benchmark-map",
        nargs="*",
        default=None,
        metavar="TICKER=BENCHMARK",
        help=(
            "Ticker-specific benchmark overrides for multi-ticker runs, e.g. "
            "MU=SMH AAPL=QQQ UNH=XLV."
        ),
    )

    parser.add_argument(
        "--skip-relative-performance",
        action="store_true",
        help="Skip benchmark-relative performance analysis for debugging.",
    )

    parser.add_argument(
        "--use-llm-synthesis",
        action="store_true",
        help="Deprecated/no-op: LLM synthesis is enabled by default.",
    )

    parser.add_argument(
        "--no-llm-synthesis",
        action="store_true",
        help="Disable LLM synthesis explicitly for debugging/cheap runs.",
    )

    parser.add_argument(
        "--strict-llm",
        action="store_true",
        help="Fail the run if final LLM synthesis fails instead of saving a partial report.",
    )

    parser.add_argument(
        "--use-llm-profile",
        action="store_true",
        help="Deprecated/no-op: LLM company profiles are enabled by default.",
    )

    parser.add_argument(
        "--no-llm-profile",
        action="store_true",
        help="Disable LLM company profile generation for debugging/cheap runs.",
    )

    parser.add_argument(
        "--refresh-company-profile",
        action="store_true",
        help="Regenerate company profile even if a cached profile exists.",
    )

    parser.add_argument(
        "--use-research-context",
        action="store_true",
        help="Deprecated/no-op: research context is enabled by default.",
    )

    parser.add_argument(
        "--no-research-context",
        action="store_true",
        help="Disable source-backed research context for debugging/cheap runs.",
    )

    parser.add_argument(
        "--refresh-research-context",
        action="store_true",
        help="Rebuild research context instead of using latest cached pack.",
    )

    parser.add_argument(
        "--transcript-path",
        default=None,
        help="Optional local earnings-call transcript path.",
    )

    parser.add_argument(
        "--transcript-paths",
        nargs="*",
        default=None,
        help="Optional local earnings-call transcript paths.",
    )

    parser.add_argument(
        "--transcript-map",
        nargs="*",
        default=None,
        metavar="TICKER=PATH",
        help=(
            "Ticker-specific transcript paths for multi-ticker runs, e.g. "
            "MU=data/manual_sources/MU_transcript.txt."
        ),
    )

    parser.add_argument(
        "--transcript-dir",
        default=None,
        help=(
            "Directory containing ticker-named transcript files such as "
            "MU_transcript.txt or AAPL_latest_transcript.txt."
        ),
    )

    parser.add_argument(
        "--manual-source-paths",
        nargs="*",
        default=None,
        help="Optional local source document paths to include.",
    )

    parser.add_argument(
        "--manual-source-urls",
        nargs="*",
        default=None,
        help="Optional source URLs to include manually.",
    )

    parser.add_argument(
        "--earnings-release-path",
        default=None,
        help="Optional local earnings-release path.",
    )

    parser.add_argument(
        "--earnings-release-paths",
        nargs="*",
        default=None,
        help="Optional local earnings-release paths.",
    )

    parser.add_argument(
        "--news-source-path",
        default=None,
        help="Optional local news/source path.",
    )

    parser.add_argument(
        "--news-source-paths",
        nargs="*",
        default=None,
        help="Optional local news/source paths.",
    )

    parser.add_argument(
        "--news-days",
        type=int,
        default=None,
        help=argparse.SUPPRESS,
    )

    parser.add_argument(
        "--news-lookback-days",
        type=int,
        default=None,
        help="Override research-context news lookback window.",
    )

    parser.add_argument(
        "--max-news-items",
        type=int,
        default=10,
        help="Maximum news documents sent to evidence extraction.",
    )

    parser.add_argument(
        "--skip-news",
        action="store_true",
        help=argparse.SUPPRESS,
    )

    parser.add_argument(
        "--skip-estimates",
        action="store_true",
        help=argparse.SUPPRESS,
    )

    parser.add_argument(
        "--skip-peer-commentary",
        action="store_true",
        help=argparse.SUPPRESS,
    )

    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print each report JSON to stdout.",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print stage progress to stderr.",
    )

    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Run without saving reports.",
    )

    parser.add_argument(
        "--latest",
        action="store_true",
        help="Load latest saved report for each ticker instead of generating a new one.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_mode = DeepFundamentalInputMode(args.mode)
    tickers = [ticker.upper().strip() for ticker in args.tickers if ticker.strip()]
    try:
        benchmark_overrides = resolve_benchmark_overrides(args, tickers)
    except ValueError as exc:
        raise SystemExit(f"error: {exc}") from exc
    if args.latest:
        transcript_resolution = TranscriptResolution(
            paths_by_ticker={ticker: [] for ticker in tickers},
            warnings_by_ticker={ticker: [] for ticker in tickers},
        )
    else:
        try:
            transcript_resolution = resolve_transcript_paths(args, tickers)
        except ValueError as exc:
            raise SystemExit(f"error: {exc}") from exc

    for ticker in tickers:
        progress_stream = sys.stderr

        def progress(message: str) -> None:
            if args.verbose:
                print(f"[{ticker}] {message}", file=progress_stream)

        if args.latest:
            progress("loading latest saved report")
            report = load_latest_deep_fundamental_report(
                ticker=ticker,
                cycle_id=args.cycle_id,
            )

            if report is None:
                print(f"{ticker}: no saved deep fundamental report found")
                continue

            saved_path = None

        else:
            use_llm = not args.no_llm_synthesis
            use_llm_profile = not args.no_llm_profile
            use_research_context = not args.no_research_context
            ticker_transcript_paths = transcript_resolution.paths_by_ticker.get(
                ticker,
                [],
            )
            transcript_mapping_warning = "; ".join(
                transcript_resolution.warnings_by_ticker.get(ticker, [])
            ) or None
            manual_transcript_path_used = (
                ", ".join(ticker_transcript_paths)
                if ticker_transcript_paths
                else None
            )
            manual_transcript_source = transcript_resolution.source_by_ticker.get(
                ticker
            )
            earnings_release_paths = list(args.earnings_release_paths or [])
            if args.earnings_release_path:
                earnings_release_paths.insert(0, args.earnings_release_path)
            news_source_paths = list(args.news_source_paths or [])
            if args.news_source_path:
                news_source_paths.insert(0, args.news_source_path)
            if use_llm or use_llm_profile or use_research_context:
                progress("loading company profile, macro context, and research context")
                if ticker_transcript_paths:
                    progress("loading manual transcript")
                if args.macro_forecast_path:
                    progress("loading macro forecast")
                if use_research_context:
                    progress("building/loading research context")
                    progress("fetching SEC, news, transcript, and estimate sources")
                    progress("extracting evidence")
                if not args.skip_relative_performance:
                    progress("running benchmark-relative performance analysis")
                if use_llm:
                    progress("running final LLM synthesis")
                report = asyncio.run(
                    build_deep_fundamental_report_async(
                        ticker=ticker,
                        input_mode=input_mode,
                        horizon=args.horizon,
                        cycle_id=args.cycle_id,
                        candidate_id=args.candidate_id,
                        trade_id=args.trade_id,
                        user_supplied_thesis=args.thesis,
                        macro_forecast_path=args.macro_forecast_path,
                        refresh_theme_mapping=args.refresh_theme_mapping,
                        enable_theme_mapping=not args.no_theme_mapping,
                        use_llm_synthesis=use_llm,
                        strict_llm=args.strict_llm,
                        use_llm_profile=use_llm_profile,
                        refresh_company_profile=args.refresh_company_profile,
                        use_research_context=use_research_context,
                        refresh_research_context=args.refresh_research_context,
                        transcript_path=None,
                        transcript_paths=ticker_transcript_paths,
                        manual_transcript_path_used=manual_transcript_path_used,
                        manual_transcript_source=manual_transcript_source,
                        transcript_mapping_warning=transcript_mapping_warning,
                        manual_source_paths=args.manual_source_paths,
                        manual_source_urls=args.manual_source_urls,
                        earnings_release_paths=earnings_release_paths,
                        news_source_paths=news_source_paths,
                        news_days=args.news_days,
                        news_lookback_days=args.news_lookback_days,
                        max_news_items=args.max_news_items,
                        include_news=not args.skip_news,
                        include_estimates=not args.skip_estimates,
                        include_peer_commentary=not args.skip_peer_commentary,
                        benchmark_override=benchmark_overrides.get(ticker),
                        skip_relative_performance=args.skip_relative_performance,
                    )
                )
            else:
                progress("running deterministic report path")
                report = build_deep_fundamental_report(
                    ticker=ticker,
                    input_mode=input_mode,
                    horizon=args.horizon,
                    cycle_id=args.cycle_id,
                    candidate_id=args.candidate_id,
                    trade_id=args.trade_id,
                    user_supplied_thesis=args.thesis,
                    macro_forecast_path=args.macro_forecast_path,
                    refresh_theme_mapping=args.refresh_theme_mapping,
                    enable_theme_mapping=not args.no_theme_mapping,
                    use_llm_profile=False,
                    refresh_company_profile=args.refresh_company_profile,
                    use_research_context=False,
                    use_llm_synthesis=False,
                    strict_llm=args.strict_llm,
                    manual_transcript_path_used=manual_transcript_path_used,
                    manual_transcript_source=manual_transcript_source,
                    transcript_mapping_warning=transcript_mapping_warning,
                    benchmark_override=benchmark_overrides.get(ticker),
                    skip_relative_performance=args.skip_relative_performance,
                )

            saved_path = None

            if not args.no_save:
                progress("saving report")
                saved_path = save_deep_fundamental_report(report)
            progress(
                "partial complete"
                if report.run_configuration
                and report.run_configuration.llm_synthesis_status == "failed"
                else "complete"
            )

        output_stream = sys.stderr if args.print_json else sys.stdout

        print(
            f"{report.ticker}: "
            f"verdict={report.verdict.value} "
            f"score={report.scores.final_underwriting_score:.1f} "
            f"profile={report.company_profile.profile_source} "
            f"llm={report.llm_synthesis is not None} "
            f"path={saved_path if saved_path else 'not saved / loaded existing'}",
            file=output_stream,
        )

        if report.run_configuration is not None:
            cfg = report.run_configuration
            research_mode = (
                "refreshed"
                if cfg.research_context_refreshed
                else "cached"
                if cfg.research_context_cache_used
                else "provided"
                if cfg.research_context_used
                else "not used"
            )
            print(
                f"  LLM synthesis: {'used' if cfg.llm_synthesis_used else 'not used'}"
                f" ({cfg.llm_synthesis_status or 'unknown'})",
                file=output_stream,
            )
            if cfg.llm_synthesis_prompt_chars is not None:
                print(
                    "  LLM prompt: "
                    f"chars={cfg.llm_synthesis_prompt_chars} "
                    f"est_tokens={cfg.llm_synthesis_prompt_est_tokens} "
                    f"retries={cfg.llm_retry_count or 0}",
                    file=output_stream,
                )
            if cfg.llm_last_error:
                print(
                    f"  LLM last error: {cfg.llm_last_error[:240]}",
                    file=output_stream,
                )
            print(
                f"  LLM profile: {'used' if cfg.llm_profile_used else 'not used'}; "
                f"profile source={cfg.company_profile_source or 'n/a'}",
                file=output_stream,
            )
            print(
                f"  Research context: "
                f"{'used' if cfg.research_context_used else 'not used'}; "
                f"{research_mode}",
                file=output_stream,
            )
            if cfg.manual_transcript_path_used:
                print(
                    "  Manual transcript: "
                    f"used from {cfg.manual_transcript_source or 'manual input'} "
                    f"{cfg.manual_transcript_path_used}",
                    file=output_stream,
                )
            else:
                print("  Manual transcript: not supplied", file=output_stream)
            if cfg.transcript_mapping_warning:
                print(
                    f"  Transcript mapping: {cfg.transcript_mapping_warning}",
                    file=output_stream,
                )
            if cfg.source_coverage_summary:
                print(f"  Source coverage: {cfg.source_coverage_summary}", file=output_stream)
            if cfg.data_gaps:
                print("  Data gaps: " + "; ".join(cfg.data_gaps[:4]), file=output_stream)

        if report.relative_performance_context is not None:
            relative = report.relative_performance_context
            selection = relative.benchmark_selection
            primary = relative.primary_metrics
            six_month = None
            if primary is not None:
                six_month = next(
                    (
                        window
                        for window in primary.windows
                        if window.window == "6m"
                    ),
                    None,
                )
            excess_text = (
                f"{six_month.excess_return_pct:+.1f}%"
                if six_month is not None
                and six_month.excess_return_pct is not None
                else "n/a"
            )
            print(
                "  Benchmark-relative: "
                f"primary={selection.primary_benchmark} "
                f"label={relative.overall_label or 'n/a'} "
                f"6m_excess={excess_text}",
                file=output_stream,
            )

        if report.research_context is not None:
            print(
                f"  research_coverage={report.research_context.source_coverage_summary or 'n/a'} "
                f"evidence={report.research_context.evidence_item_count}",
                file=output_stream,
            )
            if report.research_context.data_gaps:
                print(
                    "  research_gaps="
                    + "; ".join(report.research_context.data_gaps[:4]),
                    file=output_stream,
                )

        if args.print_json:
            print(report.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
