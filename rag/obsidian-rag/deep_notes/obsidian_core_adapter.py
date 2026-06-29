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
_REQUIRED_CORE_FILES = (
    "obsidian_intelligence_core/__init__.py",
    "obsidian_intelligence_core/core/markdown.py",
    "obsidian_intelligence_core/adapters/hermes_brain/__init__.py",
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
    core_src_path = _ensure_core_path(obsidian_core_path)
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
            "Install it in the active RAG environment or set OBSIDIAN_CORE_PATH to the "
            "core repo root or src/ checkout; do not create/install a new venv without "
            "approval."
        ) from exc

    if core_src_path is not None:
        _assert_callable_loaded_from_core_path(parse_markdown_file, core_src_path)
        _assert_callable_loaded_from_core_path(
            document_to_hermes_brain_rag_payload,
            core_src_path,
        )
    return parse_markdown_file, document_to_hermes_brain_rag_payload


def _ensure_core_path(obsidian_core_path: str) -> Path | None:
    explicit_path = obsidian_core_path.strip()
    if explicit_path:
        path = _validated_core_src_path(Path(explicit_path).expanduser())
        _prepend_sys_path(path)
        return path

    try:
        import obsidian_intelligence_core  # noqa: F401  # type: ignore[import-not-found]
        return None
    except ImportError:
        pass

    for candidate in _CORE_SRC_CANDIDATES:
        if candidate.is_dir() and _has_required_core_files(candidate):
            _prepend_sys_path(candidate)
            return candidate.resolve()
    return None


def _validated_core_src_path(path: Path) -> Path:
    """Return a safe core src path or fail before Python import resolution.

    Explicit OBSIDIAN_CORE_PATH should not silently fall through to another installed
    package or auto-detected checkout. Accept either the core repo root or its src/
    directory, but require the expected package directory to exist there.
    """

    if not path.is_dir():
        raise RuntimeError(
            f"obsidian-intelligence-core path does not exist: {path}. "
            "Set OBSIDIAN_CORE_PATH to the core repo root or src/ directory."
        )

    if _has_required_core_files(path):
        return path.resolve()

    repo_src = path / "src"
    if _has_required_core_files(repo_src):
        return repo_src.resolve()

    raise RuntimeError(
        f"obsidian-intelligence-core path does not contain required core modules: {path}. "
        "Set OBSIDIAN_CORE_PATH to the core repo root or src/ directory."
    )


def _has_required_core_files(path: Path) -> bool:
    return all((path / relative_file).is_file() for relative_file in _REQUIRED_CORE_FILES)


def _assert_callable_loaded_from_core_path(func: Callable, core_src_path: Path) -> None:
    module_name = getattr(func, "__module__", "")
    module = sys.modules.get(module_name)
    origin = getattr(module, "__file__", "") if module is not None else ""
    if not origin:
        raise RuntimeError(
            "obsidian-intelligence-core import origin could not be verified for "
            f"{module_name or func!r}."
        )

    origin_path = Path(origin).resolve()
    core_root = core_src_path.resolve()
    try:
        origin_path.relative_to(core_root)
    except ValueError as exc:
        raise RuntimeError(
            "obsidian-intelligence-core import resolved outside OBSIDIAN_CORE_PATH: "
            f"{origin_path} is not under {core_root}. Restart the process or unset "
            "the conflicting package before enabling OBSIDIAN_CORE_PATH."
        ) from exc


def _prepend_sys_path(path: Path) -> None:
    value = str(path)
    if value not in sys.path:
        sys.path.insert(0, value)


def _relative_file_path(path: Path, root: Path) -> str:
    try:
        return path.expanduser().resolve().relative_to(root.expanduser().resolve()).as_posix()
    except ValueError:
        return path.as_posix()
