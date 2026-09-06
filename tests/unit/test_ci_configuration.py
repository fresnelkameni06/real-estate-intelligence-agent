"""Static checks for the GitHub Actions CI and gated Render deployment."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _workflow() -> str:
    return (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")


def test_ci_runs_quality_tests_and_container_build() -> None:
    workflow = _workflow()
    assert "python -m ruff check ." in workflow
    assert "python -m pytest -q" in workflow
    assert "pgvector/pgvector:0.8.6-pg18" in workflow
    assert "docker compose config --quiet" in workflow
    assert "docker build --tag paris-real-estate-intelligence:" in workflow


def test_ci_uses_read_only_permissions_and_no_production_secrets() -> None:
    workflow = _workflow()
    assert "permissions:\n  contents: read" in workflow
    assert "OPENAI_API_KEY: ci-placeholder-not-a-real-key" in workflow
    assert "secrets." not in workflow
    assert "sk-" not in workflow


def test_ci_targets_main_and_pins_python_version() -> None:
    workflow = _workflow()
    assert "actions/checkout@v7" in workflow
    assert "actions/setup-python@v7" in workflow
    assert 'python-version: "3.12"' in workflow
    assert "branches: [main]" in workflow
