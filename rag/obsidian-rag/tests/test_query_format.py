from deep_notes.query import SourceChunk, format_context


def test_source_chunk_book_citation():
    source = SourceChunk(
        file_name="programming-design-patterns.md",
        file_path="programming-design-patterns.md",
        text="Adapter text",
        score=0.82,
        layer="book",
        source_kind="book",
        book_title="Programming Design Patterns",
        page_range="184-186",
        section_title="Adapter",
    )

    assert source.citation == "Programming Design Patterns — Adapter — pp. 184-186"
    context = format_context([source])
    assert "Programming Design Patterns — Adapter — pp. 184-186" in context
    assert "layer=book" in context
    assert "Adapter text" in context
