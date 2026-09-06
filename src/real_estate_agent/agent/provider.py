"""Provider-neutral boundary for model-directed function calling."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any, Protocol

from real_estate_agent.agent.models import AgentModelTurn, AgentToolCall
from real_estate_agent.tools.registry import ToolSpecification


class AgentProviderError(RuntimeError):
    """Raised when the model provider cannot return a usable turn."""


class AgentModel(Protocol):
    """Minimal model contract required by the orchestration service."""

    model: str

    def respond(
        self,
        *,
        instructions: str,
        input_items: Sequence[dict[str, Any]],
        tools: Sequence[ToolSpecification],
        max_output_tokens: int,
    ) -> AgentModelTurn:
        """Return text or validated-looking function-call requests."""


class OpenAIResponsesAgentModel:
    """Use OpenAI Responses function calling without server-side conversation storage."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float = 90.0,
        client: Any | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("An OpenAI API key is required.")
        if not model.strip():
            raise ValueError("An OpenAI agent model is required.")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero.")
        self.model = model.strip()
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:  # pragma: no cover - dependency setup failure
                raise AgentProviderError(
                    "The openai package is missing. Install .[database,app,rag]."
                ) from exc
            self._client = OpenAI(
                api_key=self._api_key,
                timeout=self._timeout_seconds,
                max_retries=3,
            )
        return self._client

    @staticmethod
    def _provider_tools(
        specifications: Sequence[ToolSpecification],
    ) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "name": specification.name,
                "description": specification.description,
                "parameters": specification.input_schema,
                # Local Pydantic validation remains authoritative. Several tool
                # fields intentionally have defaults, which strict provider schemas
                # do not consistently accept as optional fields.
                "strict": False,
            }
            for specification in specifications
        ]

    @staticmethod
    def _output_items(response: Any) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for item in getattr(response, "output", []):
            if hasattr(item, "model_dump"):
                payload = item.model_dump(mode="json", exclude_none=True)
            elif isinstance(item, dict):
                payload = dict(item)
            else:
                continue
            items.append(payload)
        return items

    @staticmethod
    def _tool_calls(items: Sequence[dict[str, Any]]) -> list[AgentToolCall]:
        calls: list[AgentToolCall] = []
        for item in items:
            if item.get("type") != "function_call":
                continue
            try:
                arguments = json.loads(str(item.get("arguments", "{}")))
            except json.JSONDecodeError:
                arguments = {"__invalid_json__": True}
            if not isinstance(arguments, dict):
                arguments = {"__invalid_json__": True}
            calls.append(
                AgentToolCall(
                    call_id=str(item.get("call_id", "")),
                    name=str(item.get("name", "")),
                    arguments=arguments,
                )
            )
        return calls

    def respond(
        self,
        *,
        instructions: str,
        input_items: Sequence[dict[str, Any]],
        tools: Sequence[ToolSpecification],
        max_output_tokens: int,
    ) -> AgentModelTurn:
        if not instructions.strip() or not input_items:
            raise ValueError("Instructions and input items must not be empty.")
        try:
            response = self._get_client().responses.create(
                model=self.model,
                instructions=instructions,
                input=list(input_items),
                tools=self._provider_tools(tools),
                tool_choice="auto",
                parallel_tool_calls=True,
                max_tool_calls=6,
                max_output_tokens=max_output_tokens,
                reasoning={"effort": "low"},
                store=False,
            )
        except Exception as exc:
            raise AgentProviderError(
                "OpenAI agent execution failed. Check the model, API access and quota."
            ) from exc

        if getattr(response, "status", None) == "incomplete":
            raise AgentProviderError(
                "OpenAI returned an incomplete agent turn. Increase the agent output limit."
            )
        output_items = self._output_items(response)
        tool_calls = self._tool_calls(output_items)
        output_text = str(getattr(response, "output_text", "")).strip()
        if not output_text and not tool_calls:
            raise AgentProviderError("OpenAI returned neither an answer nor a tool call.")
        return AgentModelTurn(
            output_text=output_text,
            output_items=output_items,
            tool_calls=tool_calls,
        )
