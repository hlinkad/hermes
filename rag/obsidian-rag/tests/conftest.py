"""Shared test fixtures.

Strips environment variables and configured env files so tests see the
pure code defaults from `Settings`, not whatever happens to live in
`deep_notes/.env` or the active Hermes `.env`.
"""

import pytest

_ENV_PREFIXES = (
    "API_",
    "VAULT_",
    "SOURCE_",
    "BOOK_",
    "EMBED_",
    "OLLAMA_",
    "OPENAI_",
    "OPENROUTER_",
    "VECTOR_",
    "QDRANT_",
    "COLLECTION_",
    "CHUNK_",
    "LLM_",
    "SIMILARITY_",
    "AUTO_CONTEXT_",
    "OBSIDIAN_CORE_",
)


@pytest.fixture(autouse=True)
def isolate_settings(monkeypatch):
    """Run every test with a clean environment for Settings."""
    import os

    for key in list(os.environ):
        if key.startswith(_ENV_PREFIXES):
            monkeypatch.delenv(key, raising=False)

    try:
        from deep_notes import config
    except ModuleNotFoundError as exc:
        # Some lightweight integration tests exercise dependency-free artifacts
        # (for example Hermes gateway plugins) without installing the full RAG
        # app stack. Tests that import deep_notes directly will still surface the
        # missing dependency at their import boundary.
        if exc.name in {"pydantic", "pydantic_settings"}:
            return
        raise

    monkeypatch.setattr(
        config.Settings,
        "model_config",
        {"env_file": None, "env_file_encoding": "utf-8"},
    )
