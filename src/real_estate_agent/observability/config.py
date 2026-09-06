"""Environment-backed settings for lightweight application observability."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
LogFormat = Literal["json", "text"]


class ObservabilitySettings(BaseSettings):
    """Validated log configuration with production-safe defaults."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    service_name: str = Field(
        default="real-estate-intelligence-api",
        alias="SERVICE_NAME",
        min_length=1,
        max_length=80,
    )
    log_level: LogLevel = Field(default="INFO", alias="LOG_LEVEL")
    log_format: LogFormat = Field(default="json", alias="LOG_FORMAT")

    @field_validator("service_name")
    @classmethod
    def service_name_must_be_trimmed(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("SERVICE_NAME must not be blank")
        return value

    @field_validator("log_level", mode="before")
    @classmethod
    def normalize_log_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @field_validator("log_format", mode="before")
    @classmethod
    def normalize_log_format(cls, value: object) -> object:
        return value.casefold() if isinstance(value, str) else value
