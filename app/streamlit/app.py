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

# Future AI-analyst example questions (display only; no LLM is ever called).
AI_EXAMPLE_QUESTIONS = [
    "Compare le 13e et le 20e arrondissement.",
    "Quels arrondissements offrent le meilleur compromis entre prix et DPE ?",
    "Comment les prix ont-ils évolué depuis 2021 ?",
    "Quelles contraintes concernent un logement classé G ?",
    "Analyse le profil d’investissement du 15e arrondissement.",
]

# Roadmap shown on the AI preview page (honest project status).
AI_ROADMAP = [
    ("Data Engineering", True),
    ("PostgreSQL", True),
    ("Analytics Engine", True),
    ("FastAPI", True),
    ("Streamlit", True),
    ("RAG", False),
    ("AI Tools", False),
    ("AI Agent", False),
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
# AI Analyst preview (no LLM, no external call — visual placeholder only)
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
        .ai-orb {
            width: 54px; height: 54px; border-radius: 50%;
            background: radial-gradient(circle at 30% 30%, #8fe3ff, #2c7be5 60%, #14306b);
            box-shadow: 0 0 18px 4px rgba(90, 190, 255, 0.55);
            animation: ai-orb-pulse 2.8s ease-in-out infinite;
            flex: 0 0 auto;
        }
        .ai-hero-title { font-size: 1.35rem; font-weight: 700; margin: 0; }
        .ai-badge {
            display: inline-block; margin-left: 10px; padding: 2px 10px;
            font-size: 0.72rem; font-weight: 600; letter-spacing: .5px;
            border-radius: 999px; background: rgba(255, 214, 102, 0.18);
            color: #ffd666; border: 1px solid rgba(255, 214, 102, 0.5);
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
            background: #ffd666; margin-right: 8px;
            animation: ai-orb-pulse 2s ease-in-out infinite;
        }
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
    """Render the animated AI Analyst hero card below the title/description."""
    _inject_ai_styles()

    # Rotate the example question on each rerun (stable, no JS).
    idx = st.session_state.get("_ai_q_index", 0)
    question = AI_EXAMPLE_QUESTIONS[idx % len(AI_EXAMPLE_QUESTIONS)]
    st.session_state["_ai_q_index"] = (idx + 1) % len(AI_EXAMPLE_QUESTIONS)

    st.markdown(
        f"""
        <div class="ai-hero">
          <div class="ai-hero-row">
            <div class="ai-orb"></div>
            <div>
              <p class="ai-hero-title">🤖 Analyste IA
                <span class="ai-badge">EN CONSTRUCTION</span>
              </p>
              <p class="ai-hero-sub">
                Un assistant conversationnel permettra bientôt d’explorer cette
                plateforme d’intelligence immobilière en langage naturel.
              </p>
              <p class="ai-hero-q">« {question} »</p>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("✨ Découvrir l’Analyste IA", key="ai_hero_button"):
        st.session_state["nav_page"] = "✨ Analyste IA — bientôt"
        st.rerun()


def render_ai_preview() -> None:
    """Render the dedicated AI Analyst preview page (no LLM, disabled input)."""
    _inject_ai_styles()
    st.markdown(
        """
        <div class="ai-hero">
          <div class="ai-hero-row">
            <div class="ai-orb"></div>
            <div>
              <p class="ai-hero-title">🤖 Analyste IA d’investissement immobilier</p>
              <p class="ai-hero-sub">
                <span class="ai-status-dot"></span>
                Bientôt disponible — moteur conversationnel en préparation.
              </p>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        "L’Analyste IA s’appuiera sur le moteur analytique déterministe déjà en "
        "place pour répondre en langage naturel, avec des chiffres calculés par "
        "SQL/Python (jamais inventés par le modèle) et des sources citées."
    )

    st.info(
        "💬 **Message d’accueil (aperçu)** — « Bonjour ! Je pourrai bientôt "
        "analyser le marché parisien, comparer des arrondissements, expliquer "
        "les DPE et la réglementation, et générer des graphiques. Le moteur "
        "conversationnel n’est pas encore activé. »"
    )

    st.subheader("Exemples de questions futures")
    cols = st.columns(2)
    for i, q in enumerate(AI_EXAMPLE_QUESTIONS):
        with cols[i % 2]:
            st.button(q, key=f"ai_example_{i}", disabled=True,
                      use_container_width=True)

    st.subheader("Capacités prévues")
    caps = [
        "Analyses de marché", "Comparaisons d’arrondissements", "Analyse DPE",
        "Recherche documentaire réglementaire", "Citations de sources",
        "Génération de graphiques", "Orchestration multi-outils",
    ]
    st.markdown("".join(f"- {c}\n" for c in caps))

    st.subheader("Fondations du projet")
    r1, r2 = st.columns(2)
    for i, (name, done) in enumerate(AI_ROADMAP):
        target = r1 if i % 2 == 0 else r2
        badge = "✅ Terminé" if done else "🕒 À venir"
        target.markdown(f"**{name}** — {badge}")

    st.divider()
    st.chat_input(
        "L’assistant IA sera activé après les phases RAG, AI Tools et "
        "orchestration…",
        disabled=True,
    )
    st.caption(
        "🔒 Aucune requête n’est envoyée à un modèle de langage. Le moteur "
        "conversationnel sera activé une fois les phases RAG, AI Tools et "
        "orchestration agentique terminées."
    )


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
    "✨ Analyste IA — bientôt",
]


def main() -> None:
    """Configure navigation and render only the selected section."""
    st.title("🏙️ Paris Real Estate Intelligence")
    st.caption(
        "Analyse déterministe du marché résidentiel parisien à partir des "
        "données publiques DVF et DPE."
    )

    # Animated AI hero directly below the title/description.
    render_ai_hero()

    # Stable navigation via session state (survives reruns from the hero button).
    if "nav_page" not in st.session_state:
        st.session_state["nav_page"] = PAGES[0]

    with st.sidebar:
        st.header("Navigation")
        page = st.radio("Analyse", PAGES, key="nav_page")

        st.divider()
        st.header("Filtres")
        start_year, end_year = st.slider(
            "Période",
            min_value=2021,
            max_value=2026,
            value=(2021, 2025),
        )

        # The single global geographic selector appears only where it applies.
        area_choice: int | None = None
        if page in GLOBAL_AREA_PAGES:
            area_choice = st.selectbox(
                "Zone analysée",
                options=[None, *range(1, 21)],
                format_func=arrondissement_label,
                help="« Paris entier » agrège les 20 arrondissements.",
            )
        st.divider()
        st.caption(f"API : {api_client().base_url}")

    if page == "✨ Analyste IA — bientôt":
        render_ai_preview()
        return

    if end_year == 2026:
        st.warning(
            "L’année DPE 2026 est partielle. Les résultats qui l’incluent "
            "doivent être interprétés avec prudence."
        )

    client = api_client()
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
