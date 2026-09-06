"""Environment-backed limits for the bounded agent orchestration loop."""

from __future__ import annotations

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from real_estate_agent.secret_files import require_secret


class AgentSettings(BaseSettings):
    """OpenAI model and local orchestration limits without secret exposure."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: SecretStr | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_api_key_file: str | None = Field(
        default=None,
        alias="OPENAI_API_KEY_FILE",
    )
    model: str = Field(default="gpt-5.6-luna", alias="OPENAI_AGENT_MODEL")
    max_output_tokens: int = Field(
        default=1600,
        alias="OPENAI_AGENT_MAX_OUTPUT_TOKENS",
        ge=200,
        le=4000,
    )
    timeout_seconds: float = Field(
        default=90.0,
        alias="OPENAI_REQUEST_TIMEOUT_SECONDS",
        gt=0,
        le=300,
    )
    max_tool_rounds: int = Field(
        default=4,
        alias="AGENT_MAX_TOOL_ROUNDS",
        ge=1,
        le=6,
    )
    max_history_messages: int = Field(
        default=12,
        alias="AGENT_MAX_HISTORY_MESSAGES",
        ge=2,
        le=20,
    )

    @field_validator("model")
    @classmethod
    def model_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("OPENAI_AGENT_MODEL must not be blank")
        return value

    def require_api_key(self) -> str:
        """Return the configured secret locally without logging it."""
        direct_value = (
            self.openai_api_key.get_secret_value()
            if self.openai_api_key is not None
            else None
        )
        return require_secret(
            direct_value,
            self.openai_api_key_file,
            variable_name="OPENAI_API_KEY",
        )
