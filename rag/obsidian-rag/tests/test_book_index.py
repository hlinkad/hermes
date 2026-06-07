from deep_notes.book_index import documents_from_book, load_book_pages, render_book_index
from deep_notes.config import Settings


def test_text_book_page_markers_and_section_metadata(tmp_path):
    book = tmp_path / "programming-design-patterns.md"
    book.write_text(
        "<!-- page: 184 -->\n"
        "# Adapter\n"
        "The Adapter pattern converts the interface of one class into another.\n"
        "<!-- page: 185 -->\n"
        "Adapters wrap incompatible objects.\n"
        "<!-- page: 186 -->\n"
        "Object adapters use composition.\n",
        encoding="utf-8",
    )

    docs, index_entries = documents_from_book(
        book,
        tmp_path,
        Settings(vault_path="", book_pages_per_chunk=3),
    )

    assert len(docs) == 1
    metadata = docs[0].metadata
    assert metadata["source_kind"] == "book"
    assert metadata["layer"] == "book"
    assert metadata["book_title"] == "Programming Design Patterns"
    assert metadata["page_range"] == "184-186"
    assert metadata["section_title"] == "Adapter"
    assert "Adapter" in metadata["aliases"]
    assert "[Page 184]" in docs[0].text

    adapter = next(entry for entry in index_entries if entry.title == "Adapter")
    assert adapter.page_start == 184
    assert adapter.page_end == 186
    assert adapter.aliases == ["Adapter"]


def test_text_book_without_page_markers_defaults_to_page_one(tmp_path):
    book = tmp_path / "short-book.txt"
    book.write_text("# Intro\nA short extracted book.\n", encoding="utf-8")

    pages = load_book_pages(book)

    assert len(pages) == 1
    assert pages[0].page_number == 1
    assert "short extracted book" in pages[0].text


def test_render_book_index(tmp_path):
    book = tmp_path / "patterns.md"
    book.write_text(
        "[page 1]\n# Adapter\nText\n[page 2]\n# Bridge\nText\n",
        encoding="utf-8",
    )
    docs, entries = documents_from_book(book, tmp_path, Settings(vault_path=""))

    from deep_notes.book_index import BookIndex

    index = BookIndex()
    for entry in entries:
        index.add("Patterns", entry)

    rendered = render_book_index(index)
    assert "# Patterns" in rendered
    assert "Adapter" in rendered
    assert "p. 1" in rendered
    assert docs[0].metadata["page_start"] == 1
