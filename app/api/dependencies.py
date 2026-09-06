"""Shared FastAPI dependencies.

The SQLAlchemy engine is created lazily once per process and reused through its
connection pool. No database connection is opened merely by importing the app.
"""

from __future__ import annotations

from threading import Lock

from sqlalchemy import Engine

from app.api.errors import AiServiceUnavailableError, ServiceUnavailableError
from real_estate_agent.agent import (
    AgentService,
    AgentSettings,
    OpenAIResponsesAgentModel,
)
from real_estate_agent.database.config import load_settings
from real_estate_agent.database.engine import make_engine
from real_estate_agent.rag.embeddings import (
    EmbeddingSettings,
    OpenAIEmbeddingProvider,
    PgVectorRepository,
)
from real_estate_agent.rag.generation import (
    OpenAIResponsesGenerator,
    RagAnswerService,
    RagGenerationSettings,
)
from real_estate_agent.tools import build_tool_registry

_engine: Engine | None = None
_engine_lock = Lock()
_rag_answer_service: RagAnswerService | None = None
_rag_service_lock = Lock()
_agent_service: AgentService | None = None
_agent_service_lock = Lock()


def get_database_engine() -> Engine:
    """Return the process-wide engine, creating it from DATABASE_URL if needed."""
    global _engine

    if _engine is not None:
        return _engine

    with _engine_lock:
        if _engine is None:
            try:
                database_url = load_settings().require_database_url()
            except RuntimeError as exc:
                raise ServiceUnavailableError from exc
            _engine = make_engine(database_url)
    return _engine


def dispose_database_engine() -> None:
    """Dispose the shared connection pool during application shutdown."""
    global _engine

    with _engine_lock:
        if _engine is not None:
            _engine.dispose()
            _engine = None


def get_rag_answer_service() -> RagAnswerService:
    """Return the process-wide, lazily configured documentary answer service."""
    global _rag_answer_service

    if _rag_answer_service is not None:
        return _rag_answer_service

    with _rag_service_lock:
        if _rag_answer_service is None:
            try:
                embedding_settings = EmbeddingSettings()
                generation_settings = RagGenerationSettings()
                _rag_answer_service = RagAnswerService(
                    embedding_provider=OpenAIEmbeddingProvider(
                        api_key=embedding_settings.require_api_key(),
                        model=embedding_settings.model,
                        dimensions=embedding_settings.dimensions,
                        timeout_seconds=embedding_settings.timeout_seconds,
                    ),
                    repository=PgVectorRepository(get_database_engine()),
                    response_generator=OpenAIResponsesGenerator(
                        api_key=generation_settings.require_api_key(),
                        model=generation_settings.model,
                        timeout_seconds=generation_settings.timeout_seconds,
                    ),
                    top_k=generation_settings.retrieval_top_k,
                    minimum_similarity=generation_settings.minimum_similarity,
                    context_max_characters=(
                        generation_settings.context_max_characters
                    ),
                    max_output_tokens=generation_settings.max_output_tokens,
                )
            except (RuntimeError, ValueError) as exc:
                raise AiServiceUnavailableError from exc
    return _rag_answer_service


def dispose_rag_answer_service() -> None:
    """Release the cached RAG composition during application shutdown."""
    global _rag_answer_service

    with _rag_service_lock:
        _rag_answer_service = None


def get_agent_service() -> AgentService:
    """Return the process-wide agent composed from the approved local tools."""
    global _agent_service

    if _agent_service is not None:
        return _agent_service

    with _agent_service_lock:
        if _agent_service is None:
            try:
                settings = AgentSettings()
                _agent_service = AgentService(
                    model=OpenAIResponsesAgentModel(
                        api_key=settings.require_api_key(),
                        model=settings.model,
                        timeout_seconds=settings.timeout_seconds,
                    ),
                    registry=build_tool_registry(
                        get_database_engine(),
                        get_rag_answer_service(),
                    ),
                    max_tool_rounds=settings.max_tool_rounds,
                    max_history_messages=settings.max_history_messages,
                    max_output_tokens=settings.max_output_tokens,
                )
            except (RuntimeError, ValueError) as exc:
                raise AiServiceUnavailableError from exc
    return _agent_service


def dispose_agent_service() -> None:
    """Release the cached agent composition during application shutdown."""
    global _agent_service

    with _agent_service_lock:
        _agent_service = None
