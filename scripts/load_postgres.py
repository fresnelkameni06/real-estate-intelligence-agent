"""Load processed Parquet datasets into PostgreSQL (idempotent).

Usage:
    py scripts/load_postgres.py --dataset dvf
    py scripts/load_postgres.py --dataset dpe
    py scripts/load_postgres.py --dataset all
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from real_estate_agent.database.config import load_settings
from real_estate_agent.database.engine import make_engine
from real_estate_agent.database.loader import load_dataset

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("load_postgres")

REPO_ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load Parquet into PostgreSQL.")
    parser.add_argument("--dataset", choices=["dvf", "dpe", "all"], required=True)
    args = parser.parse_args(argv)

    settings = load_settings()
    engine = make_engine(settings.require_database_url())

    datasets = ["dvf", "dpe"] if args.dataset == "all" else [args.dataset]
    for ds in datasets:
        result = load_dataset(engine, ds, REPO_ROOT)
        if result.get("skipped"):
            logger.info("%s: skipped (idempotent no-op)", ds)
        else:
            logger.info("%s: loaded %d rows in %ss", ds,
                        result["loaded_rows"], result.get("duration_s"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
