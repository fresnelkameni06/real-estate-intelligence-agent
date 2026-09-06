"""Grounded documentary RAG endpoint for the conversational interface."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies import get_rag_answer_service
from app.api.errors import AiServiceUnavailableError
from app.api.schemas import RagAnswerRequest
from real_estate_agent.conversation import local_conversation_reply
from real_estate_agent.rag.generation.models import RagAnswerResult
from real_estate_agent.rag.generation.service import RagAnswerService

router = APIRouter()

RagServiceDependency = Annotated[RagAnswerService, Depends(get_rag_answer_service)]


@router.post(
    "/rag/answer",
    response_model=RagAnswerResult,
    tags=["rag"],
    summary="Answer from indexed official documents",
)
def answer_documentary_question(
    request: RagAnswerRequest,
    rag_service: RagServiceDependency,
) -> RagAnswerResult:
    """Retrieve official passages and return one grounded, cited answer."""
    local_reply = local_conversation_reply(request.question)
    if local_reply is not None:
        return RagAnswerResult(
            question=request.question,
            answer=local_reply,
            citations=[],
            retrieved_chunks=0,
            top_similarity=None,
            model="local-conversation-router",
            requested_style=request.style,
            grounded=False,
            insufficient_context=False,
        )
    try:
        return rag_service.answer(request.question, style=request.style)
    except (RuntimeError, ValueError) as exc:
        raise AiServiceUnavailableError from exc
