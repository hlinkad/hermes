import os
import re
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PACKAGE_DIR = Path(__file__).resolve().parent
_PROJECT_ENV_FILE = _PACKAGE_DIR / ".env"
_HERMES_ENV_FILE = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes")) / ".env"

# Settings precedence is:
# 1. Explicit Settings(...) overrides
# 2. OS environment variables
# 3. Project-local deep_notes/.env, for standalone RAG testing
# 4. Active Hermes ~/.hermes/.env, for gateway/plugin runtime
# 5. Code defaults below
#
# Keep secrets out of git. deep_notes/.env is ignored; .env.example documents
# non-secret defaults and comments for API keys.
_ENV_FILES = (str(_HERMES_ENV_FILE), str(_PROJECT_ENV_FILE))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # API
    api_port: int = 8000
    api_key: str = ""

    # Vault / sources
    vault_path: str = ""
    # Optional comma-separated extra source roots, e.g. Google Drive text extracts.
    # These are indexed as derived retrieval material; originals remain the source of truth.
    source_paths: str = ""
    # Optional comma-separated book files/directories. Supports text/markdown with
    # page markers and PDFs when pypdf is installed. Book chunks keep page-range
    # metadata so queries can cite pages like pp. 184-186.
    book_paths: str = ""
    book_pages_per_chunk: int = 3

    # Embedding
    embed_provider: str = "ollama"  # "ollama" | "openai"
    embed_model: str = "bge-m3"
    ollama_base_url: str = "http://localhost:11434"
    openai_api_key: str = ""

    # Vector store
    vector_store_provider: str = "qdrant"  # "qdrant" | "chroma"
    qdrant_url: str = "http://localhost:6333"
    collection_name: str = ""

    @model_validator(mode="after")
    def _derive_collection_name(self):
        if not self.collection_name and self.vault_path:
            slug = re.sub(r"[^a-z0-9]+", "-", Path(self.vault_path).name.lower()).strip("-")
            self.collection_name = slug or "obsidian_notes"
        elif not self.collection_name:
            self.collection_name = "obsidian_notes"
        return self

    # Chunking
    chunk_strategy: str = "markdown"  # "sentence" | "token" | "markdown"
    chunk_size: int = 512
    chunk_overlap: int = 50

    # LLM
    llm_provider: str = "openai"  # "openrouter" | "openai" | "ollama" | "deepseek"
    llm_model: str = "gpt-5.5"
    openrouter_api_key: str = ""
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"

    # Retrieval
    similarity_top_k: int = 3
    # Compact context injected by the optional Hermes pre_llm_call plugin.
    auto_context_enabled: bool = True
    auto_context_top_k: int = 5
    auto_context_min_score: float = 0.55
    auto_context_max_chars: int = 3500


def get_settings(**overrides) -> Settings:
    return Settings(**overrides)
