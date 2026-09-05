"""Environment-backed settings for grounded RAG answer generation."""

from __future__ import annotations

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class RagGenerationSettings(BaseSettings):
    """OpenAI response and retrieval configuration without secret exposure."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: SecretStr | None = Field(default=None, alias="OPENAI_API_KEY")
    model: str = Field(default="gpt-5.6-luna", alias="OPENAI_CHAT_MODEL")
    max_output_tokens: int = Field(
        default=1600,
        alias="OPENAI_CHAT_MAX_OUTPUT_TOKENS",
        ge=100,
        le=4000,
    )
    timeout_seconds: float = Field(
        default=60.0,
        alias="OPENAI_REQUEST_TIMEOUT_SECONDS",
        gt=0,
        le=300,
    )
    retrieval_top_k: int = Field(default=5, alias="RAG_RETRIEVAL_TOP_K", ge=1, le=8)
    minimum_similarity: float = Field(
        default=0.42,
        alias="RAG_MINIMUM_SIMILARITY",
        ge=-1.0,
        le=1.0,
    )
    context_max_characters: int = Field(
        default=12_000,
        alias="RAG_CONTEXT_MAX_CHARACTERS",
        ge=2_000,
        le=30_000,
    )

    @field_validator("model")
    @classmethod
    def model_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("OPENAI_CHAT_MODEL must not be blank")
        return value

    def require_api_key(self) -> str:
        """Return the secret locally or fail without revealing it."""
        if self.openai_api_key is None:
            raise RuntimeError(
                "OPENAI_API_KEY is not set. Add it only to the local .env file."
            )
        value = self.openai_api_key.get_secret_value().strip()
        if not value:
            raise RuntimeError(
                "OPENAI_API_KEY is empty. Add it only to the local .env file."
            )
        return value
