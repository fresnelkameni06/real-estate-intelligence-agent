"""Static checks for repeatable, secret-free container deployment files."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_dockerfile_runs_as_non_root_and_uses_dynamic_cloud_port():
    dockerfile = _read("Dockerfile")
    assert "FROM python:3.12-slim-bookworm" in dockerfile
    assert "USER app" in dockerfile
    assert "${PORT:-8000}" in dockerfile
    assert "alembic upgrade head" in dockerfile


def test_docker_build_context_excludes_secrets_and_generated_data():
    ignored = set(_read(".dockerignore").splitlines())
    assert ".env" in ignored
    assert "data" in ignored
    assert ".git" in ignored
    assert "tests" in ignored


def test_compose_defines_pgvector_healthchecks_and_private_service_url():
    compose = _read("compose.yaml")
    assert "pgvector/pgvector:0.8.6-pg18" in compose
    assert "pg_isready" in compose
    assert "API_BASE_URL: http://api:8000" in compose
    assert "condition: service_healthy" in compose
    assert "postgres_data:/var/lib/postgresql\n" in compose
    assert "postgres_data:/var/lib/postgresql/data" not in compose
    assert "OPENAI_API_KEY_FILE: /run/secrets/openai_api_key" in compose
    assert "environment: OPENAI_API_KEY" in compose
    assert "OPENAI_API_KEY: ${" not in compose
    assert "sk-" not in compose


def test_render_blueprint_keeps_secrets_external_and_links_services():
    blueprint = _read("render.yaml")
    assert "OPENAI_API_KEY" in blueprint
    assert "sync: false" in blueprint
    assert "property: connectionString" in blueprint
    assert "property: hostport" in blueprint
    assert "postgresMajorVersion: \"18\"" in blueprint
    assert blueprint.count("autoDeployTrigger: checksPass") == 2
    assert "preDeployCommand" not in blueprint
    assert "sk-" not in blueprint
