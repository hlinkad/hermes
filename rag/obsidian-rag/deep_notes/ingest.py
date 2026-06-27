import re
from pathlib import Path

import yaml
from llama_index.core import Document, StorageContext, VectorStoreIndex

from deep_notes.book_index import configured_book_paths, load_books
from deep_notes.components.chunking import get_splitter
from deep_notes.components.embeddings import get_embed_model
from deep_notes.components.vector_store import get_vector_store
from deep_notes.config import Settings, get_settings
from deep_notes.obsidian_core_adapter import document_from_obsidian_core

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
TEXT_EXTENSIONS = {
    ".md",
    ".markdown",
    ".txt",
    ".text",
    ".rst",
    ".org",
    ".json",
    ".jsonl",
    ".yaml",
    ".yml",
    ".csv",
    ".tsv",
    ".html",
    ".htm",
}
SKIP_DIRS = {
    ".git",
    ".obsidian",
    ".trash",
    "node_modules",
    "__pycache__",
    ".derived",
    "vector-index",
    "rag",
}


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Extract YAML frontmatter and return (metadata_dict, body_text)."""
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        return {}, text
    body = text[match.end() :]
    return meta, body


def infer_layer(relative_path: Path, source_kind: str) -> str:
    """Rankable source layer for Hermes Brain retrieval."""
    parts = {part.lower() for part in relative_path.parts}
    if "wiki" in parts:
        return "wiki"
    if "raw" in parts:
        return "raw"
    if source_kind == "vault":
        return "vault"
    return "drive"


def iter_text_files(root: Path, extensions: set[str]) -> list[Path]:
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in extensions:
            continue
        files.append(path)
    return files


def document_from_file(
    path: Path,
    root: Path,
    source_kind: str,
    *,
    use_obsidian_core: bool = False,
    obsidian_core_path: str = "",
) -> Document | None:
    rel = path.relative_to(root)
    layer = infer_layer(rel, source_kind)
    if use_obsidian_core and path.suffix.lower() in {".md", ".markdown"}:
        return document_from_obsidian_core(
            path,
            root,
            source_kind=source_kind,
            layer=layer,
            obsidian_core_path=obsidian_core_path,
        )

    text = path.read_text(encoding="utf-8", errors="replace")
    meta, body = parse_frontmatter(text)
    if not body.strip():
        return None

    doc_meta = {
        "file_name": path.name,
        "file_path": str(rel),
        "source_root": str(root),
        "source_kind": source_kind,
        "layer": layer,
    }

    tags = meta.get("tags", [])
    if isinstance(tags, list):
        doc_meta["tags"] = tags
    elif isinstance(tags, str):
        doc_meta["tags"] = [t.strip() for t in tags.split(",")]

    title = meta.get("title")
    if isinstance(title, str) and title.strip():
        doc_meta["title"] = title.strip()

    sources = meta.get("sources")
    if sources:
        doc_meta["sources"] = sources

    return Document(text=body, metadata=doc_meta)


def load_vault(
    vault_path: str,
    *,
    use_obsidian_core: bool = False,
    obsidian_core_path: str = "",
) -> list[Document]:
    """Load all .md files from an Obsidian vault directory."""
    vault = Path(vault_path).expanduser()
    if not vault.is_dir():
        raise FileNotFoundError(f"Vault path not found: {vault_path}")

    documents: list[Document] = []
    for md_file in iter_text_files(vault, {".md", ".markdown"}):
        doc = document_from_file(
            md_file,
            vault,
            source_kind="vault",
            use_obsidian_core=use_obsidian_core,
            obsidian_core_path=obsidian_core_path,
        )
        if doc:
            documents.append(doc)
    return documents


def load_source_root(
    source_path: str,
    *,
    use_obsidian_core: bool = False,
    obsidian_core_path: str = "",
) -> list[Document]:
    """Load text/extracted files from a Drive/source root.

    Binary originals stay in Google Drive but must be OCR/extracted before this loader can index them.
    """
    root = Path(source_path).expanduser()
    if not root.is_dir():
        raise FileNotFoundError(f"Source path not found: {source_path}")

    documents: list[Document] = []
    for text_file in iter_text_files(root, TEXT_EXTENSIONS):
        doc = document_from_file(
            text_file,
            root,
            source_kind="drive",
            use_obsidian_core=use_obsidian_core,
            obsidian_core_path=obsidian_core_path,
        )
        if doc:
            documents.append(doc)
    return documents


def configured_source_paths(config: Settings) -> list[str]:
    return [p.strip() for p in config.source_paths.split(",") if p.strip()]


def load_documents(config: Settings) -> list[Document]:
    documents: list[Document] = []

    if config.vault_path:
        print(f"Loading Obsidian vault from: {config.vault_path}")
        vault_docs = load_vault(
            config.vault_path,
            use_obsidian_core=config.obsidian_core_enabled,
            obsidian_core_path=config.obsidian_core_path,
        )
        print(f"Found {len(vault_docs)} vault documents")
        documents.extend(vault_docs)

    for source_path in configured_source_paths(config):
        print(f"Loading source root from: {source_path}")
        source_docs = load_source_root(
            source_path,
            use_obsidian_core=config.obsidian_core_enabled,
            obsidian_core_path=config.obsidian_core_path,
        )
        print(f"Found {len(source_docs)} source documents in {source_path}")
        documents.extend(source_docs)

    for book_path in configured_book_paths(config):
        print(f"Loading book root from: {book_path}")
    book_docs, book_index = load_books(config)
    if book_docs:
        print(
            f"Found {len(book_docs)} book chunks across "
            f"{len(book_index.books)} book(s)"
        )
        documents.extend(book_docs)

    return documents


def run_ingest(config: Settings | None = None) -> int:
    """Run the full ingestion pipeline. Returns number of documents indexed."""
    if config is None:
        config = get_settings()

    if not config.vault_path and not configured_source_paths(config) and not configured_book_paths(config):
        raise ValueError("Set VAULT_PATH, SOURCE_PATHS, and/or BOOK_PATHS")

    documents = load_documents(config)
    print(f"Total documents: {len(documents)}")

    if not documents:
        print("No documents to index.")
        return 0

    splitter = get_splitter(config)
    embed_model = get_embed_model(config)
    vector_store = get_vector_store(config)

    storage_context = StorageContext.from_defaults(vector_store=vector_store)

    print("Indexing documents...")
    VectorStoreIndex.from_documents(
        documents,
        storage_context=storage_context,
        embed_model=embed_model,
        transformations=[splitter],
        show_progress=True,
    )

    print("Ingestion complete.")
    return len(documents)


if __name__ == "__main__":
    run_ingest()
