"""Typed, versioned contracts for repeatable Agent evaluations."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from real_estate_agent.agent.models import AgentRoute, ConversationMessage

EvaluationCategory = Literal[
    "conversation",
    "market",
    "dpe",
    "documentary",
    "combined",
    "memory",
    "scope",
    "security",
]


class AgentEvaluationCase(BaseModel):
    """One user scenario with structural expectations, not a fixed prose answer."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{2,79}$")
    category: EvaluationCategory
    question: str = Field(min_length=1, max_length=2_000)
    history: list[ConversationMessage] = Field(default_factory=list, max_length=12)
    expected_route: AgentRoute
    required_tools: list[str] = Field(default_factory=list, max_length=6)
    allowed_tools: list[str] = Field(default_factory=list, max_length=6)
    citations_required: bool = False
    expected_visualization_tools: list[str] = Field(default_factory=list, max_length=3)
    expected_memory_used: bool | None = None
    expected_model: str | None = Field(default=None, min_length=1, max_length=100)
    required_answer_terms: list[str] = Field(default_factory=list, max_length=6)

    @model_validator(mode="after")
    def expectations_must_be_coherent(self) -> AgentEvaluationCase:
        if len(set(self.required_tools)) != len(self.required_tools):
            raise ValueError("required_tools must contain unique names")
        if len(set(self.allowed_tools)) != len(self.allowed_tools):
            raise ValueError("allowed_tools must contain unique names")
        if len(set(self.expected_visualization_tools)) != len(
            self.expected_visualization_tools
        ):
            raise ValueError("expected_visualization_tools must contain unique names")
        if len(set(self.required_answer_terms)) != len(self.required_answer_terms):
            raise ValueError("required_answer_terms must contain unique values")
        if not set(self.required_tools).issubset(self.allowed_tools):
            raise ValueError("required_tools must be included in allowed_tools")
        if not set(self.expected_visualization_tools).issubset(self.allowed_tools):
            raise ValueError(
                "expected_visualization_tools must be included in allowed_tools"
            )
        if self.expected_route == "conversation" and self.allowed_tools:
            raise ValueError("conversation cases must not allow tools")
        return self

    @property
    def memory_expected(self) -> bool:
        if self.expected_memory_used is not None:
            return self.expected_memory_used
        return bool(self.history)


class AgentEvaluationSuite(BaseModel):
    """Versioned collection of representative evaluation cases."""

    model_config = ConfigDict(extra="forbid")

    suite_name: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=30)
    cases: list[AgentEvaluationCase] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def case_ids_must_be_unique(self) -> AgentEvaluationSuite:
        identifiers = [case.case_id for case in self.cases]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("evaluation case_id values must be unique")
        return self


class AgentEvaluationResult(BaseModel):
    """Machine-readable outcome for one scenario."""

    case_id: str
    category: EvaluationCategory
    passed: bool
    actual_route: AgentRoute | None = None
    actual_model: str | None = None
    successful_tools: list[str] = Field(default_factory=list)
    failed_tools: list[str] = Field(default_factory=list)
    missing_required_tools: list[str] = Field(default_factory=list)
    unexpected_tools: list[str] = Field(default_factory=list)
    visualization_tools: list[str] = Field(default_factory=list)
    route_correct: bool = False
    tool_selection_correct: bool = False
    citations_correct: bool = False
    visualizations_correct: bool = False
    memory_correct: bool = False
    model_correct: bool = False
    answer_terms_correct: bool = False
    answer_present: bool = False
    latency_ms: float = Field(ge=0)
    failures: list[str] = Field(default_factory=list)


class AgentEvaluationSummary(BaseModel):
    """Aggregate quality indicators plus the individual case outcomes."""

    suite_name: str
    suite_version: str
    evaluated_cases: int = Field(ge=1)
    passed_cases: int = Field(ge=0)
    pass_rate: float = Field(ge=0, le=1)
    route_accuracy: float = Field(ge=0, le=1)
    tool_selection_accuracy: float = Field(ge=0, le=1)
    citation_accuracy: float = Field(ge=0, le=1)
    visualization_accuracy: float = Field(ge=0, le=1)
    memory_accuracy: float = Field(ge=0, le=1)
    model_policy_accuracy: float = Field(ge=0, le=1)
    answer_constraint_accuracy: float = Field(ge=0, le=1)
    average_latency_ms: float = Field(ge=0)
    results: list[AgentEvaluationResult]
