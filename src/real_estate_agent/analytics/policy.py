"""Documented analytical rules and plausibility policy.

Centralizes the constants and thresholds that define how market and DPE
analytics behave, so they are auditable in one place rather than scattered.
"""

from __future__ import annotations

# Default complete analytical period (2026 is partial and excluded by default).
DEFAULT_START_YEAR = 2021
DEFAULT_END_YEAR = 2025

# Valid DVF source years present in the fact table.
MIN_VALID_YEAR = 2021
MAX_VALID_YEAR = 2026  # 2026 exists but is partial; allowed only if requested

# Price-per-m2 plausibility band (broad, configurable analytical limits).
# Records outside this band are excluded from the *market* median but never
# deleted; the raw eligible median is also reported for sensitivity.
PRICE_PER_M2_MIN = 1000.0
PRICE_PER_M2_MAX = 50000.0

# Paris arrondissements.
MIN_ARRONDISSEMENT = 1
MAX_ARRONDISSEMENT = 20

# Minimum sample size for a ranking entry to be considered reliable. Below this,
# an arrondissement is reported as "insufficient sample" rather than ranked with
# a potentially noisy median.
MIN_RANKING_SAMPLE = 30

# Comparison input bounds.
MIN_COMPARE_AREAS = 2
MAX_COMPARE_AREAS = 20

# Rounding rules (decimals).
ROUND_PRICE = 2
ROUND_PCT = 2
ROUND_SURFACE = 2
ROUND_INTENSITY = 2

# Valid DPE/GES labels.
VALID_LABELS = ("A", "B", "C", "D", "E", "F", "G")
POOR_LABELS = ("F", "G")  # "passoires thermiques"


def is_partial_year(year: int) -> bool:
    """Return True if the year is a partial (incomplete) analytical year."""
    return year == 2026
