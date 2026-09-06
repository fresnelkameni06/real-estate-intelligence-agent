"""Load, select and execute Agent evaluation cases."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol

from real_estate_agent.agent.models import AgentAnswerResult, ConversationMessage
from real_estate_agent.evaluation.models import (
    AgentEvaluationCase,
    AgentEvaluationResult,
    AgentEvaluationSuite,
    AgentEvaluationSummary,
    EvaluationCategory,
)
from real_estate_agent.evaluation.scoring import (
    failed_execution_result,
    score_agent_answer,
    summarize_results,
)


class AgentAnswerer(Protocol):
    """Minimal service boundary required by the evaluator."""

    def answer(
        self,
        question: str,
        *,
        history: Sequence[ConversationMessage] = (),
    ) -> AgentAnswerResult: ...


def load_evaluation_suite(path: Path) -> AgentEvaluationSuite:
    """Read and validate one versioned JSON suite."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Unable to read evaluation suite: {path}") from exc
    return AgentEvaluationSuite.model_validate(payload)


def select_cases(
    suite: AgentEvaluationSuite,
    *,
    case_ids: Sequence[str] = (),
    category: EvaluationCategory | None = None,
    max_cases: int | None = None,
) -> list[AgentEvaluationCase]:
    """Select cases predictably without changing their declared order."""
    requested_ids = set(case_ids)
    known_ids = {case.case_id for case in suite.cases}
    unknown_ids = sorted(requested_ids - known_ids)
    if unknown_ids:
        raise ValueError("Unknown evaluation case(s): " + ", ".join(unknown_ids))
    if max_cases is not None and max_cases < 1:
        raise ValueError("max_cases must be greater than zero")

    selected = [
        case
        for case in suite.cases
        if (not requested_ids or case.case_id in requested_ids)
        and (category is None or case.category == category)
    ]
    if max_cases is not None:
        selected = selected[:max_cases]
    if not selected:
        raise ValueError("No evaluation cases match the requested filters.")
    return selected


def run_evaluation(
    service: AgentAnswerer,
    suite: AgentEvaluationSuite,
    cases: Sequence[AgentEvaluationCase],
    *,
    on_result: Callable[[AgentEvaluationResult], None] | None = None,
) -> AgentEvaluationSummary:
    """Run selected cases independently and continue after controlled failures."""
    results = []
    for case in cases:
        started = time.perf_counter()
        try:
            answer = service.answer(case.question, history=case.history)
            latency_ms = (time.perf_counter() - started) * 1_000
            result = score_agent_answer(case, answer, latency_ms=latency_ms)
        except Exception as exc:  # each live case must remain isolated
            latency_ms = (time.perf_counter() - started) * 1_000
            result = failed_execution_result(
                case,
                latency_ms=latency_ms,
                error_type=type(exc).__name__,
            )
        results.append(result)
        if on_result is not None:
            on_result(result)
    return summarize_results(suite.suite_name, suite.version, results)
