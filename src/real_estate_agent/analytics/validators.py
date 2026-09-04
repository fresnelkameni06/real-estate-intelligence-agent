"""Input validation for analytics requests.

Raises AnalyticsInputError with a clear message on invalid input. Never builds
SQL; only validates and normalizes parameters.
"""

from __future__ import annotations

from real_estate_agent.analytics import policy


class AnalyticsInputError(ValueError):
    """Raised when analytics inputs are invalid."""


def validate_year_range(start_year: int, end_year: int) -> tuple[int, int]:
    """Validate a year range against the allowed bounds."""
    if start_year > end_year:
        raise AnalyticsInputError(
            f"start_year ({start_year}) must be <= end_year ({end_year})"
        )
    for y in (start_year, end_year):
        if y < policy.MIN_VALID_YEAR or y > policy.MAX_VALID_YEAR:
            raise AnalyticsInputError(
                f"year {y} out of range "
                f"[{policy.MIN_VALID_YEAR}, {policy.MAX_VALID_YEAR}]"
            )
    return start_year, end_year


def validate_arrondissement(arr: int | None) -> int | None:
    """Validate an optional arrondissement (1-20) or None."""
    if arr is None:
        return None
    if arr < policy.MIN_ARRONDISSEMENT or arr > policy.MAX_ARRONDISSEMENT:
        raise AnalyticsInputError(
            f"arrondissement {arr} out of range "
            f"[{policy.MIN_ARRONDISSEMENT}, {policy.MAX_ARRONDISSEMENT}]"
        )
    return arr


def validate_comparison_areas(areas: list[int]) -> list[int]:
    """Validate a list of 2-20 unique valid arrondissements."""
    unique = list(dict.fromkeys(areas))  # de-duplicate, preserve order
    if len(unique) < policy.MIN_COMPARE_AREAS:
        raise AnalyticsInputError(
            f"at least {policy.MIN_COMPARE_AREAS} distinct arrondissements "
            f"required (got {len(unique)})"
        )
    if len(unique) > policy.MAX_COMPARE_AREAS:
        raise AnalyticsInputError(
            f"at most {policy.MAX_COMPARE_AREAS} arrondissements allowed"
        )
    for a in unique:
        validate_arrondissement(a)
    return unique


def includes_partial_year(start_year: int, end_year: int) -> bool:
    """Return True if the requested range includes a partial year (2026)."""
    return any(policy.is_partial_year(y) for y in range(start_year, end_year + 1))
