"""Multi-tool real-estate agent endpoint with bounded client-side memory."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies import get_agent_service
from app.api.errors import AiServiceUnavailableError
from app.api.schemas import AgentChatRequest
from real_estate_agent.agent import (
    AgentAnswerResult,
    AgentOrchestrationError,
    AgentProviderError,
    AgentService,
)

router = APIRouter()

AgentServiceDependency = Annotated[AgentService, Depends(get_agent_service)]


@router.post(
    "/agent/chat",
    response_model=AgentAnswerResult,
    tags=["agent"],
    summary="Ask the multi-tool Paris real-estate agent",
)
def chat_with_agent(
    request: AgentChatRequest,
    agent_service: AgentServiceDependency,
) -> AgentAnswerResult:
    """Route one conversational turn through approved analytics/RAG tools."""
    try:
        return agent_service.answer(request.message, history=request.history)
    except (AgentOrchestrationError, AgentProviderError, RuntimeError) as exc:
        raise AiServiceUnavailableError from exc
