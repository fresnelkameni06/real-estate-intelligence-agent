"""Deterministic tool exposure policy applied before model orchestration."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence

from real_estate_agent.tools.registry import ToolSpecification

_DPE_MARKERS = (
    "dpe",
    "diagnostic de performance energetique",
    "performance energetique",
    "classe energetique",
    "etiquette energetique",
)
_DPE_STATISTICAL_MARKERS = (
    "repartition",
    "distribution",
    "statistique",
    "pourcentage",
    "proportion",
    "diagnostics",
    "consommation",
    "emission",
    "intensite",
    "classe",
    "etiquette",
)
_MARKET_MARKERS = (
    "prix",
    "transaction",
    "dvf",
    "marche",
    "valeur fonciere",
)
_DOCUMENTARY_MARKERS = (
    "audit",
    "definition",
    "interdiction",
    "location",
    "louer",
    "loi",
    "methodologie",
    "obligation",
    "reglement",
    "restriction",
    "validite",
    "valable",
)


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    without_accents = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return " ".join(re.sub(r"[^a-z0-9]+", " ", without_accents).split())


def allowed_tool_names_for_question(question: str) -> frozenset[str] | None:
    """Return a narrow allow-list for unambiguous requests, otherwise ``None``."""
    normalized = _normalize(question)
    is_dpe = any(marker in normalized for marker in _DPE_MARKERS)
    is_statistical = any(
        marker in normalized for marker in _DPE_STATISTICAL_MARKERS
    )
    is_market = any(marker in normalized for marker in _MARKET_MARKERS)
    is_documentary = any(marker in normalized for marker in _DOCUMENTARY_MARKERS)

    if is_dpe and is_statistical and not is_market and not is_documentary:
        return frozenset({"analyze_dpe"})
    return None


def filter_tool_specifications(
    specifications: Sequence[ToolSpecification],
    question: str,
) -> list[ToolSpecification]:
    """Expose only policy-approved tools for an unambiguous narrow request."""
    allowed_names = allowed_tool_names_for_question(question)
    if allowed_names is None:
        return list(specifications)
    return [item for item in specifications if item.name in allowed_names]
