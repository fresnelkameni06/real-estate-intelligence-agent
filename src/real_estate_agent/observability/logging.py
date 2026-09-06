"""Structured formatters that expose useful fields without logging secrets."""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

from real_estate_agent.observability.config import ObservabilitySettings
from real_estate_agent.observability.context import get_request_id

_SAFE_EXTRA_FIELDS = (
    "duration_ms",
    "error_type",
    "http_method",
    "http_path",
    "http_status",
    "input_tokens",
    "memory_used",
    "model",
    "orchestration_round",
    "output_tokens",
    "route",
    "service",
    "success",
    "tool_call_count",
    "tool_name",
    "total_tokens",
)
_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)(api[_ -]?key|password|token)\s*[:=]\s*\S+"),
    re.compile(r"(://[^:/\s]+:)[^@\s]+@"),
)
_MAX_LOG_STRING_LENGTH = 500
_HANDLER_MARKER = "_real_estate_observability_handler"
_APPLICATION_LOGGER_PREFIXES = ("app", "real_estate_agent")


def _redact(value: str) -> str:
    result = value
    for pattern in _SECRET_PATTERNS:
        if pattern.pattern.startswith("(://"):
            result = pattern.sub(r"\1***@", result)
        else:
            result = pattern.sub("[REDACTED]", result)
    if len(result) > _MAX_LOG_STRING_LENGTH:
        return result[:_MAX_LOG_STRING_LENGTH] + "…"
    return result


def _safe_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _redact(value)
    if isinstance(value, (list, tuple)):
        return [_safe_value(item) for item in value[:20]]
    return _redact(str(value))


def _timestamp(record: logging.LogRecord) -> str:
    return datetime.fromtimestamp(record.created, tz=UTC).isoformat(
        timespec="milliseconds"
    )


def _fields(record: logging.LogRecord, service_name: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "timestamp": _timestamp(record),
        "level": record.levelname,
        "service": service_name,
        "logger": record.name,
        "event": _redact(str(getattr(record, "event", record.getMessage()))),
    }
    request_id = getattr(record, "request_id", None) or get_request_id()
    if request_id:
        payload["request_id"] = _redact(str(request_id))
    for name in _SAFE_EXTRA_FIELDS:
        if name == "service" or not hasattr(record, name):
            continue
        payload[name] = _safe_value(getattr(record, name))
    if record.exc_info and "error_type" not in payload:
        payload["error_type"] = record.exc_info[0].__name__
    return payload


class SafeJsonFormatter(logging.Formatter):
    """Render one compact JSON object per record with an explicit field allow-list."""

    def __init__(self, service_name: str) -> None:
        super().__init__()
        self._service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            _fields(record, self._service_name),
            ensure_ascii=False,
            separators=(",", ":"),
        )


class SafeTextFormatter(logging.Formatter):
    """Readable local alternative that uses the same safe fields as JSON logs."""

    def __init__(self, service_name: str) -> None:
        super().__init__()
        self._service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        fields = _fields(record, self._service_name)
        base_names = {"timestamp", "level", "service", "logger", "event"}
        details = " ".join(
            f"{name}={json.dumps(value, ensure_ascii=False)}"
            for name, value in fields.items()
            if name not in base_names
        )
        base = (
            f"{fields['timestamp']} {fields['level']} {fields['service']} "
            f"{fields['logger']} {fields['event']}"
        )
        return f"{base} {details}".rstrip()


def configure_logging(settings: ObservabilitySettings | None = None) -> None:
    """Configure application logging without removing host-owned handlers."""
    settings = settings or ObservabilitySettings()
    formatter: logging.Formatter
    if settings.log_format == "json":
        formatter = SafeJsonFormatter(settings.service_name)
    else:
        formatter = SafeTextFormatter(settings.service_name)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    setattr(handler, _HANDLER_MARKER, True)
    root_logger = logging.getLogger()
    for existing_handler in list(root_logger.handlers):
        if getattr(existing_handler, _HANDLER_MARKER, False):
            root_logger.removeHandler(existing_handler)
    root_logger.addHandler(handler)
    root_logger.setLevel(settings.log_level)

    # A host process or a migration library may have disabled application
    # loggers before this function runs.  Re-enable our complete logger tree;
    # setting only the parent is insufficient when a child has disabled=True.
    logger_registry = logging.root.manager.loggerDict
    application_loggers = [
        logging.getLogger(prefix) for prefix in _APPLICATION_LOGGER_PREFIXES
    ]
    application_loggers.extend(
        logger
        for name, logger in logger_registry.items()
        if isinstance(logger, logging.Logger)
        and any(
            name.startswith(f"{prefix}.")
            for prefix in _APPLICATION_LOGGER_PREFIXES
        )
    )
    for application_logger in application_loggers:
        application_logger.disabled = False

    for noisy_logger in (
        "httpcore",
        "httpx",
        "httpx2",
        "openai._base_client",
        "uvicorn.access",
    ):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)
