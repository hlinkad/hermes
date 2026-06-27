"""Thin Hermes Brain consumer of obsidian-intelligence-core parser output.

This module is intentionally a boundary layer: the generic core parses Obsidian
Markdown and creates inert Hermes Brain metadata, while deep_notes keeps ownership
of source roots, source layers, LlamaIndex documents, Qdrant indexing, and
retrieval/citation behavior.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

from llama_index.core import Document

OBSIDIAN_STRUCTURAL_METADATA_KEYS = (
    "frontmatter",
    "properties",
    "aliases",
    "cssclasses",
    "inline_tags",
    "headings",
    "links",
    "wikilinks",
    "embeds",
    "blocks",
    "block_ids",
    "callouts",
    "graph_edges",
    "diagnostics",
    "obsidian_summary",
)

_CORE_SRC_CANDIDATES = (
    Path("/workspace/obsidian-intelligence-core/src"),
    Path("/Users/denishlinka/hermes-infra/obsidian-intelligence-core/src"),
)


def document_from_obsidian_core(
    path: Path,
    root: Path,
    *,
    source_kind: str,
    layer: str,
    obsidian_core_path: str = "",
) -> Document | None:
    """Parse one Markdown file with obsidian-intelligence-core and wrap it for RAG."""

    parse_markdown_file, document_to_payload = _load_core_adapter(obsidian_core_path)
    root = root.expanduser()
    relative_path = _relative_file_path(path, root)
    parsed_document = parse_markdown_file(path, vault_root=root)
    if not parsed_document.body.strip():
        return None

    payload = document_to_payload(
        parsed_document,
        source_root=str(root),
        source_kind=source_kind,
        layer=layer,
        file_path=relative_path,
    )
    return Document(
        text=payload.text,
        metadata=dict(payload.metadata),
        excluded_embed_metadata_keys=list(OBSIDIAN_STRUCTURAL_METADATA_KEYS),
        excluded_llm_metadata_keys=list(OBSIDIAN_STRUCTURAL_METADATA_KEYS),
    )


def _load_core_adapter(obsidian_core_path: str) -> tuple[Callable, Callable]:
    _ensure_core_path(obsidian_core_path)
    try:
        from obsidian_intelligence_core.adapters.hermes_brain import (  # type: ignore[import-not-found]
            document_to_hermes_brain_rag_payload,
        )
        from obsidian_intelligence_core.core.markdown import (  # type: ignore[import-not-found]
            parse_markdown_file,
        )
    except ImportError as exc:  # pragma: no cover - exercised through RuntimeError path
        raise RuntimeError(
            "obsidian-intelligence-core is required when OBSIDIAN_CORE_ENABLED=true. "
            "Install it in the active RAG environment or set OBSIDIAN_CORE_PATH to its src/ "
            "checkout; do not create/install a new venv without approval."
        ) from exc
    return parse_markdown_file, document_to_hermes_brain_rag_payload


def _ensure_core_path(obsidian_core_path: str) -> None:
    explicit_path = obsidian_core_path.strip()
    if explicit_path:
        path = Path(explicit_path).expanduser()
        if not path.is_dir():
            raise RuntimeError(
                f"obsidian-intelligence-core path does not exist: {path}. "
                "Set OBSIDIAN_CORE_PATH to the checkout's src/ directory."
            )
        _prepend_sys_path(path)
        return

    try:
        import obsidian_intelligence_core  # noqa: F401  # type: ignore[import-not-found]
        return
    except ImportError:
        pass

    for candidate in _CORE_SRC_CANDIDATES:
        if candidate.is_dir():
            _prepend_sys_path(candidate)
            return


def _prepend_sys_path(path: Path) -> None:
    value = str(path)
    if value not in sys.path:
        sys.path.insert(0, value)


def _relative_file_path(path: Path, root: Path) -> str:
    try:
        return path.expanduser().resolve().relative_to(root.expanduser().resolve()).as_posix()
    except ValueError:
        return path.as_posix()
