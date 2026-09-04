# PostgreSQL Schema Proposal — Phase 3.1 (design only)

> **Design-only.** No PostgreSQL dependency installed, no migration, no
> connection, no data load. This document proposes a schema for architect
> validation. Types below are confirmed against the real Parquet schemas
> (PyArrow inspection via `scripts/schema_discovery/inspect_parquet.py`) and the
> Phase 2 quality reports.

---

## 1. Inspected Parquet schemas

> Row counts come from the Phase 2 quality reports; column types from PyArrow.
> Run `py scripts/schema_discovery/inspect_parquet.py` locally to reproduce.

### 1.1 `dvf_residential_mutations.parquet` — 24 cols, **160 977 rows**
Grain: **one residential mutation** (`id_mutation`). Candidate PK `id_mutation`,
**unique** (verified: 160 977 unique = row count in Phase 2.1).

| Column | Arrow type | Note |
|---|---|---|
| id_mutation | large_string | PK candidate |
| residential_unit_count | int64 | |
| apartment_count | int64 | |
| house_count | int64 | |
| dependency_count | int64 | |
| commercial_unit_count | int64 | |
| total_component_count | int64 | |
| distinct_parcel_count | int64 | |
| mutation_value | double | monetary → NUMERIC in PG |
| mutation_date | timestamp[us] | store as DATE |
| value_consistent | bool | |
| geo_consistent | bool | |
| residential_property_type | large_string | Appartement/Maison/NULL |
| residential_surface | double | nullable (**5.14 % null** — mono-unit sans surface) |
| residential_rooms | double | nullable |
| arrondissement | **double** (nullable, **0.088 % null**) | 1–20 → cast to SMALLINT on load |
| longitude | double | |
| latitude | double | |
| source_year | int64 | 2021–2025 |
| source_file | large_string | lineage |
| source_sha256 | large_string | lineage |
| price_ineligibility_reason | large_string | nullable |
| is_price_per_m2_eligible | bool | |
| price_per_m2_raw | double | nullable |

> **Observed null rates (real data):** `arrondissement` 0.088 %,
> `mutation_value` 0.058 %, `residential_surface` 5.144 %. `id_mutation` and
> `mutation_date` are 0 %. ⚠️ `arrondissement` is stored as **double** in the
> Parquet (nullable Int became float) — the loader must cast to SMALLINT and map
> NaN → NULL.

### 1.2 `dvf_residential_units.parquet` — 16 cols, **181 346 rows**
Grain: **one residential component** (Appartement/Maison sale row). **No single
natural primary key** (a mutation can have several unit rows; `id_parcelle` is
not guaranteed unique per row). See §2.5 for the load decision.

Columns: id_mutation, date_mutation, valeur_fonciere, type_local,
surface_reelle_bati, nombre_pieces_principales, code_commune, code_postal,
arrondissement, id_parcelle, longitude, latitude, nombre_lots, source_year,
source_file, source_sha256.

### 1.3 `dpe_diagnostics.parquet` — **38 cols, 838 532 rows**
Grain: **one DPE** (`numero_dpe`). Candidate PK `numero_dpe`, **unique**
(verified: 838 532 unique, 0 null). The real file carries all Phase 2.2 fields
and flags (confirmed by PyArrow):

- **Identifiers/dates:** numero_dpe, date_etablissement_dpe, date_reception_dpe,
  date_fin_validite_dpe (all timestamp[us]), diagnostic_year (int64).
- **Labels (raw + normalized):** etiquette_dpe, etiquette_dpe_norm,
  etiquette_ges, etiquette_ges_norm (large_string).
- **Measures:** conso_5_usages_par_m2_ep, emission_ges_5_usages_par_m2,
  surface_habitable_logement (double).
- **Building/geo:** type_batiment, type_batiment_norm, analysis_population,
  periode_construction, code_insee_ban, code_postal_ban, arrondissement (int64),
  arrondissement_source, _geopoint (large_string).
- **Flags (bool):** is_valid_dpe_number, is_valid_arrondissement,
  is_geography_consistent, is_valid_dpe_label, is_valid_ges_label,
  is_valid_surface, is_valid_consumption, is_valid_emission,
  is_residential_unit_type, is_complete_analysis_year, is_partial_year,
  is_label_analysis_eligible, is_intensity_analysis_eligible, is_analysis_eligible.
- **Exclusion reasons (large_string):** label_exclusion_reason,
  intensity_exclusion_reason, exclusion_reason.

**Observed null rates:** numero_dpe/arrondissement/diagnostic_year/
etiquette_dpe_norm 0 %; surface_habitable_logement **2.109 %**.

> **Loading note:** `dpe_diagnostics.arrondissement` is int64 here (0 % null,
> since only valid Paris rows carry it). We do NOT need all 38 columns in
> PostgreSQL — see §2.3 for the loaded subset. `_geopoint` is a `"lat,lon"`
> string; store as-is initially (no PostGIS).

---

## 2. Proposed tables

### 2.1 `arrondissements` (dimension)
Purpose: reference dimension for Paris arrondissements; both facts reference it.
Grain: one row per arrondissement (**exactly 20**).

| Column | PG type | Constraints |
|---|---|---|
| arrondissement_number | smallint | **PK**, CHECK 1–20 |
| insee_code | char(5) | UNIQUE, NOT NULL, CHECK `75101`–`75120` |
| postal_code | char(5) | UNIQUE, NOT NULL, CHECK `75001`–`75020` |
| arrondissement_name | text | NOT NULL |

**Primary key = `arrondissement_number`** (smallint 1–20): it is the natural,
compact, stable analytical key both facts already carry. `insee_code` and
`postal_code` are UNIQUE alternates. (Rationale in §9.)

### 2.2 `dvf_mutations` (fact)
Purpose: residential mutation-level facts for market analytics.
Grain: one residential mutation. **PK = `id_mutation` (text)**.

Key columns & types: `mutation_value NUMERIC(14,2)` (monetary, exact),
`mutation_date DATE NOT NULL`, `residential_surface NUMERIC(10,2)`,
`price_per_m2_raw NUMERIC(14,2)` (nullable), counts `SMALLINT`/`INTEGER`,
`arrondissement SMALLINT` **FK → arrondissements**, `source_year SMALLINT NOT
NULL CHECK 2021–2025`, booleans for flags, `source_sha256 TEXT`,
`load_run_id BIGINT` **FK → data_load_runs**.

CHECK: `residential_unit_count >= 0`; `price_per_m2_raw` only present when
`is_price_per_m2_eligible` (documented, enforced by load not hard constraint).

### 2.3 `dpe_diagnostics` (fact)
Purpose: DPE diagnostics for energy-performance analytics.
Grain: one `numero_dpe`. **PK = `numero_dpe` (text)**.

The Parquet has 38 columns; we load a **useful subset** (raw+normalized labels,
measures, geo, population, and the analytic flags), not every intermediate flag.

Loaded columns & types: `date_etablissement_dpe DATE`,
`date_fin_validite_dpe DATE` (nullable), `diagnostic_year SMALLINT`,
`etiquette_dpe_norm char(1)` CHECK A–G or NULL, `etiquette_ges_norm char(1)`
same, `surface_habitable_logement NUMERIC(10,2)` (nullable, 2.1 % null),
`conso_5_usages_par_m2_ep DOUBLE PRECISION`,
`emission_ges_5_usages_par_m2 DOUBLE PRECISION`,
`type_batiment_norm TEXT`, `analysis_population TEXT CHECK (dwelling_unit,
whole_building, unknown)`, `periode_construction TEXT`,
`arrondissement SMALLINT` **FK → arrondissements**, `geopoint TEXT` (from
`_geopoint`, `"lat,lon"`), `is_label_analysis_eligible BOOLEAN`,
`is_intensity_analysis_eligible BOOLEAN`, `is_complete_analysis_year BOOLEAN`,
`is_partial_year BOOLEAN`, `label_exclusion_reason TEXT`,
`intensity_exclusion_reason TEXT`, `load_run_id BIGINT` **FK → data_load_runs**.

**Not loaded** (intermediate validity flags kept only in Parquet lineage):
`is_valid_*` per-field flags, `is_analysis_eligible`/`exclusion_reason` (legacy
alias), raw `etiquette_dpe`/`etiquette_ges` (normalized versions suffice),
`arrondissement_source`, `code_insee_ban`/`code_postal_ban` (arrondissement
already derived). *This subset is a proposal — confirm which flags to persist.*

> No street name, house number or full address is stored (none exists in the
> processed Parquet).

### 2.4 `data_load_runs` (audit)
Purpose: one row per loading execution and dataset, for idempotence & audit.
Grain: one load run per dataset. **PK = `load_run_id BIGSERIAL`**.

Columns: `dataset_name TEXT NOT NULL` (`dvf_mutations`|`dpe_diagnostics`|…),
`source_sha256 TEXT NOT NULL`, `source_rows INTEGER`, `loaded_rows INTEGER`,
`started_at TIMESTAMPTZ`, `finished_at TIMESTAMPTZ`, `status TEXT CHECK
(started, succeeded, failed)`, `notes TEXT`. UNIQUE `(dataset_name,
source_sha256)` so re-running the same snapshot is detected.

### 2.5 `dvf_residential_units` — **recommendation: do NOT load in V1**
The component table (181 346 rows) has no natural PK, and every V1 analytic
(median price/m², counts, comparisons) is served by `dvf_mutations`. Storing it
adds a table with no clear analytical or traceability gain for a medium-sized
project. **Rejected for now**; can be revisited if unit-level analytics appear
(a surrogate `BIGSERIAL` PK + FK to `dvf_mutations` would then be added).

---

## 3. Arrondissement dimension

Exactly 20 rows, seeded from a static mapping (INSEE `75101`–`75120`, postal
`75001`–`75020`, names "Paris 1er"…"Paris 20e"). **PK = `arrondissement_number`**
because it is the compact natural key the facts already carry (`arrondissement`
SMALLINT), avoids repeating 5-char codes on 1M+ fact rows, and keeps joins cheap.

---

## 4. Relationships

- **No direct DVF↔DPE foreign key** (different grains/processes; textual-address
  joins are unreliable).
- Both facts reference `arrondissements` (many-to-one).
- Temporal comparisons use **2021–2025**; DPE **2026 is stored** but flagged
  `is_partial_year = true` and excluded from complete-year comparisons unless
  explicitly requested.

```mermaid
erDiagram
    arrondissements ||--o{ dvf_mutations : "located in"
    arrondissements ||--o{ dpe_diagnostics : "located in"
    data_load_runs ||--o{ dvf_mutations : "loaded by"
    data_load_runs ||--o{ dpe_diagnostics : "loaded by"

    arrondissements {
        smallint arrondissement_number PK
        char insee_code UK
        char postal_code UK
        text arrondissement_name
    }
    dvf_mutations {
        text id_mutation PK
        date mutation_date
        numeric mutation_value
        numeric price_per_m2_raw
        smallint arrondissement FK
        smallint source_year
        boolean is_price_per_m2_eligible
        bigint load_run_id FK
    }
    dpe_diagnostics {
        text numero_dpe PK
        date date_etablissement_dpe
        smallint diagnostic_year
        char etiquette_dpe_norm
        text analysis_population
        smallint arrondissement FK
        boolean is_partial_year
        bigint load_run_id FK
    }
    data_load_runs {
        bigint load_run_id PK
        text dataset_name
        text source_sha256
        integer loaded_rows
        text status
    }
```

---

## 5. Index strategy

Only query-justified indexes (beyond the automatic PK indexes):

| Index | Table (cols) | Accelerates |
|---|---|---|
| `idx_dvf_arr_year` | dvf_mutations (arrondissement, source_year) | market queries by area & year |
| `idx_dvf_date` | dvf_mutations (mutation_date) | time-trend / range scans |
| `idx_dvf_price_eligible` | dvf_mutations (arrondissement) **WHERE is_price_per_m2_eligible** | partial index for price/m² stats on eligible rows only |
| `idx_dpe_arr_year` | dpe_diagnostics (arrondissement, diagnostic_year) | DPE queries by area & year |
| `idx_dpe_label` | dpe_diagnostics (etiquette_dpe_norm) | label-distribution filtering |
| `idx_dpe_label_eligible` | dpe_diagnostics (arrondissement) **WHERE is_label_analysis_eligible** | partial index for label analytics on dwelling units |

No index on low-cardinality booleans alone, lineage columns, or every column.
Partial indexes are justified because analytics almost always filter on
eligibility.

---

## 6. Loading strategy (design only)

Idempotent bulk load, **not** row-by-row ORM:

1. Read the processed Parquet, compute/read its `source_sha256`.
2. Check `data_load_runs` for `(dataset_name, source_sha256)`: if a `succeeded`
   run exists → **skip** (idempotent no-op).
3. Insert a `data_load_runs` row `status=started`.
4. `COPY` the Parquet-derived rows into a **staging table** (`stg_<dataset>`)
   via PostgreSQL `COPY` (or `copy_expert`) — fast bulk path.
5. Validate in a transaction: row count vs source, PK uniqueness, arrondissement
   FK validity, label domain.
6. On success: upsert/replace into the target table (truncate-and-load, or
   `INSERT … ON CONFLICT (pk) DO UPDATE`), then mark the run `succeeded` with
   `loaded_rows`; **commit**.
7. On any validation failure: **rollback** and mark the run `failed`.

**Recommendation:** PostgreSQL **`COPY`** into staging + set-based upsert.
Rationale: ~838k DPE rows load in seconds via COPY, versus minutes/OOM with ORM
`add()` per row. Rerunning the same snapshot is a no-op (checksum match).

---

## 7. Security and configuration

Future environment variables (placeholders only in `.env.example`, no real
secrets):

```
DATABASE_URL=postgresql://user:password@localhost:5432/real_estate
TEST_DATABASE_URL=postgresql://user:password@localhost:5432/real_estate_test
```

- AI-accessible read path (later phases) will use a **read-only** role — not in
  scope here.
- **No detailed DPE address** is stored (none exists in processed data).
- **pgvector is NOT introduced** now; it arrives in the RAG phase.

---

## 8. Security decisions (summary)

- Credentials only via environment; `.env` never committed.
- Monetary values use `NUMERIC` (exact), never floating point.
- Lineage (`source_sha256`, `source_year`) retained for traceability.
- Address-level data excluded by construction.

---

## 9. Rejected alternatives

- **`dvf_residential_units` table in V1** — no natural PK, no V1 analytic needs
  it; rejected to avoid a low-value table.
- **INSEE/postal as arrondissement PK** — 5-char codes repeated across 1M+ fact
  rows; rejected in favor of compact SMALLINT `arrondissement_number` (codes kept
  as UNIQUE alternates).
- **Direct DVF↔DPE FK** — unreliable (grain/date/address mismatch); rejected.
- **`DOUBLE PRECISION` for money** — inexact; rejected for `NUMERIC`.
- **PostGIS/geopoint geometry** — unnecessary for arrondissement-level V1;
  deferred.

---

## 10. Unresolved questions

1. **DPE `numero_dpe` as text PK** vs surrogate: text is unique and natural;
   confirm acceptable (≈13-char strings, 838k rows) or prefer a surrogate BIGINT.
2. **Truncate-and-load vs upsert** for facts: which does the architect prefer as
   the default replacement behavior?
3. **`analysis_population = unknown`** rows: store as-is (recommended) — confirm.
4. **2026 partial DPE**: keep in the same table with a flag (recommended) vs a
   separate partition — confirm.
5. **`_geopoint`** storage: keep as one `"lat,lon"` TEXT column (recommended, no
   PostGIS for now) — confirm.
6. Exact **NUMERIC precisions** (`NUMERIC(14,2)` for value, `(10,2)` for surface)
   — confirm against observed maxima (mutation_value up to 695 M€ fits 14 digits;
   surface up to ~18 637 m² fits easily).
7. **DVF `arrondissement` stored as `double`** in Parquet (0.088 % null): the
   loader must cast NaN → NULL and float → SMALLINT. Confirm this cast is
   acceptable and that ~0.09 % of mutations legitimately have no arrondissement.
8. **DPE loaded subset (out of 38 columns):** confirm which flags to persist. The
   proposal keeps the two analytic-eligibility flags + partial-year flags +
   exclusion reasons and drops per-field `is_valid_*` and the legacy
   `is_analysis_eligible` alias.

---

## 11. Loading audit & reproducibility

`data_load_runs` records dataset, source checksum, row counts, timestamps and
status. The `(dataset_name, source_sha256)` UNIQUE key guarantees the same
snapshot is never loaded twice, giving idempotent reloads and a clear audit
trail.

*End of design proposal — awaiting architect validation before migrations.*

---

## 12. Final approved decisions (Phase 3.2)

The architect approved the design with these corrections, now implemented:

- **DPE coordinates**: `_geopoint` is parsed into `latitude` / `longitude`
  (DOUBLE PRECISION) with range CHECK constraints; malformed values become NULL
  (never crash the load).
- **Load idempotence**: no unconditional UNIQUE on `(dataset_name,
  source_sha256)`. Instead a **partial unique index** `WHERE status =
  'succeeded'`, so failed attempts can be retried.
- **Audit transactions**: `started` and `failed` audit records are written in
  their own committed transactions, separate from the data transaction that may
  roll back.
- **Schema**: dedicated `real_estate` schema. No pgvector, no PostGIS.
- **`dvf_residential_units`**: not loaded in V1 (confirmed).
- **`numero_dpe`**: natural TEXT primary key (confirmed unique: 838 532).
- **DPE loaded subset**: keeps the analytic flags listed in the task
  (`is_valid_arrondissement`, `is_geography_consistent`, `is_valid_dpe_label`,
  `is_valid_ges_label`, `is_valid_surface`, `is_valid_consumption`,
  `is_valid_emission`, `is_residential_unit_type`, `is_label_analysis_eligible`,
  `is_intensity_analysis_eligible`, `is_complete_analysis_year`,
  `is_partial_year`) plus exclusion reasons; the legacy `is_analysis_eligible`
  alias is dropped.
- **Snapshot replacement**: full atomic replacement (DELETE + INSERT from
  staging) rather than row-by-row upsert.
- **Bulk method**: PostgreSQL `COPY` into a TEMP staging table.
