from __future__ import annotations

import os
from functools import lru_cache
from importlib import util
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PACKAGE_ROOT / "data"


class Settings(BaseSettings):
    """Every credential is a `SecretStr`, not a `str`.

    One object holds four live secrets, so anything that renders it renders all four -- a
    `log.info(..., settings=settings)`, a `repr()` in a serialised traceback frame. This repository
    is public. `.get_secret_value()` therefore marks every point a secret escapes; grep for it
    rather than trusting any count written down here.

    `docs/TECHNICAL_DECISIONS.md` § Secrets in Settings has the rest.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    anthropic_api_key: SecretStr = Field(default=SecretStr(""))
    answer_model: str = Field(default="claude-sonnet-5")
    figure_caption_model: str = Field(default="claude-sonnet-5")
    # Bounded, not unbounded: the ceiling is Anthropic's rate limit, and a 429 storm is slower
    # than running sequentially.
    figure_caption_concurrency: int = Field(default=5)

    # Docling's PictureItem is *any* embedded image region -- icons, logos, rules included. Both
    # dimensions must clear this. At images_scale=1.5 a 16pt icon renders ~33px, so 64 excludes
    # icons and leaves real charts (hundreds of px) untouched. Lower it and decorative glyphs
    # become vision calls and retrievable chunks.
    figure_min_dimension_px: int = Field(
        default=64, description="Skip captioning images smaller than this in either dimension."
    )
    # A caption is the figure's *only* searchable text, so an unusable one is worse than none --
    # it becomes a chunk competing with real content in retrieval.
    figure_min_caption_chars: int = Field(
        default=40, description="Captions shorter than this are treated as unusable and dropped."
    )

    voyage_api_key: SecretStr = Field(default=SecretStr(""))
    voyage_model: str = Field(default="voyage-4")

    langsmith_api_key: SecretStr = Field(default=SecretStr(""))
    langsmith_tracing: bool = Field(default=False)
    langsmith_project: str = Field(default="portfolio-rag")
    langsmith_endpoint: str = Field(default="https://api.smith.langchain.com")

    reranker_backend: Literal["voyage", "local"] = Field(default="voyage")
    """Which reranker to use. A `Literal`, not a bare `str`: as a `str` a typo'd
    `RERANKER_BACKEND=locl` fell through the `== "local"` test to Voyage with no error and no
    log, so an operator could believe they had switched backends and be billing an API they
    thought they had turned off. Now it fails at `Settings` construction."""
    voyage_rerank_model: str = Field(default="rerank-2.5")
    local_reranker_model: str = Field(default="BAAI/bge-reranker-v2-m3")

    qdrant_url: str = Field(default="http://localhost:6333")
    qdrant_collection: str = Field(default="portfolio_rag")

    # `POSTGRES_USER`/`PASSWORD`/`DB` are the names the official postgres image reads itself, so
    # one trio serves both consumers -- do not reintroduce a parallel `DB_USER`/`PASSWORD`/`NAME`.
    # `DATABASE_URL` overrides all of them at once when set.
    db_driver: str = Field(default="postgresql+psycopg")
    db_host: str = Field(default="localhost")
    db_port: int = Field(default=5432)
    postgres_user: str = Field(default="portfolio")
    postgres_password: SecretStr = Field(default=SecretStr("portfolio"))
    postgres_db: str = Field(default="portfolio")
    database_url: SecretStr = Field(
        default=SecretStr(""),
        description="Full DSN override. If unset, built from db_host/db_port/db_driver/postgres_user/password/db.",
    )

    # Per gunicorn worker, not shared across forks. **`GUNICORN_WORKERS * (pool_size +
    # max_overflow)` must stay under Postgres's `max_connections`** (100 by default): 2 workers is
    # 30, but the ~17 an 8-vCPU box wants would reach ~255 and exhaust it. Raising workers means
    # lowering this, raising `max_connections`, or adding PgBouncer.
    db_pool_size: int = Field(default=10)
    db_max_overflow: int = Field(default=5)
    db_pool_timeout: int = Field(default=30)
    db_pool_recycle: int = Field(default=1800)

    processed_dir: Path = Field(default=DATA_DIR / "processed")
    upload_dir: Path = Field(default=DATA_DIR / "uploads")
    max_upload_size_mb: int = Field(default=20)

    retrieval_top_k: int = Field(default=20)
    rerank_top_n: int = Field(default=5)

    chunk_max_tokens: int = Field(default=700)

    # `DOCLING_NUM_THREADS` is the same env var Docling's own `AcceleratorOptions` reads
    # (`env_prefix="DOCLING_"`), so one setting configures both paths rather than two competing
    # knobs. Docling's own default is 4, which leaves a modern box idle; `None` detects at runtime.
    docling_num_threads: int | None = Field(
        default=None, description="CPU threads for Docling model inference. None = os.cpu_count()."
    )

    # **`WORKER_CONCURRENCY` is deliberately not a field here** -- procrastinate takes it as a CLI
    # argument, so nothing in Python reads it and a field would be a second value drifting from the
    # CMD's fallback. Its *product* with `docling_num_threads` competes for cores: on the 8-vCPU
    # target 2x4 fits and 4x8 oversubscribes 4x, making concurrent ingests slower than serial ones.
    # Raise one only alongside lowering the other.

    # **The wildcard default is inert only while `cors_allow_credentials` is False and
    # `cors_allow_headers` is empty** -- a browser then cannot attach `x-api-key`, so nothing
    # authenticated is reachable. It must not survive a browser UI; the validator below refuses the
    # dangerous pair.
    cors_allow_origins: list[str] = Field(default_factory=lambda: ["*"])
    # DELETE because `DELETE /v1/keys/{key_id}` exists -- omitting it surfaces as a preflight
    # rejection on revocation, the one call nobody wants to debug in a hurry.
    cors_allow_methods: list[str] = Field(default_factory=lambda: ["GET", "POST", "DELETE"])
    cors_allow_headers: list[str] = Field(default_factory=list)
    # A browser cannot *read* a non-safelisted response header unless it is exposed here, so
    # without this the `X-RateLimit-*` headers arrive and `fetch` cannot see them -- which reads as
    # the API not sending them. `Retry-After` likewise: it is what a client paces itself on.
    cors_expose_headers: list[str] = Field(
        default_factory=lambda: ["X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset", "Retry-After"]
    )
    cors_allow_credentials: bool = Field(
        default=False, description="Required for cookie-based browser sessions. Forbidden with '*' origins."
    )

    log_level: str = Field(default="INFO")
    log_json: bool = Field(default=False)  # True in containers; console-friendly locally

    # Counters must be shared, not per-process: with `GUNICORN_WORKERS > 1`, in-process counters
    # let through workers x limit requests.
    redis_host: str = Field(default="localhost")
    redis_port: int = Field(default=6379)
    redis_db: int = Field(default=0)
    redis_username: str = Field(default="")
    redis_password: SecretStr = Field(default=SecretStr(""))
    # Passed explicitly because **`limits` defaults it to 100** (measured against 5.8.0) and its
    # pool raises `MaxConnectionsError` rather than queueing -- so the default turns burst load into
    # 500s, under exactly the concurrency rate limiting exists to absorb. Per *process*.
    redis_max_connections: int = Field(default=512)

    # Per-key request budgets, per `rate_limit_window_seconds`. Uploads get a much
    # tighter budget than questions because they cost far more: Docling parsing (CPU), one
    # Anthropic vision call per figure, and a Voyage embedding call per chunk. /ask is a
    # retrieve + rerank + one generation.
    #
    # Key management is tighter still, and not for cost -- it is three cheap queries. A
    # legitimate client mints a key when a human asks it to, so anything faster than a few
    # per minute is either a loop or someone walking the key space.
    rate_limit_window_seconds: int = Field(default=60)
    rate_limit_ask: int = Field(default=60)
    rate_limit_upload: int = Field(default=10)
    rate_limit_keys: int = Field(default=10)
    # Document reads had been sharing the `ask` bucket, which inverts the cost-based split
    # the rest of this design rests on: the API's own docs tell a client to *poll* the status
    # route while a document ingests, and each poll was spending the same budget as a
    # question (retrieve + rerank + generate) to do one indexed Postgres read.
    rate_limit_documents: int = Field(default=120)

    @property
    def redis_url(self) -> str:
        credentials = ""
        if self.redis_password:
            credentials = f"{self.redis_username}:{self.redis_password.get_secret_value()}@"
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
            # `SecretStr`, and this is the field that made masking `postgres_password` alone
            # theatre: the assembled DSN embeds the password in plain text and sat two lines
            # away from it in every repr. Caught by the masking test, not by review.
            self.database_url = SecretStr(
                URL.create(
                    drivername=self.db_driver,
                    username=self.postgres_user,
                    password=self.postgres_password.get_secret_value(),
                    host=self.db_host,
                    port=self.db_port,
                    database=self.postgres_db,
                ).render_as_string(hide_password=False)
            )
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
    os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key.get_secret_value()
    os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
    os.environ["LANGSMITH_ENDPOINT"] = settings.langsmith_endpoint


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    _configure_langsmith(settings)
    return settings


class MissingCredentialsError(RuntimeError):
    """Raised when a provider key needed to do actual work isn't configured."""


def require_provider_credentials() -> None:
    """Fail loudly when the keys the pipeline cannot work without are absent.

    Deliberately *not* a `Settings` validator. Plenty of legitimate entry points need no
    provider keys at all -- `scripts/create_tenant.py`, the whole unit suite, `ty`, and any
    `import app.config` -- and making construction raise would break all of them to catch a
    deployment mistake.

    Called instead from the two places where the absence actually matters:

    - `api/main.py`'s lifespan, so a misconfigured container refuses to start rather than
      accepting traffic and failing every request deep inside an HTTP call;
    - `worker/tasks.py`'s job, where it fails *that document* with a readable
      `error_message` instead of killing the worker. A user who uploaded something gets
      "ANTHROPIC_API_KEY is not configured" on their document rather than silence.

    Both keys are unconditional: Voyage is the embedding provider (needed even when
    `RERANKER_BACKEND=local`, which only replaces reranking), and Anthropic answers questions
    and captions every figure.
    """
    settings = get_settings()
    missing = [
        name
        for name, value in (
            ("ANTHROPIC_API_KEY", settings.anthropic_api_key),
            ("VOYAGE_API_KEY", settings.voyage_api_key),
        )
        # `.get_secret_value()` because the check is on the *content*, and a `SecretStr` is
        # truthy by length -- so a key of three spaces would pass a bare truthiness test and
        # then fail every request with a 401 from the provider. `.strip()` keeps the original
        # behaviour: whitespace is not a credential.
        if not value.get_secret_value().strip()
    ]
    if missing:
        msg = (
            f"{' and '.join(missing)} not configured. Set them in portfolio/.env "
            f"(see .env.example). Ingestion and /ask cannot work without them."
        )
        raise MissingCredentialsError(msg)


def require_reranker_backend() -> None:
    """Fail at boot if `RERANKER_BACKEND=local` is set but the local model isn't installed.

    The README documents the local cross-encoder as a supported no-API-key fallback, but the
    single Dockerfile stage runs `uv sync` with no `--extra`, so `sentence-transformers` and
    `langchain-classic` are absent from every container this project builds. The result was
    the exact shape `require_provider_credentials` exists to prevent, one layer along: the
    container boots, passes `/health/ready`, accepts traffic, and then raises
    `ModuleNotFoundError` inside `_local_compressor()` on the first `/ask` -- and on every
    `/ask` after it.

    An import probe rather than a version check, because "installed" is precisely the
    question: the extra may be present locally and absent in the image, which is how this
    stayed invisible. `find_spec` does not execute the module, so it costs no model load.
    """
    if get_settings().reranker_backend != "local":
        return
    missing = [name for name in ("sentence_transformers", "langchain_classic") if util.find_spec(name) is None]
    if missing:
        verb = "is" if len(missing) == 1 else "are"
        msg = (
            f"RERANKER_BACKEND=local needs {' and '.join(missing)}, which {verb} not installed. "
            f"Install the extra (`uv sync --extra local-reranker`, or add it to the image build) "
            f"or set RERANKER_BACKEND=voyage."
        )
        raise MissingCredentialsError(msg)
