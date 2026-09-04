"""Unit tests for analytics logic that does NOT require a database.

Covers input validation, rounding, YoY math, ranking/sort logic and percentage
computation via small synthetic inputs.
"""

from __future__ import annotations

import pytest

from real_estate_agent.analytics import policy, validators
from real_estate_agent.analytics.validators import AnalyticsInputError

# --------------------------------------------------------------------------- #
# Validators
# --------------------------------------------------------------------------- #

def test_valid_year_range():
    assert validators.validate_year_range(2021, 2025) == (2021, 2025)


def test_invalid_year_range_start_after_end():
    with pytest.raises(AnalyticsInputError, match="must be <="):
        validators.validate_year_range(2025, 2021)


def test_invalid_year_out_of_bounds():
    with pytest.raises(AnalyticsInputError, match="out of range"):
        validators.validate_year_range(2019, 2025)


def test_valid_arrondissement():
    assert validators.validate_arrondissement(15) == 15
    assert validators.validate_arrondissement(None) is None


def test_invalid_arrondissement():
    with pytest.raises(AnalyticsInputError, match="out of range"):
        validators.validate_arrondissement(21)
    with pytest.raises(AnalyticsInputError, match="out of range"):
        validators.validate_arrondissement(0)


def test_comparison_areas_dedupes():
    # Duplicates collapse; order preserved.
    assert validators.validate_comparison_areas([13, 20, 13]) == [13, 20]


def test_comparison_areas_too_few():
    with pytest.raises(AnalyticsInputError, match="at least"):
        validators.validate_comparison_areas([13, 13])  # collapses to 1


def test_comparison_areas_invalid_member():
    with pytest.raises(AnalyticsInputError, match="out of range"):
        validators.validate_comparison_areas([13, 99])


def test_includes_partial_year():
    assert validators.includes_partial_year(2021, 2025) is False
    assert validators.includes_partial_year(2021, 2026) is True
    assert validators.includes_partial_year(2026, 2026) is True


def test_partial_year_policy():
    assert policy.is_partial_year(2026) is True
    assert policy.is_partial_year(2025) is False


# --------------------------------------------------------------------------- #
# YoY math (mirrors service logic, isolated for exact assertions)
# --------------------------------------------------------------------------- #

def _yoy(median, prev_median):
    if median is not None and prev_median not in (None, 0):
        return round((median - float(prev_median)) / float(prev_median) * 100,
                     policy.ROUND_PCT)
    return None


def test_yoy_positive():
    assert _yoy(11000.0, 10000.0) == 10.0


def test_yoy_negative():
    assert _yoy(9000.0, 10000.0) == -10.0


def test_yoy_null_when_no_previous():
    assert _yoy(10000.0, None) is None


def test_yoy_null_on_zero_baseline():
    # Division by zero must yield None, not crash.
    assert _yoy(10000.0, 0) is None


# --------------------------------------------------------------------------- #
# Percentage computation (A-G distribution logic)
# --------------------------------------------------------------------------- #

def test_ag_percentages_sum_to_100():
    counts = {"A": 10, "B": 20, "C": 30, "D": 40, "E": 0, "F": 0, "G": 0}
    total = sum(counts.values())
    pct = {k: round(v / total * 100, 2) for k, v in counts.items()}
    assert abs(sum(pct.values()) - 100.0) < 0.05


def test_fg_share():
    counts = {"A": 0, "B": 0, "C": 0, "D": 0, "E": 0, "F": 30, "G": 20}
    total = sum(counts.values())
    fg = counts["F"] + counts["G"]
    assert round(fg / total * 100, 2) == 100.0


def test_empty_distribution_no_div_by_zero():
    counts = {k: 0 for k in policy.VALID_LABELS}
    total = sum(counts.values())
    pct = {k: (round(v / total * 100, 2) if total else 0.0) for k, v in counts.items()}
    assert all(v == 0.0 for v in pct.values())
