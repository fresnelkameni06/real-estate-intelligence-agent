"""Tests for deterministic narrowing of tools exposed to the Agent model."""

from __future__ import annotations

from real_estate_agent.agent.tool_policy import (
    allowed_tool_names_for_question,
    filter_tool_specifications,
)
from real_estate_agent.tools import ToolSpecification


def _specification(name: str) -> ToolSpecification:
    return ToolSpecification(
        name=name,
        description=name,
        input_schema={"type": "object", "properties": {}},
    )


def test_dpe_statistics_expose_only_dpe_analysis():
    question = (
        "Analyse la répartition des classes DPE dans le 15e arrondissement "
        "entre 2021 et 2025."
    )
    assert allowed_tool_names_for_question(question) == frozenset({"analyze_dpe"})
    filtered = filter_tool_specifications(
        [_specification("get_market_overview"), _specification("analyze_dpe")],
        question,
    )
    assert [item.name for item in filtered] == ["analyze_dpe"]


def test_dpe_accents_and_energy_intensity_are_normalized():
    assert allowed_tool_names_for_question(
        "Quelle est la consommation et la classe énergétique dans le 12e ?"
    ) == frozenset({"analyze_dpe"})


def test_combined_dvf_and_dpe_request_keeps_full_agent_choice():
    assert (
        allowed_tool_names_for_question(
            "Compare l'évolution des prix DVF et la répartition DPE dans le 6e."
        )
        is None
    )


def test_dpe_regulatory_question_keeps_documentary_tool_available():
    assert (
        allowed_tool_names_for_question(
            "Quelles restrictions de location concernent les classes DPE G ?"
        )
        is None
    )
