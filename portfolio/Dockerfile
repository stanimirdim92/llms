# syntax=docker/dockerfile:1
#
# Two runnable images from one build: `api` (FastAPI) and `streamlit` (demo UI).
# Build/run a specific one with `--target`:
#   docker build --target api -t portfolio-api .
#   docker build --target streamlit -t portfolio-streamlit .
# (docker-compose.yml does this for you.)

FROM python:3.14-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=0

# Installing uv this way (copying the prebuilt binary, version-pinned to match
# build-system.requires in pyproject.toml) is Astral's own recommended approach for
# Docker images -- no curl/pip bootstrap needed.
COPY --from=ghcr.io/astral-sh/uv:0.11.29 /uv /uvx /bin/

WORKDIR /app

# Dependencies only, no project source yet: this layer stays cached across rebuilds
# as long as pyproject.toml doesn't change, regardless of how often app/ changes.
#
# We deliberately stop at --no-install-project rather than also installing this
# project itself (Astral's own example does a second `uv sync --no-editable` here).
# `app/config.py` resolves DATA_DIR relative to its own file location
# (`Path(__file__).resolve().parent.parent`), matching the local-dev layout where
# `data/` sits next to `app/` -- a non-editable install would move config.py into
# site-packages, breaking that assumption. Skipping the install and relying on
# PYTHONPATH=/app (set below) keeps the same layout in the container as on disk.
COPY pyproject.toml ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-install-project


FROM python:3.14-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PATH="/opt/venv/bin:$PATH"

# libgomp1: the OpenMP runtime torch (a docling dependency) needs at import time.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY app ./app
COPY streamlit_app ./streamlit_app
COPY data/manifest.json ./data/manifest.json


FROM runtime AS api
EXPOSE 8000
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]


FROM runtime AS streamlit
EXPOSE 8501
CMD ["streamlit", "run", "streamlit_app/Home.py", "--server.address=0.0.0.0", "--server.port=8501"]
