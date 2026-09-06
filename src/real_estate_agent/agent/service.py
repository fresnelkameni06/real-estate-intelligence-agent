"""Bounded model-tool loop with short conversational memory and audit metadata."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any

from pydantic import ValidationError

from real_estate_agent.agent.models import (
    AgentAnswerResult,
    AgentRoute,
    ConversationMessage,
    ToolExecutionSummary,
)
from real_estate_agent.agent.prompts import AGENT_SYSTEM_INSTRUCTIONS
from real_estate_agent.agent.provider import AgentModel
from real_estate_agent.agent.tool_policy import filter_tool_specifications
from real_estate_agent.agent.visualizations import build_tool_visualization
from real_estate_agent.conversation import local_conversation_reply
from real_estate_agent.rag.generation.models import AnswerCitation, RagAnswerResult
from real_estate_agent.tools import ToolNotFoundError, ToolRegistry


class AgentOrchestrationError(RuntimeError):
    """Raised when a bounded agent run cannot safely produce a final answer."""


_MARKET_TOOLS = {
    "get_market_overview",
    "get_market_trend",
    "rank_arrondissements",
    "compare_arrondissements",
}
_DPE_TOOLS = {"analyze_dpe"}
_DOCUMENTARY_TOOLS = {"answer_documentary_question"}
_MAX_TOOL_CALLS_PER_ROUND = 6


def _route_for(tool_names: set[str]) -> AgentRoute:
    categories = 0
    categories += bool(tool_names & _MARKET_TOOLS)
    categories += bool(tool_names & _DPE_TOOLS)
    categories += bool(tool_names & _DOCUMENTARY_TOOLS)
    if categories > 1:
        return "combined"
    if tool_names & _MARKET_TOOLS:
        return "market"
    if tool_names & _DPE_TOOLS:
        return "dpe"
    if tool_names & _DOCUMENTARY_TOOLS:
        return "documentary"
    return "conversation"


def _referenced_citations(
    answer: str,
    citations: Sequence[AnswerCitation],
) -> list[AnswerCitation]:
    referenced_ids = set(re.findall(r"\[(S\d+)\]", answer))
    unique: dict[tuple[str, str], AnswerCitation] = {}
    for citation in citations:
        if citation.citation_id in referenced_ids:
            unique[(citation.citation_id, citation.chunk_id)] = citation
    return list(unique.values())


class AgentService:
    """Let the model select allow-listed tools within explicit local limits."""

    def __init__(
        self,
        *,
        model: AgentModel,
        registry: ToolRegistry,
        max_tool_rounds: int = 4,
        max_history_messages: int = 12,
        max_output_tokens: int = 1600,
    ) -> None:
        if not 1 <= max_tool_rounds <= 6:
            raise ValueError("max_tool_rounds must be between 1 and 6")
        if not 2 <= max_history_messages <= 20:
            raise ValueError("max_history_messages must be between 2 and 20")
        if max_output_tokens < 200:
            raise ValueError("max_output_tokens must be at least 200")
        self._model = model
        self._registry = registry
        self._max_tool_rounds = max_tool_rounds
        self._max_history_messages = max_history_messages
        self._max_output_tokens = max_output_tokens

    @staticmethod
    def _validate_question(question: str) -> str:
        value = question.strip()
        if not value:
            raise ValueError("The question must not be blank.")
        if len(value) > 2_000:
            raise ValueError("The question must contain at most 2000 characters.")
        return value

    def _initial_input(
        self,
        question: str,
        history: Sequence[ConversationMessage],
    ) -> list[dict[str, Any]]:
        bounded_history = list(history)[-self._max_history_messages :]
        items = [
            {"role": message.role, "content": message.content}
            for message in bounded_history
        ]
        items.append({"role": "user", "content": question})
        return items

    @staticmethod
    def _safe_tool_error(call_id: str, code: str) -> dict[str, Any]:
        return {
            "type": "function_call_output",
            "call_id": call_id,
            "output": json.dumps(
                {
                    "error": {
                        "code": code,
                        "message": "The requested tool could not complete safely.",
                    }
                }
            ),
        }

    def answer(
        self,
        question: str,
        *,
        history: Sequence[ConversationMessage] = (),
    ) -> AgentAnswerResult:
        """Answer one turn and execute only model-selected allow-listed tools."""
        validated_question = self._validate_question(question)
        local_reply = local_conversation_reply(
            validated_question,
            history=[
                message.content for message in history if message.role == "user"
            ],
        )
        if local_reply is not None:
            return AgentAnswerResult(
                question=validated_question,
                answer=local_reply,
                route="conversation",
                model="local-conversation-router",
                conversation_memory_used=bool(history),
                orchestration_rounds=0,
            )

        input_items = self._initial_input(validated_question, history)
        specifications = filter_tool_specifications(
            self._registry.specifications(),
            validated_question,
        )
        execution_summaries: list[ToolExecutionSummary] = []
        visualizations = []
        collected_citations: list[AnswerCitation] = []
        used_tools: set[str] = set()
        seen_calls: set[str] = set()

        for round_number in range(1, self._max_tool_rounds + 2):
            turn = self._model.respond(
                instructions=AGENT_SYSTEM_INSTRUCTIONS,
                input_items=input_items,
                tools=specifications,
                max_output_tokens=self._max_output_tokens,
            )
            if not turn.tool_calls:
                answer = turn.output_text.strip()
                if not answer:
                    raise AgentOrchestrationError("The agent returned an empty answer.")
                return AgentAnswerResult(
                    question=validated_question,
                    answer=answer,
                    route=_route_for(used_tools),
                    tool_executions=execution_summaries,
                    visualizations=visualizations,
                    citations=_referenced_citations(answer, collected_citations),
                    model=self._model.model,
                    conversation_memory_used=bool(history),
                    orchestration_rounds=round_number,
                )

            if round_number > self._max_tool_rounds:
                break
            if len(turn.tool_calls) > _MAX_TOOL_CALLS_PER_ROUND:
                raise AgentOrchestrationError(
                    "The agent requested too many tools in one round."
                )
            input_items.extend(turn.output_items)
            for call in turn.tool_calls:
                used_tools.add(call.name)
                call_signature = call.name + ":" + json.dumps(
                    call.arguments,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                if call_signature in seen_calls:
                    input_items.append(
                        self._safe_tool_error(call.call_id, "duplicate_tool_request")
                    )
                    execution_summaries.append(
                        ToolExecutionSummary(name=call.name, success=False)
                    )
                    continue
                seen_calls.add(call_signature)
                try:
                    result = self._registry.execute(call.name, call.arguments)
                    result_json = result.model_dump(mode="json")
                    if isinstance(result, RagAnswerResult):
                        collected_citations.extend(result.citations)
                    input_items.append(
                        {
                            "type": "function_call_output",
                            "call_id": call.call_id,
                            "output": json.dumps(
                                result_json,
                                ensure_ascii=False,
                                separators=(",", ":"),
                            ),
                        }
                    )
                    execution_summaries.append(
                        ToolExecutionSummary(name=call.name, success=True)
                    )
                    visualization = build_tool_visualization(call.name, result)
                    if visualization is not None:
                        visualizations.append(visualization)
                except (ValidationError, ToolNotFoundError):
                    input_items.append(
                        self._safe_tool_error(call.call_id, "invalid_tool_request")
                    )
                    execution_summaries.append(
                        ToolExecutionSummary(name=call.name, success=False)
                    )
                except Exception:
                    input_items.append(
                        self._safe_tool_error(call.call_id, "tool_execution_failed")
                    )
                    execution_summaries.append(
                        ToolExecutionSummary(name=call.name, success=False)
                    )

        raise AgentOrchestrationError(
            "The agent exceeded the allowed number of tool rounds."
        )
