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

    # Split vars are the configurable surface (e.g. rotate DB_PASSWORD alone without
    # touching a DSN string); DATABASE_URL is an escape hatch that overrides all of them
    # at once when set. `postgresql+psycopg` (psycopg 3, already pinned in pyproject.toml)
    # has native asyncio support in the same package -- unlike MySQL's psycopg2/aiomysql
    # split, there's no separate async driver to add for Postgres.
    db_driver: str = Field(default="postgresql+psycopg")
    db_host: str = Field(default="localhost")
    db_port: int = Field(default=5432)
    db_user: str = Field(default="portfolio")
    db_password: str = Field(default="portfolio")
    db_name: str = Field(default="portfolio")
    database_url: str = Field(
        default="",
        description="Full DSN override. If unset, built from db_host/db_port/db_user/db_password/db_name/db_driver.",
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

    # Defaults preserve today's hardcoded CORSMiddleware call in api/main.py exactly --
    # override via .env once there's a real frontend origin to lock this down to.
    cors_allow_origins: list[str] = Field(default_factory=lambda: ["*"])
    cors_allow_methods: list[str] = Field(default_factory=lambda: ["GET", "POST"])
    cors_allow_headers: list[str] = Field(default_factory=list)
    cors_expose_headers: list[str] = Field(default_factory=list)

    log_level: str = Field(default="INFO")
    log_json: bool = Field(default=False)  # True in containers; console-friendly locally

    @model_validator(mode="after")
    def _assemble_database_url(self) -> Settings:
        if not self.database_url:
            self.database_url = URL.create(
                drivername=self.db_driver,
                username=self.db_user,
                password=self.db_password,
                host=self.db_host,
                port=self.db_port,
                database=self.db_name,
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
