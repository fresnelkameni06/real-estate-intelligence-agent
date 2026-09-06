"""Tests for deterministic chart payloads derived from approved Agent tools."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from real_estate_agent.agent import AgentVisualization
from real_estate_agent.agent.visualizations import build_tool_visualization
from real_estate_agent.analytics.models import (
    AppliedFilters,
    AreaMarketMetrics,
    ComparisonResult,
    DpeDistribution,
    DpeIntensitySummary,
    PriceTrend,
    YearPricePoint,
)
from real_estate_agent.tools.models import DpeAnalysisResult


def _filters(arrondissement: int | None = None) -> AppliedFilters:
    return AppliedFilters(
        arrondissement=arrondissement,
        start_year=2021,
        end_year=2025,
        price_per_m2_min=1_000,
        price_per_m2_max=50_000,
        eligibility_policy="test policy",
    )


def test_market_trend_becomes_line_chart_and_ignores_missing_values():
    result = PriceTrend(
        points=[
            YearPricePoint(
                year=2021,
                transaction_count=100,
                market_analysis_count=90,
                median_price_per_m2=10_000,
                price_p25=8_000,
                price_p75=12_000,
                yoy_median_change_pct=None,
            ),
            YearPricePoint(
                year=2022,
                transaction_count=0,
                market_analysis_count=0,
                median_price_per_m2=None,
                price_p25=None,
                price_p75=None,
                yoy_median_change_pct=None,
            ),
            YearPricePoint(
                year=2023,
                transaction_count=80,
                market_analysis_count=75,
                median_price_per_m2=9_500,
                price_p25=7_800,
                price_p75=11_500,
                yoy_median_change_pct=-5,
            ),
        ],
        filters=_filters(6),
    )

    chart = build_tool_visualization("get_market_trend", result)

    assert chart is not None
    assert chart.chart_type == "line"
    assert chart.source_tool == "get_market_trend"
    assert chart.labels == ["2021", "2023"]
    assert chart.values == [10_000, 9_500]
    assert "Paris 6e" in chart.title


def test_area_comparison_becomes_price_bar_chart():
    result = ComparisonResult(
        areas=[
            AreaMarketMetrics(
                arrondissement=1,
                total_residential_transactions=100,
                market_analysis_transactions=90,
                median_price_per_m2=12_500,
                price_p25=10_000,
                price_p75=15_000,
                median_residential_surface=45,
            ),
            AreaMarketMetrics(
                arrondissement=20,
                total_residential_transactions=200,
                market_analysis_transactions=180,
                median_price_per_m2=8_900,
                price_p25=7_500,
                price_p75=10_000,
                median_residential_surface=40,
            ),
        ],
        filters=_filters(),
    )

    chart = build_tool_visualization("compare_arrondissements", result)

    assert chart is not None
    assert chart.chart_type == "bar"
    assert chart.labels == ["Paris 1er", "Paris 20e"]
    assert chart.values == [12_500, 8_900]


def test_dpe_analysis_becomes_ordered_ag_bar_chart():
    distribution = DpeDistribution(
        eligible_dpe_count=100,
        counts={label: 1 for label in "ABCDEFG"},
        percentages={
            "A": 1,
            "B": 2,
            "C": 12,
            "D": 30,
            "E": 29,
            "F": 15,
            "G": 11,
        },
        f_count=15,
        g_count=11,
        fg_count=26,
        fg_percentage=26,
        start_year=2021,
        end_year=2025,
        includes_partial_year=False,
    )
    intensity = DpeIntensitySummary(
        eligible_intensity_count=90,
        median_consumption=250,
        consumption_p25=180,
        consumption_p75=340,
        median_emissions=20,
        emissions_p25=10,
        emissions_p75=35,
        median_surface=42,
        start_year=2021,
        end_year=2025,
        includes_partial_year=False,
    )

    chart = build_tool_visualization(
        "analyze_dpe",
        DpeAnalysisResult(distribution=distribution, intensity=intensity),
    )

    assert chart is not None
    assert chart.labels == list("ABCDEFG")
    assert chart.values == [1, 2, 12, 30, 29, 15, 11]


def test_unknown_or_non_visual_result_has_no_chart():
    class OtherResult(BaseModel):
        value: int

    assert build_tool_visualization("get_market_overview", OtherResult(value=1)) is None


def test_chart_contract_rejects_misaligned_data():
    with pytest.raises(ValidationError, match="same length"):
        AgentVisualization(
            visualization_id="bad-chart",
            source_tool="test",
            chart_type="bar",
            title="Bad chart",
            x_axis_title="X",
            y_axis_title="Y",
            labels=["A", "B"],
            values=[1],
        )
