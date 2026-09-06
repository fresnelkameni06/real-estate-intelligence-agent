"""ASGI middleware for request correlation and safe HTTP latency logging."""

from __future__ import annotations

import logging
import re
import time
import uuid
from typing import Any

from real_estate_agent.observability.context import bind_request_id, reset_request_id

logger = logging.getLogger(__name__)

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
_REQUEST_ID_HEADER = b"x-request-id"


def _request_id_from(scope: dict[str, Any]) -> str:
    for name, value in scope.get("headers", []):
        if name.lower() != _REQUEST_ID_HEADER:
            continue
        candidate = value.decode("ascii", errors="ignore").strip()
        if _REQUEST_ID_PATTERN.fullmatch(candidate):
            return candidate
    return uuid.uuid4().hex


class RequestObservabilityMiddleware:
    """Add a request ID and log one bounded event for every HTTP request."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        request_id = _request_id_from(scope)
        token = bind_request_id(request_id)
        started = time.perf_counter()
        status_code = 500

        async def send_with_request_id(message: dict[str, Any]) -> None:
            nonlocal status_code
            if message.get("type") == "http.response.start":
                status_code = int(message.get("status", 500))
                headers = [
                    (name, value)
                    for name, value in message.get("headers", [])
                    if name.lower() != _REQUEST_ID_HEADER
                ]
                headers.append((_REQUEST_ID_HEADER, request_id.encode("ascii")))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception as exc:
            logger.error(
                "http_request_failed",
                extra={
                    "event": "http_request_failed",
                    "http_method": scope.get("method", "UNKNOWN"),
                    "http_path": scope.get("path", ""),
                    "duration_ms": round(
                        (time.perf_counter() - started) * 1_000,
                        2,
                    ),
                    "error_type": type(exc).__name__,
                },
            )
            raise
        else:
            logger.info(
                "http_request_completed",
                extra={
                    "event": "http_request_completed",
                    "http_method": scope.get("method", "UNKNOWN"),
                    "http_path": scope.get("path", ""),
                    "http_status": status_code,
                    "duration_ms": round(
                        (time.perf_counter() - started) * 1_000,
                        2,
                    ),
                },
            )
        finally:
            reset_request_id(token)
