FROM python:3.12-slim-bookworm

LABEL org.opencontainers.image.title="Paris Real Estate Intelligence Agent"
LABEL org.opencontainers.image.description="FastAPI and Streamlit runtime for the Paris real-estate AI Agent"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /workspace

RUN addgroup --system app && \
    adduser --system --ingroup app --home /home/app app

COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install --upgrade pip && \
    python -m pip install ".[database,app,rag,discovery]"

COPY --chown=app:app alembic.ini ./
COPY --chown=app:app app ./app
COPY --chown=app:app database ./database
COPY --chown=app:app scripts ./scripts

USER app
EXPOSE 8000
STOPSIGNAL SIGTERM

CMD ["sh", "-c", "python -m alembic upgrade head && exec python -m uvicorn --app-dir . app.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
