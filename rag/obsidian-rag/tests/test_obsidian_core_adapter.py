from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from llama_index.core.schema import MetadataMode

from deep_notes.components.chunking import get_splitter
from deep_notes.config import Settings
from deep_notes.ingest import load_documents, load_source_root, load_vault
from deep_notes.obsidian_core_adapter import (
    OBSIDIAN_STRUCTURAL_METADATA_KEYS,
    _ensure_core_path,
    document_from_obsidian_core,
    qdrant_safe_metadata,
)

CORE_SRC = Path("/workspace/obsidian-intelligence-core/src")


def _compound_note() -> str:
    return (
        "---\n"
        "title: Core Adapter Note\n"
        "tags: [brain, rag]\n"
        "aliases: [Adapter Alias]\n"
        "sources: [source-a]\n"
        "---\n"
        "# Core Adapter Note\n"
        "Body #inline-tag links to [[Target Note|target alias]].\n"
        "![[diagram.png|400]]\n"
        "## Details\n"
        "Important detail. ^detail-block\n"
        "> [!note] Keep\n"
        "> Callout body.\n"
    )


def _compound_note_with_sensitive_metadata() -> str:
    return (
        "---\n"
        "title: Secret-Free Payload Note\n"
        "tags: [brain, rag]\n"
        "aliases: [Safe Alias]\n"
        "sources: [https://example.org/report?token=TOP_SECRET_TOKEN&safe=1]\n"
        "api_key: TOP_SECRET_API_KEY\n"
        "session_token: TOP_SECRET_SESSION\n"
        "request_headers: [Authorization Bearer TOP_SECRET_HEADER]\n"
        "safe_source_url: "
        "https://user:pass@example.org/article?"
        "api_key=TOP_SECRET_QUERY&safe=1#access_token=TOP_SECRET_FRAGMENT\n"
        "---\n"
        "# Secret-Free Payload Note\n"
        "Body with [[Safe Link]].\n"
    )


def test_document_from_obsidian_core_preserves_existing_and_native_metadata(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    note_dir = vault / "wiki"
    note_dir.mkdir(parents=True)
    note_path = note_dir / "core-adapter.md"
    note_path.write_text(_compound_note(), encoding="utf-8")

    doc = document_from_obsidian_core(
        note_path,
        vault,
        source_kind="vault",
        layer="wiki",
        obsidian_core_path=str(CORE_SRC),
    )

    assert doc is not None
    assert "Body #inline-tag" in doc.text
    assert doc.metadata["file_name"] == "core-adapter.md"
    assert doc.metadata["file_path"] == "wiki/core-adapter.md"
    assert doc.metadata["source_root"] == str(vault)
    assert doc.metadata["source_kind"] == "vault"
    assert doc.metadata["layer"] == "wiki"
    assert doc.metadata["tags"] == ["brain", "rag"]
    assert doc.metadata["title"] == "Core Adapter Note"
    assert doc.metadata["sources"] == ["source-a"]
    assert doc.metadata["aliases"] == ["Adapter Alias"]
    assert doc.metadata["inline_tags"] == ["inline-tag"]
    assert doc.metadata["links"][0]["target"] == "Target Note"
    assert doc.metadata["links"][0]["alias"] == "target alias"
    assert doc.metadata["embeds"][0]["target"] == "diagram.png"
    assert doc.metadata["embeds"][0]["width"] == 400
    assert doc.metadata["headings"][1]["path"] == ["Core Adapter Note", "Details"]
    assert doc.metadata["block_ids"] == ["detail-block"]
    assert doc.metadata["callouts"][0]["callout_type"] == "note"
    assert doc.metadata["obsidian_summary"] == {
        "links": 1,
        "embeds": 1,
        "headings": 2,
        "blocks": 1,
        "callouts": 1,
    }
    for key in OBSIDIAN_STRUCTURAL_METADATA_KEYS:
        assert key in doc.excluded_embed_metadata_keys
        assert key in doc.excluded_llm_metadata_keys


def test_core_document_metadata_is_safe_for_qdrant_payload(tmp_path: Path) -> None:
    note = tmp_path / "secret-free.md"
    note.write_text(_compound_note_with_sensitive_metadata(), encoding="utf-8")

    doc = document_from_obsidian_core(
        note,
        tmp_path,
        source_kind="vault",
        layer="vault",
        obsidian_core_path=str(CORE_SRC),
    )

    assert doc is not None
    metadata = doc.metadata
    assert metadata["file_name"] == "secret-free.md"
    assert metadata["title"] == "Secret-Free Payload Note"
    assert metadata["aliases"] == ["Safe Alias"]
    assert metadata["links"][0]["target"] == "Safe Link"
    assert metadata["sources"] == ["https://example.org/report?token=[redacted]&safe=1"]
    assert "api_key" not in metadata["frontmatter"]
    assert "session_token" not in metadata["frontmatter"]
    assert "request_headers" not in metadata["frontmatter"]
    assert "api_key" not in metadata["properties"]
    assert "session_token" not in metadata["properties"]
    assert "request_headers" not in metadata["properties"]
    assert metadata["frontmatter"]["safe_source_url"] == (
        "https://[redacted]@example.org/article?api_key=[redacted]&safe=1#access_token=[redacted]"
    )

    encoded = json.dumps(metadata, sort_keys=True)
    assert "TOP_SECRET" not in encoded
    assert "Bearer" not in encoded


def test_qdrant_metadata_sanitizer_redacts_key_variants_without_corrupting_benign_text() -> None:
    metadata = qdrant_safe_metadata(
        {
            "title": "Secret project: Token economy",
            "frontmatter": {
                "api key": "TOP_SECRET_API_KEY",
                "AWS_ACCESS_KEY_ID": "TOP_SECRET_AWS_ACCESS_KEY_ID",
                "OpenAIAPIKey": "TOP_SECRET_OPENAI_API_KEY",
                "XAPIKey": "TOP_SECRET_X_API_KEY",
                "privateKey": "TOP_SECRET_PRIVATE_KEY",
                "x-auth": "TOP_SECRET_AUTH",
                "basic_auth": "TOP_SECRET_BASIC_AUTH",
                "responseHeaders": {"authorization": "Basic TOP_SECRET_HEADER"},
                "secretariat": "benign organization name",
            },
            "sources": [
                "https://user:pass@example.test/report?"
                "auth=TOP_SECRET_AUTH&safe=1#password=TOP_SECRET_PASSWORD",
                "Authorization: Basic dXNlcjpwYXNz",
                "Authorization Basic c2Vjb25kc2VjcmV0",
                "Authorization guide",
                "openai_api_key=TOP_SECRET_OPENAI_ASSIGNMENT",
                "aws_secret_access_key=TOP_SECRET_AWS_ASSIGNMENT",
                "privateKey=TOP_SECRET_PRIVATE_ASSIGNMENT",
                "APIToken=TOP_SECRET_API_TOKEN_ASSIGNMENT",
                "api key: TOP_SECRET_SPACED_API_KEY",
                'password: "p a s s"',
                "Token economy research",
            ],
        }
    )

    assert metadata["title"] == "Secret project: Token economy"
    assert metadata["frontmatter"] == {"secretariat": "benign organization name"}
    assert metadata["sources"][0] == (
        "https://[redacted]@example.test/report?auth=[redacted]&safe=1#password=[redacted]"
    )
    assert metadata["sources"][1] == "Authorization: [redacted]"
    assert metadata["sources"][2] == "Authorization [redacted]"
    assert metadata["sources"][3] == "Authorization guide"
    assert metadata["sources"][4] == "openai_api_key=[redacted]"
    assert metadata["sources"][5] == "aws_secret_access_key=[redacted]"
    assert metadata["sources"][6] == "privateKey=[redacted]"
    assert metadata["sources"][7] == "APIToken=[redacted]"
    assert metadata["sources"][8] == "api key: [redacted]"
    assert metadata["sources"][9] == "password: [redacted]"
    assert metadata["sources"][10] == "Token economy research"
    encoded = json.dumps(metadata, sort_keys=True)
    assert "TOP_SECRET" not in encoded
    assert "dXNlcjpwYXNz" not in encoded
    assert "c2Vjb25kc2VjcmV0" not in encoded


def test_core_metadata_survives_into_chunk_node_payload(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    wiki = vault / "wiki"
    wiki.mkdir(parents=True)
    (wiki / "note.md").write_text(_compound_note(), encoding="utf-8")

    docs = load_documents(
        Settings(
            vault_path=str(vault),
            obsidian_core_enabled=True,
            obsidian_core_path=str(CORE_SRC),
            chunk_strategy="markdown",
        )
    )
    splitter = get_splitter(Settings(vault_path="", chunk_strategy="markdown"))
    nodes = splitter.get_nodes_from_documents(docs)

    assert nodes
    node_metadata = nodes[0].metadata
    assert node_metadata["file_name"] == "note.md"
    assert node_metadata["file_path"] == "wiki/note.md"
    assert node_metadata["source_kind"] == "vault"
    assert node_metadata["layer"] == "wiki"
    assert node_metadata["title"] == "Core Adapter Note"
    assert node_metadata["tags"] == ["brain", "rag"]
    assert node_metadata["sources"] == ["source-a"]
    assert node_metadata["aliases"] == ["Adapter Alias"]
    assert node_metadata["links"][0]["target"] == "Target Note"
    assert node_metadata["wikilinks"][0]["target"] == "Target Note"
    assert node_metadata["embeds"][0]["target"] == "diagram.png"
    assert node_metadata["headings"][1]["path"] == ["Core Adapter Note", "Details"]
    assert node_metadata["blocks"][0]["block_id"] == "detail-block"
    assert node_metadata["block_ids"] == ["detail-block"]
    assert node_metadata["callouts"][0]["callout_type"] == "note"
    assert node_metadata["graph_edges"][0]["kind"] == "link"
    assert node_metadata["frontmatter"]["aliases"] == ["Adapter Alias"]
    assert node_metadata["properties"]["title"] == "Core Adapter Note"
    assert node_metadata["obsidian_metadata_schema"] == "hermes_brain.rag_metadata.v1"
    assert node_metadata["obsidian_summary"]["links"] == 1
    assert "canvas_refs" in OBSIDIAN_STRUCTURAL_METADATA_KEYS
    assert "base_refs" in OBSIDIAN_STRUCTURAL_METADATA_KEYS


def test_document_from_obsidian_core_excludes_structural_metadata_from_embed_and_llm_text(
    tmp_path: Path,
) -> None:
    note = tmp_path / "note.md"
    note.write_text(_compound_note(), encoding="utf-8")

    doc = document_from_obsidian_core(
        note,
        tmp_path,
        source_kind="vault",
        layer="vault",
        obsidian_core_path=str(CORE_SRC),
    )

    assert doc is not None
    assert doc.metadata["aliases"] == ["Adapter Alias"]
    assert "Adapter Alias" in doc.get_content(metadata_mode=MetadataMode.ALL)
    assert "Adapter Alias" not in doc.get_content(metadata_mode=MetadataMode.EMBED)
    assert "Adapter Alias" not in doc.get_content(metadata_mode=MetadataMode.LLM)
    assert "obsidian_summary" not in doc.get_content(metadata_mode=MetadataMode.EMBED)
    assert "obsidian_summary" not in doc.get_content(metadata_mode=MetadataMode.LLM)


def test_document_from_obsidian_core_skips_empty_body(tmp_path: Path) -> None:
    note = tmp_path / "empty.md"
    note.write_text("---\ntitle: Empty\n---\n   \n", encoding="utf-8")

    assert (
        document_from_obsidian_core(
            note,
            tmp_path,
            source_kind="vault",
            layer="vault",
            obsidian_core_path=str(CORE_SRC),
        )
        is None
    )


def test_load_vault_can_use_obsidian_core_adapter_when_enabled(tmp_path: Path) -> None:
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki" / "note.md").write_text(_compound_note(), encoding="utf-8")
    (tmp_path / "plain.md").write_text("Plain note.\n", encoding="utf-8")

    docs = load_vault(
        str(tmp_path),
        use_obsidian_core=True,
        obsidian_core_path=str(CORE_SRC),
    )

    assert len(docs) == 2
    by_name = {doc.metadata["file_name"]: doc for doc in docs}
    assert by_name["note.md"].metadata["layer"] == "wiki"
    assert by_name["note.md"].metadata["aliases"] == ["Adapter Alias"]
    assert by_name["note.md"].metadata["links"][0]["target"] == "Target Note"
    assert by_name["plain.md"].metadata["obsidian_summary"] == {
        "links": 0,
        "embeds": 0,
        "headings": 0,
        "blocks": 0,
        "callouts": 0,
    }


def test_load_source_root_uses_core_for_markdown_and_preserves_drive_layers(
    tmp_path: Path,
) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "drive-note.md").write_text(_compound_note(), encoding="utf-8")
    (tmp_path / "plain.txt").write_text("Plain source text.\n", encoding="utf-8")

    docs = load_source_root(
        str(tmp_path),
        use_obsidian_core=True,
        obsidian_core_path=str(CORE_SRC),
    )

    assert len(docs) == 2
    by_name = {doc.metadata["file_name"]: doc for doc in docs}
    assert by_name["drive-note.md"].metadata["source_kind"] == "drive"
    assert by_name["drive-note.md"].metadata["layer"] == "raw"
    assert by_name["drive-note.md"].metadata["aliases"] == ["Adapter Alias"]
    assert "aliases" not in by_name["plain.txt"].metadata
    assert by_name["plain.txt"].metadata["source_kind"] == "drive"
    assert by_name["plain.txt"].metadata["layer"] == "drive"


def test_load_documents_respects_disabled_feature_gate_for_compound_note(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "note.md").write_text(_compound_note(), encoding="utf-8")

    docs = load_documents(
        Settings(
            vault_path=str(vault),
            obsidian_core_enabled=False,
            obsidian_core_path=str(tmp_path / "missing-core-src"),
        )
    )

    assert len(docs) == 1
    assert docs[0].metadata["file_name"] == "note.md"
    assert docs[0].metadata["source_kind"] == "vault"
    assert docs[0].metadata["layer"] == "vault"
    assert docs[0].metadata["tags"] == ["brain", "rag"]
    assert docs[0].metadata["title"] == "Core Adapter Note"
    assert "aliases" not in docs[0].metadata
    assert "obsidian_summary" not in docs[0].metadata


def test_legacy_ingest_sanitizes_frontmatter_sources_when_core_disabled(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "note.md").write_text(
        "---\n"
        "title: Safe Legacy Note\n"
        "sources:\n"
        "  - https://example.test/report?token=TOP_SECRET_TOKEN&safe=1\n"
        "---\n"
        "Legacy body.\n",
        encoding="utf-8",
    )

    docs = load_documents(
        Settings(
            vault_path=str(vault),
            obsidian_core_enabled=False,
            obsidian_core_path=str(tmp_path / "missing-core-src"),
        )
    )

    assert docs[0].metadata["title"] == "Safe Legacy Note"
    assert docs[0].metadata["sources"] == [
        "https://example.test/report?token=[redacted]&safe=1"
    ]
    assert "TOP_SECRET" not in json.dumps(docs[0].metadata, sort_keys=True)


def test_load_documents_routes_enabled_markdown_vault_notes_through_core(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    wiki = vault / "wiki"
    wiki.mkdir(parents=True)
    (wiki / "note.md").write_text(_compound_note(), encoding="utf-8")

    docs = load_documents(
        Settings(
            vault_path=str(vault),
            obsidian_core_enabled=True,
            obsidian_core_path=str(CORE_SRC),
        )
    )

    assert len(docs) == 1
    assert docs[0].metadata["file_name"] == "note.md"
    assert docs[0].metadata["file_path"] == "wiki/note.md"
    assert docs[0].metadata["source_kind"] == "vault"
    assert docs[0].metadata["layer"] == "wiki"
    assert docs[0].metadata["aliases"] == ["Adapter Alias"]
    assert docs[0].metadata["obsidian_summary"] == {
        "links": 1,
        "embeds": 1,
        "headings": 2,
        "blocks": 1,
        "callouts": 1,
    }


def test_core_enabled_fails_loudly_when_core_cannot_be_imported(tmp_path: Path) -> None:
    note = tmp_path / "note.md"
    note.write_text("Body\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="obsidian-intelligence-core"):
        document_from_obsidian_core(
            note,
            tmp_path,
            source_kind="vault",
            layer="vault",
            obsidian_core_path=str(tmp_path / "missing-core-src"),
        )


def test_explicit_core_path_must_be_the_core_checkout(tmp_path: Path) -> None:
    wrong_src = tmp_path / "not-core-src"
    wrong_src.mkdir()

    with pytest.raises(RuntimeError, match="required core modules"):
        _ensure_core_path(str(wrong_src))


def test_explicit_core_path_rejects_malformed_core_package(tmp_path: Path) -> None:
    malformed_src = tmp_path / "src"
    (malformed_src / "obsidian_intelligence_core").mkdir(parents=True)

    with pytest.raises(RuntimeError, match="required core modules"):
        _ensure_core_path(str(malformed_src))


def test_explicit_core_path_accepts_core_repo_root() -> None:
    _ensure_core_path(str(CORE_SRC.parent))
    assert str(CORE_SRC) in sys.path


def test_explicit_core_path_does_not_fall_through_to_preloaded_package(
    tmp_path: Path,
) -> None:
    real_note = tmp_path / "real.md"
    real_note.write_text("Real body\n", encoding="utf-8")
    assert document_from_obsidian_core(
        real_note,
        tmp_path,
        source_kind="vault",
        layer="vault",
        obsidian_core_path=str(CORE_SRC),
    ) is not None

    fake_src = tmp_path / "fake-core" / "src"
    for relative_file in (
        "obsidian_intelligence_core/__init__.py",
        "obsidian_intelligence_core/core/markdown.py",
        "obsidian_intelligence_core/adapters/hermes_brain/__init__.py",
    ):
        file_path = fake_src / relative_file
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text("# fake module\n", encoding="utf-8")

    fake_note = tmp_path / "fake.md"
    fake_note.write_text("Fake body\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="resolved outside OBSIDIAN_CORE_PATH"):
        document_from_obsidian_core(
            fake_note,
            tmp_path,
            source_kind="vault",
            layer="vault",
            obsidian_core_path=str(fake_src),
        )
