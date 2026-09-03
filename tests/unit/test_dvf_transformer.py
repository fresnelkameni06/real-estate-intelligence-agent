"""Unit tests for the DVF transformer, using small synthetic fixtures only.

No network calls, no public dataset downloads. Each fixture row is hand-built to
exercise one grain/eligibility rule.
"""

from __future__ import annotations

import pandas as pd
import pytest

from real_estate_agent.processing.dvf.transformer import (
    SchemaError,
    add_lineage,
    add_price_eligibility,
    build_mutations,
    build_residential_components,
    derive_arrondissement,
    detect_encoding_corruption,
    handle_exact_duplicates,
    validate_schema,
)

BASE_COLUMNS = [
    "id_mutation", "date_mutation", "nature_mutation", "valeur_fonciere",
    "code_commune", "code_departement", "id_parcelle", "type_local",
    "surface_reelle_bati", "nombre_pieces_principales", "longitude", "latitude",
    "code_postal", "code_type_local", "adresse_code_voie", "numero_disposition",
    "nombre_lots",
]


def _row(**kwargs) -> dict:
    """Build a fixture row with sensible Paris defaults, overridable per test."""
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
        "code_postal": "75015",
        "code_type_local": "2",
        "adresse_code_voie": "1234",
        "numero_disposition": "1",
        "nombre_lots": 1,
    }
    row.update(kwargs)
    return row


def _frame(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=BASE_COLUMNS)
    return add_lineage(df, 2025, "data/raw/dvf/2025/75.csv.gz", "deadbeef")


def _mutations_from(rows: list[dict]) -> pd.DataFrame:
    deduped, _ = handle_exact_duplicates(_frame(rows))
    return add_price_eligibility(build_mutations(deduped))


# --------------------------------------------------------------------------- #
# 1. One apartment sale
# --------------------------------------------------------------------------- #

def test_single_apartment_sale_is_eligible():
    m = _mutations_from([_row()])
    assert len(m) == 1
    assert m.iloc[0]["residential_unit_count"] == 1
    assert bool(m.iloc[0]["is_price_per_m2_eligible"]) is True
    assert m.iloc[0]["price_per_m2_raw"] == pytest.approx(500000.0 / 50.0)


# --------------------------------------------------------------------------- #
# 2. Apartment + dependency: one mutation, one residential unit, still eligible
# --------------------------------------------------------------------------- #

def test_apartment_plus_dependency_stays_eligible():
    rows = [
        _row(id_parcelle="751150001"),
        _row(type_local="Dépendance", surface_reelle_bati=None,
             nombre_pieces_principales=0.0, id_parcelle="751150002"),
    ]
    m = _mutations_from(rows)
    assert len(m) == 1
    r = m.iloc[0]
    assert r["residential_unit_count"] == 1
    assert r["dependency_count"] == 1
    assert bool(r["is_price_per_m2_eligible"]) is True


# --------------------------------------------------------------------------- #
# 3. Two apartments (same type): count == 2, NOT eligible
# --------------------------------------------------------------------------- #

def test_two_apartments_same_type_count_two_not_eligible():
    rows = [
        _row(id_parcelle="751150001"),
        _row(id_parcelle="751150002"),
    ]
    m = _mutations_from(rows)
    assert len(m) == 1
    r = m.iloc[0]
    # The important correction: two Appartement rows == two units, not nunique==1.
    assert r["residential_unit_count"] == 2
    assert bool(r["is_price_per_m2_eligible"]) is False
    assert r["price_ineligibility_reason"] == "not_single_residential_unit"


# --------------------------------------------------------------------------- #
# 4. Apartment + house: residential_unit_count == 2
# --------------------------------------------------------------------------- #

def test_apartment_plus_house_count_two():
    rows = [
        _row(type_local="Appartement", id_parcelle="751150001"),
        _row(type_local="Maison", id_parcelle="751150002"),
    ]
    m = _mutations_from(rows)
    r = m.iloc[0]
    assert r["residential_unit_count"] == 2
    assert r["apartment_count"] == 1
    assert r["house_count"] == 1


# --------------------------------------------------------------------------- #
# 5. Exact duplicate row: removed only from the working copy
# --------------------------------------------------------------------------- #

def test_exact_duplicate_removed_from_working_copy():
    rows = [_row(), _row()]  # identical rows
    frame = _frame(rows)
    deduped, stats = handle_exact_duplicates(frame)
    assert stats["rows_before_dedup"] == 2
    assert stats["exact_duplicates"] == 1
    assert stats["rows_after_dedup"] == 1
    # Raw frame is untouched.
    assert len(frame) == 2


# --------------------------------------------------------------------------- #
# 6. Missing surface -> not eligible
# --------------------------------------------------------------------------- #

def test_missing_surface_not_eligible():
    m = _mutations_from([_row(surface_reelle_bati=None)])
    r = m.iloc[0]
    assert bool(r["is_price_per_m2_eligible"]) is False
    assert r["price_ineligibility_reason"] == "missing_or_nonpositive_surface"


# --------------------------------------------------------------------------- #
# 7. Zero surface -> not eligible
# --------------------------------------------------------------------------- #

def test_zero_surface_not_eligible():
    m = _mutations_from([_row(surface_reelle_bati=0.0)])
    assert m.iloc[0]["price_ineligibility_reason"] == "missing_or_nonpositive_surface"


# --------------------------------------------------------------------------- #
# 8. Missing or zero mutation value -> not eligible
# --------------------------------------------------------------------------- #

def test_zero_value_not_eligible():
    m = _mutations_from([_row(valeur_fonciere=0.0)])
    assert m.iloc[0]["price_ineligibility_reason"] == "missing_or_nonpositive_value"


def test_missing_value_not_eligible():
    m = _mutations_from([_row(valeur_fonciere=None)])
    assert m.iloc[0]["price_ineligibility_reason"] == "missing_or_nonpositive_value"


# --------------------------------------------------------------------------- #
# 9. Invalid Paris code -> not eligible (invalid arrondissement)
# --------------------------------------------------------------------------- #

def test_invalid_paris_code_not_eligible():
    m = _mutations_from([_row(code_commune="92050")])
    r = m.iloc[0]
    assert bool(r["is_price_per_m2_eligible"]) is False
    assert r["price_ineligibility_reason"] == "invalid_arrondissement"


# --------------------------------------------------------------------------- #
# 10. Inconsistent mutation values across rows -> not eligible
# --------------------------------------------------------------------------- #

def test_inconsistent_mutation_values_not_eligible():
    rows = [
        _row(valeur_fonciere=500000.0, id_parcelle="751150001"),
        _row(type_local="Dépendance", valeur_fonciere=600000.0,
             surface_reelle_bati=None, id_parcelle="751150002"),
    ]
    m = _mutations_from(rows)
    r = m.iloc[0]
    assert bool(r["value_consistent"]) is False
    assert bool(r["is_price_per_m2_eligible"]) is False
    assert r["price_ineligibility_reason"] == "inconsistent_mutation_value"


# --------------------------------------------------------------------------- #
# 11. Corrupted French-category detection
# --------------------------------------------------------------------------- #

def test_encoding_corruption_detected():
    bad = pd.DataFrame({
        "nature_mutation": ["Vente"],
        "type_local": ["DΘpendance"],  # mojibake
        "nature_culture": [None],
    })
    report = detect_encoding_corruption(bad)
    assert report["looks_clean"] is False
    assert "Θ" in report["mojibake_markers_found"]


def test_validate_schema_raises_on_corruption():
    bad = pd.DataFrame([_row(type_local="DΘpendance")], columns=BASE_COLUMNS)
    with pytest.raises(SchemaError):
        validate_schema(bad, 2025)


def test_validate_schema_raises_on_missing_column():
    df = pd.DataFrame([_row()], columns=BASE_COLUMNS).drop(columns=["valeur_fonciere"])
    with pytest.raises(SchemaError):
        validate_schema(df, 2025)


def test_clean_french_values_pass_validation():
    good = pd.DataFrame(
        [_row(type_local="Dépendance", nature_mutation="Échange")],
        columns=BASE_COLUMNS,
    )
    result = validate_schema(good, 2025)
    assert result["encoding"]["looks_clean"] is True


# --------------------------------------------------------------------------- #
# 12. Arrondissement derivation from 75101 and 75120
# --------------------------------------------------------------------------- #

def test_arrondissement_derivation_bounds():
    codes = pd.Series(["75101", "75120", "75115", "92050", None], dtype="string")
    arr = derive_arrondissement(codes)
    assert arr.iloc[0] == 1
    assert arr.iloc[1] == 20
    assert arr.iloc[2] == 15
    assert pd.isna(arr.iloc[3])
    assert pd.isna(arr.iloc[4])


# --------------------------------------------------------------------------- #
# Extra: residential component table only keeps residential sale rows
# --------------------------------------------------------------------------- #

def test_components_exclude_non_residential_and_non_sale():
    rows = [
        _row(type_local="Appartement"),
        _row(type_local="Dépendance", surface_reelle_bati=None),
        _row(nature_mutation="Échange", type_local="Appartement",
             id_mutation="2025-2"),
    ]
    deduped, _ = handle_exact_duplicates(_frame(rows))
    comp = build_residential_components(deduped)
    # Only the first row qualifies (Vente + Appartement).
    assert len(comp) == 1
    assert comp.iloc[0]["type_local"] == "Appartement"
    assert comp.iloc[0]["arrondissement"] == 15
