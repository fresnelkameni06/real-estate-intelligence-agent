"""Small helpers for secrets supplied directly or as mounted files."""

from __future__ import annotations

from pathlib import Path


def require_secret(
    direct_value: str | None,
    file_path: str | None,
    *,
    variable_name: str,
) -> str:
    """Return a non-empty secret without including it in an error message."""
    if direct_value is not None and direct_value.strip():
        return direct_value.strip()

    if file_path is not None and file_path.strip():
        path = Path(file_path.strip())
        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise RuntimeError(
                f"{variable_name}_FILE could not be read."
            ) from exc
        if value:
            return value
        raise RuntimeError(f"{variable_name}_FILE is empty.")

    raise RuntimeError(
        f"{variable_name} is not set. Configure it as an environment "
        f"variable or mount it through {variable_name}_FILE."
    )
