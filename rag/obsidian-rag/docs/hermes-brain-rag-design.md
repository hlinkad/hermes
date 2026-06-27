# Hermes Brain RAG ingest and automatic lookup design

## Requirement

Hermes Brain needs to ingest large books and existing Obsidian/Google Drive knowledge so Hermes can answer questions such as “how is the Adapter design pattern implemented?” without Denis having to say “look up Obsidian” every time.

The retrieval layer must be fast, grounded, and rebuildable. Qdrant is a cache, not the brain.

## Source layers

1. Google Drive originals and extracted source files: canonical source material.
2. Obsidian `raw/`: lightweight source cards / normalized extracts, written only with Denis approval.
3. Obsidian `wiki/`: compiled durable knowledge, written only with Denis approval.
4. Qdrant: derived chunks and vectors rebuilt from the above layers plus configured book roots.

Retrieval priority for answers is `wiki` first, then `raw`/vault notes, then `book`/Drive chunks. Book chunks are still valuable evidence, especially when the compiled wiki has no page-level detail yet.

## Obsidian intelligence core boundary

Hermes Brain consumes Obsidian Markdown intelligence through the generic `/workspace/obsidian-intelligence-core` parser/adapter instead of inventing Obsidian mechanics inside `deep_notes.ingest`.

- Generic core owns read-only Obsidian mechanics: frontmatter/properties, wikilinks, embeds, aliases, headings, block IDs, callouts, graph edges, diagnostics, and deterministic inert payloads.
- Hermes Brain owns source roots, source-layer semantics (`wiki`, `raw`, `vault`, `drive`, `book`), LlamaIndex/Qdrant indexing, citation formatting, API endpoints, and Hermes plugin integration.
- `deep_notes.obsidian_core_adapter` is the thin consumer boundary: it lazily imports the core parser, converts the core Hermes Brain payload into `llama_index.core.Document`, and excludes structural Obsidian metadata from embedding/LLM text while keeping it in Qdrant payload metadata.
- `OBSIDIAN_CORE_ENABLED=false` by default preserves the legacy ingest path. Set `OBSIDIAN_CORE_ENABLED=true` only when `obsidian-intelligence-core` is importable or `OBSIDIAN_CORE_PATH` points at its `src/` checkout.
- Qdrant remains a derived cache. Neither the core adapter nor RAG ingest writes to the live Obsidian vault or Google Drive.

## Book ingest algorithm

Books are configured with `BOOK_PATHS`, a comma-separated list of files or directories. Supported formats:

- `.md`, `.markdown`, `.txt`, `.text` with optional page markers.
- `.pdf` when `pypdf` is installed in the RAG venv.

Page marker examples for extracted text/markdown:

```text
<!-- page: 184 -->
[page 184]
--- page 184 ---
Page 184
```

For a book like “Programming Design Patterns” where Adapter spans pages 184-186:

1. Load pages from PDF extraction or page-marked text.
2. Detect headings from Markdown headings and numbered/chapter-style headings.
3. Build chunk documents of `BOOK_PAGES_PER_CHUNK` pages, default 3.
4. Store Qdrant metadata:
   - `layer=book`
   - `source_kind=book`
   - `book_title`
   - `file_path`
   - `page_start`
   - `page_end`
   - `page_range`
   - `section_title`
   - `section_path`
   - `aliases`
5. Build a derived book index from headings and page ranges.
6. Embed chunks with the configured embedding model and store them in Qdrant.

This means a query for “Adapter design pattern implementation” can retrieve the chunk tagged with `book_title=Programming Design Patterns`, `section_title=Adapter`, and `page_range=184-186` and cite it directly.

## Book index

The book index is generated, not canonical. It exists to mimic a physical book index and make page-oriented lookup easier.

Command:

```bash
cd /gdrive/hermes-brain/rag/obsidian-rag
/workspace/.hermes-venvs/hermes-global-scripts/bin/python -m deep_notes.book_index
```

JSON output:

```bash
/workspace/.hermes-venvs/hermes-global-scripts/bin/python -m deep_notes.book_index --json --output /tmp/hermes-brain-book-index.json
```

Do not store generated indexes as source-of-truth inside Obsidian unless Denis explicitly approves the specific Obsidian write.

## Retrieval and answers

`deep_notes.query.retrieve()` returns `SourceChunk` values with citation metadata. `format_context()` renders chunks like:

```text
[Source: Programming Design Patterns — Adapter — pp. 184-186; layer=book; path=programming-design-patterns.md; score=0.812]
...
```

`stream_answer()` tells the answer LLM to use only retrieved context, cite files, and cite book page ranges when available.

## Automatic Hermes lookup hook

Use a Hermes plugin `pre_llm_call` hook, not a gateway-only hook, because plugin hooks work in CLI and gateway sessions.

The hook should call the local RAG API context endpoint, not import LlamaIndex directly into Hermes. The retrieval helper is still useful for testing:

```bash
cd /gdrive/hermes-brain/rag/obsidian-rag
/workspace/.hermes-venvs/hermes-global-scripts/bin/python -m deep_notes.hermes_context "What is Adapter pattern?"
```

The helper:

1. Reads active Hermes env through `deep_notes.config`.
2. Uses `AUTO_CONTEXT_TOP_K`, `AUTO_CONTEXT_MIN_SCORE`, and `AUTO_CONTEXT_MAX_CHARS`.
3. Embeds the current user prompt and queries Qdrant.
4. Returns an empty string when nothing strong is found.
5. Returns a compact context block when relevant evidence exists.
6. Fails closed so a broken RAG service does not block Hermes turns.

Run the local API in the RAG runtime:

```bash
cd /workspace/hermes-related-code/rag/obsidian-rag
/workspace/.venv/bin/python -m uvicorn deep_notes.api:app --host 127.0.0.1 --port 8000
```

Test retrieval-only context over HTTP:

```bash
curl -s -X POST http://127.0.0.1:8000/api/context \
  -H 'Authorization: Bearer <rag-token>' \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"Adapter design pattern implementation"}'
```

Plugin artifacts:

```text
/workspace/hermes-related-code/plugins-source/hermes-brain-rag/__init__.py
/workspace/hermes-related-code/plugins-source/hermes-brain-rag/plugin.yaml
/workspace/hermes-related-code/rag/obsidian-rag/plugins/hermes-brain-rag/__init__.py
/workspace/hermes-related-code/rag/obsidian-rag/plugins/hermes-brain-rag/plugin.yaml
```

Install on the host after confirming Qdrant/Ollama/RAG paths are reachable from Hermes:

```bash
mkdir -p ~/.hermes/plugins/hermes-brain-rag
cp /Users/denishlinka/hermes-infra/hermes-related-code/plugins-source/hermes-brain-rag/plugin.yaml ~/.hermes/plugins/hermes-brain-rag/plugin.yaml
cp /Users/denishlinka/hermes-infra/hermes-related-code/plugins-source/hermes-brain-rag/__init__.py ~/.hermes/plugins/hermes-brain-rag/__init__.py
hermes plugins enable hermes-brain-rag
hermes gateway restart
```

The exact callback arguments can evolve, so the callback accepts `**kwargs` and tries `user_message`, `conversation_history`, and `messages`.

## Runtime env

Recommended non-secret settings for either `deep_notes/.env` (standalone repo testing) or the active Hermes `.env` (`~/.hermes/.env` for gateway/plugin runtime):

```env
VAULT_PATH=/Users/denishlinka/hermes/brain
SOURCE_PATHS=/gdrive/hermes-brain
BOOK_PATHS=/gdrive/hermes-brain/books,/gdrive/hermes-brain/pdf-docs
QDRANT_URL=http://127.0.0.1:6333
COLLECTION_NAME=hermes_brain
EMBED_PROVIDER=ollama
EMBED_MODEL=bge-m3
OLLAMA_BASE_URL=http://127.0.0.1:11434
LLM_PROVIDER=openai
LLM_MODEL=gpt-5.5
AUTO_CONTEXT_ENABLED=true
AUTO_CONTEXT_TOP_K=5
AUTO_CONTEXT_MIN_SCORE=0.55
AUTO_CONTEXT_MAX_CHARS=3500
OBSIDIAN_CORE_ENABLED=true
OBSIDIAN_CORE_PATH=/workspace/obsidian-intelligence-core/src
HERMES_BRAIN_RAG_CONTEXT_URL=http://127.0.0.1:8000/api/context
HERMES_BRAIN_RAG_API_KEY=<same value as API_KEY, keep secret>
HERMES_BRAIN_RAG_TIMEOUT=2.5
```

## Verification path

1. Qdrant health returns OK.
2. Ollama has `bge-m3`.
3. `BOOK_PATHS` contains at least one extracted book/PDF visible to this runtime.
4. `python -m deep_notes.book_index` prints section/page entries.
5. With `OBSIDIAN_CORE_ENABLED=true`, a fixture Markdown note ingests through `obsidian-intelligence-core` and carries both legacy Hermes metadata and Obsidian-native metadata.
6. `python -m deep_notes.ingest` indexes vault/source/book docs.
7. `python -m deep_notes.hermes_context "linear regression"` returns context with book/page citations.
8. `/api/context` returns the same page-cited context when called with the configured API key.
9. The plugin `pre_llm_call` hook returns `{ "context": ... }` for that API response and fails closed on API errors.
10. A negative query returns empty context or an explicit insufficient-context answer.
