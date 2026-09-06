"""Typed contracts exchanged by the agent, provider, API and dashboard."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from real_estate_agent.rag.generation.models import AnswerCitation

ConversationRole = Literal["user", "assistant"]
AgentRoute = Literal["conversation", "market", "dpe", "documentary", "combined"]
MAX_USER_MESSAGE_CHARACTERS = 2_000
MAX_ASSISTANT_MESSAGE_CHARACTERS = 12_000


class ConversationMessage(BaseModel):
    """One bounded message retained in the user's current UI session."""

    model_config = ConfigDict(extra="forbid")

    role: ConversationRole
    content: str = Field(min_length=1, max_length=MAX_ASSISTANT_MESSAGE_CHARACTERS)

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("message content must not be blank")
        return value

    @model_validator(mode="after")
    def user_message_must_remain_bounded(self) -> ConversationMessage:
        if self.role == "user" and len(self.content) > MAX_USER_MESSAGE_CHARACTERS:
            raise ValueError(
                f"user message must contain at most {MAX_USER_MESSAGE_CHARACTERS} characters"
            )
        return self


class AgentToolCall(BaseModel):
    """Provider-neutral function call selected by the model."""

    call_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    arguments: dict[str, Any]


class AgentModelTurn(BaseModel):
    """One provider response, possibly requesting one or more tools."""

    output_text: str = ""
    output_items: list[dict[str, Any]] = Field(default_factory=list)
    tool_calls: list[AgentToolCall] = Field(default_factory=list)


class ToolExecutionSummary(BaseModel):
    """Safe execution trace returned to the UI without raw database results."""

    name: str
    success: bool


class AgentVisualization(BaseModel):
    """Safe single-series chart derived from one deterministic tool result."""

    model_config = ConfigDict(extra="forbid")

    visualization_id: str = Field(min_length=1, max_length=100)
    source_tool: str = Field(min_length=1, max_length=100)
    chart_type: Literal["line", "bar"]
    title: str = Field(min_length=1, max_length=200)
    x_axis_title: str = Field(min_length=1, max_length=100)
    y_axis_title: str = Field(min_length=1, max_length=100)
    labels: list[str] = Field(min_length=1, max_length=50)
    values: list[float] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def labels_and_values_must_align(self) -> AgentVisualization:
        if len(self.labels) != len(self.values):
            raise ValueError("labels and values must have the same length")
        return self


class AgentAnswerResult(BaseModel):
    """Final user-facing agent answer with traceability and provenance."""

    question: str
    answer: str
    route: AgentRoute
    tool_executions: list[ToolExecutionSummary] = Field(default_factory=list)
    visualizations: list[AgentVisualization] = Field(default_factory=list)
    citations: list[AnswerCitation] = Field(default_factory=list)
    model: str
    conversation_memory_used: bool
    orchestration_rounds: int = Field(ge=0, le=7)
