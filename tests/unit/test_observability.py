"""Tests for safe structured logs and request-scoped correlation."""

from __future__ import annotations

import json
import logging

from real_estate_agent.observability import (
    ObservabilitySettings,
    SafeJsonFormatter,
    SafeTextFormatter,
    bind_request_id,
    configure_logging,
    get_request_id,
    reset_request_id,
)


def _record(message: str, **extra: object) -> logging.LogRecord:
    record = logging.LogRecord(
        name="real_estate_agent.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )
    for name, value in extra.items():
        setattr(record, name, value)
    return record


def test_json_formatter_emits_correlation_and_allow_listed_fields():
    token = bind_request_id("request-12345678")
    try:
        record = _record(
            "agent_completed",
            event="agent_completed",
            route="market",
            duration_ms=12.5,
            question="This user content must never be serialized",
        )
        payload = json.loads(SafeJsonFormatter("test-service").format(record))
    finally:
        reset_request_id(token)

    assert payload["event"] == "agent_completed"
    assert payload["service"] == "test-service"
    assert payload["request_id"] == "request-12345678"
    assert payload["route"] == "market"
    assert payload["duration_ms"] == 12.5
    assert "question" not in payload


def test_formatters_redact_common_secret_shapes_and_database_passwords():
    message = (
        "api_key=private-value Bearer bearer-secret "
        "postgresql://user:database-secret@localhost/db sk-proj-private123"
    )
    record = _record(message)

    json_output = SafeJsonFormatter("test-service").format(record)
    text_output = SafeTextFormatter("test-service").format(record)

    for output in (json_output, text_output):
        assert "private-value" not in output
        assert "bearer-secret" not in output
        assert "database-secret" not in output
        assert "sk-proj-private123" not in output
        assert "REDACTED" in output or "***" in output


def test_request_context_is_restored_after_reset():
    assert get_request_id() is None
    token = bind_request_id("request-abcdefgh")
    assert get_request_id() == "request-abcdefgh"
    reset_request_id(token)
    assert get_request_id() is None


def test_observability_settings_normalize_values_without_env_file():
    settings = ObservabilitySettings(
        SERVICE_NAME=" test-api ",
        LOG_LEVEL="debug",
        LOG_FORMAT="TEXT",
        _env_file=None,
    )
    assert settings.service_name == "test-api"
    assert settings.log_level == "DEBUG"
    assert settings.log_format == "text"


def test_logging_configuration_is_idempotent():
    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    original_foreign_handlers = [
        handler
        for handler in original_handlers
        if not getattr(handler, "_real_estate_observability_handler", False)
    ]
    original_level = root_logger.level
    settings = ObservabilitySettings(
        SERVICE_NAME="test-api",
        LOG_LEVEL="INFO",
        LOG_FORMAT="json",
        _env_file=None,
    )
    try:
        configure_logging(settings)
        configure_logging(settings)
        application_handlers = [
            handler
            for handler in root_logger.handlers
            if getattr(handler, "_real_estate_observability_handler", False)
        ]
        assert len(application_handlers) == 1
        assert isinstance(application_handlers[0].formatter, SafeJsonFormatter)
        assert all(
            handler in root_logger.handlers for handler in original_foreign_handlers
        )
    finally:
        root_logger.handlers.clear()
        root_logger.handlers.extend(original_handlers)
        root_logger.setLevel(original_level)


def test_logging_configuration_reenables_application_child_loggers():
    child_logger = logging.getLogger("real_estate_agent.agent.service")
    original_disabled = child_logger.disabled
    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    original_level = root_logger.level
    settings = ObservabilitySettings(
        SERVICE_NAME="test-api",
        LOG_LEVEL="INFO",
        LOG_FORMAT="json",
        _env_file=None,
    )
    try:
        child_logger.disabled = True
        configure_logging(settings)
        assert child_logger.disabled is False
    finally:
        child_logger.disabled = original_disabled
        root_logger.handlers.clear()
        root_logger.handlers.extend(original_handlers)
        root_logger.setLevel(original_level)
