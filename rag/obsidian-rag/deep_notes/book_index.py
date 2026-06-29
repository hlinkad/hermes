"""Book-aware loading and indexing helpers for Hermes Brain RAG.

This module deliberately keeps the book index derived and rebuildable. The
canonical source is the book file in Google Drive or an extracted text/markdown
file; Qdrant metadata and the optional JSON index are accelerators only.
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from llama_index.core import Document

from deep_notes.config import Settings, get_settings

TEXT_BOOK_EXTENSIONS = {".md", ".markdown", ".txt", ".text"}
PDF_BOOK_EXTENSIONS = {".pdf"}
BOOK_EXTENSIONS = TEXT_BOOK_EXTENSIONS | PDF_BOOK_EXTENSIONS

# Common page marker shapes emitted by OCR/PDF-to-markdown tools and useful for
# hand-normalised books. Examples: "<!-- page: 184 -->", "[page 184]",
# "--- page 184 ---", "Page 184".
PAGE_MARKER_RE = re.compile(
    r"(?im)^\s*(?:<!--\s*)?(?:\[?\s*page\s*[:#-]?\s*(\d{1,5})\s*\]?)(?:\s*-->)?\s*$|"
    r"^\s*-{2,}\s*page\s*[:#-]?\s*(\d{1,5})\s*-{2,}\s*$"
)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
NUMBERED_HEADING_RE = re.compile(
    r"^\s*((?:chapter|part|section)\s+\d+[\w.-]*|\d+(?:\.\d+){0,4})\s+(.+?)\s*$",
    re.IGNORECASE,
)
TITLE_CLEAN_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class BookPage:
    page_number: int
    text: str


@dataclass
class BookIndexEntry:
    title: str
    page_start: int
    page_end: int
    section_path: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    file_path: str = ""
    source_root: str = ""


@dataclass
class BookIndex:
    books: dict[str, list[BookIndexEntry]] = field(default_factory=dict)

    def add(self, book_title: str, entry: BookIndexEntry) -> None:
        self.books.setdefault(book_title, []).append(entry)

    def to_dict(self) -> dict:
        return {
            book: [asdict(entry) for entry in entries]
            for book, entries in sorted(self.books.items())
        }


def configured_book_paths(config: Settings) -> list[str]:
    return [p.strip() for p in config.book_paths.split(",") if p.strip()]


def iter_book_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root] if root.suffix.lower() in BOOK_EXTENSIONS else []
    if not root.is_dir():
        raise FileNotFoundError(f"Book path not found: {root}")
    return sorted(
        p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in BOOK_EXTENSIONS
    )


def _normalise_title(raw: str) -> str:
    title = raw.strip().strip("#").strip()
    title = re.sub(r"\s+#+$", "", title).strip()
    return TITLE_CLEAN_RE.sub(" ", title)


def _book_title_from_path(path: Path) -> str:
    return _normalise_title(path.stem.replace("_", " ").replace("-", " ")).title()


def _split_text_pages(text: str) -> list[BookPage]:
    matches = list(PAGE_MARKER_RE.finditer(text))
    if not matches:
        return [BookPage(page_number=1, text=text)]

    pages: list[BookPage] = []
    for i, match in enumerate(matches):
        number = int(next(group for group in match.groups() if group))
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if body:
            pages.append(BookPage(page_number=number, text=body))
    return pages


def _load_pdf_pages(path: Path) -> list[BookPage]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - depends on optional runtime dep
        raise RuntimeError(
            "PDF book ingestion requires pypdf. Install it in the RAG venv or pre-extract "
            "PDFs to markdown/text with page markers."
        ) from exc

    reader = PdfReader(str(path))
    pages: list[BookPage] = []
    for idx, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            pages.append(BookPage(page_number=idx, text=text))
    return pages


def load_book_pages(path: Path) -> list[BookPage]:
    suffix = path.suffix.lower()
    if suffix in TEXT_BOOK_EXTENSIONS:
        text = path.read_text(encoding="utf-8", errors="replace")
        return _split_text_pages(text)
    if suffix in PDF_BOOK_EXTENSIONS:
        return _load_pdf_pages(path)
    raise ValueError(f"Unsupported book extension: {path.suffix}")


def _heading_from_line(line: str) -> tuple[int, str] | None:
    markdown = HEADING_RE.match(line)
    if markdown:
        return len(markdown.group(1)), _normalise_title(markdown.group(2))

    numbered = NUMBERED_HEADING_RE.match(line)
    if numbered:
        return 2, _normalise_title(f"{numbered.group(1)} {numbered.group(2)}")

    return None


def _aliases_for_title(title: str) -> list[str]:
    aliases = {title}
    cleaned = re.sub(r"^(chapter|part|section)\s+\d+[\w.-]*\s+", "", title, flags=re.I)
    cleaned = re.sub(r"^\d+(?:\.\d+){0,4}\s+", "", cleaned).strip()
    if cleaned and cleaned.lower() != title.lower():
        aliases.add(cleaned)
    # Useful for book queries such as "Adapter design pattern" when headings are
    # "Adapter" or "The Adapter Pattern".
    patternless = re.sub(r"\b(the|pattern|design pattern)\b", " ", cleaned, flags=re.I)
    patternless = TITLE_CLEAN_RE.sub(" ", patternless).strip()
    if patternless and len(patternless) >= 3:
        aliases.add(patternless)
    return sorted(aliases, key=lambda s: (len(s), s.lower()))


def _page_text_with_marker(page: BookPage) -> str:
    return f"[Page {page.page_number}]\n{page.text.strip()}"


def _chunk_pages(pages: list[BookPage], pages_per_chunk: int) -> Iterable[list[BookPage]]:
    if pages_per_chunk < 1:
        raise ValueError("BOOK_PAGES_PER_CHUNK must be >= 1")
    for idx in range(0, len(pages), pages_per_chunk):
        yield pages[idx : idx + pages_per_chunk]


def documents_from_book(path: Path, root: Path, config: Settings) -> tuple[list[Document], list[BookIndexEntry]]:
    pages = load_book_pages(path)
    if not pages:
        return [], []

    rel = path.relative_to(root) if path.is_relative_to(root) else path.name
    rel_str = str(rel)
    title = _book_title_from_path(path)
    section_stack: dict[int, str] = {}
    documents: list[Document] = []
    index_entries: list[BookIndexEntry] = []

    # Discover section starts before chunking, so every page chunk can inherit the
    # nearest section path.
    page_sections: dict[int, list[str]] = {}
    for page in pages:
        for line in page.text.splitlines():
            heading = _heading_from_line(line)
            if not heading:
                continue
            level, heading_title = heading
            section_stack = {k: v for k, v in section_stack.items() if k < level}
            section_stack[level] = heading_title
            section_path = [section_stack[k] for k in sorted(section_stack)]
            page_sections[page.page_number] = section_path
            index_entries.append(
                BookIndexEntry(
                    title=heading_title,
                    page_start=page.page_number,
                    page_end=page.page_number,
                    section_path=section_path,
                    aliases=_aliases_for_title(heading_title),
                    file_path=rel_str,
                    source_root=str(root),
                )
            )

    active_section: list[str] = []
    for chunk in _chunk_pages(pages, config.book_pages_per_chunk):
        for page in chunk:
            if page.page_number in page_sections:
                active_section = page_sections[page.page_number]

        page_start = chunk[0].page_number
        page_end = chunk[-1].page_number
        text = "\n\n".join(_page_text_with_marker(page) for page in chunk)
        section_title = active_section[-1] if active_section else ""
        aliases = _aliases_for_title(section_title) if section_title else []
        metadata = {
            "file_name": path.name,
            "file_path": rel_str,
            "source_root": str(root),
            "source_kind": "book",
            "layer": "book",
            "book_title": title,
            "page_start": page_start,
            "page_end": page_end,
            "page_range": f"{page_start}-{page_end}" if page_start != page_end else str(page_start),
            "section_path": active_section,
            "section_title": section_title,
            "aliases": aliases,
        }
        documents.append(Document(text=text, metadata=metadata))

    # Close index entry ranges at the page before the next heading.
    if index_entries:
        sorted_pages = sorted({p.page_number for p in pages})
        max_page = max(sorted_pages)
        for idx, entry in enumerate(index_entries):
            next_start = index_entries[idx + 1].page_start if idx + 1 < len(index_entries) else max_page + 1
            entry.page_end = max(entry.page_start, next_start - 1)

    if not index_entries:
        index_entries.append(
            BookIndexEntry(
                title=title,
                page_start=min(p.page_number for p in pages),
                page_end=max(p.page_number for p in pages),
                section_path=[title],
                aliases=[title],
                file_path=rel_str,
                source_root=str(root),
            )
        )

    return documents, index_entries


def load_books(config: Settings) -> tuple[list[Document], BookIndex]:
    documents: list[Document] = []
    index = BookIndex()
    for configured in configured_book_paths(config):
        root = Path(configured).expanduser()
        files = iter_book_files(root)
        source_root = root if root.is_dir() else root.parent
        for book_file in files:
            book_documents, entries = documents_from_book(book_file, source_root, config)
            documents.extend(book_documents)
            title = _book_title_from_path(book_file)
            for entry in entries:
                index.add(title, entry)
    return documents, index


def render_book_index(index: BookIndex) -> str:
    lines: list[str] = []
    for book, entries in sorted(index.books.items()):
        lines.append(f"# {book}")
        for entry in entries:
            page = f"p. {entry.page_start}" if entry.page_start == entry.page_end else f"pp. {entry.page_start}-{entry.page_end}"
            path = " > ".join(entry.section_path) if entry.section_path else entry.title
            aliases = f" aliases: {', '.join(entry.aliases)}" if entry.aliases else ""
            lines.append(f"- {page}: {path}{aliases}")
        lines.append("")
    return "\n".join(lines).strip() + ("\n" if lines else "")


def build_book_index(config: Settings | None = None) -> BookIndex:
    if config is None:
        config = get_settings()
    _, index = load_books(config)
    return index


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a derived Hermes Brain book index.")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of markdown")
    parser.add_argument("--output", help="Optional output path. Defaults to stdout.")
    args = parser.parse_args()

    index = build_book_index()
    content = json.dumps(index.to_dict(), ensure_ascii=False, indent=2) if args.json else render_book_index(index)
    if args.output:
        Path(args.output).expanduser().write_text(content, encoding="utf-8")
    else:
        print(content, end="")


if __name__ == "__main__":
    main()
