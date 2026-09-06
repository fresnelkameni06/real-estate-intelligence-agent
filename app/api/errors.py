"""Controlled API errors and exception-to-HTTP translation."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from real_estate_agent.analytics.validators import AnalyticsInputError


class ServiceUnavailableError(RuntimeError):
    """Raised when a required local service cannot be reached or configured."""


class AiServiceUnavailableError(RuntimeError):
    """Raised when a bounded AI service cannot complete a request."""


def _error_response(
    status_code: int,
    code: str,
    message: str,
    details: list[dict[str, object]] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details or [],
            }
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Install safe, consistent handlers for expected application failures."""

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = [
            {
                "location": [str(part) for part in error["loc"]],
                "message": error["msg"],
                "type": error["type"],
            }
            for error in exc.errors()
        ]
        return _error_response(
            422,
            "request_validation_error",
            "One or more request parameters are invalid.",
            details,
        )

    @app.exception_handler(AnalyticsInputError)
    async def analytics_input_handler(
        _request: Request, exc: AnalyticsInputError
    ) -> JSONResponse:
        return _error_response(422, "analytics_input_error", str(exc))

    @app.exception_handler(ServiceUnavailableError)
    async def unavailable_handler(
        _request: Request, _exc: ServiceUnavailableError
    ) -> JSONResponse:
        return _error_response(
            503,
            "service_unavailable",
            "The database service is temporarily unavailable.",
        )

    @app.exception_handler(AiServiceUnavailableError)
    async def ai_unavailable_handler(
        _request: Request, _exc: AiServiceUnavailableError
    ) -> JSONResponse:
        return _error_response(
            503,
            "ai_service_unavailable",
            "The AI service is temporarily unavailable.",
        )

    @app.exception_handler(SQLAlchemyError)
    async def database_error_handler(
        _request: Request, _exc: SQLAlchemyError
    ) -> JSONResponse:
        return _error_response(
            503,
            "database_unavailable",
            "The database could not complete the request.",
        )
