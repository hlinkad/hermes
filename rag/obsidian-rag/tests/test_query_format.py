from llama_index.core.schema import MetadataMode

from deep_notes.query import SourceChunk, _node_text_for_context, format_context


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


def test_node_text_for_context_uses_metadata_free_body_text():
    class NoisyNode:
        def __init__(self):
            self.seen_metadata_mode = None

        def get_content(self, metadata_mode=None):
            self.seen_metadata_mode = metadata_mode
            if metadata_mode is MetadataMode.NONE:
                return "Body text only."
            return (
                "Body text only.\n"
                "aliases: Adapter Alias\n"
                "links: Target Note\n"
                "obsidian_summary: {'links': 1}"
            )

    node = NoisyNode()

    assert _node_text_for_context(node) == "Body text only."
    assert node.seen_metadata_mode is MetadataMode.NONE
