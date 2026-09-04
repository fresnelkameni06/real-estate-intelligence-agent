# Phase 5 — FastAPI and Streamlit

## Purpose

Phase 5 turns the deterministic analytics engine into a usable local Data
application. It does not introduce an LLM, RAG or an AI agent.

The runtime flow is:

1. the user selects an analysis in Streamlit;
2. Streamlit sends a bounded HTTP request to FastAPI;
3. FastAPI validates the parameters and calls the analytics service;
4. the analytics repository executes predefined parameterized SQL aggregates;
5. FastAPI returns a typed JSON result;
6. Streamlit formats the KPIs and charts.

Streamlit never connects directly to PostgreSQL. This makes the analytics
boundary reusable by the future AI tools and avoids duplicating business rules.

The API and UI entry points live in the repository-level `app/` package. The
project root is declared explicitly in the Pytest configuration, and Uvicorn is
started with `--app-dir .`, so imports behave consistently on Windows and Linux.

## HTTP boundary

The API exposes liveness and readiness separately:

- `/health` checks only that the Python API process is alive;
- `/ready` runs a lightweight `SELECT 1` against PostgreSQL.

Market, DPE and profile endpoints live below `/api/v1`. Inputs are bounded to
Paris arrondissements 1–20 and supported years 2021–2026. Invalid requests use a
stable public error envelope. Database errors never reveal SQL, passwords or
connection URLs.

The DPE API currently supports the validated `dwelling_unit` analytical scope.
Other populations are deliberately rejected instead of being silently mixed.

## Dashboard boundary

The dashboard uses five sections:

1. market overview;
2. arrondissement rankings;
3. cross-area comparison;
4. DPE analysis;
5. combined arrondissement profile.

Only the selected section is evaluated, which avoids executing all expensive
database aggregates during every Streamlit rerun. Comparison is limited to five
areas in the interface to keep charts legible, while the API contract retains
the analytics engine's validated 2–20 limit.

## Current limitations

- There is no geographic map because arrondissement boundary geometries are not
  part of the validated data layer.
- Property-type filtering is not exposed because Phase 4 does not yet define it
  in the analytics contract.
- DPE figures represent recorded diagnostics, not the full housing stock.
- 2026 is allowed only as an explicitly selected partial DPE year.
- Authentication, deployment hardening, RAG and LLM orchestration belong to
  later approved phases.
