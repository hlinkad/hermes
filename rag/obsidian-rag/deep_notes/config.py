import os
import re
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - fallback for minimal environments
    load_dotenv = None

_HERMES_ENV_FILE = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes")) / ".env"


def _load_env_without_override(path: Path) -> None:
    """Load simple KEY=VALUE dotenv files without overriding existing env vars."""
    if load_dotenv is not None:
        load_dotenv(path, override=False)
        return
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ[key] = value


# Load the single active env file for Hermes Brain RAG. Keep both secrets and
# deep_notes runtime settings in ~/.hermes/.env, or in $HERMES_HOME/.env for a
# non-default Hermes profile. OS environment values still have highest priority.
_load_env_without_override(_HERMES_ENV_FILE)


class Settings(BaseSettings):
    model_config = {}

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
    llm_provider: str = "openrouter"  # "openrouter" | "openai" | "ollama" | "deepseek"
    llm_model: str = "anthropic/claude-sonnet-4"
    openrouter_api_key: str = ""
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"

    # Retrieval
    similarity_top_k: int = 3
    # Compact context injected by the optional Hermes pre_llm_call plugin.
    auto_context_enabled: bool = True
    auto_context_top_k: int = 5
    auto_context_min_score: float = 0.25
    auto_context_max_chars: int = 3500


def get_settings(**overrides) -> Settings:
    return Settings(**overrides)
