# Hermes Brain Schema

Hermes Brain is Denis's compiled AI/technical knowledge base. It turns raw books, PDFs, notes, and project material into short, sourced, reusable Obsidian wiki pages.

## Architecture

```text
Google Drive raw source -> hermes-brain-rag -> Qdrant
Qdrant + source metadata -> hermes-brain-wiki-compiler -> wiki pages
```

- Google Drive raw sources are canonical originals. Do not mutate them.
- Qdrant is a derived retrieval cache. Use it to find chunks, source paths, and page ranges; do not cite Qdrant as a source.
- This schema is for wiki compilation only. RAG ingestion does not need to read it.

## Structure

```text
wiki/
├── SCHEMA.md
├── index.md
├── log.md
├── entities/
├── projects/
├── concepts/
└── _archive/
```

## Page types

- `concepts/`: definitions, mechanisms, patterns, and difficult AI/ML ideas. Example: `quantization.md`.
- `entities/`: named concrete things: tools, models, people, organizations, products, papers, systems. Example: `qdrant.md`.
- `projects/`: Denis's specific projects and how concepts/entities are applied. Example: `hermes-brain.md`.
- `_archive/`: superseded pages kept for history.

## Page rules

- File names: lowercase kebab-case, e.g. `context-engineering.md`.
- Every page needs frontmatter:

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

- Every durable claim must be traceable to a source path, page range, or existing wiki page.
- Prefer concise synthesis over exhaustive summaries.
- Use Obsidian links like `[[context-engineering]]`.
- New pages should link to related pages where useful.

## Create or update

Create a page when the topic is central to a source, likely reusable, or requested by Denis.
Update an existing page when the idea already exists. Do not create duplicate pages for synonyms; use `aliases`.
Do not create pages for passing mentions or trivia.

## Index and log

- `index.md` lists every durable page under Concepts, Entities, or Projects with a one-line summary.
- `log.md` is append-only. Log meaningful compilation actions, sources used, files created/updated, and unresolved review notes.

## Compiler behavior

`hermes-brain-wiki-compiler` must read `SCHEMA.md`, `index.md`, and recent `log.md` before writing. For long books, subagents may analyze assigned sections, but only the orchestrator writes final wiki pages, `index.md`, and `log.md`.

Subagents analyze; orchestrator merges and writes.
