"""Interactive Streamlit dashboard backed exclusively by FastAPI."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import plotly.graph_objects as go
import streamlit as st
from api_client import ApiClientError, RealEstateApiClient
from formatters import (
    arrondissement_label,
    format_euro_per_m2,
    format_integer,
    format_percentage,
    format_surface,
)

DPE_COLORS = {
    "A": "#319834",
    "B": "#33A852",
    "C": "#99C93D",
    "D": "#F1DE35",
    "E": "#F4A62A",
    "F": "#E76B2B",
    "G": "#C9362B",
}

# Pages that use the single global "Zone analysée" selector.
GLOBAL_AREA_PAGES = {"Vue d’ensemble", "DPE", "Profil arrondissement"}

# Examples intentionally cover separate and combined agent capabilities.
AGENT_EXAMPLE_QUESTIONS = [
    "Quel est le prix médian au m² dans le 13e entre 2021 et 2025 ?",
    "Compare le marché immobilier du 13e et du 20e arrondissement.",
    "Quelle est la répartition DPE dans le 15e arrondissement ?",
    "Quelles restrictions concernent les logements classés G ?",
]

AGENT_PAGE = "✨ Analyste IA — Agent actif"
AGENT_CHAT_STATE_KEY = "agent_chat_messages"

# Roadmap shown on the active assistant page (honest project status).
AI_ROADMAP = [
    ("Data Engineering", True),
    ("PostgreSQL", True),
    ("Analytics Engine", True),
    ("FastAPI", True),
    ("Streamlit", True),
    ("RAG documentaire", True),
    ("AI Tools", True),
    ("AI Agent", True),
]

st.set_page_config(
    page_title="Paris Real Estate Intelligence",
    page_icon="🏙️",
    layout="wide",
)


@st.cache_resource
def api_client() -> RealEstateApiClient:
    """Reuse HTTP connections across Streamlit reruns."""
    return RealEstateApiClient()


def show_warnings(payload: Mapping[str, Any]) -> None:
    """Display analytical warnings returned by the backend."""
    for warning in payload.get("warnings", []):
        st.warning(str(warning))


def run_request(call: Any, *args: Any) -> dict[str, Any]:
    """Execute one API call with a consistent user-facing failure state."""
    try:
        with st.spinner("Calcul des indicateurs…"):
            return call(*args)
    except ApiClientError as exc:
        st.error(str(exc))
        st.info(
            "Démarrez FastAPI avec : "
            "`py -m uvicorn --app-dir . app.api.main:app --reload`"
        )
        st.stop()
    return {}  # pragma: no cover - st.stop interrupts normal execution


# --------------------------------------------------------------------------- #
# Multi-tool assistant (Agent through FastAPI; no direct LLM/database import)
# --------------------------------------------------------------------------- #

def _inject_ai_styles() -> None:
    """Inject the CSS for the AI hero/orb once per run.

    Uses only CSS keyframes (no CDN, no JS, no video). Honors
    prefers-reduced-motion for accessibility.
    """
    st.markdown(
        """
        <style>
        .ai-hero {
            border-radius: 16px;
            padding: 22px 26px;
            margin: 6px 0 18px 0;
            background: linear-gradient(120deg, #0f2027 0%, #203a43 45%, #2c5364 100%);
            background-size: 200% 200%;
            animation: ai-hero-gradient 12s ease infinite;
            color: #eaf6ff;
            border: 1px solid rgba(120, 200, 255, 0.25);
        }
        .ai-hero-row { display: flex; align-items: center; gap: 18px; flex-wrap: wrap; }
        .ai-hero-compact { padding: 16px 20px; margin-bottom: 10px; }
        .ai-orb {
            width: 54px; height: 54px; border-radius: 50%;
            background: radial-gradient(circle at 30% 30%, #8fe3ff, #2c7be5 60%, #14306b);
            box-shadow: 0 0 18px 4px rgba(90, 190, 255, 0.55);
            animation: ai-orb-pulse 2.8s ease-in-out infinite;
            flex: 0 0 auto;
        }
        .ai-orb-compact { width: 42px; height: 42px; }
        .ai-hero-title { font-size: 1.35rem; font-weight: 700; margin: 0; }
        .ai-badge {
            display: inline-block; margin-left: 10px; padding: 2px 10px;
            font-size: 0.72rem; font-weight: 600; letter-spacing: .5px;
            border-radius: 999px; background: rgba(90, 230, 160, 0.16);
            color: #7ef0b5; border: 1px solid rgba(90, 230, 160, 0.5);
            vertical-align: middle;
        }
        .ai-hero-sub { margin: 4px 0 0 0; opacity: 0.9; font-size: 0.95rem; }
        .ai-hero-q {
            margin-top: 10px; font-style: italic; color: #bfe6ff;
            min-height: 1.4em;
            animation: ai-q-fade 1.2s ease;
        }
        .ai-status-dot {
            display: inline-block; width: 10px; height: 10px; border-radius: 50%;
            background: #58e59b; margin-right: 8px;
            animation: ai-orb-pulse 2s ease-in-out infinite;
        }
        div[data-testid="stChatMessage"] {
            border: 1px solid rgba(128, 145, 165, 0.18);
            border-radius: 14px;
            padding: 0.75rem 0.9rem;
            margin-bottom: 0.65rem;
        }
        div[data-testid="stChatMessageContent"] p { line-height: 1.55; }
        @keyframes ai-hero-gradient {
            0% { background-position: 0% 50%; }
            50% { background-position: 100% 50%; }
            100% { background-position: 0% 50%; }
        }
        @keyframes ai-orb-pulse {
            0%, 100% { transform: scale(1); opacity: 0.9; }
            50% { transform: scale(1.12); opacity: 1; }
        }
        @keyframes ai-q-fade {
            from { opacity: 0; } to { opacity: 1; }
        }
        @media (prefers-reduced-motion: reduce) {
            .ai-hero { animation: none; }
            .ai-orb, .ai-status-dot { animation: none; }
            .ai-hero-q { animation: none; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_ai_hero() -> None:
    """Render the animated multi-tool-agent hero below the title/description."""
    _inject_ai_styles()

    # Rotate the example question on each rerun (stable, no JS).
    idx = st.session_state.get("_ai_q_index", 0)
    question = AGENT_EXAMPLE_QUESTIONS[idx % len(AGENT_EXAMPLE_QUESTIONS)]
    st.session_state["_ai_q_index"] = (idx + 1) % len(AGENT_EXAMPLE_QUESTIONS)

    st.markdown(
        f"""
        <div class="ai-hero">
          <div class="ai-hero-row">
            <div class="ai-orb"></div>
            <div>
              <p class="ai-hero-title">🤖 Analyste IA immobilier
                <span class="ai-badge">AGENT ACTIF</span>
              </p>
              <p class="ai-hero-sub">
                Explorez les prix, les arrondissements, le DPE et la réglementation
                dans une conversation unique.
              </p>
              <p class="ai-hero-q">« {question} »</p>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("✨ Ouvrir l’Analyste IA", key="ai_hero_button"):
        st.session_state["nav_page"] = AGENT_PAGE
        st.rerun()


def initial_chat_messages() -> list[dict[str, Any]]:
    """Return a fresh welcome conversation for one Streamlit session."""
    return [
        {
            "role": "assistant",
            "content": (
                "Bonjour ! Je suis votre **Analyste IA immobilier pour Paris**. "
                "Je peux analyser les **prix**, comparer les **arrondissements**, "
                "étudier le **DPE** et consulter les **sources officielles**. "
                "Vous pouvez aussi poursuivre avec une question comme « et le 15e ? »."
            ),
            "citations": [],
            "insufficient_context": False,
            "tool_executions": [],
            "visualizations": [],
        }
    ]


def group_citations_by_source(
    citations: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Group passage citations by source URL while preserving first-seen order."""
    grouped: dict[str, dict[str, Any]] = {}
    for citation in citations:
        key = str(citation.get("url") or citation.get("source_id") or "source")
        if key not in grouped:
            grouped[key] = {
                "url": citation.get("url"),
                "title": citation.get("title", "Source officielle"),
                "publisher": citation.get("publisher", ""),
                "sections": [],
                "references": [],
            }
        reference = str(citation.get("citation_id", "")).strip()
        section = str(citation.get("section", "")).strip()
        if reference and reference not in grouped[key]["references"]:
            grouped[key]["references"].append(reference)
        if section and section not in grouped[key]["sections"]:
            grouped[key]["sections"].append(section)
    return list(grouped.values())


def render_rag_sources(citations: list[Mapping[str, Any]]) -> None:
    """Render compact, expandable and deduplicated official provenance."""
    sources = group_citations_by_source(citations)
    if not sources:
        return
    with st.expander(f"Sources officielles · {len(sources)}"):
        for source in sources:
            references = ", ".join(source["references"])
            title = str(source["title"])
            url = str(source["url"] or "")
            publisher = str(source["publisher"])
            heading = f"**{references} — {title}**" if references else f"**{title}**"
            st.markdown(heading)
            if publisher:
                st.caption(publisher)
            if source["sections"]:
                st.caption("Section : " + " · ".join(source["sections"][:2]))
            if url:
                st.markdown(f"[Consulter la source officielle]({url})")


def build_agent_figure(visualization: Mapping[str, Any]) -> go.Figure:
    """Build a Plotly figure exclusively from the API's validated chart payload."""
    labels = [str(item) for item in visualization.get("labels", [])]
    values = [float(item) for item in visualization.get("values", [])]
    chart_type = str(visualization.get("chart_type", "bar"))
    visualization_id = str(visualization.get("visualization_id", ""))

    if chart_type == "line":
        trace: Any = go.Scatter(
            x=labels,
            y=values,
            mode="lines+markers",
            line={"color": "#2C7BE5", "width": 3},
            marker={"size": 8},
            hovertemplate="%{x}<br>%{y:,.0f}<extra></extra>",
        )
    else:
        colors: str | list[str] = "#2C7BE5"
        if visualization_id == "dpe-label-distribution":
            colors = [DPE_COLORS.get(label, "#2C7BE5") for label in labels]
        trace = go.Bar(
            x=labels,
            y=values,
            marker_color=colors,
            hovertemplate="%{x}<br>%{y:,.2f}<extra></extra>",
        )

    figure = go.Figure(trace)
    figure.update_layout(
        title=str(visualization.get("title", "Visualisation")),
        xaxis_title=str(visualization.get("x_axis_title", "")),
        yaxis_title=str(visualization.get("y_axis_title", "")),
        height=360,
        margin={"l": 20, "r": 20, "t": 60, "b": 20},
        showlegend=False,
    )
    return figure


def render_agent_visualizations(
    visualizations: list[Mapping[str, Any]],
    *,
    message_key: str,
) -> None:
    """Display deterministic tool charts directly below an Agent answer."""
    for index, visualization in enumerate(visualizations):
        figure = build_agent_figure(visualization)
        visualization_id = str(
            visualization.get("visualization_id", f"chart-{index}")
        )
        st.plotly_chart(
            figure,
            width="stretch",
            key=f"agent-chart-{message_key}-{index}-{visualization_id}",
        )


def render_chat_message(
    message: Mapping[str, Any],
    *,
    message_key: str = "persisted",
) -> None:
    """Render one persisted chat message and its optional provenance."""
    role = str(message.get("role", "assistant"))
    avatar = "🏛️" if role == "assistant" else "👤"
    with st.chat_message(role, avatar=avatar):
        st.markdown(str(message.get("content", "")))
        render_agent_visualizations(
            list(message.get("visualizations", [])),
            message_key=message_key,
        )
        render_rag_sources(list(message.get("citations", [])))
        render_agent_trace(list(message.get("tool_executions", [])))
        if message.get("insufficient_context"):
            st.caption(
                "Le corpus actuel ne contient pas assez d’éléments fiables pour "
                "compléter cette réponse."
            )


def render_agent_trace(executions: list[Mapping[str, Any]]) -> None:
    """Show the exact technical names of successful tools for transparency."""
    used = [
        str(execution.get("name", ""))
        for execution in executions
        if execution.get("success")
    ]
    if used:
        st.caption("Outils : " + " · ".join(used))


def render_agent_chat(client: RealEstateApiClient) -> None:
    """Render the compact multi-tool agent with bounded session memory."""
    _inject_ai_styles()
    st.markdown(
        """
        <div class="ai-hero ai-hero-compact">
          <div class="ai-hero-row">
            <div class="ai-orb ai-orb-compact"></div>
            <div>
              <p class="ai-hero-title">🤖 Analyste IA immobilier
                <span class="ai-badge">AGENT ACTIF</span>
              </p>
              <p class="ai-hero-sub">
                <span class="ai-status-dot"></span>
                Posez votre question naturellement : l’Agent choisit les outils
                nécessaires et conserve le contexte récent.
              </p>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.caption(
        "Données : DVF + DPE dans PostgreSQL · réglementation issue de 6 sources "
        "officielles · aucune requête SQL libre."
    )

    title_col, action_col = st.columns([6, 1])
    title_col.markdown("### Conversation")
    if action_col.button(
        "↻ Effacer",
        key="clear_agent_chat",
        use_container_width=True,
        help="Effacer uniquement l’historique affiché dans cette session.",
    ):
        st.session_state[AGENT_CHAT_STATE_KEY] = initial_chat_messages()
        st.rerun()

    messages = st.session_state.get(AGENT_CHAT_STATE_KEY)
    if not isinstance(messages, list):
        messages = initial_chat_messages()
        st.session_state[AGENT_CHAT_STATE_KEY] = messages

    suggested_question: str | None = None
    if len(messages) == 1:
        st.markdown("**Suggestions**")
        columns = st.columns(2)
        for index, question in enumerate(AGENT_EXAMPLE_QUESTIONS):
            with columns[index % 2]:
                if st.button(
                    question,
                    key=f"agent_example_{index}",
                    use_container_width=True,
                ):
                    suggested_question = question

    chat_window = st.container(height=520, border=True)
    with chat_window:
        for index, message in enumerate(messages):
            render_chat_message(message, message_key=f"history-{index}")

    submitted_question = st.chat_input(
        "Écrivez votre message…",
        key="agent_chat_input",
        max_chars=2_000,
    )
    question = submitted_question or suggested_question
    if not question:
        return

    user_message = {"role": "user", "content": question}
    messages.append(user_message)
    with chat_window:
        render_chat_message(user_message, message_key=f"current-{len(messages)}")
        with st.chat_message("assistant", avatar="🏛️"):
            try:
                with st.status(
                    "Analyse de votre demande…",
                    expanded=True,
                ) as status:
                    st.write("Sélection des outils utiles…")
                    payload = client.ask_agent(question, messages[:-1])
                    route_labels = {
                        "conversation": "Réponse conversationnelle",
                        "market": "Analyse du marché terminée",
                        "dpe": "Analyse énergétique terminée",
                        "documentary": "Réponse vérifiée dans les sources",
                        "combined": "Analyse multi-outils terminée",
                    }
                    completion_label = route_labels.get(
                        str(payload.get("route")),
                        "Analyse terminée",
                    )
                    status.update(
                        label=completion_label,
                        state="complete",
                        expanded=False,
                    )
                st.markdown(str(payload.get("answer", "")))
                visualizations = list(payload.get("visualizations", []))
                render_agent_visualizations(
                    visualizations,
                    message_key=f"current-{len(messages)}-assistant",
                )
                render_rag_sources(list(payload.get("citations", [])))
                tool_executions = list(payload.get("tool_executions", []))
                render_agent_trace(tool_executions)
                assistant_message = {
                    "role": "assistant",
                    "content": payload.get("answer", ""),
                    "citations": payload.get("citations", []),
                    "tool_executions": tool_executions,
                    "visualizations": visualizations,
                    "insufficient_context": payload.get(
                        "insufficient_context", False
                    ),
                }
            except ApiClientError as exc:
                error_message = (
                    f"Je n’ai pas pu produire la réponse : {exc} "
                    "Vérifiez que FastAPI est démarré, puis réessayez."
                )
                st.error(error_message)
                assistant_message = {
                    "role": "assistant",
                    "content": error_message,
                    "citations": [],
                    "insufficient_context": False,
                    "tool_executions": [],
                    "visualizations": [],
                }
    messages.append(assistant_message)
    st.session_state[AGENT_CHAT_STATE_KEY] = messages


# --------------------------------------------------------------------------- #
# Existing analytical sections (unchanged behavior)
# --------------------------------------------------------------------------- #

def render_overview(
    client: RealEstateApiClient,
    arrondissement: int | None,
    start_year: int,
    end_year: int,
) -> None:
    """Render market KPIs and yearly price trend."""
    overview = run_request(
        client.market_overview, arrondissement, start_year, end_year
    )
    trend = run_request(client.market_trends, arrondissement, start_year, end_year)

    st.subheader(f"Marché — {arrondissement_label(arrondissement)}")
    columns = st.columns(4)
    columns[0].metric(
        "Prix médian",
        format_euro_per_m2(overview.get("median_price_per_m2")),
    )
    columns[1].metric(
        "Transactions analysées",
        format_integer(overview.get("market_analysis_transactions")),
    )
    columns[2].metric(
        "Surface médiane",
        format_surface(overview.get("median_residential_surface")),
    )
    columns[3].metric(
        "Valeurs atypiques exclues",
        format_integer(overview.get("excluded_outlier_count")),
    )

    points = trend.get("points", [])
    years = [point["year"] for point in points]
    prices = [point["median_price_per_m2"] for point in points]
    figure = go.Figure(
        go.Scatter(
            x=years,
            y=prices,
            mode="lines+markers",
            name="Prix médian/m²",
            line={"color": "#176B87", "width": 3},
        )
    )
    figure.update_layout(
        title="Évolution annuelle du prix médian au m²",
        xaxis_title="Année",
        yaxis_title="€/m²",
        hovermode="x unified",
    )
    st.plotly_chart(figure, width="stretch")

    with st.expander("Voir les quartiles et les variations annuelles"):
        st.dataframe(
            [
                {
                    "Année": point["year"],
                    "Échantillon": point["market_analysis_count"],
                    "Prix médian (€/m²)": point["median_price_per_m2"],
                    "P25": point["price_p25"],
                    "P75": point["price_p75"],
                    "Évolution YoY (%)": point["yoy_median_change_pct"],
                }
                for point in points
            ],
            width="stretch",
            hide_index=True,
        )
    show_warnings(overview)
    show_warnings(trend)


def render_rankings(
    client: RealEstateApiClient, start_year: int, end_year: int
) -> None:
    """Render one of the three approved arrondissement rankings."""
    payload = run_request(client.market_rankings, start_year, end_year)
    st.subheader("Classement des arrondissements")

    metric = st.selectbox(
        "Indicateur",
        ["Prix médian au m²", "Volume de transactions", "Surface médiane"],
    )
    configurations = {
        "Prix médian au m²": (
            "by_median_price_per_m2",
            "median_price_per_m2",
            "€/m²",
        ),
        "Volume de transactions": (
            "by_transaction_volume",
            "transaction_volume",
            "Transactions",
        ),
        "Surface médiane": (
            "by_median_surface",
            "median_residential_surface",
            "m²",
        ),
    }
    collection, field, unit = configurations[metric]
    entries = payload.get(collection, [])
    labels = [arrondissement_label(entry["arrondissement"]) for entry in entries]
    values = [entry[field] for entry in entries]

    figure = go.Figure(
        go.Bar(
            x=values,
            y=labels,
            orientation="h",
            marker_color="#176B87",
            customdata=[entry["sample_size"] for entry in entries],
            hovertemplate=(
                "%{y}<br>%{x:,.2f} " + unit + "<br>Échantillon: %{customdata}<extra></extra>"
            ),
        )
    )
    figure.update_layout(
        xaxis_title=unit,
        yaxis_title="Arrondissement",
        yaxis={"categoryorder": "total ascending"},
        height=620,
    )
    st.plotly_chart(figure, width="stretch")
    st.caption(
        f"Seuls les arrondissements comptant au moins "
        f"{payload.get('min_sample_size', 30)} observations sont classés."
    )
    show_warnings(payload)


def render_comparison(
    client: RealEstateApiClient, start_year: int, end_year: int
) -> None:
    """Render cross-area KPIs and price trends."""
    st.subheader("Comparaison d’arrondissements")
    areas = st.multiselect(
        "Choisissez entre 2 et 5 arrondissements",
        options=list(range(1, 21)),
        default=[13, 20],
        format_func=arrondissement_label,
        max_selections=5,
    )
    if len(areas) < 2:
        st.info("Sélectionnez au moins deux arrondissements pour comparer.")
        return

    payload = run_request(client.market_comparison, areas, start_year, end_year)
    records = payload.get("areas", [])
    st.dataframe(
        [
            {
                "Arrondissement": arrondissement_label(item["arrondissement"]),
                "Prix médian (€/m²)": item["median_price_per_m2"],
                "Transactions": item["market_analysis_transactions"],
                "Surface médiane (m²)": item["median_residential_surface"],
                "P25": item["price_p25"],
                "P75": item["price_p75"],
            }
            for item in records
        ],
        width="stretch",
        hide_index=True,
    )

    price_figure = go.Figure(
        go.Bar(
            x=[arrondissement_label(item["arrondissement"]) for item in records],
            y=[item["median_price_per_m2"] for item in records],
            marker_color="#176B87",
        )
    )
    price_figure.update_layout(
        title="Prix médian au m²",
        xaxis_title="Arrondissement",
        yaxis_title="€/m²",
    )
    st.plotly_chart(price_figure, width="stretch")

    trend_figure = go.Figure()
    for area in areas:
        trend = run_request(client.market_trends, area, start_year, end_year)
        trend_figure.add_trace(
            go.Scatter(
                x=[point["year"] for point in trend.get("points", [])],
                y=[
                    point["median_price_per_m2"]
                    for point in trend.get("points", [])
                ],
                mode="lines+markers",
                name=arrondissement_label(area),
            )
        )
    trend_figure.update_layout(
        title="Évolution comparée des prix",
        xaxis_title="Année",
        yaxis_title="€/m²",
        hovermode="x unified",
    )
    st.plotly_chart(trend_figure, width="stretch")
    show_warnings(payload)


def render_dpe(
    client: RealEstateApiClient,
    arrondissement: int | None,
    start_year: int,
    end_year: int,
) -> None:
    """Render DPE label and energy-intensity indicators."""
    distribution = run_request(
        client.dpe_distribution, arrondissement, start_year, end_year
    )
    intensity = run_request(
        client.dpe_intensity, arrondissement, start_year, end_year
    )
    st.subheader(f"Performance énergétique — {arrondissement_label(arrondissement)}")

    columns = st.columns(4)
    columns[0].metric(
        "Diagnostics éligibles",
        format_integer(distribution.get("eligible_dpe_count")),
    )
    columns[1].metric(
        "Classes F + G",
        format_percentage(distribution.get("fg_percentage")),
    )
    columns[2].metric(
        "Consommation médiane",
        (
            f"{intensity['median_consumption']:.1f} kWh/m²/an"
            if intensity.get("median_consumption") is not None
            else "N/D"
        ),
    )
    columns[3].metric(
        "Émissions médianes",
        (
            f"{intensity['median_emissions']:.1f} kgCO₂/m²/an"
            if intensity.get("median_emissions") is not None
            else "N/D"
        ),
    )

    labels = list(DPE_COLORS)
    percentages = distribution.get("percentages", {})
    figure = go.Figure(
        go.Bar(
            x=labels,
            y=[percentages.get(label, 0) for label in labels],
            marker_color=[DPE_COLORS[label] for label in labels],
            text=[f"{percentages.get(label, 0):.2f} %" for label in labels],
            textposition="outside",
        )
    )
    figure.update_layout(
        title="Répartition des étiquettes DPE",
        xaxis_title="Classe DPE",
        yaxis_title="Part des diagnostics (%)",
    )
    st.plotly_chart(figure, width="stretch")

    with st.expander("Détails des intensités"):
        st.json(
            {
                "Échantillon intensité": intensity.get("eligible_intensity_count"),
                "Consommation P25": intensity.get("consumption_p25"),
                "Consommation médiane": intensity.get("median_consumption"),
                "Consommation P75": intensity.get("consumption_p75"),
                "Émissions P25": intensity.get("emissions_p25"),
                "Émissions médianes": intensity.get("median_emissions"),
                "Émissions P75": intensity.get("emissions_p75"),
                "Surface médiane": intensity.get("median_surface"),
            }
        )
    show_warnings(distribution)
    show_warnings(intensity)


def render_profile(
    client: RealEstateApiClient,
    arrondissement: int | None,
    start_year: int,
    end_year: int,
) -> None:
    """Render one arrondissement's combined aggregate market/DPE profile.

    The arrondissement comes from the single global "Zone analysée" selector.
    "Paris entier" is not a valid profile scope, so we ask for one area.
    """
    st.subheader("Profil complet d’un arrondissement")
    if arrondissement is None:
        st.info(
            "Sélectionnez un arrondissement précis dans « Zone analysée » "
            "(le profil complet ne s’applique pas à « Paris entier »)."
        )
        return

    payload = run_request(client.area_profile, arrondissement, start_year, end_year)
    market = payload["market"]
    dpe = payload["dpe_distribution"]
    intensity = payload["dpe_intensity"]

    st.markdown(f"### {arrondissement_label(arrondissement)}")
    columns = st.columns(5)
    columns[0].metric("Prix médian", format_euro_per_m2(market["median_price_per_m2"]))
    columns[1].metric(
        "Transactions", format_integer(market["market_analysis_transactions"])
    )
    columns[2].metric("Surface médiane", format_surface(market["median_residential_surface"]))
    columns[3].metric("DPE F + G", format_percentage(dpe["fg_percentage"]))
    columns[4].metric(
        "Consommation médiane",
        (
            f"{intensity['median_consumption']:.1f} kWh/m²/an"
            if intensity["median_consumption"] is not None
            else "N/D"
        ),
    )
    st.info(
        "Les indicateurs DVF et DPE sont rapprochés uniquement au niveau agrégé "
        "de l’arrondissement et de la période."
    )
    show_warnings(payload)
    show_warnings(market)
    show_warnings(dpe)
    show_warnings(intensity)


# --------------------------------------------------------------------------- #
# Navigation
# --------------------------------------------------------------------------- #

PAGES = [
    "Vue d’ensemble",
    "Classements",
    "Comparaison",
    "DPE",
    "Profil arrondissement",
    AGENT_PAGE,
]


def main() -> None:
    """Configure navigation and render only the selected section."""
    if "nav_page" not in st.session_state:
        st.session_state["nav_page"] = PAGES[0]

    st.title("🏙️ Paris Real Estate Intelligence")
    st.caption(
        "Analyse déterministe du marché résidentiel parisien à partir des "
        "données publiques DVF et DPE."
    )

    # Analytics pages advertise the assistant. Its own page renders one header only.
    if st.session_state["nav_page"] != AGENT_PAGE:
        render_ai_hero()

    with st.sidebar:
        st.header("Navigation")
        page = st.radio("Analyse", PAGES, key="nav_page")

        start_year, end_year = (2021, 2025)
        area_choice: int | None = None
        st.divider()
        if page == AGENT_PAGE:
            st.success("Agent multi-outils actif")
            st.caption(
                "Mémoire de session · Analytics PostgreSQL · RAG avec citations."
            )
        else:
            st.header("Filtres")
            start_year, end_year = st.slider(
                "Période",
                min_value=2021,
                max_value=2026,
                value=(2021, 2025),
            )

            # The global geographic selector appears only where it applies.
            if page in GLOBAL_AREA_PAGES:
                area_choice = st.selectbox(
                    "Zone analysée",
                    options=[None, *range(1, 21)],
                    format_func=arrondissement_label,
                    help="« Paris entier » agrège les 20 arrondissements.",
                )
        st.divider()
        st.caption(f"API : {api_client().base_url}")

    client = api_client()
    if page == AGENT_PAGE:
        render_agent_chat(client)
        return

    if end_year == 2026:
        st.warning(
            "L’année DPE 2026 est partielle. Les résultats qui l’incluent "
            "doivent être interprétés avec prudence."
        )

    if page == "Vue d’ensemble":
        render_overview(client, area_choice, start_year, end_year)
    elif page == "Classements":
        render_rankings(client, start_year, end_year)
    elif page == "Comparaison":
        render_comparison(client, start_year, end_year)
    elif page == "DPE":
        render_dpe(client, area_choice, start_year, end_year)
    else:  # Profil arrondissement
        render_profile(client, area_choice, start_year, end_year)

    st.divider()
    with st.expander("Méthodologie et limites"):
        st.markdown(
            """
- Les prix proviennent des transactions résidentielles DVF validées.
- Les observations hors de la bande de plausibilité approuvée sont exclues des
  indicateurs de marché, sans être supprimées de la base.
- Les statistiques DPE représentent les diagnostics enregistrés et non un
  recensement exhaustif du parc immobilier parisien.
- DVF et DPE ne sont jamais joints individuellement par adresse : leur mise en
  perspective est uniquement agrégée par arrondissement et période.
- L’année DPE 2026 est partielle et exclue par défaut.
- Ces résultats sont informatifs et ne constituent pas un conseil financier.
            """
        )


if __name__ == "__main__":
    main()
