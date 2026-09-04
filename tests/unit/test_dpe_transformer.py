"""Unit tests for the DPE transformer, using small synthetic fixtures only."""

from __future__ import annotations

import pandas as pd

from real_estate_agent.processing.dpe.transformer import (
    PROCESSED_COLUMNS,
    add_quality_flags,
    derive_arrondissement,
    geography_consistent,
    load_snapshot_frame,
    normalize_building_type,
    normalize_label,
    resolve_duplicates,
    select_processed_columns,
)


def _record(**kwargs) -> dict:
    rec = {
        "_id": "id1",
        "numero_dpe": "DPE-1",
        "date_etablissement_dpe": "2023-05-01",
        "date_reception_dpe": "2023-05-02",
        "date_fin_validite_dpe": "2033-05-01",
        "etiquette_dpe": "D",
        "etiquette_ges": "C",
        "conso_5_usages_par_m2_ep": 250.0,
        "emission_ges_5_usages_par_m2": 30.0,
        "surface_habitable_logement": 45.0,
        "type_batiment": "appartement",
        "periode_construction": "1948-1974",
        "code_postal_ban": "75015",
        "code_insee_ban": "75115",
        "code_departement_ban": "75",
        "_geopoint": "48.84,2.29",
    }
    rec.update(kwargs)
    return rec


def _flagged(records: list[dict]) -> pd.DataFrame:
    df = load_snapshot_frame(records)
    resolved, _ = resolve_duplicates(df)
    return add_quality_flags(resolved)


# --------------------------------------------------------------------------- #
# INSEE arrondissement mapping + postal fallback
# --------------------------------------------------------------------------- #

def test_insee_arrondissement_mapping():
    insee = pd.Series(["75101", "75120", "75115"], dtype="string")
    postal = pd.Series([pd.NA, pd.NA, pd.NA], dtype="string")
    arr, source = derive_arrondissement(insee, postal)
    assert arr.tolist() == [1, 20, 15]
    assert source.tolist() == ["insee", "insee", "insee"]


def test_postal_fallback_when_insee_missing():
    insee = pd.Series([pd.NA], dtype="string")
    postal = pd.Series(["75011"], dtype="string")
    arr, source = derive_arrondissement(insee, postal)
    assert arr.tolist() == [11]
    assert source.tolist() == ["postal"]


def test_invalid_arrondissement_is_na():
    insee = pd.Series(["92050"], dtype="string")
    postal = pd.Series(["92000"], dtype="string")
    arr, _ = derive_arrondissement(insee, postal)
    assert pd.isna(arr.iloc[0])


# --------------------------------------------------------------------------- #
# Geography inconsistency
# --------------------------------------------------------------------------- #

def test_geography_inconsistency_flagged():
    insee = pd.Series(["75115"], dtype="string")   # arr 15
    postal = pd.Series(["75016"], dtype="string")  # arr 16 -> disagree
    consistent = geography_consistent(insee, postal)
    assert bool(consistent.iloc[0]) is False


def test_geography_consistent_when_agree():
    insee = pd.Series(["75115"], dtype="string")
    postal = pd.Series(["75015"], dtype="string")
    assert bool(geography_consistent(insee, postal).iloc[0]) is True


# --------------------------------------------------------------------------- #
# Valid / invalid DPE labels
# --------------------------------------------------------------------------- #

def test_valid_and_invalid_labels():
    labels = pd.Series(["A", "g", "X", None], dtype="string")
    norm = normalize_label(labels)
    assert norm.iloc[0] == "A"
    assert norm.iloc[1] == "G"   # lowercased input normalized
    assert pd.isna(norm.iloc[2])  # invalid
    assert pd.isna(norm.iloc[3])


# --------------------------------------------------------------------------- #
# Building type normalization
# --------------------------------------------------------------------------- #

def test_building_type_normalization():
    types = pd.Series(["Appartement", "MAISON", "immeuble", "chateau"], dtype="string")
    norm = normalize_building_type(types)
    assert norm.tolist()[:3] == ["appartement", "maison", "immeuble"]
    assert pd.isna(norm.iloc[3])  # unknown flagged as NA


# --------------------------------------------------------------------------- #
# Exact duplicates, duplicate numero_dpe, conflicting duplicates
# --------------------------------------------------------------------------- #

def test_exact_duplicates_counted():
    df = load_snapshot_frame([_record(), _record()])  # identical
    _, stats = resolve_duplicates(df)
    assert stats["exact_duplicates"] == 1
    assert stats["rows_after"] == 1


def test_duplicate_numero_dpe_deduplicated():
    df = load_snapshot_frame([
        _record(_id="a", date_etablissement_dpe="2022-01-01"),
        _record(_id="b", date_etablissement_dpe="2023-01-01"),  # newer, same DPE
    ])
    resolved, stats = resolve_duplicates(df)
    assert stats["unique_numero_dpe"] == 1
    # Deterministic resolution keeps the newest establishment date.
    assert resolved.iloc[0]["_id"] == "b"


def test_conflicting_duplicates_counted():
    df = load_snapshot_frame([
        _record(_id="a", etiquette_dpe="D"),
        _record(_id="b", etiquette_dpe="E"),  # same numero_dpe, different label
    ])
    _, stats = resolve_duplicates(df)
    assert stats["conflicting_duplicates"] == 1


def test_missing_numero_dpe_counted():
    df = load_snapshot_frame([_record(numero_dpe=None)])
    _, stats = resolve_duplicates(df)
    assert stats["missing_numero_dpe"] == 1


# --------------------------------------------------------------------------- #
# Missing dates / numeric conversion / surface
# --------------------------------------------------------------------------- #

def test_missing_date_parsed_as_nat():
    df = load_snapshot_frame([_record(date_etablissement_dpe=None)])
    assert pd.isna(df.iloc[0]["date_etablissement_dpe"])


def test_numeric_conversion():
    df = load_snapshot_frame([_record(surface_habitable_logement="45.5")])
    assert df.iloc[0]["surface_habitable_logement"] == 45.5


def test_zero_surface_flagged_invalid():
    flagged = _flagged([_record(surface_habitable_logement=0.0)])
    assert bool(flagged.iloc[0]["is_valid_surface"]) is False
    assert flagged.iloc[0]["exclusion_reason"] == "invalid_surface"


def test_missing_surface_flagged_invalid():
    flagged = _flagged([_record(surface_habitable_logement=None)])
    assert bool(flagged.iloc[0]["is_valid_surface"]) is False


# --------------------------------------------------------------------------- #
# Eligibility + exclusion reasons
# --------------------------------------------------------------------------- #

def test_clean_record_is_eligible():
    flagged = _flagged([_record()])
    assert bool(flagged.iloc[0]["is_analysis_eligible"]) is True
    assert pd.isna(flagged.iloc[0]["exclusion_reason"])


def test_invalid_arrondissement_excluded():
    flagged = _flagged([_record(code_insee_ban="92050", code_postal_ban="92000")])
    assert flagged.iloc[0]["exclusion_reason"] == "invalid_arrondissement"


def test_invalid_label_excluded():
    flagged = _flagged([_record(etiquette_dpe="Z")])
    assert flagged.iloc[0]["exclusion_reason"] == "invalid_dpe_label"


# --------------------------------------------------------------------------- #
# Deterministic duplicate resolution is stable
# --------------------------------------------------------------------------- #

def test_deterministic_resolution_is_stable():
    records = [
        _record(_id="b", date_etablissement_dpe="2023-01-01"),
        _record(_id="a", date_etablissement_dpe="2023-01-01"),  # tie on date
    ]
    r1, _ = resolve_duplicates(load_snapshot_frame(records))
    r2, _ = resolve_duplicates(load_snapshot_frame(list(reversed(records))))
    # Tie broken by _id ascending -> "a" wins, regardless of input order.
    assert r1.iloc[0]["_id"] == "a"
    assert r2.iloc[0]["_id"] == "a"


# --------------------------------------------------------------------------- #
# No detailed address fields in processed output
# --------------------------------------------------------------------------- #

def test_processed_output_has_no_address_fields():
    flagged = _flagged([_record()])
    processed = select_processed_columns(flagged)
    forbidden = {
        "adresse_ban", "adresse_brut", "nom_rue_ban", "numero_rue_ban",
        "adresse_nom_voie", "adresse_numero",
    }
    assert forbidden.isdisjoint(set(processed.columns))
    # Only declared processed columns are present.
    assert set(processed.columns).issubset(set(PROCESSED_COLUMNS))


# --------------------------------------------------------------------------- #
# Phase 2.2 corrections: population, split eligibility, partial year, outliers
# --------------------------------------------------------------------------- #

def test_appartement_and_maison_are_dwelling_unit():
    flagged = _flagged([
        _record(numero_dpe="A", type_batiment="appartement"),
        _record(numero_dpe="B", type_batiment="maison"),
    ])
    pops = set(flagged["analysis_population"].tolist())
    assert pops == {"dwelling_unit"}


def test_immeuble_is_whole_building():
    flagged = _flagged([_record(type_batiment="immeuble")])
    assert flagged.iloc[0]["analysis_population"] == "whole_building"


def test_immeuble_excluded_from_dwelling_analytics():
    flagged = _flagged([_record(type_batiment="immeuble")])
    row = flagged.iloc[0]
    # Not eligible for either dwelling-level population analysis.
    assert bool(row["is_label_analysis_eligible"]) is False
    assert bool(row["is_intensity_analysis_eligible"]) is False
    assert row["label_exclusion_reason"] == "not_dwelling_unit"


def test_valid_dpe_without_surface_still_label_eligible():
    flagged = _flagged([_record(surface_habitable_logement=None)])
    row = flagged.iloc[0]
    # Missing surface must NOT block label-distribution analysis.
    assert bool(row["is_label_analysis_eligible"]) is True
    assert pd.isna(row["label_exclusion_reason"])


def test_same_record_ineligible_for_intensity_without_surface():
    flagged = _flagged([_record(surface_habitable_logement=None)])
    row = flagged.iloc[0]
    assert bool(row["is_intensity_analysis_eligible"]) is False
    assert row["intensity_exclusion_reason"] == "invalid_surface"


def test_complete_analysis_years_2021_2025():
    recs = [
        _record(numero_dpe=f"Y{y}", date_etablissement_dpe=f"{y}-06-01")
        for y in (2021, 2022, 2023, 2024, 2025)
    ]
    flagged = _flagged(recs)
    assert bool(flagged["is_complete_analysis_year"].all()) is True
    assert bool(flagged["is_partial_year"].any()) is False


def test_2026_is_partial_year():
    flagged = _flagged([_record(date_etablissement_dpe="2026-03-01")])
    row = flagged.iloc[0]
    assert bool(row["is_partial_year"]) is True
    assert bool(row["is_complete_analysis_year"]) is False
    # 2026 is retained, not deleted.
    assert row["diagnostic_year"] == 2026


def test_outlier_record_not_physically_deleted():
    # An extreme surface value is an outlier, not invalid data: it must remain.
    flagged = _flagged([
        _record(numero_dpe="NORMAL", surface_habitable_logement=45.0),
        _record(numero_dpe="OUTLIER", surface_habitable_logement=18637.0),
    ])
    numbers = set(flagged["numero_dpe"].tolist())
    assert "OUTLIER" in numbers  # preserved
    # The outlier has a valid (positive) surface, so it stays intensity-eligible.
    outlier = flagged[flagged["numero_dpe"] == "OUTLIER"].iloc[0]
    assert bool(outlier["is_valid_surface"]) is True
    assert bool(outlier["is_intensity_analysis_eligible"]) is True
