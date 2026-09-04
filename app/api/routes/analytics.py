"""Versioned aggregate-only real-estate analytics endpoints."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy import Engine

from app.api.dependencies import get_database_engine
from real_estate_agent.analytics import policy, service
from real_estate_agent.analytics.models import (
    AreaProfile,
    AreaRankings,
    ComparisonResult,
    DpeDistribution,
    DpeIntensitySummary,
    MarketOverview,
    PriceTrend,
)

router = APIRouter()

EngineDependency = Annotated[Engine, Depends(get_database_engine)]
OptionalArea = Annotated[
    int | None,
    Query(ge=policy.MIN_ARRONDISSEMENT, le=policy.MAX_ARRONDISSEMENT),
]
StartYear = Annotated[
    int,
    Query(ge=policy.MIN_VALID_YEAR, le=policy.MAX_VALID_YEAR),
]
EndYear = Annotated[
    int,
    Query(ge=policy.MIN_VALID_YEAR, le=policy.MAX_VALID_YEAR),
]
ComparisonAreas = Annotated[
    list[int],
    Query(
        min_length=policy.MIN_COMPARE_AREAS,
        max_length=policy.MAX_COMPARE_AREAS,
        description="Repeat the parameter for each arrondissement.",
    ),
]
DpeScope = Literal["dwelling_unit"]


@router.get(
    "/market/overview",
    response_model=MarketOverview,
    tags=["market"],
    summary="Get aggregate market indicators",
)
def market_overview(
    engine: EngineDependency,
    arrondissement: OptionalArea = None,
    start_year: StartYear = policy.DEFAULT_START_YEAR,
    end_year: EndYear = policy.DEFAULT_END_YEAR,
) -> MarketOverview:
    """Return deterministic DVF market indicators for Paris or one area."""
    return service.get_market_overview(engine, arrondissement, start_year, end_year)


@router.get(
    "/market/trends",
    response_model=PriceTrend,
    tags=["market"],
    summary="Get the annual price trend",
)
def market_trends(
    engine: EngineDependency,
    arrondissement: OptionalArea = None,
    start_year: StartYear = policy.DEFAULT_START_YEAR,
    end_year: EndYear = policy.DEFAULT_END_YEAR,
) -> PriceTrend:
    """Return yearly median price/m², quartiles and YoY changes."""
    return service.get_price_trend(engine, arrondissement, start_year, end_year)


@router.get(
    "/market/compare",
    response_model=ComparisonResult,
    tags=["market"],
    summary="Compare Paris arrondissements",
)
def market_compare(
    engine: EngineDependency,
    arrondissements: ComparisonAreas,
    start_year: StartYear = policy.DEFAULT_START_YEAR,
    end_year: EndYear = policy.DEFAULT_END_YEAR,
) -> ComparisonResult:
    """Compare two to twenty arrondissements using identical analytical rules."""
    return service.compare_arrondissements(
        engine, arrondissements, start_year, end_year
    )


@router.get(
    "/market/rankings",
    response_model=AreaRankings,
    tags=["market"],
    summary="Rank Paris arrondissements",
)
def market_rankings(
    engine: EngineDependency,
    start_year: StartYear = policy.DEFAULT_START_YEAR,
    end_year: EndYear = policy.DEFAULT_END_YEAR,
) -> AreaRankings:
    """Rank areas by price, transaction volume and median surface."""
    return service.get_area_rankings(engine, start_year, end_year)


@router.get(
    "/dpe/distribution",
    response_model=DpeDistribution,
    tags=["energy"],
    summary="Get the DPE label distribution",
)
def dpe_distribution(
    engine: EngineDependency,
    arrondissement: OptionalArea = None,
    start_year: StartYear = policy.DEFAULT_START_YEAR,
    end_year: EndYear = policy.DEFAULT_END_YEAR,
    scope: Annotated[DpeScope, Query()] = "dwelling_unit",
) -> DpeDistribution:
    """Return aggregate A–G labels for eligible dwelling-unit diagnostics."""
    del scope  # The literal parameter documents and enforces the supported scope.
    return service.get_dpe_distribution(engine, arrondissement, start_year, end_year)


@router.get(
    "/dpe/intensity",
    response_model=DpeIntensitySummary,
    tags=["energy"],
    summary="Get aggregate DPE intensity indicators",
)
def dpe_intensity(
    engine: EngineDependency,
    arrondissement: OptionalArea = None,
    start_year: StartYear = policy.DEFAULT_START_YEAR,
    end_year: EndYear = policy.DEFAULT_END_YEAR,
    scope: Annotated[DpeScope, Query()] = "dwelling_unit",
) -> DpeIntensitySummary:
    """Return consumption, emissions and surface medians/quartiles."""
    del scope
    return service.get_dpe_intensity_summary(
        engine, arrondissement, start_year, end_year
    )


@router.get(
    "/areas/{arrondissement}/profile",
    response_model=AreaProfile,
    tags=["areas"],
    summary="Get a combined aggregate area profile",
)
def area_profile(
    engine: EngineDependency,
    arrondissement: Annotated[
        int,
        Path(ge=policy.MIN_ARRONDISSEMENT, le=policy.MAX_ARRONDISSEMENT),
    ],
    start_year: StartYear = policy.DEFAULT_START_YEAR,
    end_year: EndYear = policy.DEFAULT_END_YEAR,
) -> AreaProfile:
    """Combine independent DVF and DPE aggregates without a record-level join."""
    return service.get_area_profile(engine, arrondissement, start_year, end_year)
