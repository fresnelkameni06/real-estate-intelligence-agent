# Real Estate Investment Intelligence Agent — Paris

A portfolio Data & Generative-AI application for exploring the **Paris residential
real-estate market** through reliable analytics and natural-language questions,
backed by public transaction data (DVF), energy-performance data (ADEME DPE), and
official regulatory documents.

## Current status

**Phase 7 — Validated AI tools.** The project currently provides:

- validated DVF and DPE ingestion/processing pipelines;
- a PostgreSQL schema, migrations and idempotent loaders;
- a deterministic SQL/Python analytics engine;
- a versioned FastAPI backend over aggregate analytics;
- a Streamlit dashboard that consumes FastAPI without direct database access;
- acquisition, extraction and structure-aware chunking of six official documents;
- idempotent OpenAI embeddings stored in PostgreSQL with pgvector;
- exact cosine semantic search with traceable source metadata;
- adaptive GPT answers grounded only in retrieved official passages;
- verified inline citations and explicit abstention when evidence is insufficient;
- a secured FastAPI RAG endpoint and an active Streamlit chat with source display;
- six provider-neutral tools with strict inputs and structured outputs for later
  agentic orchestration.

Agentic routing and multi-tool conversation remain a later phase.

## High-level capabilities

- Paris market indicators (prices, volumes, price/m², trends) from DVF data
- Energy-performance analysis from ADEME DPE data
- Arrondissement comparisons
- Retrieval-augmented answers over official DVF/DPE and regulatory documents
- Natural-language questions answered via validated, tool-based AI orchestration

The underlying analytics and documentary capabilities are available today. The
natural-language router that chooses among them is introduced in Phase 8.

## Requirements

- Python 3.11 or newer
- PostgreSQL with the Phase 3 schema and data loaded
- Git

## Installation (Windows)

Create and activate a virtual environment, then install the project in editable
mode with development tools:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -e ".[dev,database,app,rag]"
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

## Application configuration

Copy `.env.example` to `.env`, then keep the real credentials only in `.env`:

```dotenv
DATABASE_URL=postgresql+psycopg://real_estate_app:YOUR_PASSWORD@localhost:5432/real_estate_db
TEST_DATABASE_URL=postgresql+psycopg://real_estate_app:YOUR_PASSWORD@localhost:5432/real_estate_test
API_BASE_URL=http://localhost:8000
API_TIMEOUT_SECONDS=15
AI_API_TIMEOUT_SECONDS=90
OPENAI_API_KEY=YOUR_PRIVATE_API_KEY
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
OPENAI_EMBEDDING_DIMENSIONS=1536
OPENAI_EMBEDDING_BATCH_SIZE=64
OPENAI_CHAT_MODEL=gpt-5.6-luna
OPENAI_CHAT_MAX_OUTPUT_TOKENS=1600
RAG_RETRIEVAL_TOP_K=5
RAG_MINIMUM_SIMILARITY=0.42
RAG_CONTEXT_MAX_CHARACTERS=12000
```

Percent-encode special password characters in database URLs. Never commit
`.env`.

## RAG embeddings and semantic retrieval

The `vector` extension must be installed on the PostgreSQL server and enabled in
both the development and test databases by a database administrator:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

Apply the application migration, embed the 116 local chunks, then run a retrieval
test:

```powershell
py -m alembic upgrade head
py scripts/embed_rag_chunks.py
py scripts/embed_rag_chunks.py
py scripts/search_rag.py "Quelles restrictions concernent les logements classés G ?"
```

The first embedding run calls OpenAI only for missing or changed chunks. The
second run is an idempotent no-op (`0 embedded`, `116 unchanged`). Raw documents,
processed documents and generated chunks remain ignored by Git.

Generate a user-facing answer grounded in the retrieved passages:

```powershell
py scripts/ask_rag.py "Combien de temps un DPE est-il valable ?"
py scripts/ask_rag.py "Explique en détail les restrictions pour un logement G."
py scripts/ask_rag.py "Résume le rôle du DPE." --style brief
```

The default `auto` style follows the user's requested level of detail. Normal
output contains the answer and only the sources actually cited. Use
`--show-passages` only for debugging. If the indexed evidence is insufficient,
the service says so instead of completing the answer from model memory.

## Running FastAPI and Streamlit on Windows

Open two PowerShell terminals in the repository root with `venv3` activated.

Terminal 1 — backend:

```powershell
py -m uvicorn --app-dir . app.api.main:app --reload
```

Useful backend URLs:

- API liveness: <http://localhost:8000/health>
- PostgreSQL readiness: <http://localhost:8000/ready>
- interactive OpenAPI documentation: <http://localhost:8000/docs>

Terminal 2 — dashboard:

```powershell
py -m streamlit run app/streamlit/app.py
```

Streamlit normally opens <http://localhost:8501> automatically.

With FastAPI running, validate all critical real-data endpoints with:

```powershell
py scripts/validate_application.py
```

## Available aggregate API endpoints

- `GET /api/v1/market/overview`
- `GET /api/v1/market/trends`
- `GET /api/v1/market/compare`
- `GET /api/v1/market/rankings`
- `GET /api/v1/dpe/distribution`
- `GET /api/v1/dpe/intensity`
- `GET /api/v1/areas/{arrondissement}/profile`
- `POST /api/v1/rag/answer`

All endpoints expose predefined aggregate calculations. There is no generic SQL
endpoint and no address-level API.

## Validated AI tools

Phase 7 exposes an internal allow-list for the future orchestration layer:

- `get_market_overview`
- `get_market_trend`
- `rank_arrondissements`
- `compare_arrondissements`
- `analyze_dpe`
- `answer_documentary_question`

Each tool validates its arguments with a strict schema and returns a structured
result. Market and DPE tools reuse the deterministic analytics engine, while the
documentary tool reuses grounded RAG. The registry provides no generic SQL or
arbitrary-function capability.

## Dashboard sections

- market overview and annual price trend;
- arrondissement rankings;
- comparison of two to five arrondissements;
- DPE label and energy-intensity analysis;
- combined aggregate profile for one arrondissement;
- conversational documentary RAG with suggestions, history and official sources.

The current chat answers each question independently. It does not yet route
market questions to analytics tools or retain multi-turn memory; those
capabilities belong to the later AI-tools and agentic-orchestration phases.
Simple conversational messages such as greetings, acknowledgements and thanks
are handled locally without an unnecessary embedding or generation API call;
documentary questions continue through the grounded RAG pipeline.

## Notes

- **Incremental implementation.** The project follows a phased roadmap; features
  are added phase by phase, not all at once.
- **Deterministic numbers.** All market calculations (median price/m², transaction
  volumes, year-over-year evolution, comparisons, DPE distributions) are computed
  in SQL/Python. The LLM interprets structured results — it never guesses numeric
  market values.
- **DPE limitation.** DPE results describe recorded eligible diagnostics, not a
  census of the entire Paris housing stock. The 2026 DPE year is partial.
- **No naive join.** DVF and DPE are combined only as arrondissement/period
  aggregates, never record by record through textual addresses.
- **Informational use.** The displayed analytics do not constitute financial
  advice.
