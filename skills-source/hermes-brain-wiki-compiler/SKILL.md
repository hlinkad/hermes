---
name: hermes-brain-wiki-compiler
description: Use when compiling Hermes Brain Qdrant-indexed books/PDFs/sources into concise Obsidian wiki pages; orchestrates subagents for large sources, then updates wiki pages, index.md, and log.md.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [hermes-brain, wiki, qdrant, obsidian, books, synthesis, subagents]
    related_skills: [hermes-brain-rag, llm-wiki, subagent-driven-development]
---

# Hermes Brain Wiki Compiler

## Overview

Compile already-indexed Hermes Brain sources into durable Obsidian wiki knowledge.

This skill is the semantic layer after RAG ingest:

```text
Google Drive raw source -> hermes-brain-rag -> Qdrant
Qdrant + source metadata -> hermes-brain-wiki-compiler -> wiki/
```

This skill reads `SCHEMA.md` and decides how knowledge becomes `concepts/`, `entities/`, and `projects/` pages.

## Paths

Obsidian wiki path:

```text
/Users/denishlinka/hermes/wiki
```

If /Users/denishlinka/hermes/wiki is inaccessible, stop and tell Denis. Do not fall back to the source-controlled seed.

RAG runtime:

```text
/workspace/hermes-related-code/rag/obsidian-rag
/workspace/.venv/bin/python
```

## When to Use

Use when Denis asks to:

- compile a book/PDF/article/note into Hermes Brain;
- create/update `wiki/concepts/*`, `wiki/entities/*`, or `wiki/projects/*`;
- update Hermes Brain `index.md` and `log.md` from indexed source knowledge;
- synthesize difficult AI/ML concepts for long-term learning.

Do not use for raw ingest into Qdrant; use `hermes-brain-rag` for that.

## Core Rule

**Subagents analyze; the orchestrator writes.**

Subagents must not edit final wiki pages, `index.md`, or `log.md`. They return structured analysis only. The parent/orchestrator merges, deduplicates, verifies, and performs all final writes.

This avoids duplicate pages, conflicting definitions, broken links, and index/log races.

## Required Orientation

Before any write, the orchestrator reads:

1. `wiki/SCHEMA.md`
2. `wiki/index.md`
3. recent `wiki/log.md`

For existing wikis, also search for likely duplicates before creating new pages.

## Workflow

### 1. Verify source is indexed

Use the RAG skill commands. Minimum checks:

```bash
cd /workspace/hermes-related-code/rag/obsidian-rag
/workspace/.venv/bin/python -m deep_notes.book_index --json --output /tmp/hermes-brain-book-index.json
/workspace/.venv/bin/python -m deep_notes.hermes_context "<source title or core topic>"
```

Confirm retrieved chunks include source path and page ranges. If Qdrant has no relevant chunks, run/repair RAG ingest first.

### 2. Build a source map

Create a compact map before spawning subagents:

```text
source title
source path
section/chapter -> page range -> 1-line topic hint
```

Do not read the whole PDF into parent context. Use book index, Qdrant metadata, and targeted page/section retrieval.

### 3. Split into section packs

Create section packs of roughly one chapter or 10-30 pages each, depending on density. Each pack should include:

- source title and path;
- page range;
- section headings;
- relevant retrieved snippets or extraction target;
- the exact expected output schema.

### 4. Dispatch subagents

Use `delegate_task` in batches, up to available parallelism. Each subagent receives one section pack and must read `SCHEMA.md` if file tools are available.

Subagent task contract:

```text
Goal: Analyze this section pack for Hermes Brain wiki compilation. Do not write final wiki files.

Required output:
- candidate_concepts: name, slug, definition, source pages, confidence, why durable
- candidate_entities: name, slug, what it is, source pages, confidence, why durable
- candidate_projects: name, slug, relevance to Denis's projects, source pages
- page_updates: existing page slug -> suggested additions
- wikilinks: proposed links between pages
- contradictions_or_uncertainties
- discard: notable mentions that should NOT become pages
```

Subagents should prefer short, source-grounded notes over prose essays.

### 5. Merge and dedupe

The orchestrator merges subagent outputs:

- combine synonyms under one slug using `aliases`;
- prefer `concepts/` for definitions/mechanisms and `entities/` for named concrete things;
- put Denis-specific implementations under `projects/`;
- discard passing mentions;
- identify existing pages to update instead of creating duplicates.

If the merge is ambiguous or would touch many pages, summarize the proposed page plan and ask Denis before writing.

### 6. Write final pages

Only the orchestrator writes final files.

Required page frontmatter:

```yaml
---
title: Page Title
created: YYYY-MM-DD
updated: YYYY-MM-DD
type: concept | entity | project
status: draft | active | needs-review | archived
confidence: high | medium | low
aliases: []
sources:
  - path: /gdrive/hermes-brain/books/example.pdf
    pages: 12-18
---
```

Default page body:

```markdown
# Page Title

## Summary

## Key ideas

## Details

## Relationships

## Sources
```

Keep pages concise. A definition page should explain the idea clearly enough for Denis to relearn it later without becoming a raw chapter dump.

### 7. Update navigation

Update `wiki/index.md` with every created durable page:

Below are only examples. Use the real page titles and slugs.

```markdown
## Concepts
- [[quantization]] — Reduces model weight/activation precision to lower memory and compute cost.

## Entities
- [[qdrant]] — Vector database used as a derived retrieval cache in Hermes Brain.

## Projects
- [[hermes-brain]] — Denis's personal compiled AI knowledge system.
```

Keep one-line summaries short.

### 8. Append log

Append to `wiki/log.md`:

```markdown
## YYYY-MM-DD — synthesize: Source Title

- Created:
  - `wiki/concepts/example.md`
- Updated:
  - `wiki/index.md`
- Sources:
  - `/gdrive/hermes-brain/books/example.pdf`, pp. 12-40
- Notes:
  - Review needs or unresolved questions.
```

### 9. Verify

Before reporting done:

- every created/updated page has frontmatter;
- every durable claim has source provenance;
- every created page appears in `index.md`;
- `log.md` has an append-only entry;
- no subagent output was copied blindly without orchestration review;
- if source-controlled, `git diff --stat` and `git status` are clean after commit.

## Context Budget Discipline

- Parent context should hold schema, index, recent log, source map, and merge plan only.
- Subagents handle section-level detail.
- Pass excerpts/page ranges, not whole books.
- Use cheap/fast models for extraction; use stronger models for final synthesis, dedupe, and contradiction handling.
- If a subagent returns a long essay, compress it carefully into the required structured fields before merging.

## Common Pitfalls

1. **Letting subagents write final wiki files.** Never do this. One writer only.
2. **Treating Qdrant as truth.** Qdrant locates sources; final claims cite original paths/pages.
3. **Creating pages for every mention.** Only durable, reusable knowledge gets pages.
4. **Duplicating concepts under synonyms.** Use `aliases` and update existing pages.
5. **Forgetting index/log.** A page is not done until navigation and log are updated.
6. **Reading whole PDFs into parent context.** Use source maps and section packs.
7. **Overlong schema or page templates.** Keep instructions compact because every subagent may need them.

## Done Signal

A compile run is done only when the final answer can list:

- source processed;
- pages created;
- pages updated;
- index/log updates;
- verification performed;
- any blocked live path or missing mount.
