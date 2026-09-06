# Real Estate Investment Intelligence Agent — Paris

A portfolio Data & Generative-AI application for exploring the **Paris residential
real-estate market** through reliable analytics and natural-language questions,
backed by public transaction data (DVF), energy-performance data (ADEME DPE), and
official regulatory documents.

## Current status

**Phase 10.1 — Structured logging and request observability.** The project currently
provides:

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
- six provider-neutral tools with strict inputs and structured outputs;
- bounded model-directed orchestration across Analytics, DPE and documentary RAG;
- short multi-turn session memory and an active Agent interface;
- deterministic in-chat charts for trends, comparisons and DPE distributions;
- deterministic scope, real-time limitation and prompt-injection guardrails;
- a versioned 23-case Agent evaluation suite with structural quality metrics;
- safe JSON logs, request correlation and bounded Agent/tool telemetry.

## High-level capabilities

- Paris market indicators (prices, volumes, price/m², trends) from DVF data
- Energy-performance analysis from ADEME DPE data
- Arrondissement comparisons
- Retrieval-augmented answers over official DVF/DPE and regulatory documents
- Natural-language questions answered via validated, tool-based AI orchestration

These capabilities are available through both dedicated dashboard pages and the
natural-language Agent.

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
AI_API_TIMEOUT_SECONDS=180
OPENAI_API_KEY=YOUR_PRIVATE_API_KEY
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
OPENAI_EMBEDDING_DIMENSIONS=1536
OPENAI_EMBEDDING_BATCH_SIZE=64
OPENAI_CHAT_MODEL=gpt-5.6-luna
OPENAI_CHAT_MAX_OUTPUT_TOKENS=1600
OPENAI_AGENT_MODEL=gpt-5.6-luna
OPENAI_AGENT_MAX_OUTPUT_TOKENS=1600
OPENAI_REQUEST_TIMEOUT_SECONDS=90
AGENT_MAX_TOOL_ROUNDS=4
AGENT_MAX_HISTORY_MESSAGES=12
RAG_RETRIEVAL_TOP_K=5
RAG_MINIMUM_SIMILARITY=0.42
RAG_CONTEXT_MAX_CHARACTERS=12000
SERVICE_NAME=real-estate-intelligence-api
LOG_LEVEL=INFO
LOG_FORMAT=json
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
- `POST /api/v1/agent/chat`

All endpoints expose predefined aggregate calculations. There is no generic SQL
endpoint and no address-level API.

## Validated AI tools

Phase 7 exposes the internal allow-list used by the Phase 8 orchestrator:

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

## Multi-tool Agent

The Agent uses the OpenAI Responses API for bounded function calling. For each
turn, the model can answer conversationally or select one or more approved tools.
The application validates every tool argument, executes deterministic services,
and sends only structured results back to the model for synthesis.

```text
User + recent session history
        -> Agent model selects tools
        -> validated allow-list executes
        -> Analytics/PostgreSQL and/or documentary RAG
        -> final answer + deterministic charts + tool trace + official citations
```

No unrestricted SQL, arbitrary Python function, address-level record or database
credential is exposed to the model. The loop is limited to four tool rounds and
the client sends at most twelve recent messages. Conversations are not persisted
in PostgreSQL.

Test the Agent from PowerShell without Streamlit:

```powershell
py scripts/chat_agent.py "Compare le 13e et le 20e arrondissement."
py scripts/chat_agent.py
```

The second command opens an interactive conversation and retains short-term
context until you type `quit`.

## Dashboard sections

- market overview and annual price trend;
- arrondissement rankings;
- comparison of two to five arrondissements;
- DPE label and energy-intensity analysis;
- combined aggregate profile for one arrondissement;
- a multi-tool Agent with suggestions, short-term memory, dynamic charts and
  official sources.

The Agent routes market questions to deterministic analytics, aggregate DPE
questions to the DPE tool, and regulatory or methodological questions to grounded
RAG. It can combine these capabilities in one answer. Simple greetings,
acknowledgements and thanks are handled locally without an unnecessary API call.
When a trend, arrondissement comparison or DPE distribution is returned, the
API also exposes a validated chart payload that Streamlit renders with Plotly.
The model never generates executable chart code.

## Scope and security guardrails

The Agent is intentionally specialized in Paris residential real estate. Before
any model, database or tool call, a deterministic local layer handles greetings
and rejects or redirects:

- current time, date, season, weather and device-location requests, because no
  corresponding real-time tool is available;
- unrelated general-knowledge requests;
- attempts to override instructions, reveal secrets, execute free-form SQL or
  invoke an unauthorized tool.

Valid real-estate questions and short follow-ups to recent real-estate messages
continue to the Agent. This local boundary complements the strict tool allow-list,
validated arguments, aggregate-only analytics and grounded documentary RAG.

## Agent evaluation

The versioned suite in `config/evaluation/agent_cases.json` covers conversation,
market analytics, DPE, official-document RAG, combined requests, memory, typing
errors, English, scope and security. Evaluation compares observable behavior
rather than exact wording: route, required/unauthorized tools, citations, charts,
memory, local/remote model policy, answer constraints and non-empty answers.

Validate and inspect the suite without using PostgreSQL or OpenAI:

```powershell
py scripts/evaluate_agent.py --dry-run
```

Run a low-cost smoke evaluation, one category, or the full suite:

```powershell
py scripts/evaluate_agent.py --max-cases 5
py scripts/evaluate_agent.py --category documentary
py scripts/evaluate_agent.py --category scope
py scripts/evaluate_agent.py --category security
py scripts/evaluate_agent.py
```

Live cases use the configured Agent and may consume OpenAI credit. No report file
is created by default. Add `--output evaluation-result.json` only when a complete
machine-readable result is needed. The command returns a failing exit code when
the pass rate is below 80%; change that controlled threshold with `--fail-below`.
The `scope` and `security` categories run entirely through the local guardrail and
therefore make no PostgreSQL or OpenAI request.

## Observability and safe logs

FastAPI emits one structured event per request and returns the correlation value
in the `X-Request-ID` response header. A valid caller-supplied identifier is
propagated; otherwise the API generates one. Query strings, request bodies,
conversation messages, tool arguments and tool results are not logged.

Agent logs expose only operational metadata such as route, model, orchestration
round, approved tool name, success state and duration. The formatter uses an
explicit field allow-list, redacts common secret patterns and records exception
types without exposing exception messages or stack traces. Use `LOG_FORMAT=text`
for more readable local output; keep `LOG_FORMAT=json` for containers and hosted
environments.

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
