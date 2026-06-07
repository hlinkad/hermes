---
name: hermes-brain-rag
description: Ingest and query Hermes Brain Obsidian/Drive/books with LlamaIndex + Qdrant, including automatic pre-LLM lookup context.
version: 1.0.0
author: Hermes Agent
platforms: [linux, macos]
metadata:
  hermes:
    tags: [hermes-brain, rag, obsidian, qdrant, books, hooks]
    related_skills: [llm-wiki, obsidian, hermes-agent]
---

# Hermes Brain RAG

Use this skill when Denis asks to ingest, query, debug, or wire automatic lookup for Hermes Brain knowledge across Obsidian, Google Drive sources, and books.

## Runtime paths

Current intended project runtime/code path after Denis's migration:

```text
/workspace/hermes-related-code/rag
```

Host-side source path:

```text
/Users/denishlinka/hermes-infra/hermes-related-code/rag
```

The old `/gdrive/hermes-brain/rag/...` path is no longer the preferred source-code location. Google Drive should remain canonical source data/books/docs, not the place where RAG application code and runtime venvs accumulate. See `references/mac-host-docker-workspace-architecture.md`.

Current Docker-side venv for RAG libraries:

```text
/workspace/.venv
```

Use the venv Python explicitly:

```bash
cd /workspace/hermes-related-code/rag
/workspace/.venv/bin/python -m pytest tests -q
```

Do not create venvs or runtime caches inside `/gdrive/hermes-brain`. Source code/docs are fine there; runtime artifacts should stay in host-local or container-local paths.

## Source-of-truth split

Qdrant is a derived retrieval cache only.

Canonical order:

1. Google Drive originals / extracted sources under `/gdrive/hermes-brain`.
2. Obsidian raw cards under `/Users/denishlinka/hermes/raw` when approved by Denis.
3. Obsidian compiled wiki under `/Users/denishlinka/hermes/wiki` when approved by Denis.
4. Qdrant vectors rebuilt from the above plus configured books.

Do not write to Obsidian without explicit approval.

## Book ingest algorithm

The implementation lives in:

```text
deep_notes/book_index.py
deep_notes/ingest.py
deep_notes/query.py
deep_notes/hermes_context.py
```

Books are configured with `BOOK_PATHS`, a comma-separated list of files or directories. Supported book inputs:

- `.md`, `.markdown`, `.txt`, `.text` with optional page markers.
- `.pdf` when `pypdf` is installed in the active RAG venv.

Page marker examples:

```text
<!-- page: 184 -->
[page 184]
--- page 184 ---
Page 184
```

For a book section such as Adapter on pages 184-186, ingestion:

1. Extracts page text.
2. Detects Markdown / numbered / chapter-style headings.
3. Chunks by `BOOK_PAGES_PER_CHUNK` pages, default 3.
4. Stores Qdrant metadata: `layer=book`, `source_kind=book`, `book_title`, `file_path`, `page_start`, `page_end`, `page_range`, `section_title`, `section_path`, `aliases`.
5. Generates a derived book index from heading/page ranges.

## Useful commands

Build derived book index:

```bash
cd /workspace/hermes-related-code/rag
/workspace/.venv/bin/python -m deep_notes.book_index
```

Write JSON book index to a temporary path:

```bash
cd /workspace/hermes-related-code/rag
/workspace/.venv/bin/python -m deep_notes.book_index --json --output /tmp/hermes-brain-book-index.json
```

Run ingest:

```bash
cd /workspace/hermes-related-code/rag
/workspace/.venv/bin/python -m deep_notes.ingest
```

Test automatic context retrieval for a prompt:

```bash
cd /workspace/hermes-related-code/rag
/workspace/.venv/bin/python -m deep_notes.hermes_context "Adapter design pattern implementation"
```

Run tests:

```bash
cd /workspace/hermes-related-code/rag
/workspace/.venv/bin/python -m pytest tests -q
```

## Recommended env settings

Keep these in the single active Hermes env file, usually `~/.hermes/.env` on the host:

```env
VAULT_PATH=/Users/denishlinka/hermes
SOURCE_PATHS=/gdrive/hermes-brain
BOOK_PATHS=/gdrive/hermes-brain/books,/gdrive/hermes-brain/pdf-docs
QDRANT_URL=http://127.0.0.1:6333
COLLECTION_NAME=hermes_brain
EMBED_PROVIDER=ollama
EMBED_MODEL=bge-m3
OLLAMA_BASE_URL=http://127.0.0.1:11434
LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-v4-pro
AUTO_CONTEXT_ENABLED=true
AUTO_CONTEXT_TOP_K=5
AUTO_CONTEXT_MIN_SCORE=0.25
AUTO_CONTEXT_MAX_CHARS=3500
```

## Mac Host ↔ Docker architecture consultation

When Denis asks whether the Hermes setup is becoming too complex or asks for migration planning, treat it as an architecture consultation, not an implementation request. Do not immediately edit host config, move repos, or change mounts. First separate the layers clearly:

1. Hermes profile/runtime state: `~/.hermes` config, env, memories, live skills, live plugins, sessions, logs.
2. Neutral workspace/source code: host `~/workspace` mounted to Docker `/workspace`, containing project repos such as `najdi-remeslnika/` and `hermes-brain/`.
3. Services/data: RAG API, Qdrant, Obsidian vault, Google Drive sources/books.

Default Docker `/workspace` should be neutral, not the najdi-remeslnika project root. Project-specific work should set an explicit workdir. Live skills/plugins stay under the active Hermes profile; source-controlled skill/plugin templates can live in the `hermes-brain` repo and be installed/synced into `~/.hermes`.

See `references/mac-host-docker-workspace-architecture.md` for the recommended target shape and migration sequence.

## Automatic Hermes lookup hook

Use a Hermes plugin `pre_llm_call` hook, not a gateway-only hook, because plugin hooks work in CLI and gateway sessions. Official hook behavior: `pre_llm_call` can return `{ "context": "..." }` and Hermes prepends that context to the current user message.

The project artifact is:

```text
/workspace/hermes-related-code/rag/plugins/hermes-brain-rag/__init__.py
```

The live plugin is dependency-free and calls the local RAG API endpoint instead of importing LlamaIndex/Qdrant into the Hermes host process. This matters when RAG dependencies live in the Docker venv at `/workspace/.venv` but Hermes/gateway runs on the Mac host.

Run the local RAG API from the RAG runtime:

```bash
cd /workspace/hermes-related-code/rag
/workspace/.venv/bin/python -m uvicorn deep_notes.api:app --host 127.0.0.1 --port 8000
```

Configure the host Hermes env with:

```env
HERMES_BRAIN_RAG_CONTEXT_URL=http://127.0.0.1:8000/api/context
HERMES_BRAIN_RAG_API_KEY=<same value as API_KEY, keep secret>
HERMES_BRAIN_RAG_TIMEOUT=2.5
```

Then install/enable on the host:

```bash
mkdir -p ~/.hermes/plugins/hermes-brain-rag
cp /workspace/hermes-related-code/rag/plugins/hermes-brain-rag/__init__.py ~/.hermes/plugins/hermes-brain-rag/__init__.py
hermes plugins enable hermes-brain-rag
hermes gateway restart
```

The hook must stay retrieval-only. It should call `/api/context`, which internally uses `deep_notes.hermes_context.build_context_for_prompt()`, and must not run answer generation.

## Verification checklist

Minimum done signal:

1. Qdrant health OK.
2. Ollama health OK and `bge-m3` present.
3. `BOOK_PATHS` contains at least one visible extracted book/PDF.
4. `python -m deep_notes.book_index` returns page/section entries.
5. `python -m deep_notes.ingest` indexes documents.
6. `python -m deep_notes.hermes_context "Adapter design pattern implementation"` returns context with book/page citations.
7. A negative query returns empty/insufficient context rather than fabricated facts.

## Current implementation verification

Verified with:

```text
24 passed in 1.04s
py_compile passed for book_index, hermes_context, ingest, query, plugin
sample book index output: # Programming Design Patterns / pp. 184-186: Adapter
sample load_documents metadata included layer=book, section_title=Adapter, page_range=184-186
```
