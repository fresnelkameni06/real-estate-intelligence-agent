"""Phase 1.2 — Controlled acquisition and real-data profiling (DVF & DPE).

This is EXPLORATORY discovery code, NOT the production ingestion pipeline.

It performs, for department 75 (Paris) only:
  * DVF: HTTP metadata check, single-file download of the 2025 geo-dvf
    `75.csv.gz`, checksum + acquisition metadata, then a schema/quality profile
    read directly from the compressed CSV (explicit UTF-8).
  * DPE: dataset metadata inspection (real schema), then a small technical
    sample (size=1000) filtered on department 75, saved locally and profiled.

The machine-readable profile is written directly as UTF-8 JSON by this script
(see PROFILE_OUTPUT), so it must NOT be produced via shell output redirection.

Guardrails:
  * never downloads France-wide data;
  * uses HTTP timeouts and raise_for_status();
  * reuses an already-downloaded, checksum-verified DVF file when present;
  * reads the DVF CSV with explicit UTF-8 and validates against decoding
    corruption / replacement characters;
  * forces geographical identifiers to string dtype (no "75015.0", no int),
    keeping missing identifiers missing rather than the literal "nan";
  * keeps measurement fields numeric and parses dates explicitly;
  * never prints complete address-level records.

Run (inside venv3):
    py scripts/data_discovery/profile_real_data.py
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

# --------------------------------------------------------------------------- #
# Configuration (Phase 1.2 authorized sources only)
# --------------------------------------------------------------------------- #

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("phase1_2")

# Repo root = two levels up from scripts/data_discovery/
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_RAW = REPO_ROOT / "data" / "raw"
DVF_DIR = DATA_RAW / "dvf" / "2025"
DPE_DIR = DATA_RAW / "dpe"

DVF_URL = "https://files.data.gouv.fr/geo-dvf/latest/csv/2025/departements/75.csv.gz"
DVF_FILE = DVF_DIR / "75.csv.gz"
# Known-good checksum: skip re-download when the local file already matches.
DVF_KNOWN_SHA256 = "b8110139f4f2c1c83fce33e6a5a7d7f17ab95ffccbc255292edc08f6781a8e51"

DPE_DATASET_META_URL = "https://data.ademe.fr/data-fair/api/v1/datasets/dpe03existant"
DPE_LINES_URL = "https://data.ademe.fr/data-fair/api/v1/datasets/dpe03existant/lines"
DPE_SAMPLE_FILE = DPE_DIR / "dpe_75_sample.json"

# Machine-readable profile, written directly as UTF-8 by this script.
PROFILE_OUTPUT = REPO_ROOT / "docs" / "data-discovery" / "profile_output.json"

HTTP_TIMEOUT = httpx.Timeout(30.0, connect=15.0)
DVF_DOWNLOAD_TIMEOUT = httpx.Timeout(120.0, connect=15.0)

# DVF identifier columns that must be kept as strings (never numeric).
DVF_ID_COLUMNS = [
    "id_mutation",
    "code_postal",
    "code_commune",
    "code_departement",
    "id_parcelle",
    "code_type_local",
    "adresse_code_voie",
    "ancien_code_commune",
    "ancien_id_parcelle",
    "numero_disposition",
]

# DVF measurement columns that must stay numeric.
DVF_NUMERIC_COLUMNS = [
    "valeur_fonciere",
    "surface_reelle_bati",
    "nombre_pieces_principales",
    "surface_terrain",
    "longitude",
    "latitude",
]

# Confirmed-useful DPE fields to request via `select` (only if present in schema).
DPE_CANDIDATE_FIELDS = [
    "numero_dpe",
    "date_etablissement_dpe",
    "etiquette_dpe",
    "etiquette_ges",
    "conso_5_usages_par_m2_ep",
    "emission_ges_5_usages_par_m2",
    "surface_habitable_logement",
    "type_batiment",
    "periode_construction",
    "code_departement_ban",
    "code_postal_ban",
    "code_insee_ban",
    "nom_commune_ban",
    "statut_geocodage",
    "_geopoint",
]

# Unicode replacement char + a few mojibake markers typical of a wrong decode.
_REPLACEMENT_CHAR = "\ufffd"
_MOJIBAKE_MARKERS = ("Θ", "Φ", "Γ", "α", " Γ", "Ï", "Ã©", "Ã¨", "Ã ")


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #

def _utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(UTC).isoformat()


def _sha256(path: Path) -> str:
    """Compute the SHA-256 checksum of a file, streaming to bound memory."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _pct_missing(df: pd.DataFrame) -> dict[str, float]:
    """Return per-column missing-value percentages, rounded to 2 decimals."""
    n = len(df)
    if n == 0:
        return {c: 0.0 for c in df.columns}
    return {c: round(df[c].isna().mean() * 100, 2) for c in df.columns}


def _id_series_to_str(series: pd.Series) -> pd.Series:
    """Coerce an identifier column to clean strings.

    * numbers read as floats (e.g. 75015.0) become "75015";
    * genuine missing values stay missing (pandas <NA>), never the text "nan".
    """
    # Use the nullable string dtype so NaN stays <NA> instead of "nan".
    out = series.astype("string")
    # If pandas parsed the column as float first (75015.0), strip the ".0".
    # Do this only on non-null values.
    mask = out.notna()
    out.loc[mask] = (
        out.loc[mask]
        .str.replace(r"\.0$", "", regex=True)
    )
    return out


def _detect_corruption(values: list[str]) -> dict[str, Any]:
    """Detect obvious decoding corruption in a list of string values.

    Returns a small report: whether the replacement char is present, and any
    mojibake markers found. An empty/clean report means the decode looks good.
    """
    joined = " ".join(v for v in values if isinstance(v, str))
    replacement_present = _REPLACEMENT_CHAR in joined
    markers_found = sorted({m for m in _MOJIBAKE_MARKERS if m in joined})
    return {
        "replacement_char_present": replacement_present,
        "mojibake_markers_found": markers_found,
        "looks_clean": (not replacement_present) and (not markers_found),
    }


# --------------------------------------------------------------------------- #
# DVF acquisition
# --------------------------------------------------------------------------- #

def check_dvf_metadata() -> dict[str, Any]:
    """Issue a HEAD request for the exact DVF Paris file and record metadata."""
    logger.info("DVF: requesting HTTP metadata (HEAD) for %s", DVF_URL)
    with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
        resp = client.head(DVF_URL)
        resp.raise_for_status()
    meta = {
        "url": DVF_URL,
        "http_status": resp.status_code,
        "content_length": resp.headers.get("content-length"),
        "last_modified": resp.headers.get("last-modified"),
        "content_type": resp.headers.get("content-type"),
    }
    logger.info("DVF: HEAD status=%s content-length=%s", meta["http_status"],
                meta["content_length"])
    return meta


def download_dvf(reuse_existing: bool = True) -> dict[str, Any]:
    """Download the single Paris 2025 DVF file, or reuse a verified local copy.

    Reuse is checksum-driven: if the local file already matches the known-good
    SHA-256, the download is skipped.
    """
    DVF_DIR.mkdir(parents=True, exist_ok=True)

    reused = False
    if reuse_existing and DVF_FILE.exists() and DVF_FILE.stat().st_size > 0:
        existing = _sha256(DVF_FILE)
        if existing == DVF_KNOWN_SHA256:
            logger.info("DVF: existing file matches known checksum; skipping download")
            reused = True
        else:
            logger.warning("DVF: local checksum differs from known value; re-downloading")

    if not reused:
        logger.info("DVF: downloading single department file (75) ...")
        with httpx.Client(timeout=DVF_DOWNLOAD_TIMEOUT, follow_redirects=True) as client:
            with client.stream("GET", DVF_URL) as resp:
                resp.raise_for_status()
                with DVF_FILE.open("wb") as fh:
                    for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
                        fh.write(chunk)
        logger.info("DVF: download complete -> %s", DVF_FILE)

    size = DVF_FILE.stat().st_size
    checksum = _sha256(DVF_FILE)
    meta = {
        "source_url": DVF_URL,
        "local_path": str(DVF_FILE.relative_to(REPO_ROOT)),
        "compressed_size_bytes": size,
        "compressed_size_mb": round(size / (1024 * 1024), 3),
        "sha256": checksum,
        "reused_existing": reused,
        "checksum_matches_known": checksum == DVF_KNOWN_SHA256,
        "acquired_at_utc": _utc_now_iso(),
    }
    logger.info("DVF: size=%.3f MB sha256=%s reused=%s",
                meta["compressed_size_mb"], checksum[:16], reused)
    return meta


# --------------------------------------------------------------------------- #
# DVF loading + profiling
# --------------------------------------------------------------------------- #

def load_dvf() -> pd.DataFrame:
    """Load the compressed DVF CSV with explicit UTF-8 and correct dtypes.

    * identifiers -> string dtype (no float artefacts, no "nan");
    * measurements -> numeric;
    * date_mutation -> datetime.
    """
    logger.info("DVF: reading compressed CSV with explicit UTF-8 ...")
    with gzip.open(DVF_FILE, "rt", encoding="utf-8") as fh:
        # Read identifier columns as strings from the start; let the rest infer.
        df = pd.read_csv(
            fh,
            dtype={col: "string" for col in DVF_ID_COLUMNS},
            low_memory=False,
        )

    # Normalise identifier columns that are present (strip float ".0", keep NA).
    for col in DVF_ID_COLUMNS:
        if col in df.columns:
            df[col] = _id_series_to_str(df[col])

    # Force measurement columns numeric.
    for col in DVF_NUMERIC_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Parse the mutation date explicitly.
    if "date_mutation" in df.columns:
        df["date_mutation"] = pd.to_datetime(df["date_mutation"], errors="coerce")

    logger.info("DVF: loaded %d rows x %d cols", len(df), df.shape[1])
    return df


def profile_dvf(df: pd.DataFrame) -> dict[str, Any]:
    """Profile the DVF DataFrame (schema, volume, grain, quality, encoding)."""
    cols = list(df.columns)
    profile: dict[str, Any] = {
        "n_rows": int(len(df)),
        "n_cols": int(df.shape[1]),
        "columns": cols,
        "dtypes": {c: str(t) for c, t in df.dtypes.items()},
        "duplicate_rows": int(df.duplicated().sum()),
        "missing_pct": _pct_missing(df),
    }

    # --- Encoding validation on decoded text columns ---
    text_samples: list[str] = []
    for c in ("nature_mutation", "type_local", "nom_commune", "nature_culture"):
        if c in cols:
            text_samples.extend(
                str(v) for v in df[c].dropna().unique().tolist()
            )
    corruption = _detect_corruption(text_samples)
    profile["encoding_validation"] = corruption
    if not corruption["looks_clean"]:
        logger.error("DVF: decoding corruption detected: %s", corruption)
    else:
        logger.info("DVF: encoding validation passed (no replacement/mojibake)")

    # Dates
    if "date_mutation" in cols:
        profile["date_mutation_min"] = str(df["date_mutation"].min())
        profile["date_mutation_max"] = str(df["date_mutation"].max())

    # Grain: id_mutation
    if "id_mutation" in cols:
        rows_per_mut = df.groupby("id_mutation").size()
        profile["unique_id_mutation"] = int(df["id_mutation"].nunique())
        profile["rows_per_mutation_describe"] = {
            k: float(v) for k, v in rows_per_mut.describe().items()
        }
        multi = int((rows_per_mut > 1).sum())
        profile["mutations_with_multiple_rows"] = multi
        profile["pct_mutations_multi_row"] = round(
            multi / rows_per_mut.shape[0] * 100, 2
        ) if rows_per_mut.shape[0] else 0.0

        if "valeur_fonciere" in cols:
            nun = df.groupby("id_mutation")["valeur_fonciere"].nunique(dropna=True)
            profile["mutations_with_nonconstant_valeur_fonciere"] = int((nun > 1).sum())

        if "type_local" in cols:
            residential = {"Appartement", "Maison"}
            res_df = df[df["type_local"].isin(residential)]
            distinct_res = res_df.groupby("id_mutation")["type_local"].nunique()
            profile["mutations_multi_distinct_residential_local"] = int(
                (distinct_res > 1).sum()
            )

    # Categorical frequencies (decoded labels come straight from the data)
    for c in ("nature_mutation", "type_local"):
        if c in cols:
            profile[f"{c}_freq"] = {
                str(k): int(v) for k, v in df[c].value_counts(dropna=False).items()
            }

    # Geographical distributions
    for c in ("code_commune", "code_postal"):
        if c in cols:
            profile[f"{c}_distribution"] = {
                str(k): int(v)
                for k, v in df[c].value_counts(dropna=False).head(30).items()
            }

    # Missing lat/lon
    for c in ("longitude", "latitude"):
        if c in cols:
            profile[f"missing_{c}_pct"] = round(df[c].isna().mean() * 100, 2)

    # Descriptive stats for key numeric columns
    for c in ("valeur_fonciere", "surface_reelle_bati", "nombre_pieces_principales"):
        if c in cols:
            profile[f"{c}_describe"] = {
                k: (float(v) if pd.notna(v) else None)
                for k, v in df[c].describe().items()
            }

    logger.info("DVF: profiling done")
    return profile


# --------------------------------------------------------------------------- #
# DPE schema + sample
# --------------------------------------------------------------------------- #

def inspect_dpe_schema() -> dict[str, Any]:
    """Fetch the DPE dataset metadata and return the confirmed field names."""
    logger.info("DPE: fetching dataset metadata %s", DPE_DATASET_META_URL)
    with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
        resp = client.get(DPE_DATASET_META_URL)
        resp.raise_for_status()
        meta = resp.json()

    schema = meta.get("schema", [])
    field_names = [f.get("key") for f in schema if isinstance(f, dict)]
    total_lines = meta.get("count")
    logger.info("DPE: schema has %d fields; dataset count=%s",
                len(field_names), total_lines)
    return {
        "dataset_id": meta.get("id"),
        "dataset_title": meta.get("title"),
        "total_lines_all_france": total_lines,
        "field_names": field_names,
    }


def fetch_dpe_sample(confirmed_fields: list[str]) -> dict[str, Any]:
    """Fetch a small (size=1000) Paris DPE sample and save it locally as UTF-8."""
    DPE_DIR.mkdir(parents=True, exist_ok=True)

    select_fields = [f for f in DPE_CANDIDATE_FIELDS if f in confirmed_fields]
    if not select_fields:
        logger.warning("DPE: none of the candidate fields are in the schema; "
                       "requesting without select")
    params: dict[str, Any] = {
        "qs": 'code_departement_ban:"75"',
        "size": 1000,
    }
    if select_fields:
        params["select"] = ",".join(select_fields)

    logger.info("DPE: requesting Paris sample (size=1000, dept 75) ...")
    with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
        resp = client.get(DPE_LINES_URL, params=params)
        resp.raise_for_status()
        payload = resp.json()

    # Save the full API response for reproducibility, explicit UTF-8.
    DPE_SAMPLE_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    results = payload.get("results", [])
    meta = {
        "request_url": str(resp.request.url),
        "http_status": resp.status_code,
        "select_fields": select_fields,
        "total_paris_records_reported": payload.get("total"),
        "sample_rows": len(results),
        "has_next": "next" in payload,
        "acquired_at_utc": _utc_now_iso(),
        "saved_to": str(DPE_SAMPLE_FILE.relative_to(REPO_ROOT)),
    }
    logger.info("DPE: sample rows=%d total_paris_reported=%s has_next=%s",
                meta["sample_rows"], meta["total_paris_records_reported"],
                meta["has_next"])
    return meta


def profile_dpe_sample() -> dict[str, Any]:
    """Profile the locally saved DPE sample (preliminary, not representative)."""
    logger.info("DPE: profiling local sample %s", DPE_SAMPLE_FILE)
    payload = json.loads(DPE_SAMPLE_FILE.read_text(encoding="utf-8"))

    results = payload.get("results", [])
    df = pd.DataFrame(results)

    # Keep geographical identifiers as clean strings here too.
    for col in ("code_insee_ban", "code_postal_ban", "code_departement_ban"):
        if col in df.columns:
            df[col] = _id_series_to_str(df[col])

    profile: dict[str, Any] = {
        "sample_rows": int(len(df)),
        "fields": list(df.columns),
        "dtypes": {c: str(t) for c, t in df.dtypes.items()},
        "missing_pct": _pct_missing(df),
        "total_paris_records_reported": payload.get("total"),
        "_note": "PRELIMINARY - first 1000 API rows; NOT statistically representative.",
    }

    if "numero_dpe" in df.columns:
        profile["duplicate_numero_dpe"] = int(df["numero_dpe"].duplicated().sum())

    for c in ("etiquette_dpe", "etiquette_ges"):
        if c in df.columns:
            profile[f"{c}_counts"] = {
                str(k): int(v) for k, v in df[c].value_counts(dropna=False).items()
            }

    for c in ("code_insee_ban", "code_postal_ban"):
        if c in df.columns:
            profile[f"{c}_distribution"] = {
                str(k): int(v) for k, v in df[c].value_counts(dropna=False).items()
            }

    if "code_insee_ban" in df.columns:
        valid_insee = {f"751{n:02d}" for n in range(1, 21)}
        invalid = df.loc[~df["code_insee_ban"].isin(valid_insee), "code_insee_ban"]
        profile["invalid_insee_values"] = {
            str(k): int(v) for k, v in invalid.value_counts(dropna=False).head(20).items()
        }

    if "_geopoint" in df.columns:
        profile["missing_geopoint_pct"] = round(df["_geopoint"].isna().mean() * 100, 2)

    if "date_etablissement_dpe" in df.columns:
        dates = pd.to_datetime(df["date_etablissement_dpe"], errors="coerce")
        profile["date_min"] = str(dates.min())
        profile["date_max"] = str(dates.max())

    for c in ("surface_habitable_logement", "conso_5_usages_par_m2_ep",
              "emission_ges_5_usages_par_m2"):
        if c in df.columns:
            series = pd.to_numeric(df[c], errors="coerce")
            profile[f"{c}_describe"] = {
                k: (float(v) if pd.notna(v) else None)
                for k, v in series.describe().items()
            }

    logger.info("DPE: sample profiling done")
    return profile


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #

def main() -> None:
    """Run the full Phase 1.2 discovery and write a UTF-8 JSON profile."""
    summary: dict[str, Any] = {"executed_at_utc": _utc_now_iso()}

    # --- DVF ---
    try:
        summary["dvf_http_metadata"] = check_dvf_metadata()
        summary["dvf_acquisition"] = download_dvf(reuse_existing=True)
        dvf_df = load_dvf()
        summary["dvf_profile"] = profile_dvf(dvf_df)
    except httpx.HTTPError as exc:
        logger.error("DVF step failed (network/HTTP): %s", exc)
        summary["dvf_error"] = f"{type(exc).__name__}: {exc}"

    # --- DPE ---
    try:
        schema_info = inspect_dpe_schema()
        summary["dpe_schema"] = schema_info
        summary["dpe_sample_acquisition"] = fetch_dpe_sample(
            schema_info.get("field_names", [])
        )
        summary["dpe_sample_profile"] = profile_dpe_sample()
    except httpx.HTTPError as exc:
        logger.error("DPE step failed (network/HTTP): %s", exc)
        summary["dpe_error"] = f"{type(exc).__name__}: {exc}"

    # Write the machine-readable profile directly as UTF-8 (no shell redirection).
    PROFILE_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_OUTPUT.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    logger.info("Profile written (UTF-8) -> %s", PROFILE_OUTPUT)


if __name__ == "__main__":
    main()
