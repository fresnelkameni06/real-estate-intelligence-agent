"""Request-scoped correlation identifier propagated through application logs."""

from __future__ import annotations

from contextvars import ContextVar, Token

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


def bind_request_id(request_id: str) -> Token[str | None]:
    """Bind one validated request identifier to the current async context."""
    return _request_id.set(request_id)


def get_request_id() -> str | None:
    """Return the active request identifier, when execution is HTTP-scoped."""
    return _request_id.get()


def reset_request_id(token: Token[str | None]) -> None:
    """Restore the correlation context after one request finishes."""
    _request_id.reset(token)
