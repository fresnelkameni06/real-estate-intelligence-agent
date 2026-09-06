"""Deterministic structural scoring for Agent answers."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence

from real_estate_agent.agent.models import AgentAnswerResult
from real_estate_agent.evaluation.models import (
    AgentEvaluationCase,
    AgentEvaluationResult,
    AgentEvaluationSummary,
)


def _normalize_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    without_accents = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return " ".join(re.sub(r"[^a-z0-9]+", " ", without_accents).split())


def score_agent_answer(
    case: AgentEvaluationCase,
    answer: AgentAnswerResult,
    *,
    latency_ms: float,
) -> AgentEvaluationResult:
    """Compare observable Agent behavior with one case's expectations."""
    successful_tools = [item.name for item in answer.tool_executions if item.success]
    failed_tools = [item.name for item in answer.tool_executions if not item.success]
    successful_set = set(successful_tools)
    missing_required = sorted(set(case.required_tools) - successful_set)
    unexpected = sorted(successful_set - set(case.allowed_tools))
    visualization_tools = [item.source_tool for item in answer.visualizations]

    route_correct = answer.route == case.expected_route
    tool_selection_correct = not missing_required and not unexpected and not failed_tools
    citations_correct = bool(answer.citations) == case.citations_required
    visualizations_correct = set(case.expected_visualization_tools).issubset(
        visualization_tools
    )
    memory_correct = answer.conversation_memory_used == case.memory_expected
    model_correct = case.expected_model is None or answer.model == case.expected_model
    normalized_answer = _normalize_text(answer.answer)
    missing_answer_terms = [
        term
        for term in case.required_answer_terms
        if _normalize_text(term) not in normalized_answer
    ]
    answer_terms_correct = not missing_answer_terms
    answer_present = bool(answer.answer.strip())

    failures: list[str] = []
    if not route_correct:
        failures.append(
            f"route: expected {case.expected_route}, received {answer.route}"
        )
    if missing_required:
        failures.append("missing tools: " + ", ".join(missing_required))
    if unexpected:
        failures.append("unexpected tools: " + ", ".join(unexpected))
    if failed_tools:
        failures.append("failed tools: " + ", ".join(failed_tools))
    if not citations_correct:
        expectation = "required" if case.citations_required else "not expected"
        failures.append(f"citations: {expectation}")
    if not visualizations_correct:
        missing_charts = sorted(
            set(case.expected_visualization_tools) - set(visualization_tools)
        )
        failures.append("missing visualizations: " + ", ".join(missing_charts))
    if not memory_correct:
        failures.append(
            "memory flag: expected "
            f"{case.memory_expected}, received {answer.conversation_memory_used}"
        )
    if not model_correct:
        failures.append(
            f"model: expected {case.expected_model}, received {answer.model}"
        )
    if missing_answer_terms:
        failures.append("missing answer terms: " + ", ".join(missing_answer_terms))
    if not answer_present:
        failures.append("empty answer")

    return AgentEvaluationResult(
        case_id=case.case_id,
        category=case.category,
        passed=not failures,
        actual_route=answer.route,
        actual_model=answer.model,
        successful_tools=successful_tools,
        failed_tools=failed_tools,
        missing_required_tools=missing_required,
        unexpected_tools=unexpected,
        visualization_tools=visualization_tools,
        route_correct=route_correct,
        tool_selection_correct=tool_selection_correct,
        citations_correct=citations_correct,
        visualizations_correct=visualizations_correct,
        memory_correct=memory_correct,
        model_correct=model_correct,
        answer_terms_correct=answer_terms_correct,
        answer_present=answer_present,
        latency_ms=latency_ms,
        failures=failures,
    )


def failed_execution_result(
    case: AgentEvaluationCase,
    *,
    latency_ms: float,
    error_type: str,
) -> AgentEvaluationResult:
    """Represent a controlled runtime failure without exposing exception details."""
    return AgentEvaluationResult(
        case_id=case.case_id,
        category=case.category,
        passed=False,
        latency_ms=latency_ms,
        failures=[f"execution error: {error_type}"],
    )


def _accuracy(results: Sequence[AgentEvaluationResult], attribute: str) -> float:
    return round(
        sum(bool(getattr(result, attribute)) for result in results) / len(results),
        4,
    )


def summarize_results(
    suite_name: str,
    suite_version: str,
    results: Sequence[AgentEvaluationResult],
) -> AgentEvaluationSummary:
    """Aggregate case-level signals into stable evaluation metrics."""
    if not results:
        raise ValueError("At least one evaluation result is required.")
    items = list(results)
    passed = sum(result.passed for result in items)
    return AgentEvaluationSummary(
        suite_name=suite_name,
        suite_version=suite_version,
        evaluated_cases=len(items),
        passed_cases=passed,
        pass_rate=round(passed / len(items), 4),
        route_accuracy=_accuracy(items, "route_correct"),
        tool_selection_accuracy=_accuracy(items, "tool_selection_correct"),
        citation_accuracy=_accuracy(items, "citations_correct"),
        visualization_accuracy=_accuracy(items, "visualizations_correct"),
        memory_accuracy=_accuracy(items, "memory_correct"),
        model_policy_accuracy=_accuracy(items, "model_correct"),
        answer_constraint_accuracy=_accuracy(items, "answer_terms_correct"),
        average_latency_ms=round(
            sum(result.latency_ms for result in items) / len(items), 2
        ),
        results=items,
    )
