# Real Estate Investment Intelligence Agent — Paris

A portfolio Data & Generative-AI application for exploring the **Paris residential
real-estate market** through reliable analytics and natural-language questions,
backed by public transaction data (DVF), energy-performance data (ADEME DPE), and
official regulatory documents.

## Current status

**Phase 2 — Data Engineering.** The Paris DVF pipeline (2021–2025) is
implemented: idempotent acquisition, schema/encoding validation, exact-duplicate
handling, residential component and mutation-level tables, and price/m²
eligibility, with a quality report. See `docs/data-engineering/DVF_PIPELINE.md`.
The DPE production pipeline, database, API, UI, RAG and AI features are not
implemented yet.

## Target high-level capabilities (planned, not yet built)

- Paris market indicators (prices, volumes, price/m², trends) from DVF data
- Energy-performance analysis from ADEME DPE data
- Arrondissement comparisons
- Retrieval-augmented answers over official DVF/DPE and regulatory documents
- Natural-language questions answered via validated, tool-based AI orchestration

These are delivered incrementally across later phases and are **not** available today.

## Requirements

- Python 3.11 or 3.12
- Git

## Installation (Windows)

Create and activate a virtual environment, then install the project in editable
mode with development tools:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

If PowerShell blocks activation, use Command Prompt instead:

```bat
.venv\Scripts\activate.bat
```

## Testing and linting

```powershell
python -m pytest
python -m ruff check .
```

## Notes

- **Incremental implementation.** The project follows a phased roadmap; features
  are added phase by phase, not all at once.
- **Deterministic numbers.** All market calculations (median price/m², transaction
  volumes, year-over-year evolution, comparisons, DPE distributions) are computed
  in SQL/Python. The LLM interprets structured results — it never guesses numeric
  market values.