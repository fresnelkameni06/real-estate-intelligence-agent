"""Integration tests for the analytics engine (require TEST_DATABASE_URL).

Seeds small controlled synthetic rows into the test database and asserts exact
numerical results. Skipped unless a safe TEST_DATABASE_URL is configured. Never
touches the development database.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from real_estate_agent.analytics import service
from real_estate_agent.analytics.validators import AnalyticsInputError
from real_estate_agent.database.config import load_settings
from real_estate_agent.database.engine import make_engine
from real_estate_agent.database.test_safety import (
    UnsafeTestDatabaseError,
    resolve_safe_test_url,
)

_settings = load_settings()
try:
    _TEST_URL = resolve_safe_test_url(_settings)
except UnsafeTestDatabaseError as exc:
    pytest.skip(f"No safe test database: {exc}", allow_module_level=True)

SCHEMA = "real_estate"


@pytest.fixture(scope="module")
def engine():
    eng = make_engine(_TEST_URL)
    yield eng
    eng.dispose()


@pytest.fixture(scope="module", autouse=True)
def _migrated(engine):
    import os

    from alembic import command
    from alembic.config import Config

    os.environ["DATABASE_URL"] = _TEST_URL
    cfg = Config("alembic.ini")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield
    command.downgrade(cfg, "base")


@pytest.fixture(autouse=True)
def _clean(engine):
    """Clear fact tables before each test for deterministic assertions."""
    with engine.begin() as conn:
        conn.execute(text(f"DELETE FROM {SCHEMA}.dvf_mutations"))
        conn.execute(text(f"DELETE FROM {SCHEMA}.dpe_diagnostics"))
    yield


def _insert_mutation(engine, **kw):
    cols = {
        "id_mutation": kw["id_mutation"],
        "source_year": kw.get("source_year", 2023),
        "arrondissement": kw.get("arrondissement", 15),
        "is_price_per_m2_eligible": kw.get("eligible", True),
        "price_per_m2_raw": kw.get("ppm2"),
        "residential_surface": kw.get("surface"),
    }
    keys = ", ".join(cols.keys())
    vals = ", ".join(f":{k}" for k in cols)
    with engine.begin() as conn:
        conn.execute(
            text(f"INSERT INTO {SCHEMA}.dvf_mutations ({keys}) VALUES ({vals})"),
            cols,
        )


def _insert_dpe(engine, **kw):
    cols = {
        "numero_dpe": kw["numero_dpe"],
        "diagnostic_year": kw.get("year", 2023),
        "arrondissement": kw.get("arrondissement", 15),
        "analysis_population": kw.get("population", "dwelling_unit"),
        "etiquette_dpe_norm": kw.get("label"),
        "is_label_analysis_eligible": kw.get("label_elig", True),
        "is_intensity_analysis_eligible": kw.get("intensity_elig", True),
        "conso_5_usages_par_m2_ep": kw.get("conso"),
        "emission_ges_5_usages_par_m2": kw.get("emis"),
        "surface_habitable_logement": kw.get("surface"),
    }
    keys = ", ".join(cols.keys())
    vals = ", ".join(f":{k}" for k in cols)
    with engine.begin() as conn:
        conn.execute(
            text(f"INSERT INTO {SCHEMA}.dpe_diagnostics ({keys}) VALUES ({vals})"),
            cols,
        )


# --------------------------------------------------------------------------- #
# Median: odd and even sample sizes
# --------------------------------------------------------------------------- #

def test_median_odd_sample(engine):
    for i, ppm2 in enumerate([9000, 10000, 11000]):
        _insert_mutation(engine, id_mutation=f"m{i}", ppm2=ppm2, surface=50)
    ov = service.get_market_overview(engine, 15, 2021, 2025)
    assert ov.median_price_per_m2 == 10000.0  # middle value


def test_median_even_sample(engine):
    for i, ppm2 in enumerate([8000, 10000, 12000, 14000]):
        _insert_mutation(engine, id_mutation=f"m{i}", ppm2=ppm2, surface=50)
    ov = service.get_market_overview(engine, 15, 2021, 2025)
    assert ov.median_price_per_m2 == 11000.0  # (10000+12000)/2


def test_quartiles(engine):
    for i, ppm2 in enumerate([4000, 8000, 12000, 16000, 20000]):
        _insert_mutation(engine, id_mutation=f"m{i}", ppm2=ppm2, surface=50)
    ov = service.get_market_overview(engine, 15, 2021, 2025)
    assert ov.price_p25 == 8000.0
    assert ov.price_p75 == 16000.0


# --------------------------------------------------------------------------- #
# Outlier filtering: raw vs filtered median
# --------------------------------------------------------------------------- #

def test_outlier_filtering_and_sensitivity(engine):
    # Three plausible + one extreme outlier above the band.
    for i, ppm2 in enumerate([9000, 10000, 11000]):
        _insert_mutation(engine, id_mutation=f"m{i}", ppm2=ppm2, surface=50)
    _insert_mutation(engine, id_mutation="out", ppm2=999999, surface=50)

    ov = service.get_market_overview(engine, 15, 2021, 2025)
    assert ov.price_eligible_transactions == 4
    assert ov.market_analysis_transactions == 3  # outlier excluded
    assert ov.excluded_outlier_count == 1
    assert ov.median_price_per_m2 == 10000.0  # filtered
    # Raw median includes the outlier -> different (higher).
    assert ov.raw_eligible_median_price_per_m2 == 10500.0
    assert ov.sensitivity_median_difference == round(10000.0 - 10500.0, 2)


def test_below_band_excluded(engine):
    _insert_mutation(engine, id_mutation="low", ppm2=500, surface=50)  # < 1000
    _insert_mutation(engine, id_mutation="ok", ppm2=10000, surface=50)
    ov = service.get_market_overview(engine, 15, 2021, 2025)
    assert ov.market_analysis_transactions == 1
    assert ov.median_price_per_m2 == 10000.0


# --------------------------------------------------------------------------- #
# Arrondissement filtering
# --------------------------------------------------------------------------- #

def test_arrondissement_filter(engine):
    _insert_mutation(engine, id_mutation="a", ppm2=10000, surface=50, arrondissement=13)
    _insert_mutation(engine, id_mutation="b", ppm2=20000, surface=50, arrondissement=20)
    ov13 = service.get_market_overview(engine, 13, 2021, 2025)
    assert ov13.median_price_per_m2 == 10000.0
    assert ov13.total_residential_transactions == 1


# --------------------------------------------------------------------------- #
# Empty results / invalid inputs
# --------------------------------------------------------------------------- #

def test_empty_market(engine):
    ov = service.get_market_overview(engine, 1, 2021, 2025)
    assert ov.total_residential_transactions == 0
    assert ov.median_price_per_m2 is None
    assert any("No residential" in w for w in ov.warnings)


def test_invalid_year_raises(engine):
    with pytest.raises(AnalyticsInputError):
        service.get_market_overview(engine, 15, 2025, 2021)


def test_invalid_arrondissement_raises(engine):
    with pytest.raises(AnalyticsInputError):
        service.get_market_overview(engine, 99, 2021, 2025)


def test_duplicate_comparison_inputs(engine):
    _insert_mutation(engine, id_mutation="a", ppm2=10000, surface=50, arrondissement=13)
    _insert_mutation(engine, id_mutation="b", ppm2=20000, surface=50, arrondissement=20)
    res = service.compare_arrondissements(engine, [13, 20, 13], 2021, 2025)
    assert len(res.areas) == 2  # de-duplicated


# --------------------------------------------------------------------------- #
# YoY / missing previous year
# --------------------------------------------------------------------------- #

def test_yoy_and_missing_previous(engine):
    _insert_mutation(engine, id_mutation="y22", ppm2=10000, surface=50,
                     source_year=2022)
    _insert_mutation(engine, id_mutation="y23", ppm2=11000, surface=50,
                     source_year=2023)
    trend = service.get_price_trend(engine, 15, 2021, 2025)
    by_year = {p.year: p for p in trend.points}
    # 2022 has no valid previous (2021 empty) -> YoY None.
    assert by_year[2022].yoy_median_change_pct is None
    # 2023 vs 2022 = +10%.
    assert by_year[2023].yoy_median_change_pct == 10.0


# --------------------------------------------------------------------------- #
# Default exclusion of 2026 / explicit inclusion
# --------------------------------------------------------------------------- #

def test_2026_excluded_by_default(engine):
    _insert_mutation(engine, id_mutation="y25", ppm2=10000, surface=50,
                     source_year=2025)
    # 2026 has no source_year in dvf (source_year CHECK is 2021-2025), so DVF
    # cannot hold 2026; assert the default period is 2021-2025.
    ov = service.get_market_overview(engine)
    assert ov.filters.start_year == 2021
    assert ov.filters.end_year == 2025
    assert ov.filters.includes_partial_year is False


def test_partial_year_flag_when_requested(engine):
    # DPE can hold 2026; request including it sets the flag.
    dist = service.get_dpe_distribution(engine, 15, 2021, 2026)
    assert dist.includes_partial_year is True


# --------------------------------------------------------------------------- #
# DPE distribution / F+G / eligibility / whole-building exclusion
# --------------------------------------------------------------------------- #

def test_dpe_distribution_and_fg(engine):
    for i, label in enumerate(["D", "D", "F", "G"]):
        _insert_dpe(engine, numero_dpe=f"d{i}", label=label)
    dist = service.get_dpe_distribution(engine, 15, 2021, 2025)
    assert dist.eligible_dpe_count == 4
    assert dist.counts["D"] == 2
    assert dist.f_count == 1
    assert dist.g_count == 1
    assert dist.fg_count == 2
    assert dist.fg_percentage == 50.0


def test_label_eligibility_excludes_ineligible(engine):
    _insert_dpe(engine, numero_dpe="ok", label="D", label_elig=True)
    _insert_dpe(engine, numero_dpe="no", label="D", label_elig=False)
    dist = service.get_dpe_distribution(engine, 15, 2021, 2025)
    assert dist.eligible_dpe_count == 1


def test_whole_building_excluded_from_dpe(engine):
    _insert_dpe(engine, numero_dpe="dwell", label="D", population="dwelling_unit")
    _insert_dpe(engine, numero_dpe="bldg", label="D", population="whole_building")
    dist = service.get_dpe_distribution(engine, 15, 2021, 2025)
    assert dist.eligible_dpe_count == 1  # whole_building excluded


def test_dpe_intensity_summary(engine):
    for i, (conso, emis) in enumerate([(100, 10), (200, 20), (300, 30)]):
        _insert_dpe(engine, numero_dpe=f"i{i}", label="D", conso=conso, emis=emis,
                    surface=50)
    summ = service.get_dpe_intensity_summary(engine, 15, 2021, 2025)
    assert summ.eligible_intensity_count == 3
    assert summ.median_consumption == 200.0
    assert summ.median_emissions == 20.0


def test_intensity_eligibility_excludes_ineligible(engine):
    _insert_dpe(engine, numero_dpe="ok", label="D", conso=200, emis=20,
                intensity_elig=True)
    _insert_dpe(engine, numero_dpe="no", label="D", conso=999, emis=99,
                intensity_elig=False)
    summ = service.get_dpe_intensity_summary(engine, 15, 2021, 2025)
    assert summ.eligible_intensity_count == 1
    assert summ.median_consumption == 200.0


# --------------------------------------------------------------------------- #
# Rankings / minimum sample size
# --------------------------------------------------------------------------- #

def test_rankings_respect_min_sample(engine):
    # Arr 13: 40 plausible rows (>= MIN_RANKING_SAMPLE=30).
    for i in range(40):
        _insert_mutation(engine, id_mutation=f"a{i}", ppm2=10000, surface=50,
                         arrondissement=13)
    # Arr 20: only 5 rows (< 30) -> excluded from ranking.
    for i in range(5):
        _insert_mutation(engine, id_mutation=f"b{i}", ppm2=20000, surface=50,
                         arrondissement=20)
    rankings = service.get_area_rankings(engine, 2021, 2025)
    ranked_arrs = {e.arrondissement for e in rankings.by_median_price_per_m2}
    assert 13 in ranked_arrs
    assert 20 not in ranked_arrs
    assert any("sample <" in w for w in rankings.warnings)


# --------------------------------------------------------------------------- #
# Area profile: no record-level join
# --------------------------------------------------------------------------- #

def test_area_profile_combines_at_result_level(engine):
    _insert_mutation(engine, id_mutation="m", ppm2=10000, surface=50,
                     arrondissement=15)
    _insert_dpe(engine, numero_dpe="d", label="D", arrondissement=15)
    profile = service.get_area_profile(engine, 15, 2021, 2025)
    assert profile.arrondissement == 15
    assert profile.market.median_price_per_m2 == 10000.0
    assert profile.dpe_distribution.eligible_dpe_count == 1
    # The two come from independent queries on the shared arrondissement.
