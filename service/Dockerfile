# Reproducible image for both the API and the worker (same deps; command differs in compose).
# Build context is the repo root so the image can import both `service` and `src` (pipeline).
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

# Dependencies first (cache-friendly), then source.
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY service ./service

RUN uv sync --frozen --extra service --no-dev

ENV PATH="/app/.venv/bin:$PATH"
