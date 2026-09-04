"""initial schema: real_estate tables, constraints, indexes, arrondissement seed

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-04
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "real_estate"

# Static seed: 20 Paris arrondissements (INSEE 75101-75120, postal 75001-75020).
_ARRONDISSEMENTS = [
    (n, f"751{n:02d}", f"750{n:02d}", f"Paris {n}{'er' if n == 1 else 'e'}")
    for n in range(1, 21)
]


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")

    # --- arrondissements ---
    op.create_table(
        "arrondissements",
        sa.Column("arrondissement_number", sa.SmallInteger(), primary_key=True),
        sa.Column("insee_code", sa.String(length=5), nullable=False),
        sa.Column("postal_code", sa.String(length=5), nullable=False),
        sa.Column("arrondissement_name", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "arrondissement_number BETWEEN 1 AND 20", name="ck_arr_number_range"
        ),
        sa.CheckConstraint(
            "insee_code BETWEEN '75101' AND '75120'", name="ck_arr_insee_range"
        ),
        sa.CheckConstraint(
            "postal_code BETWEEN '75001' AND '75020'", name="ck_arr_postal_range"
        ),
        sa.UniqueConstraint("insee_code", name="uq_arr_insee"),
        sa.UniqueConstraint("postal_code", name="uq_arr_postal"),
        schema=SCHEMA,
    )

    # --- data_load_runs ---
    op.create_table(
        "data_load_runs",
        sa.Column("load_run_id", sa.BigInteger(), primary_key=True,
                  autoincrement=True),
        sa.Column("dataset_name", sa.Text(), nullable=False),
        sa.Column("source_sha256", sa.Text(), nullable=False),
        sa.Column("source_rows", sa.Integer()),
        sa.Column("loaded_rows", sa.Integer()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.CheckConstraint(
            "status IN ('started', 'succeeded', 'failed')", name="ck_load_status"
        ),
        schema=SCHEMA,
    )
    # Partial unique index: only one SUCCEEDED load per (dataset, checksum).
    op.create_index(
        "uq_load_success",
        "data_load_runs",
        ["dataset_name", "source_sha256"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("status = 'succeeded'"),
    )

    # --- dvf_mutations ---
    op.create_table(
        "dvf_mutations",
        sa.Column("id_mutation", sa.Text(), primary_key=True),
        sa.Column("residential_unit_count", sa.SmallInteger()),
        sa.Column("apartment_count", sa.SmallInteger()),
        sa.Column("house_count", sa.SmallInteger()),
        sa.Column("dependency_count", sa.SmallInteger()),
        sa.Column("commercial_unit_count", sa.SmallInteger()),
        sa.Column("total_component_count", sa.SmallInteger()),
        sa.Column("distinct_parcel_count", sa.SmallInteger()),
        sa.Column("mutation_value", sa.Numeric(14, 2)),
        sa.Column("mutation_date", sa.Date()),
        sa.Column("value_consistent", sa.Boolean()),
        sa.Column("geo_consistent", sa.Boolean()),
        sa.Column("residential_property_type", sa.Text()),
        sa.Column("residential_surface", sa.Numeric(10, 2)),
        sa.Column("residential_rooms", sa.Numeric(5, 1)),
        sa.Column("arrondissement", sa.SmallInteger()),
        sa.Column("longitude", sa.Double()),
        sa.Column("latitude", sa.Double()),
        sa.Column("source_year", sa.SmallInteger(), nullable=False),
        sa.Column("source_file", sa.Text()),
        sa.Column("source_sha256", sa.Text()),
        sa.Column("is_price_per_m2_eligible", sa.Boolean()),
        sa.Column("price_ineligibility_reason", sa.Text()),
        sa.Column("price_per_m2_raw", sa.Numeric(14, 2)),
        sa.Column("load_run_id", sa.BigInteger()),
        sa.ForeignKeyConstraint(
            ["arrondissement"], [f"{SCHEMA}.arrondissements.arrondissement_number"],
            name="fk_dvf_arr",
        ),
        sa.ForeignKeyConstraint(
            ["load_run_id"], [f"{SCHEMA}.data_load_runs.load_run_id"],
            name="fk_dvf_load_run",
        ),
        sa.CheckConstraint(
            "source_year BETWEEN 2021 AND 2025", name="ck_dvf_source_year"
        ),
        sa.CheckConstraint(
            "arrondissement IS NULL OR arrondissement BETWEEN 1 AND 20",
            name="ck_dvf_arr_range",
        ),
        schema=SCHEMA,
    )
    op.create_index("idx_dvf_arr_year", "dvf_mutations",
                    ["arrondissement", "source_year"], schema=SCHEMA)
    op.create_index("idx_dvf_date", "dvf_mutations", ["mutation_date"],
                    schema=SCHEMA)
    op.create_index(
        "idx_dvf_price_eligible", "dvf_mutations", ["arrondissement"],
        schema=SCHEMA,
        postgresql_where=sa.text("is_price_per_m2_eligible = true"),
    )

    # --- dpe_diagnostics ---
    op.create_table(
        "dpe_diagnostics",
        sa.Column("numero_dpe", sa.Text(), primary_key=True),
        sa.Column("date_etablissement_dpe", sa.Date()),
        sa.Column("date_fin_validite_dpe", sa.Date()),
        sa.Column("diagnostic_year", sa.SmallInteger()),
        sa.Column("etiquette_dpe_norm", sa.String(length=1)),
        sa.Column("etiquette_ges_norm", sa.String(length=1)),
        sa.Column("surface_habitable_logement", sa.Numeric(10, 2)),
        sa.Column("conso_5_usages_par_m2_ep", sa.Double()),
        sa.Column("emission_ges_5_usages_par_m2", sa.Double()),
        sa.Column("type_batiment_norm", sa.Text()),
        sa.Column("analysis_population", sa.Text()),
        sa.Column("periode_construction", sa.Text()),
        sa.Column("arrondissement", sa.SmallInteger()),
        sa.Column("latitude", sa.Double()),
        sa.Column("longitude", sa.Double()),
        sa.Column("is_valid_arrondissement", sa.Boolean()),
        sa.Column("is_geography_consistent", sa.Boolean()),
        sa.Column("is_valid_dpe_label", sa.Boolean()),
        sa.Column("is_valid_ges_label", sa.Boolean()),
        sa.Column("is_valid_surface", sa.Boolean()),
        sa.Column("is_valid_consumption", sa.Boolean()),
        sa.Column("is_valid_emission", sa.Boolean()),
        sa.Column("is_residential_unit_type", sa.Boolean()),
        sa.Column("is_label_analysis_eligible", sa.Boolean()),
        sa.Column("is_intensity_analysis_eligible", sa.Boolean()),
        sa.Column("is_complete_analysis_year", sa.Boolean()),
        sa.Column("is_partial_year", sa.Boolean()),
        sa.Column("label_exclusion_reason", sa.Text()),
        sa.Column("intensity_exclusion_reason", sa.Text()),
        sa.Column("load_run_id", sa.BigInteger()),
        sa.ForeignKeyConstraint(
            ["arrondissement"], [f"{SCHEMA}.arrondissements.arrondissement_number"],
            name="fk_dpe_arr",
        ),
        sa.ForeignKeyConstraint(
            ["load_run_id"], [f"{SCHEMA}.data_load_runs.load_run_id"],
            name="fk_dpe_load_run",
        ),
        sa.CheckConstraint(
            "etiquette_dpe_norm IS NULL OR etiquette_dpe_norm IN "
            "('A','B','C','D','E','F','G')", name="ck_dpe_label_domain",
        ),
        sa.CheckConstraint(
            "etiquette_ges_norm IS NULL OR etiquette_ges_norm IN "
            "('A','B','C','D','E','F','G')", name="ck_ges_label_domain",
        ),
        sa.CheckConstraint(
            "analysis_population IS NULL OR analysis_population IN "
            "('dwelling_unit','whole_building','unknown')",
            name="ck_dpe_population_domain",
        ),
        sa.CheckConstraint(
            "arrondissement IS NULL OR arrondissement BETWEEN 1 AND 20",
            name="ck_dpe_arr_range",
        ),
        sa.CheckConstraint(
            "latitude IS NULL OR latitude BETWEEN -90 AND 90",
            name="ck_dpe_lat_range",
        ),
        sa.CheckConstraint(
            "longitude IS NULL OR longitude BETWEEN -180 AND 180",
            name="ck_dpe_lon_range",
        ),
        schema=SCHEMA,
    )
    op.create_index("idx_dpe_arr_year", "dpe_diagnostics",
                    ["arrondissement", "diagnostic_year"], schema=SCHEMA)
    op.create_index("idx_dpe_label", "dpe_diagnostics", ["etiquette_dpe_norm"],
                    schema=SCHEMA)
    op.create_index(
        "idx_dpe_label_eligible", "dpe_diagnostics", ["arrondissement"],
        schema=SCHEMA,
        postgresql_where=sa.text("is_label_analysis_eligible = true"),
    )

    # --- seed exactly 20 arrondissements ---
    op.bulk_insert(
        sa.table(
            "arrondissements",
            sa.column("arrondissement_number", sa.SmallInteger),
            sa.column("insee_code", sa.String),
            sa.column("postal_code", sa.String),
            sa.column("arrondissement_name", sa.Text),
            schema=SCHEMA,
        ),
        [
            {"arrondissement_number": n, "insee_code": insee,
             "postal_code": postal, "arrondissement_name": name}
            for (n, insee, postal, name) in _ARRONDISSEMENTS
        ],
    )


def downgrade() -> None:
    op.drop_table("dpe_diagnostics", schema=SCHEMA)
    op.drop_table("dvf_mutations", schema=SCHEMA)
    op.drop_table("data_load_runs", schema=SCHEMA)
    op.drop_table("arrondissements", schema=SCHEMA)
    # Note: the real_estate schema is intentionally NOT dropped here, because
    # Alembic's version table lives in it. Dropping the schema would remove that
    # table and break Alembic's own downgrade bookkeeping.
