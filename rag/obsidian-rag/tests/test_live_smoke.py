from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from deep_notes.live_smoke import (
    FIXTURE_RELATIVE_PATH,
    UNIQUE_PHRASE,
    LiveSmokeReport,
    _parser,
    create_fixture_vault,
    main,
    run_live_smoke,
    verify_obsidian_payload,
)
from deep_notes.obsidian_core_adapter import OBSIDIAN_STRUCTURAL_METADATA_KEYS
from deep_notes.query import RetrievalResult, SourceChunk


def _sample_payload(source_root: str = "/tmp/dh223-smoke-vault") -> dict:
    return {
        "file_name": "dh223-live-smoke.md",
        "file_path": FIXTURE_RELATIVE_PATH,
        "source_root": source_root,
        "source_kind": "vault",
        "layer": "wiki",
        "title": "DH223 Live Smoke Note",
        "tags": ["dh223", "smoke", "obsidian-rag"],
        "aliases": ["DH223 Smoke Alias"],
        "sources": ["dh223-live-smoke-fixture"],
        "obsidian_metadata_schema": "hermes_brain.rag_metadata.v1",
        "links": [{"target": "Target Smoke Note", "alias": "target smoke alias"}],
        "embeds": [{"target": "smoke-diagram.png", "width": 400}],
        "block_ids": ["dh223-smoke-block"],
        "callouts": [{"callout_type": "tip", "title": "Smoke citation"}],
        "obsidian_summary": {"links": 1, "embeds": 1, "headings": 1, "blocks": 1, "callouts": 1},
        "_node_content": json.dumps(
            {
                "text": f"The unique retrieval phrase is {UNIQUE_PHRASE}.\n"
                "This note links to target smoke alias.\n"
                "Smoke citation\n"
                "Retrieval should cite this Obsidian-backed note.",
                "excluded_embed_metadata_keys": list(OBSIDIAN_STRUCTURAL_METADATA_KEYS),
                "excluded_llm_metadata_keys": list(OBSIDIAN_STRUCTURAL_METADATA_KEYS),
            }
        ),
    }


def test_create_fixture_vault_writes_scoped_obsidian_note(tmp_path: Path) -> None:
    vault = create_fixture_vault(tmp_path)
    note = vault / FIXTURE_RELATIVE_PATH

    text = note.read_text(encoding="utf-8")

    assert note.is_file()
    assert UNIQUE_PHRASE in text
    assert "[[Target Smoke Note|target smoke alias]]" in text
    assert "![[smoke-diagram.png|400]]" in text
    assert "^dh223-smoke-block" in text
    assert "[!tip]" in text


def test_verify_obsidian_payload_accepts_rich_metadata_and_noise_free_text() -> None:
    result = verify_obsidian_payload(_sample_payload(), UNIQUE_PHRASE)

    assert result["file_path"] == FIXTURE_RELATIVE_PATH
    assert result["obsidian_metadata_schema"] == "hermes_brain.rag_metadata.v1"
    assert result["structural_metadata_excluded_from_embed_text"] is True
    assert result["structural_metadata_excluded_from_llm_text"] is True
    assert "aliases" in result["obsidian_fields_present"]


def test_verify_obsidian_payload_rejects_structural_noise_in_semantic_text() -> None:
    payload = _sample_payload()
    content = json.loads(payload["_node_content"])
    content["text"] += "\n![[smoke-diagram.png|400]]"
    payload["_node_content"] = json.dumps(content)

    with pytest.raises(RuntimeError, match="structural noise"):
        verify_obsidian_payload(payload, UNIQUE_PHRASE)


def test_main_json_stdout_is_parseable_when_ingest_logs_are_emitted(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_run_live_smoke(**kwargs) -> LiveSmokeReport:
        print("noisy ingest log")
        return LiveSmokeReport(
            collection_name="dh223_obsidian_live_smoke_test",
            qdrant_url="http://qdrant.example.test:6333",
            vault_path="/tmp/vault",
            fixture_file="/tmp/vault/wiki/dh223-live-smoke.md",
            docs_indexed=1,
            qdrant_points=1,
            positive_query="positive",
            positive_sources=[],
            negative_query="negative",
            negative_top_score=0.1,
            negative_context_injected=False,
            metadata_checks={"semantic_text_noise_removed": True},
            cleanup_collection=True,
            cleanup_collection_verified=True,
            cleanup_vault=True,
            cleanup_vault_verified=True,
            remaining_feature_gates=[],
        )

    monkeypatch.setattr("deep_notes.live_smoke.run_live_smoke", fake_run_live_smoke)

    assert main(["--json"]) == 0
    captured = capsys.readouterr()

    assert "noisy ingest log" in captured.err
    parsed = json.loads(captured.out)
    assert parsed["collection_name"] == "dh223_obsidian_live_smoke_test"


def test_parser_defaults_to_live_ollama_embedder_even_when_env_differs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EMBED_PROVIDER", "openai")
    monkeypatch.setenv("EMBED_MODEL", "text-embedding-3-large")

    args = _parser().parse_args([])

    assert args.embed_provider == "ollama"
    assert args.embed_model == "bge-m3"


def test_run_live_smoke_hard_scopes_settings_and_cleans_custom_fixture_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    class FakeQdrantClient:
        def __init__(self, *args, **kwargs):
            pass

        def collection_exists(self, collection_name: str) -> bool:
            return False

        def delete_collection(self, collection_name: str) -> None:
            pass

        def count(self, collection_name: str, exact: bool):
            return SimpleNamespace(count=1)

        def scroll(self, collection_name: str, **kwargs):
            config = captured["config"]
            return ([SimpleNamespace(payload=_sample_payload(config.vault_path))], None)

    def fake_run_ingest(config) -> int:
        captured["config"] = config
        return 1

    def fake_retrieve(question: str, config) -> RetrievalResult:
        if UNIQUE_PHRASE in question:
            return RetrievalResult(
                sources=[
                    SourceChunk(
                        file_name="DH223 Live Smoke Note",
                        file_path=FIXTURE_RELATIVE_PATH,
                        text=f"The unique retrieval phrase is {UNIQUE_PHRASE}.",
                        score=0.91,
                        layer="wiki",
                        source_kind="vault",
                    )
                ],
                context_str="",
            )
        return RetrievalResult(sources=[], context_str="")

    monkeypatch.setenv("SOURCE_PATHS", "/tmp/real-source")
    monkeypatch.setenv("BOOK_PATHS", "/tmp/real-book")
    monkeypatch.setenv("EMBED_PROVIDER", "openai")
    monkeypatch.setenv("AUTO_CONTEXT_ENABLED", "false")
    monkeypatch.setitem(
        __import__("sys").modules,
        "qdrant_client",
        SimpleNamespace(QdrantClient=FakeQdrantClient),
    )
    monkeypatch.setattr("deep_notes.live_smoke.run_ingest", fake_run_ingest)
    monkeypatch.setattr("deep_notes.live_smoke.retrieve", fake_retrieve)
    monkeypatch.setattr("deep_notes.live_smoke.build_context_for_prompt", lambda *args: "")

    report = run_live_smoke(
        qdrant_url="http://qdrant.example.test:6333",
        ollama_base_url="http://ollama.example.test:11434",
        obsidian_core_path="/workspace/obsidian-intelligence-core/src",
        fixture_root=tmp_path,
    )
    config = captured["config"]

    assert config.source_paths == ""
    assert config.book_paths == ""
    assert config.vector_store_provider == "qdrant"
    assert config.embed_provider == "ollama"
    assert config.auto_context_enabled is True
    assert report.docs_indexed == 1
    assert report.metadata_checks["all_payloads_scoped_to_fixture"] is True
    assert report.cleanup_vault_verified is True
    assert list(tmp_path.iterdir()) == []


def test_run_live_smoke_fails_when_requested_collection_cleanup_is_unverified(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}
    exists_calls = {"count": 0}

    class FakeQdrantClient:
        def __init__(self, *args, **kwargs):
            pass

        def collection_exists(self, collection_name: str) -> bool:
            exists_calls["count"] += 1
            return exists_calls["count"] > 1

        def delete_collection(self, collection_name: str) -> None:
            pass

        def count(self, collection_name: str, exact: bool):
            return SimpleNamespace(count=1)

        def scroll(self, collection_name: str, **kwargs):
            config = captured["config"]
            return ([SimpleNamespace(payload=_sample_payload(config.vault_path))], None)

    def fake_run_ingest(config) -> int:
        captured["config"] = config
        return 1

    def fake_retrieve(question: str, config) -> RetrievalResult:
        if UNIQUE_PHRASE in question:
            return RetrievalResult(
                sources=[
                    SourceChunk(
                        file_name="DH223 Live Smoke Note",
                        file_path=FIXTURE_RELATIVE_PATH,
                        text=f"The unique retrieval phrase is {UNIQUE_PHRASE}.",
                        score=0.91,
                        layer="wiki",
                        source_kind="vault",
                    )
                ],
                context_str="",
            )
        return RetrievalResult(sources=[], context_str="")

    monkeypatch.setitem(
        __import__("sys").modules,
        "qdrant_client",
        SimpleNamespace(QdrantClient=FakeQdrantClient),
    )
    monkeypatch.setattr("deep_notes.live_smoke.run_ingest", fake_run_ingest)
    monkeypatch.setattr("deep_notes.live_smoke.retrieve", fake_retrieve)
    monkeypatch.setattr("deep_notes.live_smoke.build_context_for_prompt", lambda *args: "")

    with pytest.raises(RuntimeError, match="cleanup failed"):
        run_live_smoke(
            qdrant_url="http://qdrant.example.test:6333",
            ollama_base_url="http://ollama.example.test:11434",
            obsidian_core_path="/workspace/obsidian-intelligence-core/src",
            fixture_root=tmp_path,
        )

    assert list(tmp_path.iterdir()) == []


def test_run_live_smoke_refuses_to_delete_existing_named_collection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    deleted: list[str] = []

    class FakeQdrantClient:
        def __init__(self, *args, **kwargs):
            pass

        def collection_exists(self, collection_name: str) -> bool:
            return collection_name == "custom_existing"

        def delete_collection(self, collection_name: str) -> None:
            deleted.append(collection_name)

    monkeypatch.setitem(
        __import__("sys").modules,
        "qdrant_client",
        SimpleNamespace(QdrantClient=FakeQdrantClient),
    )

    with pytest.raises(RuntimeError, match="already exists"):
        run_live_smoke(
            qdrant_url="http://qdrant.example.test:6333",
            ollama_base_url="http://ollama.example.test:11434",
            obsidian_core_path="/workspace/obsidian-intelligence-core/src",
            collection_name="custom_existing",
            fixture_root=tmp_path,
        )

    assert deleted == []


def test_run_live_smoke_blocks_reserved_collection_even_when_absent(
    tmp_path: Path,
) -> None:
    with pytest.raises(RuntimeError, match="reserved for persistent Hermes Brain data"):
        run_live_smoke(
            qdrant_url="http://qdrant.example.test:6333",
            ollama_base_url="http://ollama.example.test:11434",
            obsidian_core_path="/workspace/obsidian-intelligence-core/src",
            collection_name="hermes_brain",
            fixture_root=tmp_path,
        )

    assert list(tmp_path.iterdir()) == []


def test_run_live_smoke_refuses_to_delete_generated_collection_collision(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    deleted: list[str] = []

    class FakeQdrantClient:
        def __init__(self, *args, **kwargs):
            pass

        def collection_exists(self, collection_name: str) -> bool:
            return collection_name == "dh223_obsidian_live_smoke_collision"

        def delete_collection(self, collection_name: str) -> None:
            deleted.append(collection_name)

    monkeypatch.setattr(
        "deep_notes.live_smoke._temporary_collection_name",
        lambda: "dh223_obsidian_live_smoke_collision",
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "qdrant_client",
        SimpleNamespace(QdrantClient=FakeQdrantClient),
    )

    with pytest.raises(RuntimeError, match="Refusing to delete"):
        run_live_smoke(
            qdrant_url="http://qdrant.example.test:6333",
            ollama_base_url="http://ollama.example.test:11434",
            obsidian_core_path="/workspace/obsidian-intelligence-core/src",
            fixture_root=tmp_path,
        )

    assert deleted == []
    assert list(tmp_path.iterdir()) == []
