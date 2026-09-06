"""Navigation / Agent-chat / geographic-filter tests for the dashboard.

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

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest


def _load_app_module():
    """Load app/streamlit/app.py under a unique name (not the `app` package)."""
    spec = importlib.util.spec_from_file_location("dashboard_app_module", APP_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(_STREAMLIT_DIR))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(_STREAMLIT_DIR))
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


def test_pages_include_active_agent():
    """The navigation exposes the active multi-tool agent."""
    dash = _load_app_module()
    assert dash.AGENT_PAGE in dash.PAGES
    assert "actif" in dash.AGENT_PAGE.lower()


def test_agent_examples_cover_data_and_documentary_capabilities():
    """Clickable examples demonstrate the active multi-tool scope."""
    dash = _load_app_module()
    assert len(dash.AGENT_EXAMPLE_QUESTIONS) >= 4
    assert any("prix" in q.lower() for q in dash.AGENT_EXAMPLE_QUESTIONS)
    assert any("DPE" in q for q in dash.AGENT_EXAMPLE_QUESTIONS)
    assert any("restrictions" in q.lower() for q in dash.AGENT_EXAMPLE_QUESTIONS)


def test_roadmap_marks_agent_foundations_active():
    """RAG, tools and agent orchestration are now active."""
    dash = _load_app_module()
    roadmap = dict(dash.AI_ROADMAP)
    assert roadmap["RAG documentaire"] is True
    assert roadmap["AI Tools"] is True
    assert roadmap["AI Agent"] is True
    # Completed foundations are marked done.
    assert roadmap["Analytics Engine"] is True
    assert roadmap["Streamlit"] is True


def test_no_llm_import_in_app():
    """The dashboard must not import any LLM/agent library."""
    source = Path(APP_PATH).read_text(encoding="utf-8")
    for banned in ("openai", "anthropic", "mistral", "langchain", "langgraph"):
        assert banned not in source.lower()


# --------------------------------------------------------------------------- #
# Active Agent page render (no API call until a question is submitted)
# --------------------------------------------------------------------------- #

def test_agent_page_has_enabled_chat_input():
    at = AppTest.from_file(APP_PATH)
    at.session_state["nav_page"] = "✨ Analyste IA — Agent actif"
    at.run()
    assert not at.exception
    assert len(at.chat_input) == 1
    assert at.chat_input[0].disabled is False


def test_agent_page_is_honest_about_current_scope():
    at = AppTest.from_file(APP_PATH)
    at.session_state["nav_page"] = "✨ Analyste IA — Agent actif"
    at.run()
    assert not at.exception
    text = " ".join(m.value for m in at.markdown)
    text += " ".join(c.value for c in at.caption)
    lowered = text.lower()
    assert "postgresql" in lowered
    assert "aucune requête sql libre" in lowered


def test_agent_page_has_one_header_and_clear_control():
    """The chat page must not repeat the global assistant promotion."""
    at = AppTest.from_file(APP_PATH)
    at.session_state["nav_page"] = "✨ Analyste IA — Agent actif"
    at.run()
    assert not at.exception
    labels = [b.label for b in at.button]
    assert "↻ Effacer" in labels
    assert not any("Ouvrir l’Analyste IA" in label for label in labels)


def test_initial_chat_and_citation_grouping():
    dash = _load_app_module()
    messages = dash.initial_chat_messages()
    assert messages[0]["role"] == "assistant"
    assert messages[0]["visualizations"] == []
    assert "prix" in messages[0]["content"]
    assert "sources officielles" in messages[0]["content"]
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


def test_agent_figures_support_trends_and_dpe_colors():
    dash = _load_app_module()
    trend = dash.build_agent_figure(
        {
            "visualization_id": "market-trend-6",
            "chart_type": "line",
            "title": "Évolution",
            "x_axis_title": "Année",
            "y_axis_title": "Prix",
            "labels": ["2024", "2025"],
            "values": [14_500, 14_200],
        }
    )
    assert trend.data[0].type == "scatter"
    assert list(trend.data[0].x) == ["2024", "2025"]

    dpe = dash.build_agent_figure(
        {
            "visualization_id": "dpe-label-distribution",
            "chart_type": "bar",
            "title": "DPE",
            "x_axis_title": "Classe",
            "y_axis_title": "%",
            "labels": list("ABCDEFG"),
            "values": [1, 2, 10, 30, 30, 16, 11],
        }
    )
    assert dpe.data[0].type == "bar"
    assert list(dpe.data[0].marker.color) == [
        dash.DPE_COLORS[label] for label in "ABCDEFG"
    ]


def test_agent_trace_keeps_exact_technical_tool_names():
    source = Path(APP_PATH).read_text(encoding="utf-8")
    assert 'st.caption("Outils : " + " · ".join(used))' in source


def test_dashboard_uses_agent_endpoint_instead_of_rag_chat():
    source = Path(APP_PATH).read_text(encoding="utf-8")
    assert "client.ask_agent(" in source
    assert "client.ask_rag(" not in source
