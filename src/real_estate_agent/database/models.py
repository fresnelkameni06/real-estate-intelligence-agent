"""SQLAlchemy 2.0 models for the structured and RAG data stores."""

from __future__ import annotations

from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Double,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SCHEMA = "real_estate"

metadata_obj = MetaData(schema=SCHEMA)


class Base(DeclarativeBase):
    """Declarative base bound to the real_estate schema."""

    metadata = metadata_obj


class Arrondissement(Base):
    """One row per Paris arrondissement (exactly 20)."""

    __tablename__ = "arrondissements"

    arrondissement_number: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    insee_code: Mapped[str] = mapped_column(String(5), nullable=False)
    postal_code: Mapped[str] = mapped_column(String(5), nullable=False)
    arrondissement_name: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "arrondissement_number BETWEEN 1 AND 20",
            name="ck_arr_number_range",
        ),
        CheckConstraint(
            "insee_code BETWEEN '75101' AND '75120'", name="ck_arr_insee_range"
        ),
        CheckConstraint(
            "postal_code BETWEEN '75001' AND '75020'", name="ck_arr_postal_range"
        ),
        UniqueConstraint("insee_code", name="uq_arr_insee"),
        UniqueConstraint("postal_code", name="uq_arr_postal"),
    )


class DataLoadRun(Base):
    """One row per loading execution and dataset (audit + idempotence)."""

    __tablename__ = "data_load_runs"

    load_run_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    dataset_name: Mapped[str] = mapped_column(Text, nullable=False)
    source_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    source_rows: Mapped[int | None] = mapped_column(Integer)
    loaded_rows: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(
            "status IN ('started', 'succeeded', 'failed')",
            name="ck_load_status",
        ),
        # Partial unique index: only one SUCCEEDED load per (dataset, checksum).
        # A failed attempt does not block a later successful one.
        Index(
            "uq_load_success",
            "dataset_name",
            "source_sha256",
            unique=True,
            postgresql_where=(status == "succeeded"),
        ),
    )


class DvfMutation(Base):
    """One row per residential mutation."""

    __tablename__ = "dvf_mutations"

    id_mutation: Mapped[str] = mapped_column(Text, primary_key=True)
    residential_unit_count: Mapped[int | None] = mapped_column(SmallInteger)
    apartment_count: Mapped[int | None] = mapped_column(SmallInteger)
    house_count: Mapped[int | None] = mapped_column(SmallInteger)
    dependency_count: Mapped[int | None] = mapped_column(SmallInteger)
    commercial_unit_count: Mapped[int | None] = mapped_column(SmallInteger)
    total_component_count: Mapped[int | None] = mapped_column(SmallInteger)
    distinct_parcel_count: Mapped[int | None] = mapped_column(SmallInteger)
    mutation_value: Mapped[float | None] = mapped_column(Numeric(14, 2))
    mutation_date: Mapped[date | None] = mapped_column(Date)
    value_consistent: Mapped[bool | None] = mapped_column(Boolean)
    geo_consistent: Mapped[bool | None] = mapped_column(Boolean)
    residential_property_type: Mapped[str | None] = mapped_column(Text)
    residential_surface: Mapped[float | None] = mapped_column(Numeric(10, 2))
    residential_rooms: Mapped[float | None] = mapped_column(Numeric(5, 1))
    arrondissement: Mapped[int | None] = mapped_column(
        SmallInteger, ForeignKey(f"{SCHEMA}.arrondissements.arrondissement_number")
    )
    longitude: Mapped[float | None] = mapped_column(Double)
    latitude: Mapped[float | None] = mapped_column(Double)
    source_year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    source_file: Mapped[str | None] = mapped_column(Text)
    source_sha256: Mapped[str | None] = mapped_column(Text)
    is_price_per_m2_eligible: Mapped[bool | None] = mapped_column(Boolean)
    price_ineligibility_reason: Mapped[str | None] = mapped_column(Text)
    price_per_m2_raw: Mapped[float | None] = mapped_column(Numeric(14, 2))
    load_run_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey(f"{SCHEMA}.data_load_runs.load_run_id")
    )

    __table_args__ = (
        CheckConstraint(
            "source_year BETWEEN 2021 AND 2025", name="ck_dvf_source_year"
        ),
        CheckConstraint(
            "arrondissement IS NULL OR arrondissement BETWEEN 1 AND 20",
            name="ck_dvf_arr_range",
        ),
        Index("idx_dvf_arr_year", "arrondissement", "source_year"),
        Index("idx_dvf_date", "mutation_date"),
        Index(
            "idx_dvf_price_eligible",
            "arrondissement",
            postgresql_where=(is_price_per_m2_eligible == True),  # noqa: E712
        ),
    )


class DpeDiagnostic(Base):
    """One row per numero_dpe."""

    __tablename__ = "dpe_diagnostics"

    numero_dpe: Mapped[str] = mapped_column(Text, primary_key=True)
    date_etablissement_dpe: Mapped[date | None] = mapped_column(Date)
    date_fin_validite_dpe: Mapped[date | None] = mapped_column(Date)
    diagnostic_year: Mapped[int | None] = mapped_column(SmallInteger)
    etiquette_dpe_norm: Mapped[str | None] = mapped_column(String(1))
    etiquette_ges_norm: Mapped[str | None] = mapped_column(String(1))
    surface_habitable_logement: Mapped[float | None] = mapped_column(Numeric(10, 2))
    conso_5_usages_par_m2_ep: Mapped[float | None] = mapped_column(Double)
    emission_ges_5_usages_par_m2: Mapped[float | None] = mapped_column(Double)
    type_batiment_norm: Mapped[str | None] = mapped_column(Text)
    analysis_population: Mapped[str | None] = mapped_column(Text)
    periode_construction: Mapped[str | None] = mapped_column(Text)
    arrondissement: Mapped[int | None] = mapped_column(
        SmallInteger, ForeignKey(f"{SCHEMA}.arrondissements.arrondissement_number")
    )
    latitude: Mapped[float | None] = mapped_column(Double)
    longitude: Mapped[float | None] = mapped_column(Double)
    is_valid_arrondissement: Mapped[bool | None] = mapped_column(Boolean)
    is_geography_consistent: Mapped[bool | None] = mapped_column(Boolean)
    is_valid_dpe_label: Mapped[bool | None] = mapped_column(Boolean)
    is_valid_ges_label: Mapped[bool | None] = mapped_column(Boolean)
    is_valid_surface: Mapped[bool | None] = mapped_column(Boolean)
    is_valid_consumption: Mapped[bool | None] = mapped_column(Boolean)
    is_valid_emission: Mapped[bool | None] = mapped_column(Boolean)
    is_residential_unit_type: Mapped[bool | None] = mapped_column(Boolean)
    is_label_analysis_eligible: Mapped[bool | None] = mapped_column(Boolean)
    is_intensity_analysis_eligible: Mapped[bool | None] = mapped_column(Boolean)
    is_complete_analysis_year: Mapped[bool | None] = mapped_column(Boolean)
    is_partial_year: Mapped[bool | None] = mapped_column(Boolean)
    label_exclusion_reason: Mapped[str | None] = mapped_column(Text)
    intensity_exclusion_reason: Mapped[str | None] = mapped_column(Text)
    load_run_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey(f"{SCHEMA}.data_load_runs.load_run_id")
    )

    __table_args__ = (
        CheckConstraint(
            "etiquette_dpe_norm IS NULL OR etiquette_dpe_norm IN "
            "('A','B','C','D','E','F','G')",
            name="ck_dpe_label_domain",
        ),
        CheckConstraint(
            "etiquette_ges_norm IS NULL OR etiquette_ges_norm IN "
            "('A','B','C','D','E','F','G')",
            name="ck_ges_label_domain",
        ),
        CheckConstraint(
            "analysis_population IS NULL OR analysis_population IN "
            "('dwelling_unit','whole_building','unknown')",
            name="ck_dpe_population_domain",
        ),
        CheckConstraint(
            "arrondissement IS NULL OR arrondissement BETWEEN 1 AND 20",
            name="ck_dpe_arr_range",
        ),
        CheckConstraint(
            "latitude IS NULL OR latitude BETWEEN -90 AND 90",
            name="ck_dpe_lat_range",
        ),
        CheckConstraint(
            "longitude IS NULL OR longitude BETWEEN -180 AND 180",
            name="ck_dpe_lon_range",
        ),
        Index("idx_dpe_arr_year", "arrondissement", "diagnostic_year"),
        Index("idx_dpe_label", "etiquette_dpe_norm"),
        Index(
            "idx_dpe_label_eligible",
            "arrondissement",
            postgresql_where=(is_label_analysis_eligible == True),  # noqa: E712
        ),
    )


class RagDocumentChunk(Base):
    """One official-document chunk and its OpenAI embedding."""

    __tablename__ = "rag_document_chunks"

    chunk_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    character_count: Mapped[int] = mapped_column(Integer, nullable=False)
    word_count: Mapped[int] = mapped_column(Integer, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    chunking_version: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    publisher: Mapped[str] = mapped_column(Text, nullable=False)
    source_page_url: Mapped[str] = mapped_column(Text, nullable=False)
    download_url: Mapped[str] = mapped_column(Text, nullable=False)
    document_format: Mapped[str] = mapped_column(String(8), nullable=False)
    heading_path: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    topics: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    language: Mapped[str] = mapped_column(String(16), nullable=False)
    jurisdiction: Mapped[str | None] = mapped_column(String(32))
    authority_level: Mapped[str] = mapped_column(Text, nullable=False)
    is_normative: Mapped[bool] = mapped_column(Boolean, nullable=False)
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_until: Mapped[date | None] = mapped_column(Date)
    quality_flags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    embedding_model: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_dimensions: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(1536), nullable=False)
    embedded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("char_length(chunk_id) = 64", name="ck_rag_chunk_id_length"),
        CheckConstraint(
            "char_length(content_sha256) = 64", name="ck_rag_content_sha_length"
        ),
        CheckConstraint("char_length(raw_sha256) = 64", name="ck_rag_raw_sha_length"),
        CheckConstraint("chunk_index >= 0", name="ck_rag_chunk_index_nonnegative"),
        CheckConstraint("character_count > 0", name="ck_rag_character_count_positive"),
        CheckConstraint("word_count > 0", name="ck_rag_word_count_positive"),
        CheckConstraint(
            "document_format IN ('html', 'pdf')", name="ck_rag_document_format"
        ),
        CheckConstraint(
            "embedding_dimensions = 1536", name="ck_rag_embedding_dimensions"
        ),
        UniqueConstraint("source_id", "chunk_index", name="uq_rag_source_chunk_index"),
        Index("idx_rag_source_id", "source_id"),
    )
