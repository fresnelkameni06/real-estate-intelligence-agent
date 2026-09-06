"""Validated inputs and composed outputs for the bounded AI tools."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from real_estate_agent.analytics import policy
from real_estate_agent.analytics.models import DpeDistribution, DpeIntensitySummary
from real_estate_agent.rag.generation.models import AnswerStyle

Arrondissement = Annotated[
    int,
    Field(ge=policy.MIN_ARRONDISSEMENT, le=policy.MAX_ARRONDISSEMENT),
]


class ToolInput(BaseModel):
    """Strict base model preventing silent or hallucinated arguments."""

    model_config = ConfigDict(extra="forbid")


class PeriodInput(ToolInput):
    """Shared bounded period used by market and energy tools."""

    start_year: int = Field(
        default=policy.DEFAULT_START_YEAR,
        ge=policy.MIN_VALID_YEAR,
        le=policy.MAX_VALID_YEAR,
    )
    end_year: int = Field(
        default=policy.DEFAULT_END_YEAR,
        ge=policy.MIN_VALID_YEAR,
        le=policy.MAX_VALID_YEAR,
    )

    @model_validator(mode="after")
    def end_year_must_follow_start_year(self) -> PeriodInput:
        if self.start_year > self.end_year:
            raise ValueError("start_year must be less than or equal to end_year")
        return self


class MarketScopeInput(PeriodInput):
    """Paris-wide or arrondissement-level market scope."""

    arrondissement: Arrondissement | None = None


class AreaComparisonInput(PeriodInput):
    """Two to five distinct Paris arrondissements compared identically."""

    arrondissements: list[Arrondissement] = Field(min_length=2, max_length=5)

    @model_validator(mode="after")
    def arrondissements_must_be_distinct(self) -> AreaComparisonInput:
        if len(set(self.arrondissements)) != len(self.arrondissements):
            raise ValueError("arrondissements must contain distinct values")
        return self


class DpeAnalysisInput(MarketScopeInput):
    """Aggregate DPE scope; only eligible dwelling-unit records are used."""


class DocumentaryQuestionInput(ToolInput):
    """One question answered only from indexed official documents."""

    question: str = Field(min_length=1, max_length=2_000)
    style: AnswerStyle = "auto"

    @model_validator(mode="after")
    def question_must_not_be_blank(self) -> DocumentaryQuestionInput:
        self.question = self.question.strip()
        if not self.question:
            raise ValueError("question must not be blank")
        return self


class DpeAnalysisResult(BaseModel):
    """Distribution and intensity returned together without a DVF/DPE join."""

    distribution: DpeDistribution
    intensity: DpeIntensitySummary
