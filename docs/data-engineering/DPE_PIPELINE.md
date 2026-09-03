# DPE Data Pipeline — Paris (Phase 2.2)

Production-quality ETL for the Paris DPE (energy-performance) diagnostics.

## Source and endpoint

- Dataset: ADEME **DPE logements existants** (`dpe03existant`).
- Metadata: `https://data.ademe.fr/data-fair/api/v1/datasets/dpe03existant`
- Lines: `https://data.ademe.fr/data-fair/api/v1/datasets/dpe03existant/lines`

## Geographical scope

Department **75 (Paris)** — the 20 arrondissements. Validated filter:
`code_departement_ban:"75"`. The complete filtered Paris dataset is retrieved
(not a sample).

> A DPE is a **diagnostic**, not a dwelling: the same dwelling can have several
> DPEs, and this dataset represents **available diagnostics, not the full Paris
> housing stock**.

## Selected fields (approved, non-address)

`_id`, `numero_dpe`, `date_etablissement_dpe`, `date_reception_dpe`,
`date_fin_validite_dpe`, `etiquette_dpe`, `etiquette_ges`,
`conso_5_usages_par_m2_ep`, `emission_ges_5_usages_par_m2`,
`surface_habitable_logement`, `type_batiment`, `periode_construction`,
`code_postal_ban`, `code_insee_ban`, `code_departement_ban`, `_geopoint`.

All 16 were verified present in the real API schema. **No** street name, house
number, full address or owner information is requested or stored.

## Pagination

The client requests pages of `size=10000` and follows the API `next` cursor
until exhausted. It never assumes a single response contains all records, detects
a non-advancing cursor (repeated `next`) and stops with an error, and retries
HTTP 429 / transient 5xx with bounded exponential backoff.

## Idempotence and snapshot

The filtered raw snapshot is written atomically to
`data/raw/dpe/dpe_75_snapshot.json` with a `manifest.json` (dataset id, filter,
selected fields, extraction timestamps, expected total, retrieved rows, page
count, SHA-256, completeness). On a normal run, a snapshot is reused only when it
exists, its checksum matches the manifest, and it is marked complete. `--refresh`
forces a fresh snapshot. Incomplete or corrupted downloads are never treated as
complete.

## Transformation rules

Typed load (string identifiers, numeric measures, parsed dates), then:

- **Duplicates**: exact-duplicate rows dropped; duplicate `numero_dpe` resolved
  deterministically (newest `date_etablissement_dpe`, ties broken by `_id`);
  conflicting duplicates (same `numero_dpe`, differing fields) counted; rows with
  missing `numero_dpe` kept and counted separately.
- **Geography**: `code_insee_ban` (75101–75120) is primary; `code_postal_ban`
  (75001–75020) is a documented fallback only when INSEE is missing. A
  consistency flag marks INSEE/postal disagreement.
- **Labels**: DPE/GES normalized to A–G; originals kept, normalized values added;
  invalid labels become `<NA>` and are flagged.
- **Building type**: categories are **inspected and reported** (raw distribution)
  before mapping; a documented map normalizes known ADEME forms
  (maison/appartement/immeuble); unexpected values are flagged as `<NA>`.
- **Flags**: `is_valid_dpe_number`, `is_valid_arrondissement`,
  `is_geography_consistent`, `is_valid_dpe_label`, `is_valid_ges_label`,
  `is_valid_surface`, `is_residential_unit_type`, `is_analysis_eligible`,
  `exclusion_reason`.

No questionable record is deleted from the raw snapshot — everything is expressed
through flags and exclusion reasons. No arbitrary maximum surface/consumption
threshold is applied; real distributions are reported for later decisions.

## Duplicate policy

One deterministically selected row per `numero_dpe` in the processed output.

## Output

`data/processed/dpe/dpe_diagnostics.parquet` — one row per `numero_dpe`, no
complete textual address. DPE and DVF are **not** aggregated together in this
phase.

## Limitations

- Represents available diagnostics, not the full housing stock.
- Building-type mapping is documented but may need extension if new categories
  appear.
- Coordinates come from BAN geocoding and may be partial.

## Run

```powershell
py scripts/run_dpe_pipeline.py            # reuse snapshot if valid
py scripts/run_dpe_pipeline.py --refresh  # force a fresh API snapshot

py -m pytest
py -m ruff check .
```