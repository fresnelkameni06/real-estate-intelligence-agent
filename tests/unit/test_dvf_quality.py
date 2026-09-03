"""Unit tests for the DVF quality metrics, using synthetic fixtures only."""

from __future__ import annotations

import pandas as pd

from real_estate_agent.processing.dvf.quality import (
    excluded_nature_counts,
    invalid_paris_code_count,
    missing_required_counts,
)
from real_estate_agent.processing.dvf.transformer import (
    add_lineage,
    handle_exact_duplicates,
)

BASE_COLUMNS = [
    "id_mutation", "date_mutation", "nature_mutation", "valeur_fonciere",
    "code_commune", "code_departement", "id_parcelle", "type_local",
    "surface_reelle_bati", "nombre_pieces_principales", "longitude", "latitude",
]


def _row(**kwargs) -> dict:
    row = {
        "id_mutation": "2025-1",
        "date_mutation": pd.Timestamp("2025-03-01"),
        "nature_mutation": "Vente",
        "valeur_fonciere": 500000.0,
        "code_commune": "75115",
        "code_departement": "75",
        "id_parcelle": "751150001",
        "type_local": "Appartement",
        "surface_reelle_bati": 50.0,
        "nombre_pieces_principales": 3.0,
        "longitude": 2.29,
        "latitude": 48.84,
    }
    row.update(kwargs)
    return row


def _frame(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=BASE_COLUMNS)
    return add_lineage(df, 2025, "data/raw/dvf/2025/75.csv.gz", "deadbeef")


def test_excluded_nature_counts():
    rows = [
        _row(nature_mutation="Vente"),
        _row(nature_mutation="Échange", id_mutation="2025-2"),
        _row(nature_mutation="Adjudication", id_mutation="2025-3"),
    ]
    deduped, _ = handle_exact_duplicates(_frame(rows))
    counts = excluded_nature_counts(deduped)
    assert counts["Échange"] == 1
    assert counts["Adjudication"] == 1
    assert counts["Vente terrain à bâtir"] == 0


def test_invalid_paris_code_count():
    rows = [
        _row(code_commune="75115"),
        _row(code_commune="92050", id_mutation="2025-2"),
        _row(code_commune="75199", id_mutation="2025-3"),  # out of 75101-75120
    ]
    deduped, _ = handle_exact_duplicates(_frame(rows))
    # Two sale rows have invalid Paris arrondissement codes.
    assert invalid_paris_code_count(deduped) == 2


def test_missing_required_counts():
    rows = [
        _row(valeur_fonciere=None),
        _row(valeur_fonciere=500000.0, id_mutation="2025-2"),
    ]
    deduped, _ = handle_exact_duplicates(_frame(rows))
    missing = missing_required_counts(deduped)
    assert missing["valeur_fonciere"] == 1
    assert missing["id_mutation"] == 0


def test_coordinate_coverage_same_definition_global_and_annual():
    """Regression: global and annual coordinate coverage must use the same
    population (residential components), so a multi-unit mutation with null
    mutation-level coordinates must not drag the global figure below the annual.
    """
    from real_estate_agent.processing.dvf.quality import build_year_metrics
    from real_estate_agent.processing.dvf.transformer import (
        add_price_eligibility,
        build_mutations,
        build_residential_components,
    )

    # Two mutations: one single-unit (coords set), one multi-unit (two flats,
    # each with coords, but the mutation-level row will have null coords).
    rows = [
        _row(id_mutation="2025-1", id_parcelle="p1"),
        _row(id_mutation="2025-2", id_parcelle="p2"),
        _row(id_mutation="2025-2", id_parcelle="p3"),  # second flat -> multi-unit
    ]
    frame = _frame(rows)
    deduped, stats = handle_exact_duplicates(frame)
    components = build_residential_components(deduped)
    mutations = add_price_eligibility(build_mutations(deduped))

    annual = build_year_metrics(len(frame), stats, deduped, components, mutations)
    # All three components have coordinates -> annual coverage is 100%.
    assert annual["coordinate_coverage_pct"] == 100.0

    # The multi-unit mutation has null mutation-level coords; if the global
    # figure were computed on mutations it would be < 100. Computed on
    # components (the correct definition) it stays 100.
    comp_coverage = round(
        components[["longitude", "latitude"]].notna().all(axis=1).mean() * 100, 2
    )
    assert comp_coverage == annual["coordinate_coverage_pct"]
