"""Contract tests for the allow-listed, provider-neutral AI tools."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from real_estate_agent.analytics.models import (
    AppliedFilters,
    DpeDistribution,
    DpeIntensitySummary,
    MarketOverview,
)
from real_estate_agent.rag.generation.models import RagAnswerResult
from real_estate_agent.tools import ToolNotFoundError, build_tool_registry


class FakeRagService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def answer(self, question: str, *, style: str) -> RagAnswerResult:
        self.calls.append((question, style))
        return RagAnswerResult(
            question=question,
            answer="Réponse documentaire test.",
            citations=[],
            retrieved_chunks=1,
            top_similarity=0.8,
            model="test-model",
            requested_style=style,
            grounded=True,
            insufficient_context=False,
        )


def _filters(arrondissement: int | None = None) -> AppliedFilters:
    return AppliedFilters(
        arrondissement=arrondissement,
        start_year=2021,
        end_year=2025,
        price_per_m2_min=1000,
        price_per_m2_max=50000,
        eligibility_policy="test",
    )


def _overview(arrondissement: int | None = None) -> MarketOverview:
    return MarketOverview(
        total_residential_transactions=100,
        price_eligible_transactions=95,
        market_analysis_transactions=90,
        excluded_outlier_count=5,
        median_price_per_m2=10_000,
        raw_eligible_median_price_per_m2=10_100,
        sensitivity_median_difference=-100,
        median_residential_surface=42,
        price_p25=8_500,
        price_p75=12_000,
        filters=_filters(arrondissement),
    )


def _distribution() -> DpeDistribution:
    return DpeDistribution(
        eligible_dpe_count=100,
        counts={"A": 1, "B": 2, "C": 20, "D": 30, "E": 27, "F": 12, "G": 8},
        percentages={
            "A": 1,
            "B": 2,
            "C": 20,
            "D": 30,
            "E": 27,
            "F": 12,
            "G": 8,
        },
        f_count=12,
        g_count=8,
        fg_count=20,
        fg_percentage=20,
        start_year=2021,
        end_year=2025,
        includes_partial_year=False,
    )


def _intensity() -> DpeIntensitySummary:
    return DpeIntensitySummary(
        eligible_intensity_count=90,
        median_consumption=250,
        consumption_p25=180,
        consumption_p75=330,
        median_emissions=20,
        emissions_p25=10,
        emissions_p75=35,
        median_surface=45,
        start_year=2021,
        end_year=2025,
        includes_partial_year=False,
    )


def _registry(rag_service: FakeRagService | None = None):
    return build_tool_registry(object(), rag_service or FakeRagService())  # type: ignore[arg-type]


def test_registry_exposes_exact_approved_allow_list():
    registry = _registry()
    assert registry.names == (
        "get_market_overview",
        "get_market_trend",
        "rank_arrondissements",
        "compare_arrondissements",
        "analyze_dpe",
        "answer_documentary_question",
    )


def test_specs_expose_strict_pydantic_json_schemas():
    specifications = _registry().specifications()
    assert len(specifications) == 6
    comparison = next(
        spec for spec in specifications if spec.name == "compare_arrondissements"
    )
    assert comparison.input_schema["additionalProperties"] is False
    assert comparison.input_schema["properties"]["arrondissements"]["minItems"] == 2


def test_market_tool_descriptions_distinguish_aggregate_from_trend():
    specifications = {
        specification.name: specification
        for specification in _registry().specifications()
    }
    overview = specifications["get_market_overview"].description
    trend = specifications["get_market_trend"].description
    assert "single summary value" in overview
    assert "not for year-by-year" in overview
    assert "evolution" in trend
    assert "not for one aggregate median" in trend


def test_dpe_description_prevents_implicit_market_tool_calls():
    specifications = {
        specification.name: specification
        for specification in _registry().specifications()
    }
    description = specifications["analyze_dpe"].description
    assert "Use this tool alone" in description
    assert "explicitly asks for DVF" in description


def test_market_tool_validates_then_calls_existing_service(
    monkeypatch: pytest.MonkeyPatch,
):
    calls: list[tuple[Any, int | None, int, int]] = []

    def fake_overview(engine, arrondissement, start_year, end_year):
        calls.append((engine, arrondissement, start_year, end_year))
        return _overview(arrondissement)

    monkeypatch.setattr(
        "real_estate_agent.tools.factory.service.get_market_overview",
        fake_overview,
    )
    registry = _registry()
    result = registry.execute_json(
        "get_market_overview",
        {"arrondissement": 13, "start_year": 2021, "end_year": 2025},
    )
    assert result["median_price_per_m2"] == 10_000
    assert calls[0][1:] == (13, 2021, 2025)


def test_dpe_tool_composes_two_independent_aggregate_results(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "real_estate_agent.tools.factory.service.get_dpe_distribution",
        lambda *_args: _distribution(),
    )
    monkeypatch.setattr(
        "real_estate_agent.tools.factory.service.get_dpe_intensity_summary",
        lambda *_args: _intensity(),
    )
    result = _registry().execute_json(
        "analyze_dpe",
        {"arrondissement": 1, "start_year": 2021, "end_year": 2025},
    )
    assert result["distribution"]["fg_percentage"] == 20
    assert result["intensity"]["median_consumption"] == 250


def test_documentary_tool_delegates_to_grounded_rag():
    rag_service = FakeRagService()
    result = _registry(rag_service).execute_json(
        "answer_documentary_question",
        {"question": "  Un DPE est valable combien de temps ?  ", "style": "brief"},
    )
    assert result["grounded"] is True
    assert rag_service.calls == [("Un DPE est valable combien de temps ?", "brief")]


@pytest.mark.parametrize(
    ("tool_name", "payload"),
    [
        ("get_market_overview", {"arrondissement": 21}),
        ("get_market_trend", {"start_year": 2025, "end_year": 2021}),
        ("rank_arrondissements", {"unexpected": True}),
        ("compare_arrondissements", {"arrondissements": [13, 13]}),
        ("compare_arrondissements", {"arrondissements": [1]}),
        ("answer_documentary_question", {"question": "   "}),
    ],
)
def test_invalid_tool_arguments_are_rejected_before_execution(
    tool_name: str,
    payload: dict[str, Any],
):
    with pytest.raises(ValidationError):
        _registry().execute(tool_name, payload)


def test_unknown_tool_is_blocked():
    with pytest.raises(ToolNotFoundError, match="unauthorized"):
        _registry().execute("execute_sql", {"query": "DROP TABLE anything"})
