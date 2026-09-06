"""Navigation / RAG-chat / geographic-filter tests for the dashboard.

Loads app/streamlit/app.py by file path (avoiding the name clash with the
`app/` package) and uses streamlit.testing.v1.AppTest without submitting a
question, so the suite needs no FastAPI server, database or LLM.
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


def test_pages_include_active_rag_assistant():
    """The navigation exposes the active documentary assistant."""
    dash = _load_app_module()
    assert dash.RAG_PAGE in dash.PAGES
    assert "bientôt" not in dash.RAG_PAGE.lower()


def test_rag_example_questions_match_the_current_corpus():
    """Clickable examples advertise only current documentary capabilities."""
    dash = _load_app_module()
    assert len(dash.RAG_EXAMPLE_QUESTIONS) >= 3
    assert any("DPE" in q for q in dash.RAG_EXAMPLE_QUESTIONS)
    assert any("DVF" in q for q in dash.RAG_EXAMPLE_QUESTIONS)


def test_roadmap_distinguishes_rag_from_the_future_agent():
    """RAG is active while AI tools and multi-tool orchestration remain future."""
    dash = _load_app_module()
    roadmap = dict(dash.AI_ROADMAP)
    assert roadmap["RAG documentaire"] is True
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
# Active RAG page render (no API call until a question is submitted)
# --------------------------------------------------------------------------- #

def test_rag_page_has_enabled_chat_input():
    at = AppTest.from_file(APP_PATH)
    at.session_state["nav_page"] = "✨ Analyste IA — RAG actif"
    at.run()
    assert not at.exception
    assert len(at.chat_input) == 1
    assert at.chat_input[0].disabled is False


def test_rag_page_is_honest_about_current_scope():
    at = AppTest.from_file(APP_PATH)
    at.session_state["nav_page"] = "✨ Analyste IA — RAG actif"
    at.run()
    assert not at.exception
    text = " ".join(m.value for m in at.markdown)
    text += " ".join(c.value for c in at.caption)
    lowered = text.lower()
    assert "documents officiels" in lowered
    assert "phase agent" in lowered


def test_rag_page_has_one_header_and_clear_control():
    """The chat page must not repeat the global assistant promotion."""
    at = AppTest.from_file(APP_PATH)
    at.session_state["nav_page"] = "✨ Analyste IA — RAG actif"
    at.run()
    assert not at.exception
    labels = [b.label for b in at.button]
    assert "↻ Effacer" in labels
    assert not any("Ouvrir l’Analyste IA" in label for label in labels)


def test_initial_chat_and_citation_grouping():
    dash = _load_app_module()
    messages = dash.initial_chat_messages()
    assert messages[0]["role"] == "assistant"
    assert "documents officiels" in messages[0]["content"]

    grouped = dash.group_citations_by_source(
        [
            {
                "citation_id": "S1",
                "source_id": "dpe",
                "title": "DPE",
                "publisher": "Ministère",
                "url": "https://example.test/dpe",
                "section": "Validité",
            },
            {
                "citation_id": "S2",
                "source_id": "dpe",
                "title": "DPE",
                "publisher": "Ministère",
                "url": "https://example.test/dpe",
                "section": "Location",
            },
        ]
    )
    assert len(grouped) == 1
    assert grouped[0]["references"] == ["S1", "S2"]
    assert grouped[0]["sections"] == ["Validité", "Location"]
