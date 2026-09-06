"""Tests for environment and mounted-file secret resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from real_estate_agent.agent.config import AgentSettings
from real_estate_agent.rag.embeddings.config import EmbeddingSettings
from real_estate_agent.rag.generation.config import RagGenerationSettings


@pytest.mark.parametrize(
    "settings_type",
    [AgentSettings, EmbeddingSettings, RagGenerationSettings],
)
def test_openai_key_can_be_loaded_from_mounted_secret_file(
    settings_type: type,
    tmp_path: Path,
) -> None:
    secret_file = tmp_path / "openai-key"
    secret_file.write_text("container-secret\n", encoding="utf-8")

    settings = settings_type(
        OPENAI_API_KEY=None,
        OPENAI_API_KEY_FILE=str(secret_file),
        _env_file=None,
    )

    assert settings.require_api_key() == "container-secret"


def test_direct_openai_key_takes_precedence_over_file(tmp_path: Path) -> None:
    secret_file = tmp_path / "openai-key"
    secret_file.write_text("file-secret", encoding="utf-8")
    settings = AgentSettings(
        OPENAI_API_KEY="direct-secret",
        OPENAI_API_KEY_FILE=str(secret_file),
        _env_file=None,
    )

    assert settings.require_api_key() == "direct-secret"


def test_secret_error_never_exposes_file_contents(tmp_path: Path) -> None:
    secret_file = tmp_path / "openai-key"
    secret_file.write_text("", encoding="utf-8")
    settings = AgentSettings(
        OPENAI_API_KEY=None,
        OPENAI_API_KEY_FILE=str(secret_file),
        _env_file=None,
    )

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY_FILE is empty"):
        settings.require_api_key()
