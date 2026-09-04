"""Validate a running Phase 5 API against the configured real database.

Start FastAPI first, then run:
    py scripts/validate_application.py

This script sends read-only aggregate HTTP requests. It never connects directly
to PostgreSQL and never prints credentials.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

import httpx

DEFAULT_BASE_URL = "http://localhost:8000"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.getenv("API_BASE_URL", DEFAULT_BASE_URL),
        help="FastAPI base URL (default: API_BASE_URL or http://localhost:8000)",
    )
    return parser


def _get(
    client: httpx.Client,
    path: str,
    params: list[tuple[str, str]] | dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = client.get(path, params=params)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"Unexpected response format for {path}")
    print(f"[OK] {path} -> HTTP {response.status_code}")
    return payload


def main() -> int:
    """Call every critical endpoint and verify a few response invariants."""
    args = _parser().parse_args()
    try:
        with httpx.Client(
            base_url=args.base_url.rstrip("/"), timeout=30, trust_env=False
        ) as client:
            _get(client, "/health")
            _get(client, "/ready")
            overview = _get(
                client,
                "/api/v1/market/overview",
                {"start_year": 2021, "end_year": 2025},
            )
            trend = _get(
                client,
                "/api/v1/market/trends",
                {"start_year": 2021, "end_year": 2025},
            )
            comparison = _get(
                client,
                "/api/v1/market/compare",
                [
                    ("arrondissements", "13"),
                    ("arrondissements", "20"),
                    ("start_year", "2021"),
                    ("end_year", "2025"),
                ],
            )
            distribution = _get(
                client,
                "/api/v1/dpe/distribution",
                {"start_year": 2021, "end_year": 2025},
            )
            _get(
                client,
                "/api/v1/dpe/intensity",
                {"start_year": 2021, "end_year": 2025},
            )
            _get(
                client,
                "/api/v1/areas/13/profile",
                {"start_year": 2021, "end_year": 2025},
            )

        assert overview["market_analysis_transactions"] <= overview[
            "price_eligible_transactions"
        ]
        assert len(trend["points"]) == 5
        assert {item["arrondissement"] for item in comparison["areas"]} == {13, 20}
        assert abs(sum(distribution["percentages"].values()) - 100) < 0.1
    except (httpx.HTTPError, KeyError, AssertionError, RuntimeError) as exc:
        print(f"[FAILED] {exc}", file=sys.stderr)
        return 1

    print("All Phase 5 real-API validation checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
