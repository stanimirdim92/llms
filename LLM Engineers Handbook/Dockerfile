FROM python:3.13-slim AS builder

ENV LANG=C.UTF-8 \
    PYTHONFAULTHANDLER=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=random \
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_DEFAULT_TIMEOUT=100 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONPATH=/usr/local/www/app \
    VENV_PATH="/usr/local/www/app/.venv"


ENV PATH="$VENV_PATH/bin:$PATH"

# Install necessary packages
RUN apt-get update  \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends --fix-missing   \
    ca-certificates \
    curl \
    redis \
    gnupg \
    openssl \
    build-essential \
    libssl-dev \
    libffi-dev \
    python3-dev \
    libzbar0 \
    libmagic-dev  \
    fonts-liberation \
    fonts-noto fonts-noto-color-emoji \
    &&  rm -rf /var/lib/apt/lists/* /tmp/*

# Install uv.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Install dependencies
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#intermediate-layers
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project

# Set the working directory
WORKDIR $PYTHONPATH

COPY ./pyproject.toml ./
COPY .env /.env
COPY ./README.md ./README.md
COPY ./app ./app

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync

CMD ["bash", "-c", "gunicorn app.server:app -b 0.0.0.0:8200 -k uvicorn.workers.UvicornWorker -t 80 --keep-alive 50 --max-requests-jitter 100 --max-requests 1000"]
