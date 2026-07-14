FROM python:3.13-slim AS builder

ENV LANG=C.UTF-8 \
    PYTHONFAULTHANDLER=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=random \
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_DEFAULT_TIMEOUT=100 \
    # Poetry's configuration:
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_CACHE_DIR='/var/cache/pypoetry' \
    POETRY_HOME='/usr/local/poetry' \
    POETRY_VERSION=2.2.1 \
    # Project
    PYSETUP_PATH="/usr/local/www/langchain" \
    VENV_PATH="/usr/local/www/langchain/.venv"


ENV PATH="$POETRY_HOME/bin:$VENV_PATH/bin:$PATH"

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
    tesseract-ocr \
    libtesseract-dev \
    tesseract-ocr-deu \
    libzbar0 \
    libmagic-dev  \
    poppler-utils  \
    fonts-liberation \
    fonts-noto fonts-noto-color-emoji \
    && curl -sSL https://install.python-poetry.org | python3 - \
    &&  rm -rf /var/lib/apt/lists/* /tmp/*

# Set the working directory
WORKDIR $PYSETUP_PATH

# Copy project files
COPY pyproject.toml  ./

# Install dependencies using Poetry
RUN poetry install --no-root --no-interaction --no-ansi -vvv


RUN playwright install --with-deps chromium
COPY ./app ./app
COPY ./technologies ./technologies
COPY .env ./.env
COPY ./block.txt ./block.txt
COPY ./categories.json ./categories.json
COPY ./Image-not-found.png ./Image-not-found.png

CMD ["bash", "-c", "gunicorn app.server:app -b 0.0.0.0:8200 -w 17 --threads 5 -k uvicorn.workers.UvicornWorker -t 120 --keep-alive 70 --max-requests-jitter 100 --max-requests 1000"]
