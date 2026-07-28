# syntax=docker/dockerfile:1

# The published image ships EMPTY on purpose:
#   - no collection CSV, because that would publish someone's collection;
#   - no card art and no card dump, because YGOPRODeck's guide forbids
#     redistributing their images and the data is theirs, not ours.
# Both arrive at runtime, into the mounted /data volume.

# --- build the frontend ------------------------------------------------------
FROM node:24-alpine AS frontend

WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci || npm install
COPY frontend/ ./
RUN npm run build


# --- the runtime -------------------------------------------------------------
FROM python:3.12-slim AS runtime

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    YGO_DATA_DIR=/data \
    YGO_CACHE_DIR=/data/cache \
    YGO_FRONTEND_DIST=/app/frontend/dist

WORKDIR /app

# Dependencies first, so a source edit does not reinstall the world.
COPY pyproject.toml README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --no-install-project

COPY src/ ./src/
RUN --mount=type=cache,target=/root/.cache/uv uv sync --no-dev

COPY --from=frontend /build/dist ./frontend/dist

# Runs unprivileged; /data is chowned so a fresh named volume is writable.
RUN useradd --create-home --uid 10001 explorer \
    && mkdir -p /data/cache \
    && chown -R explorer:explorer /data /app
USER explorer

VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/api/health')"

CMD ["uvicorn", "ygo_explorer.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
