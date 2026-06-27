from __future__ import annotations

from pathlib import Path

import pytest
from llama_index.core.schema import MetadataMode

from deep_notes.ingest import load_source_root, load_vault
from deep_notes.obsidian_core_adapter import (
    OBSIDIAN_STRUCTURAL_METADATA_KEYS,
    document_from_obsidian_core,
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
