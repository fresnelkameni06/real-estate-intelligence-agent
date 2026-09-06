"""Build deterministic chart payloads from approved analytical tool results."""

from __future__ import annotations

from pydantic import BaseModel

from real_estate_agent.agent.models import AgentVisualization
from real_estate_agent.analytics.models import ComparisonResult, PriceTrend
from real_estate_agent.tools.models import DpeAnalysisResult


def _area_label(arrondissement: int | None) -> str:
    if arrondissement is None:
        return "Paris entier"
    suffix = "er" if arrondissement == 1 else "e"
    return f"Paris {arrondissement}{suffix}"


def build_tool_visualization(
    tool_name: str,
    result: BaseModel,
) -> AgentVisualization | None:
    """Return a bounded chart payload only for known visualizable result types."""
    if tool_name == "get_market_trend" and isinstance(result, PriceTrend):
        points = [
            point for point in result.points if point.median_price_per_m2 is not None
        ]
        if not points:
            return None
        area = _area_label(result.filters.arrondissement)
        return AgentVisualization(
            visualization_id=f"market-trend-{result.filters.arrondissement or 'paris'}",
            source_tool=tool_name,
            chart_type="line",
            title=f"Évolution du prix médian au m² — {area}",
            x_axis_title="Année",
            y_axis_title="Prix médian (€/m²)",
            labels=[str(point.year) for point in points],
            values=[float(point.median_price_per_m2) for point in points],
        )

    if tool_name == "compare_arrondissements" and isinstance(
        result, ComparisonResult
    ):
        areas = [area for area in result.areas if area.median_price_per_m2 is not None]
        if not areas:
            return None
        return AgentVisualization(
            visualization_id="arrondissement-price-comparison",
            source_tool=tool_name,
            chart_type="bar",
            title="Comparaison des prix médians au m²",
            x_axis_title="Arrondissement",
            y_axis_title="Prix médian (€/m²)",
            labels=[_area_label(area.arrondissement) for area in areas],
            values=[float(area.median_price_per_m2) for area in areas],
        )

    if tool_name == "analyze_dpe" and isinstance(result, DpeAnalysisResult):
        labels = list("ABCDEFG")
        return AgentVisualization(
            visualization_id="dpe-label-distribution",
            source_tool=tool_name,
            chart_type="bar",
            title="Répartition des étiquettes DPE",
            x_axis_title="Classe DPE",
            y_axis_title="Part des diagnostics (%)",
            labels=labels,
            values=[float(result.distribution.percentages.get(label, 0)) for label in labels],
        )

    return None
