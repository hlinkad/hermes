from collections.abc import Generator
from dataclasses import dataclass
from typing import Any

from llama_index.core import VectorStoreIndex
from llama_index.core.llms import ChatMessage
from llama_index.core.schema import MetadataMode

from deep_notes.components.embeddings import get_embed_model
from deep_notes.components.llm import get_llm
from deep_notes.components.vector_store import get_vector_store
from deep_notes.config import Settings, get_settings

SYSTEM_PROMPT = (
    "You are a helpful assistant that answers questions based on the user's Hermes Brain context.\n"
    "Use ONLY the provided context to answer. If the context doesn't contain enough "
    "information, say so.\n"
    "Prioritize compiled wiki context over raw/source/book chunks when both are present. "
    "Always cite source files; for books, cite book title and page range."
)


@dataclass
class SourceChunk:
    file_name: str
    file_path: str
    text: str
    score: float
    layer: str = ""
    source_kind: str = ""
    book_title: str = ""
    page_range: str = ""
    section_title: str = ""
    section_path: list[str] | None = None

    @property
    def citation(self) -> str:
        parts: list[str] = []
        if self.book_title:
            parts.append(self.book_title)
        elif self.file_name:
            parts.append(self.file_name)
        if self.section_title:
            parts.append(self.section_title)
        if self.page_range:
            parts.append(f"p. {self.page_range}" if "-" not in self.page_range else f"pp. {self.page_range}")
        if not parts and self.file_path:
            parts.append(self.file_path)
        return " — ".join(parts)


@dataclass
class RetrievalResult:
    sources: list[SourceChunk]
    context_str: str


def format_context(sources: list[SourceChunk], max_chars: int | None = None) -> str:
    """Render retrieved chunks with durable provenance labels."""
    blocks: list[str] = []
    used = 0
    for source in sources:
        header_bits = [f"Source: {source.citation}"]
        if source.layer:
            header_bits.append(f"layer={source.layer}")
        if source.file_path:
            header_bits.append(f"path={source.file_path}")
        header_bits.append(f"score={source.score:.3f}")
        block = f"[{'; '.join(header_bits)}]\n{source.text.strip()}"
        if max_chars is not None and used + len(block) > max_chars:
            remaining = max_chars - used
            if remaining <= 200:
                break
            block = block[:remaining].rstrip() + "\n[truncated]"
            blocks.append(block)
            break
        blocks.append(block)
        used += len(block) + 7
    return "\n\n---\n\n".join(blocks)


def _node_text_for_context(node: Any) -> str:
    """Return only the retrieved body text for LLM context.

    Qdrant/LlamaIndex nodes can carry rich metadata payloads for filtering,
    debugging, and citations. Retrieval context should keep that metadata behind
    the explicit ``Source: ...`` header instead of letting structural Obsidian
    fields leak into the body text sent to the answer LLM.
    """

    return node.get_content(metadata_mode=MetadataMode.NONE)


def retrieve(question: str, config: Settings | None = None) -> RetrievalResult:
    """Retrieve relevant chunks without generating an answer."""
    if config is None:
        config = get_settings()

    vector_store = get_vector_store(config)
    embed_model = get_embed_model(config)

    index = VectorStoreIndex.from_vector_store(
        vector_store=vector_store,
        embed_model=embed_model,
    )

    retriever = index.as_retriever(similarity_top_k=config.similarity_top_k)
    nodes = retriever.retrieve(question)

    sources = [
        SourceChunk(
            file_name=node.metadata.get("file_name", "unknown"),
            file_path=node.metadata.get("file_path", ""),
            text=_node_text_for_context(node),
            score=node.score or 0.0,
            layer=node.metadata.get("layer", ""),
            source_kind=node.metadata.get("source_kind", ""),
            book_title=node.metadata.get("book_title", ""),
            page_range=node.metadata.get("page_range", ""),
            section_title=node.metadata.get("section_title", ""),
            section_path=node.metadata.get("section_path") or None,
        )
        for node in nodes
    ]

    context_str = format_context(sources)

    return RetrievalResult(sources=sources, context_str=context_str)


def stream_answer(
    question: str,
    context_str: str,
    chat_history: list[dict],
    config: Settings | None = None,
) -> Generator[str, None, None]:
    """Stream LLM response token by token."""
    if config is None:
        config = get_settings()

    llm = get_llm(config)

    messages = [ChatMessage(role="system", content=SYSTEM_PROMPT)]

    for msg in chat_history:
        messages.append(ChatMessage(role=msg["role"], content=msg["content"]))

    user_content = f"Context:\n-----\n{context_str}\n-----\n\nQuestion: {question}"
    messages.append(ChatMessage(role="user", content=user_content))

    try:
        response = llm.stream_chat(messages)
        for token in response:
            yield token.delta or ""
    except (NotImplementedError, AttributeError):
        # Fallback to non-streaming if provider doesn't support it
        response = llm.chat(messages)
        yield response.message.content
