from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PACKAGE_ROOT / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    anthropic_api_key: str = Field(default="")
    answer_model: str = Field(default="claude-sonnet-5")
    figure_caption_model: str = Field(default="claude-sonnet-5")
    # Figure captions are one Anthropic call per figure and were the sequential stage of
    # ingestion -- a 15-figure paper meant 15 round-trips back to back, which no amount of
    # CPU or GPU touches. Kept modest rather than unbounded: the ceiling here is Anthropic's
    # rate limit, and a 429 storm would be slower than running sequentially.
    figure_caption_concurrency: int = Field(default=5)

    voyage_api_key: str = Field(default="")
    voyage_model: str = Field(default="voyage-4")

    langsmith_api_key: str = Field(default="")
    langsmith_tracing: bool = Field(default=False)
    langsmith_project: str = Field(default="portfolio-rag")
    langsmith_endpoint: str = Field(default="https://api.smith.langchain.com")

    reranker_backend: str = Field(default="voyage")  # "voyage" | "local"
    voyage_rerank_model: str = Field(default="rerank-2.5")
    local_reranker_model: str = Field(default="BAAI/bge-reranker-v2-m3")

    qdrant_url: str = Field(default="http://localhost:6333")
    qdrant_collection: str = Field(default="portfolio_rag")

    # Split vars are the configurable surface (e.g. rotate POSTGRES_PASSWORD alone
    # without touching a DSN string); DATABASE_URL is an escape hatch that overrides all
    # of them at once when set. `postgresql+psycopg` (psycopg 3, already pinned in
    # pyproject.toml) has native asyncio support in the same package -- unlike MySQL's
    # psycopg2/aiomysql split, there's no separate async driver to add for Postgres.
    #
    # postgres_user/password/db deliberately reuse the exact env var names
    # (POSTGRES_USER/PASSWORD/DB) the official `postgres` docker image itself reads to
    # initialize the database -- one credential trio serves both consumers instead of
    # a second DB_USER/PASSWORD/NAME copy that has to be kept in sync with it.
    # db_host/db_port/db_driver have no such upstream name to reuse (the postgres image
    # doesn't take a "what port am I on" env var), so those stay ours alone.
    db_driver: str = Field(default="postgresql+psycopg")
    db_host: str = Field(default="localhost")
    db_port: int = Field(default=5432)
    postgres_user: str = Field(default="portfolio")
    postgres_password: str = Field(default="portfolio")
    postgres_db: str = Field(default="portfolio")
    database_url: str = Field(
        default="",
        description="Full DSN override. If unset, built from db_host/db_port/db_driver/postgres_user/password/db.",
    )

    # Sized for a single gunicorn worker's own engine (each worker gets its own pool --
    # api/Dockerfile's --preload doesn't eagerly open a connection, so this isn't shared
    # across forks). GUNICORN_WORKERS * (db_pool_size + db_max_overflow) must stay under
    # Postgres's max_connections (100 by default): at the default of 2 workers that's 30,
    # comfortably under; a real deployment running the ~17 workers an 8vCPU box wants
    # (2*cpu+1) would hit ~255 and needs either a lower db_pool_size here, a raised
    # Postgres max_connections, or a pooler (PgBouncer) in front -- not added speculatively.
    db_pool_size: int = Field(default=10)
    db_max_overflow: int = Field(default=5)
    db_pool_timeout: int = Field(default=30)
    db_pool_recycle: int = Field(default=1800)

    manifest_path: Path = Field(default=DATA_DIR / "manifest.json")
    raw_pdf_dir: Path = Field(default=DATA_DIR / "raw_pdfs")
    processed_dir: Path = Field(default=DATA_DIR / "processed")
    upload_dir: Path = Field(default=DATA_DIR / "uploads")
    max_upload_size_mb: int = Field(default=20)

    retrieval_top_k: int = Field(default=20)
    rerank_top_n: int = Field(default=5)

    chunk_max_tokens: int = Field(default=700)

    # Docling's own AcceleratorOptions defaults num_threads to 4, which leaves most of a
    # modern box idle during layout/table inference (the CPU-bound bulk of ingestion).
    # None means "detect at runtime" -- see parser.py. Note the env var for this field,
    # DOCLING_NUM_THREADS, is deliberately the same one Docling's AcceleratorOptions
    # reads itself (it's a BaseSettings with env_prefix="DOCLING_"), so setting it once
    # configures both paths consistently rather than having two competing knobs.
    docling_num_threads: int | None = Field(
        default=None, description="CPU threads for Docling model inference. None = os.cpu_count()."
    )

    # Concurrent ingest jobs per worker process. Neither this nor docling_num_threads means
    # anything alone -- their *product* is what competes for cores, so on the 8-vCPU target
    # box 2 x 4 fits and 4 x 8 would oversubscribe by 4x, making concurrent ingests slower
    # than running them one at a time (context-switching on top of thread contention inside
    # Docling's layout and table-structure passes). Raise this only alongside lowering
    # DOCLING_NUM_THREADS, or on a bigger machine.
    worker_concurrency: int = Field(default=2, description="Concurrent ingest jobs per worker process.")

    # Defaults preserve today's hardcoded CORSMiddleware call in api/main.py exactly --
    # override via .env once there's a real frontend origin to lock this down to.
    #
    # The wildcard default is inert *today* and must not survive a browser UI. It is inert
    # because cors_allow_credentials is False and cors_allow_headers is empty: a browser
    # can't attach `x-api-key` to a cross-origin request without it being allow-listed, so
    # the preflight fails and the underlying request 401s. Nothing authenticated is
    # reachable, so no data is exposed. What makes it dangerous is turning on credentials
    # -- see the validator below.
    cors_allow_origins: list[str] = Field(default_factory=lambda: ["*"])
    cors_allow_methods: list[str] = Field(default_factory=lambda: ["GET", "POST"])
    cors_allow_headers: list[str] = Field(default_factory=list)
    cors_expose_headers: list[str] = Field(default_factory=list)
    cors_allow_credentials: bool = Field(
        default=False, description="Required for cookie-based browser sessions. Forbidden with '*' origins."
    )

    log_level: str = Field(default="INFO")
    log_json: bool = Field(default=False)  # True in containers; console-friendly locally

    # Redis backs rate limiting (app/rate_limit.py) -- its first real consumer; the service
    # had been running as unused infra. Counters must be shared, not per-process: with
    # GUNICORN_WORKERS > 1, in-process counters would let through workers x limit requests.
    redis_host: str = Field(default="localhost")
    redis_port: int = Field(default=6379)
    redis_db: int = Field(default=0)
    redis_username: str = Field(default="")
    redis_password: str = Field(default="")

    # Per-tenant request budgets, per `rate_limit_window_seconds`. Uploads get a much
    # tighter budget than questions because they cost far more: Docling parsing (CPU), one
    # Anthropic vision call per figure, and a Voyage embedding call per chunk. /ask is a
    # retrieve + rerank + one generation.
    rate_limit_window_seconds: int = Field(default=60)
    rate_limit_ask: int = Field(default=60)
    rate_limit_upload: int = Field(default=10)

    @property
    def redis_url(self) -> str:
        credentials = ""
        if self.redis_password:
            credentials = f"{self.redis_username}:{self.redis_password}@"
        return f"redis://{credentials}{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @model_validator(mode="after")
    def _reject_credentialed_wildcard_cors(self) -> Settings:
        """Refuse to start on `cors_allow_origins=["*"]` together with credentials.

        Starlette does not reject this combination, and what it does instead is the
        problem. From `starlette/middleware/cors.py` (1.3.1):

            if self.allow_all_origins and self.allow_credentials:
                self.allow_explicit_origin(headers, origin)

        With the wildcard it echoes back *whatever* `Origin` the caller sent, alongside
        `Access-Control-Allow-Credentials: true`. `Allow-Origin: *` would at least make
        browsers refuse to send cookies; reflecting the origin tells the browser this
        specific attacker site is trusted. So any page on the internet can call this API
        with the victim's session cookie attached and read the response -- every document
        and every conversation, from a drive-by. It is the one CORS mistake with no
        partial version: it is either off or it is total.

        Raised at startup rather than logged, because the whole failure mode is that
        nothing looks wrong from the inside: the app serves correct responses, and the
        damage is only visible from the attacker's page.
        """
        if self.cors_allow_credentials and "*" in self.cors_allow_origins:
            msg = (
                "CORS_ALLOW_CREDENTIALS=true with CORS_ALLOW_ORIGINS=['*'] lets any origin read "
                "authenticated responses. List the frontend's exact origins instead, e.g. "
                'CORS_ALLOW_ORIGINS=["https://app.example.com"].'
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _assemble_database_url(self) -> Settings:
        if not self.database_url:
            self.database_url = URL.create(
                drivername=self.db_driver,
                username=self.postgres_user,
                password=self.postgres_password,
                host=self.db_host,
                port=self.db_port,
                database=self.postgres_db,
            ).render_as_string(hide_password=False)
        return self


def _configure_langsmith(settings: Settings) -> None:
    """Bridge our own env-loaded Settings into the env vars LangChain/LangSmith's
    SDK reads directly (it doesn't know about pydantic-settings or our .env file).
    A no-op if tracing is off or no key is configured, so this is safe to call
    unconditionally.
    """
    if not (settings.langsmith_tracing and settings.langsmith_api_key):
        return
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
    os.environ["LANGSMITH_ENDPOINT"] = settings.langsmith_endpoint


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    _configure_langsmith(settings)
    return settings
