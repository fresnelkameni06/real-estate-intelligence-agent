"""Small provider-neutral registry for validated AI tool execution."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel


class ToolNotFoundError(LookupError):
    """Raised when orchestration requests a tool outside the allow-list."""


class ToolSpecification(BaseModel):
    """Public metadata and JSON schema shown to an orchestration layer."""

    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class ToolDefinition:
    """One allow-listed handler with strict Pydantic input validation."""

    name: str
    description: str
    input_model: type[BaseModel]
    handler: Callable[[Any], BaseModel]

    def specification(self) -> ToolSpecification:
        return ToolSpecification(
            name=self.name,
            description=self.description,
            input_schema=self.input_model.model_json_schema(),
        )

    def invoke(self, payload: Mapping[str, Any]) -> BaseModel:
        validated_input = self.input_model.model_validate(dict(payload))
        return self.handler(validated_input)


class ToolRegistry:
    """Immutable allow-list used instead of arbitrary function or SQL access."""

    def __init__(self, tools: Sequence[ToolDefinition]) -> None:
        definitions = list(tools)
        by_name = {tool.name: tool for tool in definitions}
        if len(by_name) != len(definitions):
            raise ValueError("Tool names must be unique")
        self._tools = by_name

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._tools)

    def specifications(self) -> list[ToolSpecification]:
        return [tool.specification() for tool in self._tools.values()]

    def execute(self, name: str, payload: Mapping[str, Any]) -> BaseModel:
        try:
            tool = self._tools[name]
        except KeyError as exc:
            raise ToolNotFoundError(f"Unknown or unauthorized tool: {name}") from exc
        return tool.invoke(payload)

    def execute_json(self, name: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self.execute(name, payload).model_dump(mode="json")
