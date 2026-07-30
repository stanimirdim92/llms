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
# - libgl1/libglib2.0-0 (runtime): docling's table-structure model pulls in
#   opencv-python transitively (via docling-ibm-models), which dlopens libGL/glib
#   at import time regardless of the "headless" framing -- without these, ingesting
#   any document fails at table-model init with `ImportError: libGL.so.1`.
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
COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /uvx /bin/

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
#
# uv.lock is copied so the image installs the exact resolution the repository pins instead of
# re-resolving at build time. Without it, two builds of the same commit could ship different
# dependency versions and CI would test a set nobody deploys.
#
# `--locked`, not `--frozen`. Both use the lock as-is, but only `--locked` asserts the lock is
# still current for pyproject.toml -- checked, because the distinction is easy to get backwards:
# with `--frozen`, adding a dependency to pyproject.toml and forgetting to re-lock builds
# happily and silently omits it, and the failure lands at runtime as an ImportError.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-install-project --locked


FROM python:3.14-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PATH="/opt/venv/bin:$PATH"

# See the system-package notes at the top of this file for why each of these (and
# not others) is here.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    libgl1 \
    libglib2.0-0 \
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

# Docling downloads its models on first use, not at build time: the layout model
# (docling-layout-heron) and table-structure model from HuggingFace, plus RapidOCR's
# detection/recognition weights. That's ~1 minute of downloads on a cold start, and
# without a persisted cache it repeats on every container recreate -- which is most of
# what a "slow first upload" actually is, not inference.
#
# All three env vars point inside one directory so a single volume mount
# (docker-compose.yml mounts `model_cache` here) persists every cache at once:
# HF_HOME covers HuggingFace, TORCH_HOME covers torch.hub, and XDG_CACHE_HOME is the
# fallback RapidOCR and other libs respect. Pre-created with appuser ownership so the
# named volume inherits it -- a volume mounted over a root-owned path would leave the
# non-root process unable to write, and the downloads would silently fail to cache.
ENV XDG_CACHE_HOME=/home/appuser/.cache \
    HF_HOME=/home/appuser/.cache/huggingface \
    TORCH_HOME=/home/appuser/.cache/torch
RUN mkdir -p /home/appuser/.cache/huggingface /home/appuser/.cache/torch \
    && chown -R appuser:app /home/appuser/.cache

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
# Informational only -- EXPOSE doesn't control the actual bind port (the CMD below
# does, reading $PORT at container runtime) or enforce anything at the network level;
# docker-compose.yml's port mapping is what actually matters. Left static since making
# it dynamic would need an ARG plumbed through just for documentation's sake.
EXPOSE 8000
# /health/ready, not `/`. `/` returned a static JSON body, so this reported healthy with
# Postgres down, Qdrant unreachable and Redis gone -- and `depends_on: service_healthy` plus
# nginx both trusted that answer, so every dependency outage presented as a working container
# serving 500s. Readiness probes the dependencies and 503s when a required one is missing.
#
# --start-period is longer than the old 10s: readiness genuinely can't pass until postgres and
# qdrant accept connections, and a too-short grace period marks a correctly-starting container
# unhealthy. --timeout exceeds the endpoint's own 3s per-probe budget so a slow dependency is
# reported as down by the endpoint rather than as a curl timeout with no detail.
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/health/ready || exit 1
# gunicorn + UvicornWorker (process-supervised multi-worker serving), not bare uvicorn --
# gunicorn[http2] is already a dependency. GUNICORN_WORKERS is env-configurable rather
# than a fixed count: a much bigger box would want more than this container's default of
# 2, and hardcoding a large number here would be wrong for a demo-scale deployment.
#
# --timeout is 600 (10 minutes), raised from 120. Ingestion is synchronous today and a
# real document takes anywhere from 10s to 2min -- 120s sat close enough to the upper end
# that a large PDF could trip it, and gunicorn's timeout is not a graceful 504: it SIGKILLs
# the worker mid-parse, so the client sees a bare connection failure with nothing naming
# the timeout, and any other request being served by that worker dies with it. nginx's
# proxy_read_timeout is wired to the same value (see nginx/Dockerfile) so the two can't
# drift into a mismatch where the shorter one silently decides the real budget.
#
# This is a stopgap, not the destination: a 10-minute worker timeout means one stuck
# request holds a worker for 10 minutes, and with GUNICORN_WORKERS=2 two of them stall
# the service. Once ingestion moves behind a job queue (EPIC_4_PLAN.md Phase 5) the
# upload request returns in milliseconds and this should come back down -- the value that
# genuinely has to stay large is nginx's client_body_timeout, since the bytes still have
# to arrive over the wire no matter what processes them afterwards.
# uvicorn.workers.UvicornWorker's own CONFIG_KWARGS defaults to loop="auto", so this
# keeps the same uvloop-when-available behavior the previous bare-uvicorn --loop uvloop
# had explicitly -- no separate loop flag needed with this worker class.
# --preload loads the app (and its heavy import graph -- docling, langchain, etc.) once
# in the master process before forking, so workers share that via copy-on-write memory
# instead of each separately re-importing it. Safe here because nothing at import time
# eagerly opens a Qdrant/Postgres connection -- api/routers/{ask,documents}.py's
# @lru_cache-decorated store/service getters only construct their client on a worker's
# first actual request, after the fork, so each worker still gets its own connection
# rather than sharing one across forked processes. (Reasoned through the code, not
# load-tested against a live multi-worker deployment -- no way to do that in this sandbox.)
CMD ["bash", "-c", "gunicorn app.api.main:app \
    --workers ${GUNICORN_WORKERS:-2} \
    --worker-class uvicorn.workers.UvicornWorker \
    --bind 0.0.0.0:${PORT:-8000} \
    --timeout ${GUNICORN_TIMEOUT:-600} \
    --keep-alive 5 \
    --max-requests 1000 \
    --max-requests-jitter 100 \
    --preload"]


FROM runtime AS streamlit
USER appuser
EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1
CMD ["streamlit", "run", "streamlit_app/Home.py", "--server.address=0.0.0.0", "--server.port=8501"]


FROM runtime AS worker
# Runs document ingestion off the request path -- parse/chunk/embed for one upload takes
# 10s-2min, which the api can't hold a connection open for. Same image as `api` on purpose:
# it runs the same `ingest_document` code over the same models and the same ../data mount, so
# a separate leaner image would mean two dependency sets to keep in step for no gain.
USER appuser
# No EXPOSE and no HTTP healthcheck: this process listens on nothing. Liveness is instead
# "is it consuming jobs", which is only answerable from the database -- a `procrastinate
# healthchecks` shell probe here would report the *connector* is fine while the worker loop is
# wedged. Deliberately left without one rather than given a check that can't fail.
#
# --concurrency is bounded, not maximal: WORKER_CONCURRENCY x DOCLING_NUM_THREADS is what
# competes for cores (see config.py's comment). --one-shot is not used -- the worker is a
# long-running consumer, and restart-per-job would re-pay the torch/Docling import cost that
# dominates a short ingest.
# --app points at app.worker.tasks.app, NOT app.worker.app.app. Importing tasks.py is what
# registers the task on the app object; pointing at app.py would start a worker that connects
# fine and then rejects every job as an unknown task -- a failure that reads like a queueing
# bug rather than a missing import. (app.py deliberately carries no `import_paths`, so that the
# api can enqueue without importing Docling; see its module docstring.)
CMD ["bash", "-c", "procrastinate --app=app.worker.tasks.app worker \
    --concurrency ${WORKER_CONCURRENCY:-2} \
    --queues ingest"]
