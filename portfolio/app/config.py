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
    voyage_model: str = Field(default="voyage-3.5")

    reranker_backend: str = Field(default="voyage")  # "voyage" | "local"
    voyage_rerank_model: str = Field(default="rerank-2.5")
    local_reranker_model: str = Field(default="BAAI/bge-reranker-v2-m3")

    chroma_path: Path = Field(default=DATA_DIR / "chroma")
    chroma_collection: str = Field(default="portfolio_rag")

    manifest_path: Path = Field(default=DATA_DIR / "manifest.json")
    raw_pdf_dir: Path = Field(default=DATA_DIR / "raw_pdfs")
    processed_dir: Path = Field(default=DATA_DIR / "processed")

    retrieval_top_k: int = Field(default=20)
    rerank_top_n: int = Field(default=5)

    chunk_max_tokens: int = Field(default=700)


@lru_cache
def get_settings() -> Settings:
    return Settings()
