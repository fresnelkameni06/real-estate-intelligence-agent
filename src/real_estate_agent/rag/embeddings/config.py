"""Environment-backed settings for the Phase 6 embedding pipeline."""

from __future__ import annotations

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DATABASE_VECTOR_DIMENSIONS = 1536


class EmbeddingSettings(BaseSettings):
    """OpenAI embedding configuration loaded without exposing the API key."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: SecretStr | None = Field(default=None, alias="OPENAI_API_KEY")
    model: str = Field(default="text-embedding-3-small", alias="OPENAI_EMBEDDING_MODEL")
    dimensions: int = Field(default=1536, alias="OPENAI_EMBEDDING_DIMENSIONS", ge=1)
    batch_size: int = Field(default=64, alias="OPENAI_EMBEDDING_BATCH_SIZE", ge=1, le=256)
    timeout_seconds: float = Field(
        default=60.0,
        alias="OPENAI_REQUEST_TIMEOUT_SECONDS",
        gt=0,
        le=300,
    )

    @field_validator("model")
    @classmethod
    def model_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("OPENAI_EMBEDDING_MODEL must not be blank")
        return value

    @model_validator(mode="after")
    def dimensions_must_match_database(self) -> EmbeddingSettings:
        if self.dimensions != DATABASE_VECTOR_DIMENSIONS:
            raise ValueError(
                "OPENAI_EMBEDDING_DIMENSIONS must be 1536 because the database "
                "column is vector(1536)."
            )
        return self

    def require_api_key(self) -> str:
        """Return the secret value or fail without logging/revealing it."""
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
