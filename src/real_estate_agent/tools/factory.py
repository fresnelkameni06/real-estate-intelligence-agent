"""Compose the approved tool registry from existing deterministic services."""

from __future__ import annotations

from sqlalchemy import Engine

from real_estate_agent.analytics import service
from real_estate_agent.analytics.models import (
    AreaRankings,
    ComparisonResult,
    MarketOverview,
    PriceTrend,
)
from real_estate_agent.rag.generation.models import RagAnswerResult
from real_estate_agent.rag.generation.service import RagAnswerService
from real_estate_agent.tools.models import (
    AreaComparisonInput,
    DocumentaryQuestionInput,
    DpeAnalysisInput,
    DpeAnalysisResult,
    MarketScopeInput,
    PeriodInput,
)
from real_estate_agent.tools.registry import ToolDefinition, ToolRegistry


def build_tool_registry(engine: Engine, rag_service: RagAnswerService) -> ToolRegistry:
    """Build the six tools that are reliable enough for later orchestration."""

    def market_overview(arguments: MarketScopeInput) -> MarketOverview:
        return service.get_market_overview(
            engine,
            arguments.arrondissement,
            arguments.start_year,
            arguments.end_year,
        )

    def market_trend(arguments: MarketScopeInput) -> PriceTrend:
        return service.get_price_trend(
            engine,
            arguments.arrondissement,
            arguments.start_year,
            arguments.end_year,
        )

    def area_rankings(arguments: PeriodInput) -> AreaRankings:
        return service.get_area_rankings(
            engine,
            arguments.start_year,
            arguments.end_year,
        )

    def compare_areas(arguments: AreaComparisonInput) -> ComparisonResult:
        return service.compare_arrondissements(
            engine,
            arguments.arrondissements,
            arguments.start_year,
            arguments.end_year,
        )

    def analyze_dpe(arguments: DpeAnalysisInput) -> DpeAnalysisResult:
        distribution = service.get_dpe_distribution(
            engine,
            arguments.arrondissement,
            arguments.start_year,
            arguments.end_year,
        )
        intensity = service.get_dpe_intensity_summary(
            engine,
            arguments.arrondissement,
            arguments.start_year,
            arguments.end_year,
        )
        return DpeAnalysisResult(distribution=distribution, intensity=intensity)

    def answer_documentary_question(
        arguments: DocumentaryQuestionInput,
    ) -> RagAnswerResult:
        return rag_service.answer(arguments.question, style=arguments.style)

    return ToolRegistry(
        [
            ToolDefinition(
                name="get_market_overview",
                description=(
                    "Return one period-wide aggregate market overview for Paris or "
                    "one arrondissement: median price, transaction volume and median "
                    "surface. Use this for a single summary value over a date range, "
                    "not for year-by-year evolution."
                ),
                input_model=MarketScopeInput,
                handler=market_overview,
            ),
            ToolDefinition(
                name="get_market_trend",
                description=(
                    "Return annual median price per square metre and year-over-year "
                    "changes for Paris or one arrondissement. Use only when the user "
                    "asks for evolution, variation, a trend or year-by-year values; "
                    "not for one aggregate median over the whole period."
                ),
                input_model=MarketScopeInput,
                handler=market_trend,
            ),
            ToolDefinition(
                name="rank_arrondissements",
                description=(
                    "Rank Paris arrondissements by median price, transaction volume "
                    "and median surface with minimum-sample safeguards."
                ),
                input_model=PeriodInput,
                handler=area_rankings,
            ),
            ToolDefinition(
                name="compare_arrondissements",
                description=(
                    "Compare two to five distinct Paris arrondissements using the "
                    "same deterministic market rules and period."
                ),
                input_model=AreaComparisonInput,
                handler=compare_areas,
            ),
            ToolDefinition(
                name="analyze_dpe",
                description=(
                    "Return aggregate DPE label distribution, energy consumption and "
                    "emissions for Paris or one arrondissement. Use this tool alone "
                    "for DPE-only questions, even when an arrondissement and period "
                    "are specified. Add a market tool only when the user explicitly "
                    "asks for DVF prices, transactions or market evolution."
                ),
                input_model=DpeAnalysisInput,
                handler=analyze_dpe,
            ),
            ToolDefinition(
                name="answer_documentary_question",
                description=(
                    "Answer a DPE, energy-regulation or DVF-methodology question from "
                    "indexed official documents with citations."
                ),
                input_model=DocumentaryQuestionInput,
                handler=answer_documentary_question,
            ),
        ]
    )
