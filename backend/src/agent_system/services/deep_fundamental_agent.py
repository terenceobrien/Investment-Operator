from __future__ import annotations

import os
from datetime import date, datetime, timezone
from typing import Any

from src.agent_system.schemas.deep_fundamental import (
    BasicScreenResult,
    CompanyProfile,
    CompetitivePositionAnalysis,
    DeepFundamentalLLMSynthesis,
    DeepFundamentalInputMode,
    DeepFundamentalReport,
    DeepFundamentalRunConfiguration,
    DeepFundamentalScores,
    DeepFundamentalVerdict,
    FalsificationFramework,
    FundamentalContextPack,
    FinancialTrendAnalysis,
    MacroContextPack,
    MarketExpectationAnalysis,
    PressureInflectionAnalysis,
    RegimeSensitivityAnalysis,
    RelativePerformanceContext,
    SingleNameResearchContextPack,
    SourceRetrievalStatus,
    ThemeContextPack,
    VariantView,
    VariantViewDirection,
)
from src.agent_system.services.deep_fundamental_builders import (
    build_competitive_position_analysis,
    build_falsification_framework,
    build_financial_trend_analysis,
    build_market_expectation_analysis,
    build_pressure_inflection_analysis,
    build_regime_sensitivity_analysis,
    build_variant_view,
)
from src.agent_system.services.company_profile_builder import (
    build_company_profile,
    build_company_profile_async,
)
from src.agent_system.services.deep_fundamental_context import (
    build_fundamental_context_pack,
)
from src.agent_system.services.deep_fundamental_verdict import (
    build_deep_fundamental_scores,
    determine_deep_fundamental_verdict,
)
from src.agent_system.services.benchmark_selector import select_benchmarks
from src.agent_system.services.relative_performance_analyzer import (
    RelativePerformanceAnalyzer,
)
from src.agent_system.services.macro_forecast_context_adapter import (
    build_macro_and_theme_context_from_forecast,
    extract_macro_context_pack,
    load_macro_forecast_json,
)
from src.agent_system.research_sources.config import (
    DEFAULT_MAX_NEWS_ITEMS,
    DEFAULT_NEWS_LOOKBACK_DAYS,
)


def build_deep_fundamental_report(
    ticker: str,
    input_mode: DeepFundamentalInputMode = DeepFundamentalInputMode.STANDALONE,
    horizon: str | None = "6m",
    cycle_id: str | None = None,
    candidate_id: str | None = None,
    trade_id: str | None = None,
    user_supplied_thesis: str | None = None,
    basic_screen_result: BasicScreenResult | None = None,
    macro_context: MacroContextPack | dict[str, Any] | None = None,
    theme_context: ThemeContextPack | dict[str, Any] | None = None,
    macro_forecast: dict[str, Any] | None = None,
    macro_forecast_path: str | None = None,
    refresh_theme_mapping: bool = False,
    enable_theme_mapping: bool = True,
    use_llm_synthesis: bool = True,
    strict_llm: bool = False,
    llm_synthesis: DeepFundamentalLLMSynthesis | None = None,
    use_llm_profile: bool = True,
    refresh_company_profile: bool = False,
    research_context: SingleNameResearchContextPack | None = None,
    use_research_context: bool = True,
    refresh_research_context: bool = False,
    transcript_path: str | None = None,
    transcript_paths: list[str] | None = None,
    manual_transcript_path_used: str | None = None,
    manual_transcript_source: str | None = None,
    transcript_mapping_warning: str | None = None,
    manual_source_paths: list[str] | None = None,
    manual_source_urls: list[str] | None = None,
    earnings_release_paths: list[str] | None = None,
    news_source_paths: list[str] | None = None,
    news_days: int | None = DEFAULT_NEWS_LOOKBACK_DAYS,
    news_lookback_days: int | None = None,
    max_news_items: int = DEFAULT_MAX_NEWS_ITEMS,
    include_news: bool = True,
    include_estimates: bool = True,
    include_peer_commentary: bool = True,
    benchmark_override: str | None = None,
    skip_relative_performance: bool = False,
) -> DeepFundamentalReport:
    """
    Main orchestrator for the deep fundamental agent.

    v1 goal:
    - Build schema-valid structured underwriting output.
    - Use simple deterministic/contextual logic first.
    - Later swap each builder with richer data + LLM synthesis.
    """

    if (
        (use_llm_synthesis and llm_synthesis is None)
        or use_llm_profile
        or use_research_context
    ):
        try:
            import asyncio

            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                build_deep_fundamental_report_async(
                    ticker=ticker,
                    input_mode=input_mode,
                    horizon=horizon,
                    cycle_id=cycle_id,
                    candidate_id=candidate_id,
                    trade_id=trade_id,
                    user_supplied_thesis=user_supplied_thesis,
                    basic_screen_result=basic_screen_result,
                    macro_context=macro_context,
                    theme_context=theme_context,
                    macro_forecast=macro_forecast,
                    macro_forecast_path=macro_forecast_path,
                    refresh_theme_mapping=refresh_theme_mapping,
                    enable_theme_mapping=enable_theme_mapping,
                    use_llm_synthesis=use_llm_synthesis,
                    strict_llm=strict_llm,
                    llm_synthesis=llm_synthesis,
                    use_llm_profile=use_llm_profile,
                    refresh_company_profile=refresh_company_profile,
                    research_context=research_context,
                    use_research_context=use_research_context,
                    refresh_research_context=refresh_research_context,
                    transcript_path=transcript_path,
                    transcript_paths=transcript_paths,
                    manual_transcript_path_used=manual_transcript_path_used,
                    manual_transcript_source=manual_transcript_source,
                    transcript_mapping_warning=transcript_mapping_warning,
                    manual_source_paths=manual_source_paths,
                    manual_source_urls=manual_source_urls,
                    earnings_release_paths=earnings_release_paths,
                    news_source_paths=news_source_paths,
                    news_days=news_days,
                    news_lookback_days=news_lookback_days,
                    max_news_items=max_news_items,
                    include_news=include_news,
                    include_estimates=include_estimates,
                    include_peer_commentary=include_peer_commentary,
                    benchmark_override=benchmark_override,
                    skip_relative_performance=skip_relative_performance,
                )
            )
        raise RuntimeError(
            "build_deep_fundamental_report cannot run live enriched defaults "
            "inside an existing event loop. Use build_deep_fundamental_report_async."
        )

    prepared = _prepare_deep_fundamental_inputs(
        ticker=ticker,
        basic_screen_result=basic_screen_result,
        macro_context=macro_context,
        theme_context=theme_context,
        macro_forecast=macro_forecast,
        macro_forecast_path=macro_forecast_path,
        refresh_theme_mapping=refresh_theme_mapping,
        enable_theme_mapping=enable_theme_mapping,
        use_llm_profile=use_llm_profile,
        refresh_company_profile=refresh_company_profile,
        research_context=research_context,
        use_research_context=use_research_context,
        refresh_research_context=refresh_research_context,
        manual_transcript_path_used=manual_transcript_path_used,
        manual_transcript_source=manual_transcript_source,
        transcript_mapping_warning=transcript_mapping_warning,
        benchmark_override=benchmark_override,
        skip_relative_performance=skip_relative_performance,
    )
    return _build_deep_fundamental_report_from_prepared(
        prepared=prepared,
        input_mode=input_mode,
        horizon=horizon,
        cycle_id=cycle_id,
        candidate_id=candidate_id,
        trade_id=trade_id,
        user_supplied_thesis=user_supplied_thesis,
        basic_screen_result=basic_screen_result,
        llm_synthesis=llm_synthesis,
    )


async def build_deep_fundamental_report_async(
    ticker: str,
    input_mode: DeepFundamentalInputMode = DeepFundamentalInputMode.STANDALONE,
    horizon: str | None = "6m",
    cycle_id: str | None = None,
    candidate_id: str | None = None,
    trade_id: str | None = None,
    user_supplied_thesis: str | None = None,
    basic_screen_result: BasicScreenResult | None = None,
    macro_context: MacroContextPack | dict[str, Any] | None = None,
    theme_context: ThemeContextPack | dict[str, Any] | None = None,
    macro_forecast: dict[str, Any] | None = None,
    macro_forecast_path: str | None = None,
    refresh_theme_mapping: bool = False,
    enable_theme_mapping: bool = True,
    use_llm_synthesis: bool = True,
    strict_llm: bool = False,
    llm_synthesis: DeepFundamentalLLMSynthesis | None = None,
    use_llm_profile: bool = True,
    refresh_company_profile: bool = False,
    research_context: SingleNameResearchContextPack | None = None,
    use_research_context: bool = True,
    refresh_research_context: bool = False,
    transcript_path: str | None = None,
    transcript_paths: list[str] | None = None,
    manual_transcript_path_used: str | None = None,
    manual_transcript_source: str | None = None,
    transcript_mapping_warning: str | None = None,
    manual_source_paths: list[str] | None = None,
    manual_source_urls: list[str] | None = None,
    earnings_release_paths: list[str] | None = None,
    news_source_paths: list[str] | None = None,
    news_days: int | None = DEFAULT_NEWS_LOOKBACK_DAYS,
    news_lookback_days: int | None = None,
    max_news_items: int = DEFAULT_MAX_NEWS_ITEMS,
    include_news: bool = True,
    include_estimates: bool = True,
    include_peer_commentary: bool = True,
    benchmark_override: str | None = None,
    skip_relative_performance: bool = False,
) -> DeepFundamentalReport:
    prepared = await _prepare_deep_fundamental_inputs_async(
        ticker=ticker,
        basic_screen_result=basic_screen_result,
        macro_context=macro_context,
        theme_context=theme_context,
        macro_forecast=macro_forecast,
        macro_forecast_path=macro_forecast_path,
        refresh_theme_mapping=refresh_theme_mapping,
        enable_theme_mapping=enable_theme_mapping,
        use_llm_profile=use_llm_profile,
        refresh_company_profile=refresh_company_profile,
        research_context=research_context,
        use_research_context=use_research_context,
        refresh_research_context=refresh_research_context,
        transcript_path=transcript_path,
        transcript_paths=transcript_paths,
        manual_transcript_path_used=manual_transcript_path_used,
        manual_transcript_source=manual_transcript_source,
        transcript_mapping_warning=transcript_mapping_warning,
        manual_source_paths=manual_source_paths,
        manual_source_urls=manual_source_urls,
        earnings_release_paths=earnings_release_paths,
        news_source_paths=news_source_paths,
        news_days=news_days,
        news_lookback_days=news_lookback_days,
        max_news_items=max_news_items,
        include_news=include_news,
        include_estimates=include_estimates,
        include_peer_commentary=include_peer_commentary,
        benchmark_override=benchmark_override,
        skip_relative_performance=skip_relative_performance,
    )

    if use_llm_synthesis and llm_synthesis is None:
        from src.agent_system.agents.deep_fundamental_agent import (
            synthesize_deep_fundamental_view,
        )
        from src.agent_system.llm.client import get_last_call_diagnostics

        try:
            llm_synthesis = await synthesize_deep_fundamental_view(
                ticker=prepared.clean_ticker,
                horizon=horizon,
                company_profile=prepared.company_profile,
                fundamental_context=prepared.fundamental_context,
                macro_context=prepared.macro_context,
                theme_context=prepared.theme_context,
                relative_performance_context=prepared.relative_performance_context,
                research_context=prepared.research_context,
                basic_screen_result=basic_screen_result,
                user_supplied_thesis=user_supplied_thesis,
            )
            prepared.llm_synthesis_status = "succeeded"
            prepared.llm_diagnostics = get_last_call_diagnostics()
        except Exception as exc:
            prepared.llm_synthesis_status = "failed"
            prepared.llm_diagnostics = get_last_call_diagnostics()
            prepared.llm_last_error = (
                f"{exc.__class__.__name__}: {_sanitize_llm_error(exc)}"
            )
            prepared.warnings.append(
                "Final LLM synthesis failed: "
                f"{exc.__class__.__name__}. Partial report generated from "
                "deterministic scores and extracted evidence."
            )
            if strict_llm:
                raise

    return _build_deep_fundamental_report_from_prepared(
        prepared=prepared,
        input_mode=input_mode,
        horizon=horizon,
        cycle_id=cycle_id,
        candidate_id=candidate_id,
        trade_id=trade_id,
        user_supplied_thesis=user_supplied_thesis,
        basic_screen_result=basic_screen_result,
        llm_synthesis=llm_synthesis,
    )


class _PreparedDeepFundamentalInputs:
    def __init__(
        self,
        *,
        clean_ticker: str,
        warnings: list[str],
        company_profile: CompanyProfile,
        fundamental_context: FundamentalContextPack,
        macro_context: MacroContextPack | dict[str, Any] | None,
        theme_context: ThemeContextPack | dict[str, Any] | None,
        relative_performance_context: RelativePerformanceContext | None,
        research_context: SingleNameResearchContextPack | None,
        llm_profile_requested: bool,
        research_context_requested: bool,
        research_context_refreshed: bool = False,
        research_context_cache_used: bool = False,
        manual_transcript_path_used: str | None = None,
        manual_transcript_source: str | None = None,
        transcript_mapping_warning: str | None = None,
        llm_synthesis_status: str | None = None,
        llm_diagnostics: dict[str, Any] | None = None,
        llm_last_error: str | None = None,
    ) -> None:
        self.clean_ticker = clean_ticker
        self.warnings = warnings
        self.company_profile = company_profile
        self.fundamental_context = fundamental_context
        self.macro_context = macro_context
        self.theme_context = theme_context
        self.relative_performance_context = relative_performance_context
        self.research_context = research_context
        self.llm_profile_requested = llm_profile_requested
        self.research_context_requested = research_context_requested
        self.research_context_refreshed = research_context_refreshed
        self.research_context_cache_used = research_context_cache_used
        self.manual_transcript_path_used = manual_transcript_path_used
        self.manual_transcript_source = manual_transcript_source
        self.transcript_mapping_warning = transcript_mapping_warning
        self.llm_synthesis_status = llm_synthesis_status
        self.llm_diagnostics = llm_diagnostics or {}
        self.llm_last_error = llm_last_error


def _prepare_deep_fundamental_inputs(
    *,
    ticker: str,
    basic_screen_result: BasicScreenResult | None,
    macro_context: MacroContextPack | dict[str, Any] | None,
    theme_context: ThemeContextPack | dict[str, Any] | None,
    macro_forecast: dict[str, Any] | None,
    macro_forecast_path: str | None,
    refresh_theme_mapping: bool,
    enable_theme_mapping: bool,
    use_llm_profile: bool,
    refresh_company_profile: bool,
    research_context: SingleNameResearchContextPack | None,
    use_research_context: bool,
    refresh_research_context: bool,
    manual_transcript_path_used: str | None,
    manual_transcript_source: str | None,
    transcript_mapping_warning: str | None,
    benchmark_override: str | None,
    skip_relative_performance: bool,
) -> _PreparedDeepFundamentalInputs:
    clean_ticker = ticker.upper().strip()
    warnings: list[str] = []
    if transcript_mapping_warning:
        warnings.append(transcript_mapping_warning)

    initial_profile = build_company_profile(
        clean_ticker,
        use_llm_profile=False,
        refresh_profile=False,
    )
    peer_tickers = [
        peer.ticker
        for peer in initial_profile.peer_group
        if peer.ticker
    ]
    fundamental_context = build_fundamental_context_pack(
        ticker=clean_ticker,
        peer_tickers=peer_tickers,
        basic_screen_result=basic_screen_result,
    )
    company_profile = build_company_profile(
        clean_ticker,
        financial_context=fundamental_context,
        research_context=research_context,
        use_llm_profile=use_llm_profile,
        refresh_profile=refresh_company_profile,
    )
    final_peer_tickers = [
        peer.ticker
        for peer in company_profile.peer_group
        if peer.ticker
    ]
    if final_peer_tickers and final_peer_tickers != peer_tickers:
        fundamental_context = build_fundamental_context_pack(
            ticker=clean_ticker,
            peer_tickers=final_peer_tickers,
            basic_screen_result=basic_screen_result,
        )

    resolved_research_context = research_context
    if resolved_research_context is None and use_research_context:
        if not refresh_research_context:
            try:
                from src.agent_system.storage.repository import (
                    load_latest_research_context_pack,
                )

                resolved_research_context = load_latest_research_context_pack(
                    clean_ticker
                )
            except Exception as exc:
                warnings.append(f"Research context load failed: {exc}")
        if resolved_research_context is None:
            warnings.append(
                "Research context retrieval requires the async report builder; "
                "no cached pack was available."
            )

    resolved_macro_context, resolved_theme_context = _resolve_macro_theme_context(
        clean_ticker=clean_ticker,
        company_profile=company_profile,
        macro_context=macro_context,
        theme_context=theme_context,
        macro_forecast=macro_forecast,
        macro_forecast_path=macro_forecast_path,
        refresh_theme_mapping=refresh_theme_mapping,
        enable_theme_mapping=enable_theme_mapping,
        warnings=warnings,
    )

    relative_performance_context = _build_relative_performance_context(
        clean_ticker=clean_ticker,
        company_profile=company_profile,
        fundamental_context=fundamental_context,
        benchmark_override=benchmark_override,
        skip_relative_performance=skip_relative_performance,
        warnings=warnings,
    )

    return _PreparedDeepFundamentalInputs(
        clean_ticker=clean_ticker,
        warnings=warnings,
        company_profile=company_profile,
        fundamental_context=fundamental_context,
        macro_context=resolved_macro_context,
        theme_context=resolved_theme_context,
        relative_performance_context=relative_performance_context,
        research_context=resolved_research_context,
        llm_profile_requested=use_llm_profile,
        research_context_requested=use_research_context,
        research_context_refreshed=False,
        research_context_cache_used=resolved_research_context is not None
        and use_research_context
        and not refresh_research_context,
        manual_transcript_path_used=manual_transcript_path_used,
        manual_transcript_source=manual_transcript_source,
        transcript_mapping_warning=transcript_mapping_warning,
    )


async def _prepare_deep_fundamental_inputs_async(
    *,
    ticker: str,
    basic_screen_result: BasicScreenResult | None,
    macro_context: MacroContextPack | dict[str, Any] | None,
    theme_context: ThemeContextPack | dict[str, Any] | None,
    macro_forecast: dict[str, Any] | None,
    macro_forecast_path: str | None,
    refresh_theme_mapping: bool,
    enable_theme_mapping: bool,
    use_llm_profile: bool,
    refresh_company_profile: bool,
    research_context: SingleNameResearchContextPack | None,
    use_research_context: bool,
    refresh_research_context: bool,
    transcript_path: str | None,
    transcript_paths: list[str] | None,
    manual_transcript_path_used: str | None,
    manual_transcript_source: str | None,
    transcript_mapping_warning: str | None,
    manual_source_paths: list[str] | None,
    manual_source_urls: list[str] | None,
    earnings_release_paths: list[str] | None,
    news_source_paths: list[str] | None,
    news_days: int | None,
    news_lookback_days: int | None,
    max_news_items: int,
    include_news: bool,
    include_estimates: bool,
    include_peer_commentary: bool,
    benchmark_override: str | None,
    skip_relative_performance: bool,
) -> _PreparedDeepFundamentalInputs:
    clean_ticker = ticker.upper().strip()
    warnings: list[str] = []
    if transcript_mapping_warning:
        warnings.append(transcript_mapping_warning)

    initial_profile = build_company_profile(
        clean_ticker,
        use_llm_profile=False,
        refresh_profile=False,
    )
    peer_tickers = [
        peer.ticker
        for peer in initial_profile.peer_group
        if peer.ticker
    ]
    fundamental_context = build_fundamental_context_pack(
        ticker=clean_ticker,
        peer_tickers=peer_tickers,
        basic_screen_result=basic_screen_result,
    )

    resolved_research_context = research_context
    research_context_cache_used = False
    research_context_refreshed = False
    manual_research_inputs = _has_manual_research_inputs(
        transcript_path=transcript_path,
        transcript_paths=transcript_paths,
        manual_source_paths=manual_source_paths,
        manual_source_urls=manual_source_urls,
        earnings_release_paths=earnings_release_paths,
        news_source_paths=news_source_paths,
    )
    if (
        resolved_research_context is None
        and use_research_context
        and not refresh_research_context
        and not manual_research_inputs
    ):
        try:
            from src.agent_system.storage.repository import (
                load_latest_research_context_pack,
            )

            resolved_research_context = load_latest_research_context_pack(
                clean_ticker
            )
            if resolved_research_context is not None:
                if _research_context_is_stale(resolved_research_context):
                    warnings.append(
                        "Cached research context is stale; rebuilding source pack."
                    )
                    resolved_research_context = None
                else:
                    research_context_cache_used = True
        except Exception as exc:
            warnings.append(f"Research context load failed: {exc}")
    if resolved_research_context is None and use_research_context:
        try:
            from src.agent_system.services.research_context_builder import (
                build_research_context_pack_async,
            )

            resolved_research_context = await build_research_context_pack_async(
                ticker=clean_ticker,
                company_profile=initial_profile,
                transcript_path=transcript_path,
                transcript_paths=transcript_paths,
                manual_source_paths=manual_source_paths,
                manual_source_urls=manual_source_urls,
                earnings_release_paths=earnings_release_paths,
                news_source_paths=news_source_paths,
                news_days=news_days,
                news_lookback_days=news_lookback_days,
                max_news_items=max_news_items,
                include_news=include_news,
                include_estimates=include_estimates,
                include_peer_commentary=include_peer_commentary,
                save=True,
            )
            research_context_refreshed = True
        except Exception as exc:
            warnings.append(f"Research context build failed: {exc}")

    company_profile = await build_company_profile_async(
        clean_ticker,
        financial_context=fundamental_context,
        research_context=resolved_research_context,
        use_llm_profile=use_llm_profile,
        refresh_profile=refresh_company_profile,
    )
    final_peer_tickers = [
        peer.ticker
        for peer in company_profile.peer_group
        if peer.ticker
    ]
    if final_peer_tickers and final_peer_tickers != peer_tickers:
        fundamental_context = build_fundamental_context_pack(
            ticker=clean_ticker,
            peer_tickers=final_peer_tickers,
            basic_screen_result=basic_screen_result,
        )

    resolved_macro_context, resolved_theme_context = _resolve_macro_theme_context(
        clean_ticker=clean_ticker,
        company_profile=company_profile,
        macro_context=macro_context,
        theme_context=theme_context,
        macro_forecast=macro_forecast,
        macro_forecast_path=macro_forecast_path,
        refresh_theme_mapping=refresh_theme_mapping,
        enable_theme_mapping=enable_theme_mapping,
        warnings=warnings,
    )

    relative_performance_context = _build_relative_performance_context(
        clean_ticker=clean_ticker,
        company_profile=company_profile,
        fundamental_context=fundamental_context,
        benchmark_override=benchmark_override,
        skip_relative_performance=skip_relative_performance,
        warnings=warnings,
    )

    return _PreparedDeepFundamentalInputs(
        clean_ticker=clean_ticker,
        warnings=warnings,
        company_profile=company_profile,
        fundamental_context=fundamental_context,
        macro_context=resolved_macro_context,
        theme_context=resolved_theme_context,
        relative_performance_context=relative_performance_context,
        research_context=resolved_research_context,
        llm_profile_requested=use_llm_profile,
        research_context_requested=use_research_context,
        research_context_refreshed=research_context_refreshed,
        research_context_cache_used=research_context_cache_used,
        manual_transcript_path_used=manual_transcript_path_used,
        manual_transcript_source=manual_transcript_source,
        transcript_mapping_warning=transcript_mapping_warning,
    )


def _build_relative_performance_context(
    *,
    clean_ticker: str,
    company_profile: CompanyProfile,
    fundamental_context: FundamentalContextPack,
    benchmark_override: str | None,
    skip_relative_performance: bool,
    warnings: list[str],
) -> RelativePerformanceContext | None:
    if skip_relative_performance:
        return None

    benchmark_selection = select_benchmarks(
        clean_ticker,
        company_profile=company_profile,
        user_override=benchmark_override,
    )
    try:
        context = RelativePerformanceAnalyzer().analyze(
            ticker=clean_ticker,
            benchmark_selection=benchmark_selection,
            as_of_date=fundamental_context.as_of_date,
        )
    except Exception as exc:
        warning = (
            "Relative performance analysis failed: "
            f"{exc.__class__.__name__}: {_sanitize_llm_error(exc)}"
        )
        warnings.append(warning)
        return RelativePerformanceContext(
            benchmark_selection=benchmark_selection,
            primary_metrics=None,
            overall_label="insufficient_data",
            score_0_to_100=None,
            summary=(
                "Benchmark-relative performance could not be computed; "
                "fundamental report continued without price-relative analytics."
            ),
            warnings=[warning],
        )

    if context.warnings:
        short_warnings = "; ".join(context.warnings[:3])
        suffix = "..." if len(context.warnings) > 3 else ""
        warnings.append(f"Relative performance warnings: {short_warnings}{suffix}")
    return context


def _has_manual_research_inputs(
    *,
    transcript_path: str | None,
    transcript_paths: list[str] | None,
    manual_source_paths: list[str] | None,
    manual_source_urls: list[str] | None,
    earnings_release_paths: list[str] | None,
    news_source_paths: list[str] | None,
) -> bool:
    return any(
        [
            transcript_path,
            transcript_paths,
            manual_source_paths,
            manual_source_urls,
            earnings_release_paths,
            news_source_paths,
        ]
    )


def _research_context_max_age_days() -> int:
    raw = os.getenv("RESEARCH_CONTEXT_MAX_AGE_DAYS")
    if raw:
        try:
            return max(0, int(raw))
        except ValueError:
            return 3
    return 3


def _research_context_is_stale(
    research_context: SingleNameResearchContextPack,
) -> bool:
    created_at = research_context.created_at
    if created_at is None:
        return True
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - created_at
    return age.days > _research_context_max_age_days()


def _sanitize_llm_error(exc: BaseException) -> str:
    text = str(exc)
    for env_name in ("OPENAI_API_KEY", "FMP_API_KEY", "FINNHUB_API_KEY", "NEWS_API_KEY"):
        secret = os.getenv(env_name)
        if secret and len(secret) > 3:
            text = text.replace(secret, "***")
    return text[:500]


def _resolve_macro_theme_context(
    *,
    clean_ticker: str,
    company_profile: CompanyProfile,
    macro_context: MacroContextPack | dict[str, Any] | None,
    theme_context: ThemeContextPack | dict[str, Any] | None,
    macro_forecast: dict[str, Any] | None,
    macro_forecast_path: str | None,
    refresh_theme_mapping: bool,
    enable_theme_mapping: bool,
    warnings: list[str],
) -> tuple[
    MacroContextPack | dict[str, Any] | None,
    ThemeContextPack | dict[str, Any] | None,
]:
    resolved_macro_context = macro_context
    resolved_theme_context = theme_context
    if resolved_macro_context is not None or resolved_theme_context is not None:
        return resolved_macro_context, resolved_theme_context

    try:
        loaded_forecast = macro_forecast
        if macro_forecast_path:
            loaded_forecast = load_macro_forecast_json(macro_forecast_path)
        if loaded_forecast:
            if enable_theme_mapping:
                return build_macro_and_theme_context_from_forecast(
                    macro_forecast=loaded_forecast,
                    ticker=clean_ticker,
                    company_profile=company_profile,
                    refresh_theme_mapping=refresh_theme_mapping,
                )

            source_path = loaded_forecast.get("_source_path")
            resolved_macro_context = extract_macro_context_pack(
                loaded_forecast,
                source_path=str(source_path) if source_path else macro_forecast_path,
            )
            resolved_theme_context = None
    except Exception as exc:
        warnings.append(f"Macro forecast context extraction failed: {exc}")
        resolved_macro_context = None
        resolved_theme_context = None

    return resolved_macro_context, resolved_theme_context


def _build_deep_fundamental_report_from_prepared(
    *,
    prepared: _PreparedDeepFundamentalInputs,
    input_mode: DeepFundamentalInputMode,
    horizon: str | None,
    cycle_id: str | None,
    candidate_id: str | None,
    trade_id: str | None,
    user_supplied_thesis: str | None,
    basic_screen_result: BasicScreenResult | None,
    llm_synthesis: DeepFundamentalLLMSynthesis | None,
) -> DeepFundamentalReport:
    clean_ticker = prepared.clean_ticker
    company_profile = prepared.company_profile
    fundamental_context = prepared.fundamental_context
    macro_context = prepared.macro_context
    theme_context = prepared.theme_context
    relative_performance_context = prepared.relative_performance_context
    research_context = prepared.research_context
    warnings = list(prepared.warnings)

    financial_trend_analysis = build_financial_trend_analysis(
        ticker=clean_ticker,
        basic_screen_result=basic_screen_result,
        fundamental_context=fundamental_context,
    )

    pressure_inflection_analysis = build_pressure_inflection_analysis(
        ticker=clean_ticker,
        company_profile=company_profile,
        financial_trend_analysis=financial_trend_analysis,
        fundamental_context=fundamental_context,
        macro_context=macro_context,
        theme_context=theme_context,
    )

    competitive_position_analysis = build_competitive_position_analysis(
        ticker=clean_ticker,
        company_profile=company_profile,
    )

    regime_sensitivity_analysis = build_regime_sensitivity_analysis(
        ticker=clean_ticker,
        company_profile=company_profile,
        macro_context=macro_context,
        theme_context=theme_context,
    )

    market_expectation_analysis = build_market_expectation_analysis(
        ticker=clean_ticker,
        company_profile=company_profile,
        financial_trend_analysis=financial_trend_analysis,
        pressure_inflection_analysis=pressure_inflection_analysis,
    )

    variant_view = build_variant_view(
        ticker=clean_ticker,
        company_profile=company_profile,
        financial_trend_analysis=financial_trend_analysis,
        pressure_inflection_analysis=pressure_inflection_analysis,
        competitive_position_analysis=competitive_position_analysis,
        market_expectation_analysis=market_expectation_analysis,
        user_supplied_thesis=user_supplied_thesis,
        macro_context=macro_context,
        theme_context=theme_context,
    )

    falsification_framework = build_falsification_framework(
        ticker=clean_ticker,
        company_profile=company_profile,
        pressure_inflection_analysis=pressure_inflection_analysis,
        regime_sensitivity_analysis=regime_sensitivity_analysis,
        variant_view=variant_view,
    )

    if llm_synthesis is not None:
        if (
            llm_synthesis.suggested_score_adjustment != 0
            and abs(llm_synthesis.suggested_score_adjustment) < 1
        ):
            warnings.append(
                "LLM suggested_score_adjustment is below 1 point; verify "
                "prompt units if this was intended."
            )
        (
            financial_trend_analysis,
            pressure_inflection_analysis,
            competitive_position_analysis,
            market_expectation_analysis,
            variant_view,
            falsification_framework,
        ) = _apply_llm_synthesis(
            llm_synthesis=llm_synthesis,
            financial_trend_analysis=financial_trend_analysis,
            pressure_inflection_analysis=pressure_inflection_analysis,
            competitive_position_analysis=competitive_position_analysis,
            market_expectation_analysis=market_expectation_analysis,
            variant_view=variant_view,
            falsification_framework=falsification_framework,
        )

    (
        pressure_inflection_analysis,
        variant_view,
        falsification_framework,
    ) = _normalize_output_lists(
        pressure_inflection_analysis=pressure_inflection_analysis,
        variant_view=variant_view,
        falsification_framework=falsification_framework,
    )

    scores = build_deep_fundamental_scores(
        company_profile=company_profile,
        financial_trend_analysis=financial_trend_analysis,
        pressure_inflection_analysis=pressure_inflection_analysis,
        competitive_position_analysis=competitive_position_analysis,
        regime_sensitivity_analysis=regime_sensitivity_analysis,
        market_expectation_analysis=market_expectation_analysis,
        variant_view=variant_view,
        theme_context=_coerce_theme_context(theme_context),
        relative_performance_context=relative_performance_context,
        llm_synthesis=llm_synthesis,
    )

    verdict, screen_override, screen_override_rationale = determine_deep_fundamental_verdict(
        scores=scores,
        basic_screen_result=basic_screen_result,
        financial_trend_analysis=financial_trend_analysis,
        pressure_inflection_analysis=pressure_inflection_analysis,
        variant_view=variant_view,
        llm_synthesis=llm_synthesis,
    )

    final_rationale = _build_final_rationale(
        ticker=clean_ticker,
        verdict=verdict,
        scores=scores,
        variant_view=variant_view,
        pressure_inflection_analysis=pressure_inflection_analysis,
        screen_override=screen_override,
        screen_override_rationale=screen_override_rationale,
        relative_performance_context=relative_performance_context,
        llm_synthesis=llm_synthesis,
    )

    key_monitoring_items = _build_key_monitoring_items(
        falsification_framework=falsification_framework,
        pressure_inflection_analysis=pressure_inflection_analysis,
    )

    base_source_note = (
        "v1 generated from deterministic scaffolding with LLM synthesis; "
        "richer filing and transcript layers pending."
        if llm_synthesis is not None
        else "v1 generated from deterministic scaffolding; richer filing, "
        "transcript, and LLM synthesis layers pending."
    )
    run_configuration = _build_run_configuration(
        prepared=prepared,
        llm_synthesis=llm_synthesis,
        research_context=research_context,
        company_profile=company_profile,
        warnings=warnings,
    )

    return DeepFundamentalReport(
        ticker=clean_ticker,
        as_of_date=date.today(),
        input_mode=input_mode,
        horizon=horizon,
        cycle_id=cycle_id,
        candidate_id=candidate_id,
        trade_id=trade_id,
        macro_context=macro_context,
        theme_context=theme_context,
        research_context=research_context,
        user_supplied_thesis=user_supplied_thesis,
        basic_screen_result=basic_screen_result,
        fundamental_context=fundamental_context,
        relative_performance_context=relative_performance_context,
        llm_synthesis=llm_synthesis,
        run_configuration=run_configuration,
        company_profile=company_profile,
        financial_trend_analysis=financial_trend_analysis,
        pressure_inflection_analysis=pressure_inflection_analysis,
        competitive_position_analysis=competitive_position_analysis,
        regime_sensitivity_analysis=regime_sensitivity_analysis,
        market_expectation_analysis=market_expectation_analysis,
        variant_view=variant_view,
        falsification_framework=falsification_framework,
        scores=scores,
        verdict=verdict,
        screen_override=screen_override,
        screen_override_rationale=screen_override_rationale,
        final_rationale=final_rationale,
        key_monitoring_items=key_monitoring_items,
        recommended_next_action=_recommended_next_action(
            verdict,
            llm_synthesis=llm_synthesis,
            variant_view=variant_view,
            scores=scores,
        ),
        data_confidence=fundamental_context.data_confidence,
        source_notes=[
            base_source_note,
            *_run_configuration_source_notes(run_configuration),
            *_profile_source_notes(company_profile),
            *fundamental_context.source_notes,
            *fundamental_context.data_freshness_notes,
            *_research_context_source_notes(research_context),
            *_context_source_notes(macro_context),
            *_context_source_notes(theme_context),
        ],
        warnings=warnings,
    )


# Keep this alias temporarily so your existing CLI does not break.
def build_deep_fundamental_report_stub(
    ticker: str,
    input_mode: DeepFundamentalInputMode = DeepFundamentalInputMode.STANDALONE,
    horizon: str | None = "6m",
) -> DeepFundamentalReport:
    return build_deep_fundamental_report(
        ticker=ticker,
        input_mode=input_mode,
        horizon=horizon,
    )


def _build_run_configuration(
    *,
    prepared: _PreparedDeepFundamentalInputs,
    llm_synthesis: DeepFundamentalLLMSynthesis | None,
    research_context: SingleNameResearchContextPack | None,
    company_profile: CompanyProfile,
    warnings: list[str],
) -> DeepFundamentalRunConfiguration:
    attempted: list[str] = []
    found: list[str] = []
    skipped: list[str] = []
    errors: list[str] = []
    if research_context is not None:
        for coverage in research_context.source_coverage:
            label = _provider_status_label(
                coverage.source_name,
                coverage.source_type.value,
                provider=coverage.provider,
            )
            detailed_label = (
                f"{label}:{coverage.provider_status}"
                if coverage.provider_status
                and coverage.provider_status not in {"found", "not_found"}
                else label
            )
            attempted.append(label)
            if coverage.status == SourceRetrievalStatus.FOUND:
                found.append(label)
            elif coverage.status == SourceRetrievalStatus.SKIPPED:
                skipped.append(detailed_label)
            elif coverage.status == SourceRetrievalStatus.ERROR:
                errors.append(detailed_label)
            elif coverage.status == SourceRetrievalStatus.NOT_FOUND:
                skipped.append(f"{label}:not_found")

    return DeepFundamentalRunConfiguration(
        llm_synthesis_used=llm_synthesis is not None,
        llm_synthesis_status=(
            prepared.llm_synthesis_status
            or ("succeeded" if llm_synthesis is not None else "not_used")
        ),
        llm_synthesis_prompt_chars=_diag_int(
            prepared.llm_diagnostics,
            "prompt_chars",
        ),
        llm_synthesis_prompt_est_tokens=_diag_int(
            prepared.llm_diagnostics,
            "prompt_est_tokens",
        ),
        llm_retry_count=_diag_int(prepared.llm_diagnostics, "retry_count"),
        llm_last_error=prepared.llm_last_error
        or _diag_str(prepared.llm_diagnostics, "last_error"),
        llm_profile_used=str(company_profile.profile_source).startswith("llm_generated"),
        research_context_used=research_context is not None,
        company_profile_source=str(company_profile.profile_source),
        research_context_created_at=(
            research_context.created_at if research_context is not None else None
        ),
        research_context_refreshed=prepared.research_context_refreshed,
        research_context_cache_used=prepared.research_context_cache_used,
        manual_transcript_path_used=prepared.manual_transcript_path_used,
        manual_transcript_source=prepared.manual_transcript_source,
        transcript_mapping_warning=prepared.transcript_mapping_warning,
        source_providers_attempted=dedupe_preserve_order(attempted),
        source_providers_found=dedupe_preserve_order(found),
        source_providers_skipped=dedupe_preserve_order(skipped),
        source_providers_error=dedupe_preserve_order(errors),
        source_coverage_summary=(
            research_context.source_coverage_summary
            if research_context is not None
            else None
        ),
        data_gaps=(
            research_context.data_gaps if research_context is not None else []
        ),
        warnings=dedupe_preserve_order(warnings + (
            research_context.warnings if research_context is not None else []
        )),
    )


def _diag_int(diagnostics: dict[str, Any], key: str) -> int | None:
    value = diagnostics.get(key)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _diag_str(diagnostics: dict[str, Any], key: str) -> str | None:
    value = diagnostics.get(key)
    if value is None:
        return None
    return str(value)


def _provider_status_label(
    source_name: str | None,
    source_type: str,
    *,
    provider: str | None = None,
) -> str:
    provider_key = (provider or "").lower()
    if provider_key == "fmp":
        return "FMP transcripts"
    if provider_key == "finnhub":
        return "Finnhub transcripts" if source_type == "transcript" else "Finnhub news"
    if provider_key == "newsapi":
        return "NewsAPI news"
    if provider_key == "yfinance":
        return "yfinance estimates"
    if provider_key == "manual":
        return "manual sources"
    if provider_key == "sec":
        return "SEC"
    name = (source_name or "").lower()
    if "sec" in name:
        return "SEC"
    if "fmp" in name:
        return "FMP transcripts"
    if "finnhub" in name and "transcript" in name:
        return "Finnhub transcripts"
    if "finnhub" in name:
        return "Finnhub news"
    if "newsapi" in name:
        return "NewsAPI news"
    if "yfinance" in name:
        return "yfinance estimates"
    if "manual" in name:
        return "manual sources"
    if "company ir" in name:
        return "company IR"
    return source_type


def _build_final_rationale(
    ticker: str,
    verdict: DeepFundamentalVerdict,
    scores: DeepFundamentalScores,
    variant_view: VariantView,
    pressure_inflection_analysis: PressureInflectionAnalysis,
    screen_override: bool,
    screen_override_rationale: str | None,
    relative_performance_context: RelativePerformanceContext | None = None,
    llm_synthesis: DeepFundamentalLLMSynthesis | None = None,
) -> str:
    if llm_synthesis is not None:
        rationale = (
            f"{ticker} receives a {verdict.value} verdict with a final underwriting "
            f"score of {scores.final_underwriting_score:.1f}/100. "
            f"LLM synthesis summary: {llm_synthesis.underwriting_summary}"
        )
        if relative_performance_context is not None and relative_performance_context.summary:
            rationale = (
                f"{rationale} Benchmark-relative view: "
                f"{relative_performance_context.summary}"
            )
        if screen_override_rationale:
            rationale = f"{rationale} Calibration note: {screen_override_rationale}"
        return rationale

    parts: list[str] = []

    parts.append(
        f"{ticker} receives a {verdict.value} verdict with a final underwriting score of "
        f"{scores.final_underwriting_score:.1f}/100."
    )

    if variant_view.helix_variant_view:
        parts.append(f"Variant view: {variant_view.helix_variant_view}")

    if pressure_inflection_analysis.cyclical_vs_structural_assessment:
        parts.append(
            f"Pressure/inflection assessment: "
            f"{pressure_inflection_analysis.cyclical_vs_structural_assessment}"
        )

    if relative_performance_context is not None and relative_performance_context.summary:
        parts.append(
            f"Benchmark-relative view: {relative_performance_context.summary}"
        )

    if screen_override and screen_override_rationale:
        parts.append(f"Screen override rationale: {screen_override_rationale}")

    return " ".join(parts)


def _apply_llm_synthesis(
    *,
    llm_synthesis: DeepFundamentalLLMSynthesis,
    financial_trend_analysis: FinancialTrendAnalysis,
    pressure_inflection_analysis: PressureInflectionAnalysis,
    competitive_position_analysis: CompetitivePositionAnalysis,
    market_expectation_analysis: MarketExpectationAnalysis,
    variant_view: VariantView,
    falsification_framework: FalsificationFramework,
) -> tuple[
    FinancialTrendAnalysis,
    PressureInflectionAnalysis,
    CompetitivePositionAnalysis,
    MarketExpectationAnalysis,
    VariantView,
    FalsificationFramework,
]:
    financial_trend_analysis = financial_trend_analysis.model_copy(
        update={
            "screen_result_context": _join_text(
                financial_trend_analysis.screen_result_context,
                llm_synthesis.financial_trend_diagnosis,
            ),
            "why_screen_may_be_wrong": (
                llm_synthesis.why_screen_may_be_wrong
                or financial_trend_analysis.why_screen_may_be_wrong
            ),
        }
    )

    pressure_inflection_analysis = pressure_inflection_analysis.model_copy(
        update={
            "cyclical_vs_structural_assessment": llm_synthesis.pressure_inflection_assessment,
            "recent_pressure_points": dedupe_preserve_order(
                pressure_inflection_analysis.recent_pressure_points
                + llm_synthesis.key_risks[:5]
            ),
        }
    )

    competitive_position_analysis = competitive_position_analysis.model_copy(
        update={
            "competitive_position_summary": llm_synthesis.competitive_position_assessment,
        }
    )

    market_expectation_analysis = market_expectation_analysis.model_copy(
        update={
            "narrative_consensus": llm_synthesis.current_market_narrative,
            "expectation_summary": _join_text(
                llm_synthesis.valuation_expectations_assessment,
                llm_synthesis.benchmark_relative_view,
            ),
        }
    )

    variant_view = variant_view.model_copy(
        update=_llm_variant_view_update(
            variant_view=variant_view,
            llm_synthesis=llm_synthesis,
        )
    )

    falsification_framework = falsification_framework.model_copy(
        update={
            "fundamental_falsifiers": dedupe_preserve_order(
                falsification_framework.fundamental_falsifiers
                + llm_synthesis.fundamental_falsifiers,
                max_items=15,
            ),
            "macro_falsifiers": dedupe_preserve_order(
                falsification_framework.macro_falsifiers
                + llm_synthesis.macro_theme_falsifiers,
                max_items=15,
            ),
            "valuation_falsifiers": dedupe_preserve_order(
                falsification_framework.valuation_falsifiers
                + llm_synthesis.valuation_falsifiers,
                max_items=15,
            ),
            "timing_falsifiers": dedupe_preserve_order(
                falsification_framework.timing_falsifiers
                + llm_synthesis.timing_falsifiers,
                max_items=15,
            ),
            "monitoring_triggers": dedupe_preserve_order(
                falsification_framework.monitoring_triggers
                + llm_synthesis.suggested_monitoring_plan,
                max_items=20,
            ),
            "key_metrics_to_watch": dedupe_preserve_order(
                falsification_framework.key_metrics_to_watch
                + llm_synthesis.key_metrics_to_monitor,
                max_items=20,
            ),
        }
    )

    return (
        financial_trend_analysis,
        pressure_inflection_analysis,
        competitive_position_analysis,
        market_expectation_analysis,
        variant_view,
        falsification_framework,
    )


def _join_text(first: str | None, second: str | None) -> str | None:
    if first and second:
        return f"{first} LLM synthesis: {second}"
    return first or second


def _llm_variant_view_update(
    *,
    variant_view: VariantView,
    llm_synthesis: DeepFundamentalLLMSynthesis,
) -> dict[str, Any]:
    direction = llm_synthesis.variant_view_direction
    update: dict[str, Any] = {
        "helix_variant_view": _format_llm_variant_view(llm_synthesis),
        "variant_view_direction": direction,
        "bull_case_variant_view": llm_synthesis.bull_case_variant_view,
        "bear_case_variant_view": llm_synthesis.bear_case_variant_view,
        "variant_view_strength": llm_synthesis.variant_view_strength,
    }

    if direction == VariantViewDirection.BULLISH:
        update["evidence_supporting_variant_view"] = dedupe_preserve_order(
            variant_view.evidence_supporting_variant_view
            + llm_synthesis.evidence_supporting_variant_view,
            max_items=15,
        )
        update["why_market_may_be_wrong"] = dedupe_preserve_order(
            variant_view.why_market_may_be_wrong,
            max_items=12,
        )
        update["risks_to_variant_view"] = dedupe_preserve_order(
            variant_view.risks_to_variant_view
            + llm_synthesis.evidence_against_variant_view
            + llm_synthesis.key_risks,
            max_items=15,
        )
        return update

    if direction == VariantViewDirection.BEARISH:
        update["evidence_supporting_variant_view"] = dedupe_preserve_order(
            _prefix_items("Bear evidence", llm_synthesis.evidence_supporting_variant_view),
            max_items=15,
        )
        update["why_market_may_be_wrong"] = dedupe_preserve_order(
            _prefix_items("Bear view", llm_synthesis.evidence_supporting_variant_view),
            max_items=12,
        )
        update["risks_to_variant_view"] = dedupe_preserve_order(
            _prefix_items("Bull counter-evidence", llm_synthesis.evidence_against_variant_view)
            + _prefix_items("Risk", llm_synthesis.key_risks),
            max_items=15,
        )
        update["required_confirming_evidence"] = dedupe_preserve_order(
            variant_view.required_confirming_evidence,
            max_items=12,
        )
        return update

    if direction == VariantViewDirection.TWO_SIDED:
        update["evidence_supporting_variant_view"] = dedupe_preserve_order(
            _prefix_items("Bull evidence", variant_view.evidence_supporting_variant_view)
            + _prefix_items(
                "Two-sided evidence",
                llm_synthesis.evidence_supporting_variant_view,
            ),
            max_items=15,
        )
        update["why_market_may_be_wrong"] = dedupe_preserve_order(
            _prefix_items("Bull case", variant_view.why_market_may_be_wrong),
            max_items=12,
        )
        update["risks_to_variant_view"] = dedupe_preserve_order(
            _prefix_items(
                "Two-sided counter-evidence",
                llm_synthesis.evidence_against_variant_view,
            )
            + _prefix_items("Bear risk", llm_synthesis.key_risks),
            max_items=15,
        )
        return update

    update["evidence_supporting_variant_view"] = []
    update["why_market_may_be_wrong"] = []
    update["required_confirming_evidence"] = []
    update["risks_to_variant_view"] = dedupe_preserve_order(
        _prefix_items("Data gap", llm_synthesis.data_gaps)
        + _prefix_items("Risk", llm_synthesis.key_risks),
        max_items=15,
    )
    return update


def _format_llm_variant_view(
    llm_synthesis: DeepFundamentalLLMSynthesis,
) -> str:
    parts = [
        f"Variant direction: {llm_synthesis.variant_view_direction.value}.",
    ]
    if llm_synthesis.variant_view:
        parts.append(llm_synthesis.variant_view)
    if (
        llm_synthesis.variant_view_direction == VariantViewDirection.TWO_SIDED
        and llm_synthesis.bull_case_variant_view
    ):
        parts.append(f"Bull case: {llm_synthesis.bull_case_variant_view}")
    if (
        llm_synthesis.variant_view_direction
        in {VariantViewDirection.TWO_SIDED, VariantViewDirection.BEARISH}
        and llm_synthesis.bear_case_variant_view
    ):
        parts.append(f"Bear case: {llm_synthesis.bear_case_variant_view}")
    if (
        llm_synthesis.variant_view_direction == VariantViewDirection.BULLISH
        and llm_synthesis.bull_case_variant_view
    ):
        parts.append(f"Bull case: {llm_synthesis.bull_case_variant_view}")
    if (
        llm_synthesis.variant_view_direction == VariantViewDirection.BEARISH
        and llm_synthesis.bull_case_variant_view
    ):
        parts.append(f"What would prove caution wrong: {llm_synthesis.bull_case_variant_view}")
    return " ".join(parts)


def _prefix_items(prefix: str, items: list[str]) -> list[str]:
    return [f"{prefix}: {item}" for item in items if item and item.strip()]


def _normalize_output_lists(
    *,
    pressure_inflection_analysis: PressureInflectionAnalysis,
    variant_view: VariantView,
    falsification_framework: FalsificationFramework,
) -> tuple[PressureInflectionAnalysis, VariantView, FalsificationFramework]:
    pressure_inflection_analysis = pressure_inflection_analysis.model_copy(
        update={
            "recent_pressure_points": dedupe_preserve_order(
                pressure_inflection_analysis.recent_pressure_points,
                max_items=20,
            ),
            "recent_strength_points": dedupe_preserve_order(
                pressure_inflection_analysis.recent_strength_points,
                max_items=20,
            ),
        }
    )
    variant_view = variant_view.model_copy(
        update={
            "evidence_supporting_variant_view": dedupe_preserve_order(
                variant_view.evidence_supporting_variant_view,
                max_items=15,
            ),
            "why_market_may_be_wrong": dedupe_preserve_order(
                variant_view.why_market_may_be_wrong,
                max_items=12,
            ),
            "required_confirming_evidence": dedupe_preserve_order(
                variant_view.required_confirming_evidence,
                max_items=12,
            ),
            "risks_to_variant_view": dedupe_preserve_order(
                variant_view.risks_to_variant_view,
                max_items=15,
            ),
        }
    )
    falsification_framework = falsification_framework.model_copy(
        update={
            "fundamental_falsifiers": dedupe_preserve_order(
                falsification_framework.fundamental_falsifiers,
                max_items=15,
            ),
            "macro_falsifiers": dedupe_preserve_order(
                falsification_framework.macro_falsifiers,
                max_items=15,
            ),
            "valuation_falsifiers": dedupe_preserve_order(
                falsification_framework.valuation_falsifiers,
                max_items=15,
            ),
            "timing_falsifiers": dedupe_preserve_order(
                falsification_framework.timing_falsifiers,
                max_items=15,
            ),
            "monitoring_triggers": dedupe_preserve_order(
                falsification_framework.monitoring_triggers,
                max_items=20,
            ),
            "key_metrics_to_watch": dedupe_preserve_order(
                falsification_framework.key_metrics_to_watch,
                max_items=20,
            ),
        }
    )
    return pressure_inflection_analysis, variant_view, falsification_framework


def dedupe_preserve_order(
    items: list[str],
    *,
    max_items: int | None = None,
) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        value = item.strip() if isinstance(item, str) else str(item).strip()
        if not value:
            continue
        key = value.lower().rstrip(".!?:;").strip()
        if key in seen:
            continue
        deduped.append(value)
        seen.add(key)
        if max_items is not None and len(deduped) >= max_items:
            break
    return deduped


def _dedupe_list(values: list[str]) -> list[str]:
    return dedupe_preserve_order(values)


def _coerce_theme_context(
    theme_context: ThemeContextPack | dict[str, Any] | None,
) -> ThemeContextPack | None:
    if theme_context is None:
        return None
    if isinstance(theme_context, ThemeContextPack):
        return theme_context
    if isinstance(theme_context, dict):
        try:
            return ThemeContextPack.model_validate(theme_context)
        except Exception:
            return None
    return None


def _context_source_notes(
    context: MacroContextPack | ThemeContextPack | dict[str, Any] | None,
) -> list[str]:
    if context is None:
        return []
    if isinstance(context, (MacroContextPack, ThemeContextPack)):
        return context.source_notes
    if isinstance(context, dict):
        notes = context.get("source_notes")
        if isinstance(notes, list):
            return [str(note) for note in notes]
    return []


def _profile_source_notes(company_profile: CompanyProfile) -> list[str]:
    notes: list[str] = []
    if company_profile.profile_source == "llm_generated_unverified":
        notes.append("Company profile is LLM-generated and not yet filing-verified.")
    elif company_profile.profile_source == "manual_seed":
        notes.append("Company profile from internal static seed.")
    if company_profile.profile_confidence:
        notes.append(f"Company profile confidence: {company_profile.profile_confidence.value}.")
    notes.extend(company_profile.profile_source_notes)
    if company_profile.profile_data_gaps:
        notes.append(
            "Company profile data gaps: "
            + ", ".join(company_profile.profile_data_gaps[:8])
        )
    return dedupe_preserve_order(notes)


def _run_configuration_source_notes(
    run_configuration: DeepFundamentalRunConfiguration | None,
) -> list[str]:
    if run_configuration is None:
        return []
    notes = [
        "Source transparency: "
        f"LLM synthesis={'used' if run_configuration.llm_synthesis_used else 'not used'}"
        f" ({run_configuration.llm_synthesis_status or 'unknown'}); "
        f"LLM profile={'used' if run_configuration.llm_profile_used else 'not used'}; "
        f"research context={'used' if run_configuration.research_context_used else 'not used'}; "
        f"profile source={run_configuration.company_profile_source or 'n/a'}."
    ]
    if run_configuration.llm_synthesis_prompt_chars is not None:
        notes.append(
            "LLM synthesis prompt diagnostics: "
            f"chars={run_configuration.llm_synthesis_prompt_chars}, "
            f"est_tokens={run_configuration.llm_synthesis_prompt_est_tokens}, "
            f"retries={run_configuration.llm_retry_count or 0}."
        )
    if run_configuration.llm_last_error:
        notes.append(
            "LLM synthesis last error: "
            f"{run_configuration.llm_last_error[:240]}."
        )
    if run_configuration.research_context_used:
        mode = "refreshed" if run_configuration.research_context_refreshed else (
            "cached" if run_configuration.research_context_cache_used else "provided"
        )
        notes.append(f"Research context mode: {mode}.")
    if run_configuration.manual_transcript_path_used:
        source = run_configuration.manual_transcript_source or "manual transcript input"
        notes.append(
            "Manual transcript: "
            f"used from {source} {run_configuration.manual_transcript_path_used}."
        )
    elif run_configuration.manual_transcript_source:
        notes.append("Manual transcript: not supplied.")
    if run_configuration.transcript_mapping_warning:
        notes.append(
            "Transcript mapping warning: "
            f"{run_configuration.transcript_mapping_warning}"
        )
    if run_configuration.source_providers_attempted:
        notes.append(
            "Sources attempted: "
            + ", ".join(run_configuration.source_providers_attempted[:10])
        )
    if run_configuration.source_providers_found:
        notes.append(
            "Sources found: "
            + ", ".join(run_configuration.source_providers_found[:10])
        )
    return dedupe_preserve_order(notes)


def _research_context_source_notes(
    research_context: SingleNameResearchContextPack | None,
) -> list[str]:
    if research_context is None:
        return []
    notes: list[str] = []
    if research_context.source_coverage_summary:
        notes.append(
            "Research source coverage: "
            f"{research_context.source_coverage_summary}"
        )
    notes.append(
        f"Research context evidence items: {research_context.evidence_item_count}."
    )
    bucket_counts = {
        "strategic transaction": len(research_context.strategic_transaction_evidence),
        "regulatory capital": len(research_context.regulatory_capital_evidence),
        "stress test": len(research_context.stress_test_evidence),
        "investor presentation": len(research_context.investor_presentation_evidence),
        "other 8-K": len(research_context.other_sec_8k_evidence),
    }
    non_empty_counts = [
        f"{label}={count}"
        for label, count in bucket_counts.items()
        if count
    ]
    if non_empty_counts:
        notes.append(
            "Non-earnings SEC evidence buckets: "
            + ", ".join(non_empty_counts)
        )
    top_non_earnings = (
        research_context.strategic_transaction_evidence
        + research_context.regulatory_capital_evidence
        + research_context.stress_test_evidence
        + research_context.investor_presentation_evidence
        + research_context.other_sec_8k_evidence
    )[:3]
    if top_non_earnings:
        notes.append(
            "Top non-earnings SEC evidence: "
            + " | ".join(item.claim[:180] for item in top_non_earnings)
        )
    if research_context.data_gaps:
        notes.append(
            "Research context data gaps: "
            + "; ".join(research_context.data_gaps[:6])
        )
    return dedupe_preserve_order(notes)


def _build_key_monitoring_items(
    falsification_framework: FalsificationFramework,
    pressure_inflection_analysis: PressureInflectionAnalysis,
) -> list[str]:
    items: list[str] = []

    items.extend(falsification_framework.key_metrics_to_watch[:5])
    items.extend(falsification_framework.monitoring_triggers[:5])
    items.extend(pressure_inflection_analysis.key_timing_questions[:3])

    return dedupe_preserve_order(items)


def _recommended_next_action(
    verdict: DeepFundamentalVerdict,
    *,
    llm_synthesis: DeepFundamentalLLMSynthesis | None = None,
    variant_view: VariantView | None = None,
    scores: DeepFundamentalScores | None = None,
) -> str:
    if verdict == DeepFundamentalVerdict.STRONG_ACCEPT:
        return "Prioritize for deeper validation / trade construction."
    if verdict == DeepFundamentalVerdict.ACCEPT_WITH_CAVEATS:
        return "Advance to evidence validation and trade construction with caveats."
    if verdict == DeepFundamentalVerdict.OVERRIDE_SCREEN_REJECT:
        return "Override basic screen reject and escalate to watchlist or trade construction depending on valuation/timing."
    if verdict == DeepFundamentalVerdict.OVERRIDE_SCREEN_ACCEPT_TO_REJECT:
        return "Reject for now; revisit only if thesis, valuation, or evidence changes materially."
    if verdict == DeepFundamentalVerdict.WATCHLIST:
        base = (
            "Add to watchlist and rerun when price, estimates, macro/theme "
            "context, or company evidence changes."
        )
        reasons: list[str] = []
        if llm_synthesis is not None and llm_synthesis.data_gaps:
            reasons.append(
                "Key missing evidence: " + _sentence_list(llm_synthesis.data_gaps[:3])
            )
        if variant_view is not None and (
            variant_view.variant_view_strength in {"none", "weak"}
            or variant_view.variant_view_direction
            in {VariantViewDirection.TWO_SIDED, VariantViewDirection.NONE}
        ):
            reasons.append("Variant view is not yet strong enough for acceptance.")
        if llm_synthesis is not None and _has_valuation_expectations_risk(llm_synthesis):
            reasons.append("Valuation/expectations risk requires confirmation.")
        if scores is not None and scores.idiosyncratic_risk >= 75:
            reasons.append("Risk score remains elevated enough to require validation.")
        return " ".join([base, *dedupe_preserve_order(reasons)])
    return "Reject for now; revisit only if thesis, valuation, or evidence changes materially."


def _has_valuation_expectations_risk(
    llm_synthesis: DeepFundamentalLLMSynthesis,
) -> bool:
    text = " ".join(
        llm_synthesis.key_risks
        + llm_synthesis.valuation_falsifiers
        + [llm_synthesis.valuation_expectations_assessment]
    ).lower()
    return any(
        keyword in text
        for keyword in (
            "valuation",
            "multiple",
            "expectation",
            "priced in",
            "peak earnings",
            "forward p/e",
            "ev/ebitda",
        )
    )


def _sentence_list(items: list[str]) -> str:
    cleaned = [
        item.strip().rstrip(".")
        for item in items
        if isinstance(item, str) and item.strip()
    ]
    return "; ".join(cleaned) + "." if cleaned else ""
