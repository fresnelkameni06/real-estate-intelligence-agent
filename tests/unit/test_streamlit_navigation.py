"""Navigation / AI-preview / geographic-filter tests for the dashboard.

Loads app/streamlit/app.py by file path (avoiding the name clash with the
`app/` package) and uses streamlit.testing.v1.AppTest only for pages that make
no API call, so the suite is fast and needs no FastAPI server, database or LLM.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_STREAMLIT_DIR = Path(__file__).resolve().parents[2] / "app" / "streamlit"
APP_PATH = str(_STREAMLIT_DIR / "app.py")

# The dashboard uses flat imports (`from api_client import ...`). Mirror that so
# the module loads for direct inspection.
if str(_STREAMLIT_DIR) not in sys.path:
    sys.path.insert(0, str(_STREAMLIT_DIR))

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest


def _load_app_module():
    """Load app/streamlit/app.py under a unique name (not the `app` package)."""
    spec = importlib.util.spec_from_file_location("dashboard_app_module", APP_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------- #
# Pure-logic tests (no Streamlit run, no API)
# --------------------------------------------------------------------------- #

def test_global_selector_page_membership():
    """The single global "Zone analysée" selector applies to exactly these pages."""
    dash = _load_app_module()
    assert dash.GLOBAL_AREA_PAGES == {
        "Vue d’ensemble", "DPE", "Profil arrondissement"
    }
    assert "Classements" not in dash.GLOBAL_AREA_PAGES
    assert "Comparaison" not in dash.GLOBAL_AREA_PAGES


def test_pages_include_ai_preview():
    """The navigation exposes a dedicated AI-analyst preview page."""
    dash = _load_app_module()
    assert "✨ Analyste IA — bientôt" in dash.PAGES


def test_ai_example_questions_present():
    """Example future questions are defined for the preview (display only)."""
    dash = _load_app_module()
    assert len(dash.AI_EXAMPLE_QUESTIONS) >= 3
    assert any("13e" in q for q in dash.AI_EXAMPLE_QUESTIONS)


def test_roadmap_marks_ai_phases_upcoming():
    """RAG / AI Tools / AI Agent must be shown as not-yet-done."""
    dash = _load_app_module()
    roadmap = dict(dash.AI_ROADMAP)
    assert roadmap["RAG"] is False
    assert roadmap["AI Tools"] is False
    assert roadmap["AI Agent"] is False
    # Completed foundations are marked done.
    assert roadmap["Analytics Engine"] is True
    assert roadmap["Streamlit"] is True


def test_no_llm_import_in_app():
    """The dashboard must not import any LLM/agent library."""
    source = Path(APP_PATH).read_text(encoding="utf-8")
    for banned in ("openai", "anthropic", "mistral", "langchain", "langgraph"):
        assert banned not in source.lower()


# --------------------------------------------------------------------------- #
# AI preview page render (no API call on this page)
# --------------------------------------------------------------------------- #

def test_ai_preview_page_has_disabled_chat_input():
    at = AppTest.from_file(APP_PATH)
    at.session_state["nav_page"] = "✨ Analyste IA — bientôt"
    at.run()
    assert not at.exception
    assert len(at.chat_input) == 1
    assert at.chat_input[0].disabled is True


def test_ai_preview_states_not_connected():
    at = AppTest.from_file(APP_PATH)
    at.session_state["nav_page"] = "✨ Analyste IA — bientôt"
    at.run()
    assert not at.exception
    text = " ".join(m.value for m in at.markdown)
    text += " ".join(c.value for c in at.caption)
    lowered = text.lower()
    assert "activé" in lowered or "aucune requête" in lowered


def test_ai_hero_button_on_ai_page():
    """The animated hero (shown on every page) exposes its discover button."""
    at = AppTest.from_file(APP_PATH)
    at.session_state["nav_page"] = "✨ Analyste IA — bientôt"
    at.run()
    assert not at.exception
    labels = [b.label for b in at.button]
    assert any("Analyste IA" in lbl for lbl in labels)
