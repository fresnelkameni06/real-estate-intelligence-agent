"""Unit tests for database helpers that do NOT require a live database.

Covers settings validation, coordinate parsing, Parquet→DB mapping, and the
test-database safety guard.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from real_estate_agent.database.config import (
    DatabaseSettings,
    normalize_database_url,
    safe_url_summary,
)
from real_estate_agent.database.mapping import (
    parse_geopoint,
    prepare_dpe_frame,
    prepare_dvf_frame,
)
from real_estate_agent.database.test_safety import (
    UnsafeTestDatabaseError,
    resolve_safe_test_url,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #

def test_require_database_url_raises_when_missing():
    s = DatabaseSettings(DATABASE_URL=None, _env_file=None)
    with pytest.raises(RuntimeError, match="DATABASE_URL is not set"):
        s.require_database_url()


def test_safe_url_summary_hides_credentials():
    url = "postgresql+psycopg://user:secret@localhost:5432/real_estate"
    summary = safe_url_summary(url)
    assert "secret" not in summary
    assert "user" not in summary
    assert "localhost:5432/real_estate" in summary


@pytest.mark.parametrize("scheme", ["postgres://", "postgresql://"])
def test_cloud_database_urls_use_psycopg_3(scheme: str):
    url = f"{scheme}user:secret@database.internal:5432/real_estate"
    assert normalize_database_url(url).startswith("postgresql+psycopg://")


def test_explicit_database_driver_is_preserved():
    url = "postgresql+psycopg://user:secret@localhost:5432/real_estate"
    assert normalize_database_url(url) == url


def test_alembic_does_not_disable_existing_application_loggers():
    migration_environment = (REPO_ROOT / "database/migrations/env.py").read_text(
        encoding="utf-8"
    )
    assert "disable_existing_loggers=False" in migration_environment


# --------------------------------------------------------------------------- #
# Coordinate parsing
# --------------------------------------------------------------------------- #

def test_parse_geopoint_valid():
    assert parse_geopoint("48.85,2.29") == (48.85, 2.29)


def test_parse_geopoint_malformed_returns_none():
    assert parse_geopoint("not a point") == (None, None)
    assert parse_geopoint("48.85") == (None, None)
    assert parse_geopoint(None) == (None, None)
    assert parse_geopoint(float("nan")) == (None, None)


def test_parse_geopoint_out_of_range_returns_none():
    assert parse_geopoint("999,999") == (None, None)


# --------------------------------------------------------------------------- #
# Test-database safety guard
# --------------------------------------------------------------------------- #

def test_safety_refuses_missing_test_url():
    s = DatabaseSettings(TEST_DATABASE_URL=None, _env_file=None)
    with pytest.raises(UnsafeTestDatabaseError, match="not set"):
        resolve_safe_test_url(s)


def test_safety_refuses_test_equals_dev():
    url = "postgresql+psycopg://u:p@h:5432/real_estate_test"
    s = DatabaseSettings(DATABASE_URL=url, TEST_DATABASE_URL=url, _env_file=None)
    with pytest.raises(UnsafeTestDatabaseError, match="must differ"):
        resolve_safe_test_url(s)


def test_safety_refuses_non_test_name():
    # A non-test database name must be refused.
    s2 = DatabaseSettings(
        DATABASE_URL="postgresql+psycopg://u:p@h:5432/dev",
        TEST_DATABASE_URL="postgresql+psycopg://u:p@h:5432/production",
        _env_file=None,
    )
    with pytest.raises(UnsafeTestDatabaseError, match="look like a test"):
        resolve_safe_test_url(s2)


def test_safety_accepts_valid_test_url():
    s = DatabaseSettings(
        DATABASE_URL="postgresql+psycopg://u:p@h:5432/real_estate",
        TEST_DATABASE_URL="postgresql+psycopg://u:p@h:5432/real_estate_test",
        _env_file=None,
    )
    assert resolve_safe_test_url(s).endswith("/real_estate_test")


# --------------------------------------------------------------------------- #
# Mapping: DVF
# --------------------------------------------------------------------------- #

def _dvf_row() -> dict:
    return {
        "id_mutation": "2025-1", "residential_unit_count": 1, "apartment_count": 1,
        "house_count": 0, "dependency_count": 0, "commercial_unit_count": 0,
        "total_component_count": 1, "distinct_parcel_count": 1,
        "mutation_value": 500000.0, "mutation_date": pd.Timestamp("2025-03-01"),
        "value_consistent": True, "geo_consistent": True,
        "residential_property_type": "Appartement", "residential_surface": 50.0,
        "residential_rooms": 3.0, "arrondissement": 15.0, "longitude": 2.29,
        "latitude": 48.84, "source_year": 2025, "source_file": "f",
        "source_sha256": "x", "is_price_per_m2_eligible": True,
        "price_ineligibility_reason": None, "price_per_m2_raw": 10000.0,
    }


def test_prepare_dvf_casts_arrondissement_to_int():
    df = pd.DataFrame([_dvf_row()])
    out = prepare_dvf_frame(df)
    assert str(out["arrondissement"].dtype) == "Int64"
    assert out["arrondissement"].iloc[0] == 15


def test_prepare_dvf_arrondissement_nan_stays_na():
    row = _dvf_row()
    row["arrondissement"] = float("nan")
    out = prepare_dvf_frame(pd.DataFrame([row]))
    assert pd.isna(out["arrondissement"].iloc[0])


# --------------------------------------------------------------------------- #
# Mapping: DPE
# --------------------------------------------------------------------------- #

def _dpe_row() -> dict:
    return {
        "numero_dpe": "DPE-1", "date_etablissement_dpe": pd.Timestamp("2023-05-01"),
        "date_fin_validite_dpe": pd.Timestamp("2033-05-01"), "diagnostic_year": 2023,
        "etiquette_dpe_norm": "D", "etiquette_ges_norm": "C",
        "surface_habitable_logement": 45.0, "conso_5_usages_par_m2_ep": 250.0,
        "emission_ges_5_usages_par_m2": 30.0, "type_batiment_norm": "appartement",
        "analysis_population": "dwelling_unit", "periode_construction": "1948-1974",
        "arrondissement": 15, "_geopoint": "48.84,2.29",
        "is_valid_arrondissement": True, "is_geography_consistent": True,
        "is_valid_dpe_label": True, "is_valid_ges_label": True,
        "is_valid_surface": True, "is_valid_consumption": True,
        "is_valid_emission": True, "is_residential_unit_type": True,
        "is_label_analysis_eligible": True, "is_intensity_analysis_eligible": True,
        "is_complete_analysis_year": True, "is_partial_year": False,
        "label_exclusion_reason": None, "intensity_exclusion_reason": None,
    }


def test_prepare_dpe_parses_geopoint_columns():
    out = prepare_dpe_frame(pd.DataFrame([_dpe_row()]))
    assert out["latitude"].iloc[0] == 48.84
    assert out["longitude"].iloc[0] == 2.29
    assert "_geopoint" not in out.columns


def test_prepare_dpe_malformed_geopoint_becomes_null():
    row = _dpe_row()
    row["_geopoint"] = "garbage"
    out = prepare_dpe_frame(pd.DataFrame([row]))
    assert pd.isna(out["latitude"].iloc[0])
    assert pd.isna(out["longitude"].iloc[0])


def test_prepare_dpe_rejects_address_columns():
    row = _dpe_row()
    row["adresse_nom_voie"] = "rue de Test"
    with pytest.raises(ValueError, match="Address-level columns"):
        prepare_dpe_frame(pd.DataFrame([row]))


def test_prepare_dpe_has_no_geopoint_or_address():
    out = prepare_dpe_frame(pd.DataFrame([_dpe_row()]))
    assert "_geopoint" not in out.columns
    assert not any("adresse" in c for c in out.columns)
