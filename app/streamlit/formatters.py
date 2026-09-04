"""Presentation-only formatters for dashboard values."""

from __future__ import annotations


def format_integer(value: int | float | None) -> str:
    """Format a count with French-style grouping."""
    if value is None:
        return "N/D"
    return f"{int(value):,}".replace(",", " ")


def format_euro_per_m2(value: int | float | None) -> str:
    """Format a price-per-square-metre value."""
    if value is None:
        return "N/D"
    return f"{float(value):,.0f} €/m²".replace(",", " ")


def format_surface(value: int | float | None) -> str:
    """Format a surface value."""
    if value is None:
        return "N/D"
    return f"{float(value):.1f} m²"


def format_percentage(value: int | float | None, signed: bool = False) -> str:
    """Format a percentage, optionally showing a plus sign."""
    if value is None:
        return "N/D"
    sign = "+" if signed and float(value) > 0 else ""
    return f"{sign}{float(value):.2f} %"


def arrondissement_label(value: int | None) -> str:
    """Return a human-readable Paris scope label."""
    if value is None:
        return "Paris entier"
    suffix = "er" if value == 1 else "e"
    return f"Paris {value}{suffix}"
