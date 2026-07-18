# syntax=docker/dockerfile:1
#
# Two runnable images from one build: `api` (FastAPI) and `streamlit` (demo UI).
# Build/run a specific one with `--target`:
#   docker build --target api -t portfolio-api .
#   docker build --target streamlit -t portfolio-streamlit .
# (docker-compose.yml does this for you.)
#
# System-package notes (checked against what pyproject.toml actually declares, not
# copied wholesale from wherever this Dockerfile started as a template):
# - libzbar0 (runtime): pyzbar loads it via ctypes at import time -- pure-Python
#   wheel, but non-functional without the shared library present.
# - libcairo2 (runtime): cairosvg (via cairocffi) loads it the same way.
# - libssl3 (runtime): defensive -- see the cryptography note below.
# - build-essential/libssl-dev/libffi-dev/pkg-config/rustc/cargo (builder-only):
#   only needed if `cryptography` has no prebuilt wheel for this exact Python
#   version/arch and uv has to build it from source; harmless to include since the
#   whole builder stage is discarded and never reaches the runtime image.
# - poppler-utils (the PyPI package, not the apt one): ships its own precompiled
#   binaries, so no system `poppler-utils` package is needed.
# - tesseract-ocr and friends: NOT included. They'd only matter for the commented-out
#   `unstructured[pdf]` dependency; docling's own OCR path is RapidOCR (onnxruntime),
#   not tesseract. Add them back if `unstructured[pdf]` gets uncommented.
# - redis (the server, as an apt package): deliberately not installed in this image.
#   redis[hiredis]/aiocache[redis] are *clients* -- they connect to a Redis server,
#   they don't need to run one. When Epic 3 actually needs Redis, it belongs as its
#   own service in docker-compose.yml (e.g. the official `redis:alpine` image), not
#   bundled into the app container.
# - gnupg/openssl (the CLIs): were needed for the old Dockerfile's
#   `curl | python3 -` Poetry bootstrap. We install uv by copying the binary
#   (below), so there's no script-piping step that needs them.
# - Fonts (liberation/noto/emoji): matter once Playwright or cairosvg actually
#   render pages/text to images. Nothing in this codebase does that yet (Epic 3's
#   scraper isn't built), so they're deferred rather than paid for speculatively.

FROM python:3.14-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=0

# Build-time-only toolchain: discarded entirely once this stage isn't copied forward.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libssl-dev \
    libffi-dev \
    pkg-config \
    rustc \
    cargo \
    && rm -rf /var/lib/apt/lists/*

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

# See the system-package notes at the top of this file for why each of these (and
# not others) is here.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    libzbar0 \
    libcairo2 \
    libssl3 \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system app \
    && useradd --system --gid app --create-home --home-dir /home/appuser appuser
# --create-home: Streamlit writes to ~/.streamlit (config/credentials) on first run;
# a homeless system user would leave that with nowhere writable to go.

ENV HOME=/home/appuser

WORKDIR /app
COPY --from=builder --chown=appuser:app /opt/venv /opt/venv
COPY --chown=appuser:app app ./app
COPY --chown=appuser:app streamlit_app ./streamlit_app
COPY --chown=appuser:app data/manifest.json ./data/manifest.json

USER appuser


FROM runtime AS api
# Restated even though `runtime` already switched to it: some Dockerfile security
# scanners (e.g. the JetBrains Cloud/IaC Security plugin) only check the final stage
# for its own explicit USER line and don't trace inheritance across a multi-stage
# FROM <stage> AS <target> split.
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/ || exit 1
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]


FROM runtime AS streamlit
USER appuser
EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1
CMD ["streamlit", "run", "streamlit_app/Home.py", "--server.address=0.0.0.0", "--server.port=8501"]
