# syntax=docker/dockerfile:1
# Build context: repository root (so the bundled sample transcripts can be copied in).

FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.8.22 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app

# Dependencies first (cached layer), then the app.
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/app ./app

# Bake the embedding model into the image: fast, offline start-up and no runtime download.
RUN .venv/bin/python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir='/app/models')"


FROM python:3.12-slim
RUN useradd --create-home --uid 10001 app && mkdir /data && chown app /data
WORKDIR /app
COPY --from=builder --chown=app /app /app
COPY --chown=app sample_data /app/sample_data

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    HF_HUB_OFFLINE=1 \
    EMBEDDING_CACHE_DIR=/app/models \
    DATABASE_PATH=/data/verbatim.db \
    SAMPLE_DATA_DIR=/app/sample_data

USER app
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')" || exit 1
CMD ["uvicorn", "app.main:app_factory", "--factory", "--host", "0.0.0.0", "--port", "8000"]
