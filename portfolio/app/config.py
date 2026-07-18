import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

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

    chroma_path: Path = Field(default=DATA_DIR / "chroma")
    chroma_collection: str = Field(default="portfolio_rag")

    manifest_path: Path = Field(default=DATA_DIR / "manifest.json")
    raw_pdf_dir: Path = Field(default=DATA_DIR / "raw_pdfs")
    processed_dir: Path = Field(default=DATA_DIR / "processed")
    upload_dir: Path = Field(default=DATA_DIR / "uploads")
    max_upload_size_mb: int = Field(default=20)

    retrieval_top_k: int = Field(default=20)
    rerank_top_n: int = Field(default=5)

    chunk_max_tokens: int = Field(default=700)


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
