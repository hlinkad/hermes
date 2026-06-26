# Obsidian RAG

> Local-first semantic search and chat over your Obsidian vault — powered by LlamaIndex, Qdrant, and Ollama.

[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Built with LlamaIndex](https://img.shields.io/badge/built%20with-LlamaIndex-7c3aed.svg)](https://docs.llamaindex.ai/)
[![Vector DB: Qdrant](https://img.shields.io/badge/vector%20db-Qdrant-dc2626.svg)](https://qdrant.tech/)

Ask natural-language questions about your notes and get streamed answers grounded in your own writing — with source citations. Everything runs on your machine by default. No vendor lock-in: every component (embedding model, vector store, chunking strategy, LLM) is swappable through environment variables.

---

## Why this exists

I take a lot of notes in Obsidian and wanted to *talk* to them — not just search by keyword. Existing tools either send your notes to a third-party API or lock you into a single model. This project is a working RAG pipeline that's:

- **Local by default** — Ollama for embeddings and inference, Qdrant on Docker, no cloud calls required
- **Pluggable** — swap any provider via `.env`, no code changes
- **Built to learn** — the codebase is deliberately small and uses a clean component-factory pattern so the moving parts of a RAG system are easy to read

It also ships with an **Obsidian plugin** that lets you query the index directly from inside Obsidian.

---

## Architecture

```
┌───────────────────┐
│  Obsidian Vault   │  .md files + frontmatter
└────────┬──────────┘
         │
         ▼
┌───────────────────┐    ┌──────────────────┐
│  Chunker          │───▶│  Embedder        │  Ollama (bge-m3) | OpenAI
│  sentence/token/  │    │                  │
│  markdown         │    └─────────┬────────┘
└───────────────────┘              │
                                   ▼
                       ┌──────────────────┐
                       │  Vector Store    │  Qdrant
                       │  (similarity     │
                       │  search)         │
                       └─────────┬────────┘
                                 │
                                 ▼
┌───────────────────┐    ┌──────────────────┐
│  User Question    │───▶│  Retriever + LLM │  Ollama | OpenRouter | OpenAI
│  (UI / API /      │    │  → streamed      │
│  Obsidian plugin) │◀───│  answer + cites  │
└───────────────────┘    └──────────────────┘
```

Every box on the right is a factory in `deep_notes/components/`. Adding a new provider means one new `case` and a requirements line — no refactor.

---

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| RAG orchestration | [LlamaIndex](https://docs.llamaindex.ai/) | Well-supported plugin model for swappable components |
| Vector DB | [Qdrant](https://qdrant.tech/) | Fast, runs in Docker, has a dashboard, metadata filtering |
| Embeddings (default) | Ollama + `bge-m3` | Strong multilingual retrieval, runs locally |
| LLM (default) | Ollama + `llama3.2` | Local, no API key |
| UI | Streamlit | Fast prototyping with streaming support |
| API | FastAPI | Bearer-token auth, streaming endpoints |
| Plugin | TypeScript + esbuild | Native-feeling Obsidian integration |

**Swap any of them** by editing `.env`:

- `EMBED_PROVIDER` — `ollama` | `openai`
- `VECTOR_STORE_PROVIDER` — `qdrant`
- `LLM_PROVIDER` — `ollama` | `openrouter` | `openai` | `deepseek`
- `CHUNK_STRATEGY` — `sentence` | `token` | `markdown`

---

## Quick start

**Prerequisites:** Python 3.11+, Docker, [Ollama](https://ollama.com)

```bash
# 1. Clone and install
git clone https://github.com/lucmir/obsidian-rag.git
cd obsidian-rag
pip install -r deep_notes/requirements.txt

# 2. Start Qdrant
docker compose up -d

# 3. Pull the embedding model
ollama pull bge-m3
ollama pull llama3.2   # or configure a different LLM provider

# 4. Configure
cp deep_notes/.env.example deep_notes/.env
# Edit deep_notes/.env if needed.
# Mac-host runs can keep VAULT_PATH=/Users/denishlinka/hermes/brain and localhost URLs.
# Hermes Docker runs should leave VAULT_PATH empty unless /Users is mounted,
# and should use host.docker.internal for Qdrant/Ollama.
```

### Index your vault

```bash
python -m deep_notes.ingest
```

### Launch the Streamlit UI

```bash
streamlit run deep_notes/app.py
```

Open [http://localhost:8501](http://localhost:8501) and ask away.

### Run the REST API

```bash
uvicorn deep_notes.api:app --reload
```

Endpoints: `POST /query`, `POST /query/stream`, `POST /ingest`, `DELETE /index`. All require a Bearer token (`API_KEY` in `.env`).

---

## Obsidian plugin

`obsidian-plugin/` is a TypeScript plugin that calls the local API and renders results inside Obsidian. Build it with:

```bash
cd obsidian-plugin
npm install
npm run build
```

Then copy the built plugin folder into your vault's `.obsidian/plugins/` directory.

---

## Configuration reference

All settings can come from OS environment variables, the ignored project file `deep_notes/.env`, or the active Hermes env file `~/.hermes/.env`. Precedence is: explicit `Settings(...)` overrides > OS env > `deep_notes/.env` > `~/.hermes/.env` > code defaults. The most useful knobs:

| Variable | Default/example | Notes |
|---|---|---|
| `VAULT_PATH` | `/Users/denishlinka/hermes/brain` | Mac-host vault path. Leave empty in Hermes Docker unless that path is mounted. |
| `SOURCE_PATHS` | `/gdrive/hermes-brain` | Comma-separated extra text/extracted source roots. |
| `BOOK_PATHS` | `/gdrive/hermes-brain/books,/gdrive/hermes-brain/pdf-docs` | Comma-separated book/PDF roots. |
| `EMBED_PROVIDER` | `ollama` | `ollama`, `openai` |
| `EMBED_MODEL` | `bge-m3` | Changing this requires rebuilding Qdrant. |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Use `http://host.docker.internal:11434` from Hermes Docker. |
| `VECTOR_STORE_PROVIDER` | `qdrant` | `qdrant` |
| `QDRANT_URL` | `http://127.0.0.1:6333` | Use `http://host.docker.internal:6333` from Hermes Docker. |
| `COLLECTION_NAME` | `hermes_brain` | Shared Hermes Brain collection. |
| `CHUNK_STRATEGY` | `markdown` | `sentence`, `token`, `markdown` |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | `512` / `50` | Any integer |
| `LLM_PROVIDER` | `openai` | `openai`, `openrouter`, `ollama`, `deepseek` |
| `LLM_MODEL` | `gpt-5.5` | Retrieval-only commands do not need an LLM key. |
| `SIMILARITY_TOP_K` | `8` | Number of chunks retrieved per query |
| `AUTO_CONTEXT_MIN_SCORE` | `0.55` | Threshold for automatic Hermes context injection |

See `deep_notes/.env.example` for the full list.

---

## Project layout

```
obsidian-rag/
├── deep_notes/
│   ├── config.py             # Pydantic settings — all knobs in one place
│   ├── components/
│   │   ├── embeddings.py     # Embedding model factory
│   │   ├── vector_store.py   # Vector store factory
│   │   ├── llm.py            # LLM factory
│   │   └── chunking.py       # Chunking strategy factory
│   ├── ingest.py             # Vault loading + ingestion pipeline
│   ├── query.py              # Retrieval + answer generation
│   ├── app.py                # Streamlit UI
│   └── api.py                # FastAPI server
├── obsidian-plugin/          # TypeScript Obsidian plugin
├── docker-compose.yml        # Qdrant
└── README.md
```

---

## Adding a new provider

1. Add a `case` to the relevant factory in `deep_notes/components/`
2. Add the LlamaIndex integration package to `deep_notes/requirements.txt`
3. Add any new env vars to `config.py` and `.env.example`

That's it — no other code needs to change.

---

## Roadmap

- [ ] Test coverage for ingestion + retrieval edge cases
- [ ] Metadata filtering (tags, folders) in the UI
- [ ] Re-ranking step (e.g. Cohere Rerank, bge-reranker)
- [ ] Incremental re-indexing (skip unchanged files)
- [ ] Multi-vault support
- [ ] Published Obsidian plugin via community store

---

## License

[MIT](LICENSE)
