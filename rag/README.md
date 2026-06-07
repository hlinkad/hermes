# Hermes Brain Modern RAG Setup

This document is the operating runbook for the Hermes Brain retrieval layer.

The goal is to make Hermes Brain searchable at scale without turning the vector database into the brain itself.

## Current decision

Hermes Brain uses a modern, rebuildable RAG stack:

- **Source storage:** Google Drive folder `/gdrive/hermes-brain`
- **Compiled brain:** Obsidian vault `/Users/denishlinka/hermes`
- **RAG framework:** LlamaIndex, adapted from `lucmir/obsidian-rag`
- **Vector database:** Qdrant in Docker
- **Embedding model:** Ollama `bge-m3`
- **Answer model:** DeepSeek via API
- **Local answer fallback:** optional Ollama `llama3.2`, not required for the main setup

Framework path:

```text
/gdrive/hermes-brain/rag/obsidian-rag
```

Config example:

```text
/gdrive/hermes-brain/rag/obsidian-rag/deep_notes/.env.hermes-brain.example
```

Single active env file:

```text
~/.hermes/.env
```

Do not create a live `deep_notes/.env`. Keep `DEEPSEEK_API_KEY` and the `deep_notes` runtime settings in the Hermes env file so Hermes and Hermes Brain RAG read one source.

## Architecture

```text
Google Drive originals / extracted sources
        │
        │ canonical source material
        ▼
Obsidian raw/ source cards
        │
        │ lightweight normalized source references
        ▼
Obsidian wiki/ compiled knowledge
        │
        │ durable human-readable brain
        ▼
LlamaIndex ingest pipeline
        │
        │ parses files, extracts metadata, chunks text, embeds chunks
        ▼
Ollama bge-m3 embeddings
        │
        │ vectors
        ▼
Qdrant collection: hermes_brain
        │
        │ semantic retrieval cache
        ▼
DeepSeek answer generation
        │
        │ grounded answer from retrieved context
        ▼
User / Hermes / optional API or UI
```

## Source-of-truth rule

Qdrant is not the source of truth.

The source of truth remains, in this order:

1. Google Drive originals and extracted source material.
2. Obsidian `raw/` source cards.
3. Obsidian `wiki/` compiled knowledge.

Qdrant stores only derived vectors and chunks. If Qdrant is stale, corrupted, or built with the wrong embedding model, delete the collection and rebuild it from Drive plus Obsidian.

## Embeddings vs answer models

Embedding models and answer/chat models are different things.

`bge-m3` is an embedding model. It converts text chunks into vectors so Qdrant can do semantic similarity search.

DeepSeek is the answer model. It receives retrieved chunks and writes the final answer.

Changing the answer model does **not** require rebuilding Qdrant.

Changing the embedding model **does** require rebuilding Qdrant, because all stored vectors were produced by the previous embedding model.

Recommended default:

```text
EMBED_PROVIDER=ollama
EMBED_MODEL=bge-m3
LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-v4-pro
```

## What was adapted in `obsidian-rag`

The upstream project originally focused on one Obsidian vault path. Hermes Brain needs multiple source layers, so the local copy now supports:

- `VAULT_PATH` for the Obsidian vault.
- `SOURCE_PATHS` for extra text/extracted source roots such as Google Drive.
- Metadata fields: `file_path`, `source_root`, `source_kind`, `layer`, `tags`, `title`, `sources`.
- Layer inference: `wiki`, `raw`, `vault`, `drive`.
- Generated/tooling directory skips: `.derived`, `rag`, `.obsidian`, `node_modules`, `__pycache__`, etc.
- Direct DeepSeek answer provider through the LlamaIndex OpenAI-compatible client.

Relevant files:

```text
/gdrive/hermes-brain/rag/obsidian-rag/deep_notes/config.py
/gdrive/hermes-brain/rag/obsidian-rag/deep_notes/ingest.py
/gdrive/hermes-brain/rag/obsidian-rag/deep_notes/query.py
/gdrive/hermes-brain/rag/obsidian-rag/deep_notes/components/embeddings.py
/gdrive/hermes-brain/rag/obsidian-rag/deep_notes/components/llm.py
/gdrive/hermes-brain/rag/obsidian-rag/deep_notes/components/vector_store.py
/gdrive/hermes-brain/rag/obsidian-rag/deep_notes/.env.hermes-brain.example
```

## Runtime components

The full setup runs on the Mac host, not inside the current Hermes Docker backend, because the current backend may not see `/Users/denishlinka/hermes` and may not have access to Docker.

You need these running on the Mac host:

1. Docker Desktop or equivalent Docker runtime.
2. Qdrant container.
3. Ollama background service.
4. Ollama `bge-m3` model.
5. Python environment for `obsidian-rag`.
6. DeepSeek API key and `deep_notes` runtime settings in `~/.hermes/.env`.

## Qdrant setup from scratch

Use this if you want a clean, explicit Docker container outside Compose.

### Pull Qdrant

```bash
docker pull qdrant/qdrant:latest
```

### Create persistent volume

```bash
docker volume create hermes_brain_qdrant
```

### Run Qdrant

Bind ports to localhost only. This keeps Qdrant private to the Mac.

```bash
docker run -d \
  --name hermes-brain-qdrant \
  --restart unless-stopped \
  -p 127.0.0.1:6333:6333 \
  -p 127.0.0.1:6334:6334 \
  -v hermes_brain_qdrant:/qdrant/storage \
  qdrant/qdrant:latest
```

Ports:

- `6333`: HTTP API.
- `6334`: gRPC API.

RAG config should use:

```env
QDRANT_URL=http://127.0.0.1:6333
COLLECTION_NAME=hermes_brain
```

### Verify Qdrant

```bash
docker ps --filter name=hermes-brain-qdrant
```

```bash
curl -s http://127.0.0.1:6333/healthz
```

```bash
curl -s http://127.0.0.1:6333/collections
```

Expected health response is usually:

```text
healthz check passed
```

Expected collections response before first ingest is usually an empty collection list.

### Logs and status

```bash
docker logs --tail=100 hermes-brain-qdrant
```

```bash
docker stats hermes-brain-qdrant
```

```bash
docker inspect hermes-brain-qdrant
```

### Lifecycle commands

Stop Qdrant:

```bash
docker stop hermes-brain-qdrant
```

Start Qdrant again:

```bash
docker start hermes-brain-qdrant
```

Restart Qdrant:

```bash
docker restart hermes-brain-qdrant
```

Remove the container but keep data:

```bash
docker rm -f hermes-brain-qdrant
```

Remove the container and wipe all Qdrant data:

```bash
docker rm -f hermes-brain-qdrant
docker volume rm hermes_brain_qdrant
```

### Update Qdrant image while keeping data

```bash
docker pull qdrant/qdrant:latest
```

```bash
docker rm -f hermes-brain-qdrant
```

```bash
docker run -d \
  --name hermes-brain-qdrant \
  --restart unless-stopped \
  -p 127.0.0.1:6333:6333 \
  -p 127.0.0.1:6334:6334 \
  -v hermes_brain_qdrant:/qdrant/storage \
  qdrant/qdrant:latest
```

Then verify:

```bash
curl -s http://127.0.0.1:6333/collections
```

## Qdrant with Docker Compose

The framework also includes:

```text
/gdrive/hermes-brain/rag/obsidian-rag/docker-compose.yml
```

Current Compose service:

```yaml
services:
  qdrant:
    image: qdrant/qdrant:latest
    ports:
      - "6333:6333"
      - "6334:6334"
    volumes:
      - qdrant_data:/qdrant/storage

volumes:
  qdrant_data:
```

Start via Compose:

```bash
cd /gdrive/hermes-brain/rag/obsidian-rag
docker compose up -d qdrant
```

Verify:

```bash
docker compose ps
curl -s http://127.0.0.1:6333/healthz
curl -s http://127.0.0.1:6333/collections
```

Logs:

```bash
docker compose logs --tail=100 qdrant
```

Stop but keep data:

```bash
docker compose stop qdrant
```

Start again:

```bash
docker compose start qdrant
```

Remove container but keep named volume:

```bash
docker compose rm -sf qdrant
```

Stop and remove Compose-created containers and network, keeping volumes:

```bash
docker compose down
```

Stop and wipe Compose volume too:

```bash
docker compose down -v
```

Important: choose either the explicit `docker run` container or the Compose service. Do not run both on ports `6333` and `6334` at the same time.

## Ollama setup

Ollama is used for local embeddings, specifically `bge-m3`.

Do not rely on `ollama serve` in a disposable terminal. Use a macOS background service so it keeps running.

### Install Ollama

```bash
brew install ollama
```

### Start Ollama as a background service

```bash
brew services start ollama
```

### Verify service status

```bash
brew services list | grep ollama
```

```bash
brew services info ollama
```

### Verify the Ollama HTTP API

```bash
curl http://127.0.0.1:11434/api/tags
```

If Ollama is running but no models are installed yet, this returns JSON with an empty model list.

### Pull the embedding model

```bash
ollama pull bge-m3
```

### Verify the model exists

```bash
ollama list
```

You should see `bge-m3`.

### Optional local answer model

Only needed if you want a local answer-generation fallback instead of DeepSeek.

```bash
ollama pull llama3.2
```

For the current recommended setup, `llama3.2` is optional because DeepSeek is the answer model.

### Ollama lifecycle commands

Restart:

```bash
brew services restart ollama
```

Stop:

```bash
brew services stop ollama
```

Start:

```bash
brew services start ollama
```

Check installed models:

```bash
ollama list
```

Update the `bge-m3` model:

```bash
ollama pull bge-m3
```

## Python environment setup

Run this on the Mac host.

```bash
cd /gdrive/hermes-brain/rag/obsidian-rag
```

Create a local virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r deep_notes/requirements.txt
```

Verify Python can import the package:

```bash
python - <<'PY'
from deep_notes.config import get_settings
print(get_settings().collection_name)
PY
```

## Configure `.env`

Create the real env file:

```bash
cd /gdrive/hermes-brain/rag/obsidian-rag/deep_notes
cp .env.hermes-brain.example .env
chmod 600 .env
```

Edit `.env` manually and add your real DeepSeek API key.

Recommended current config:

```env
VAULT_PATH=/Users/denishlinka/hermes
SOURCE_PATHS=/gdrive/hermes-brain

EMBED_PROVIDER=ollama
EMBED_MODEL=bge-m3
OLLAMA_BASE_URL=http://127.0.0.1:11434

VECTOR_STORE_PROVIDER=qdrant
QDRANT_URL=http://127.0.0.1:6333
COLLECTION_NAME=hermes_brain

CHUNK_STRATEGY=markdown
CHUNK_SIZE=512
CHUNK_OVERLAP=50

LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-chat
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_API_KEY=<your key>

SIMILARITY_TOP_K=8
```

If your DeepSeek V4 Pro provider uses a model ID other than `deepseek-chat`, replace `LLM_MODEL` with that exact ID.

DeepSeek's official OpenAI-compatible base URL is:

```text
https://api.deepseek.com
```

Do not treat `/v1` as the model version. If a specific SDK or proxy requires `/v1`, follow that provider's docs, but the direct DeepSeek API docs use `https://api.deepseek.com`.

This `.env` belongs to the standalone RAG runtime under `obsidian-rag`. It is separate from configuring Hermes Agent itself. For Hermes Agent model/provider setup, use Hermes CLI commands such as `hermes model`, `hermes auth add`, and `hermes config set ...`; do not hand-edit Hermes `config.yaml` unless the CLI cannot express the setting.

If using OpenRouter instead of direct DeepSeek API:

```env
LLM_PROVIDER=openrouter
LLM_MODEL=<provider/model-id>
OPENROUTER_API_KEY=<your key>
```

If using local Ollama for answer generation instead:

```env
LLM_PROVIDER=ollama
LLM_MODEL=llama3.2
```

## Securely inserting the DeepSeek API key

Avoid pasting secrets into terminal commands that get saved to shell history.

One safe pattern:

```bash
cd /gdrive/hermes-brain/rag/obsidian-rag/deep_notes
read -r -s -p "DeepSeek API key: " DEEPSEEK_API_KEY
echo
python3 - <<'PY'
from pathlib import Path
import os

env = Path('.env')
key = os.environ['DEEPSEEK_API_KEY']
lines = env.read_text().splitlines()
out = []
seen = False
for line in lines:
    if line.startswith('DEEPSEEK_API_KEY='):
        out.append('DEEPSEEK_API_KEY=' + key)
        seen = True
    else:
        out.append(line)
if not seen:
    out.append('DEEPSEEK_API_KEY=' + key)
env.write_text('\n'.join(out) + '\n')
PY
unset DEEPSEEK_API_KEY
```

## Source visibility check

Before ingesting, confirm the host can see both source roots:

```bash
test -d /Users/denishlinka/hermes && echo "vault ok"
test -d /gdrive/hermes-brain && echo "drive ok"
```

If `/gdrive/hermes-brain` is not mounted on the host, use the actual Google Drive path on the Mac and set `SOURCE_PATHS` to that path.

If the command runs inside a Docker/backend sandbox that cannot see `/Users/denishlinka/hermes`, run ingestion on the Mac host instead.

## Ingestion

Make sure Qdrant and Ollama are both running first.

```bash
curl -s http://127.0.0.1:6333/healthz
curl -s http://127.0.0.1:11434/api/tags
```

Run ingestion:

```bash
cd /gdrive/hermes-brain/rag/obsidian-rag
source .venv/bin/activate
python -m deep_notes.ingest
```

Expected behavior:

- It loads markdown from the Obsidian vault.
- It loads text/extracted files from `SOURCE_PATHS`.
- It skips generated/tooling directories such as `rag/`.
- It embeds chunks with Ollama `bge-m3`.
- It writes vectors into Qdrant collection `hermes_brain`.

Check Qdrant after ingest:

```bash
curl -s http://127.0.0.1:6333/collections/hermes_brain
```

## What gets indexed

Vault files:

- Markdown files under `/Users/denishlinka/hermes`.
- The loader skips `.obsidian`, `.git`, `.trash`, `node_modules`, `__pycache__`, `.derived`, `vector-index`, and `rag`.

Drive/source files:

- `.md`
- `.markdown`
- `.txt`
- `.text`
- `.rst`
- `.org`
- `.json`
- `.jsonl`
- `.yaml`
- `.yml`
- `.csv`
- `.tsv`
- `.html`
- `.htm`

Binary files such as PDFs, images, Word docs, and scans must be OCR/extracted into text or markdown first before this loader can index their content.

## Retrieval-only smoke test

Do this before testing answer generation. It proves Qdrant plus embeddings work independently of DeepSeek.

```bash
cd /gdrive/hermes-brain/rag/obsidian-rag
source .venv/bin/activate
python - <<'PY'
from deep_notes.query import retrieve

question = "What is the Hermes Brain source-of-truth architecture?"
result = retrieve(question)

print(f"sources={len(result.sources)}")
for source in result.sources:
    print("---")
    print("score:", round(source.score, 4))
    print("file:", source.file_path or source.file_name)
    print(source.text[:700].replace('\n', ' '))
PY
```

Expected result:

- Several source chunks are returned.
- Results include `wiki/`, `raw/`, or Drive-derived source paths depending on the question.
- The output is grounded in actual files, not generated text.

## Answer-generation smoke test with DeepSeek

After retrieval works, test answer generation.

```bash
cd /gdrive/hermes-brain/rag/obsidian-rag
source .venv/bin/activate
python - <<'PY'
from deep_notes.query import retrieve, stream_answer

question = "Explain the Hermes Brain RAG architecture and source-of-truth rule."
retrieved = retrieve(question)
print("Retrieved sources:")
for source in retrieved.sources:
    print("-", source.file_path or source.file_name, "score=", round(source.score, 4))

print("\nAnswer:\n")
for token in stream_answer(question, retrieved.context_str, chat_history=[]):
    print(token, end="", flush=True)
print()
PY
```

Expected behavior:

- Retrieval lists real source files first.
- DeepSeek answers using only retrieved context.
- If context is insufficient, the answer should say so rather than hallucinating.

## Negative test

Ask a question that should not be in the brain.

```bash
cd /gdrive/hermes-brain/rag/obsidian-rag
source .venv/bin/activate
python - <<'PY'
from deep_notes.query import retrieve, stream_answer

question = "What is Denis's private bank account password?"
retrieved = retrieve(question)
print("Retrieved sources:", len(retrieved.sources))
print("\nAnswer:\n")
for token in stream_answer(question, retrieved.context_str, chat_history=[]):
    print(token, end="", flush=True)
print()
PY
```

Correct behavior: refuse or state that the indexed context does not contain the answer.

## Rebuild strategy

Rebuild Qdrant when:

- The embedding model changes.
- Chunking parameters change significantly.
- The collection gets stale or corrupted.
- Source metadata logic changes.
- You want a clean benchmark/eval run.

Delete only the Hermes Brain collection:

```bash
curl -X DELETE http://127.0.0.1:6333/collections/hermes_brain
```

Then re-ingest:

```bash
cd /gdrive/hermes-brain/rag/obsidian-rag
source .venv/bin/activate
python -m deep_notes.ingest
```

Full destructive wipe if you want to delete all Qdrant data:

```bash
docker rm -f hermes-brain-qdrant
docker volume rm hermes_brain_qdrant
```

Then recreate the container from the Qdrant setup section.

## Completeness checklist

A RAG setup is not complete just because containers start.

Complete means:

1. Qdrant starts and responds on `http://127.0.0.1:6333`.
2. Ollama starts as a background service and responds on `http://127.0.0.1:11434`.
3. `bge-m3` is installed in Ollama.
4. Python dependencies install successfully in `.venv`.
5. `.env` has correct paths, Qdrant URL, Ollama URL, and DeepSeek API config.
6. The ingest command indexes documents from the Obsidian vault.
7. The ingest command indexes text/extracted material from Google Drive/source paths.
8. Qdrant collection `hermes_brain` exists after ingest.
9. Retrieval-only smoke test returns relevant source chunks.
10. Answer-generation smoke test returns grounded answers through DeepSeek.
11. Negative test does not hallucinate missing private/nonexistent information.
12. Rebuild path is documented and tested.
13. A small eval set exists for recurring quality checks.

## Suggested eval set

Keep a small set of recurring questions to test retrieval quality after changes.

Suggested categories:

- Known fact from `wiki/`.
- Known fact from `raw/`.
- Known fact from Drive-derived extracted source.
- Cross-source synthesis question.
- Czech or Slovak query.
- Question with no answer in the brain.
- Question that requires citing source files.
- Question where the answer should prefer compiled `wiki/` over raw chunks.

Store eval questions outside Qdrant. Qdrant should remain rebuildable.

## Troubleshooting

### `ollama server not responding - could not find ollama app`

Ollama is not installed or not running.

```bash
brew install ollama
brew services start ollama
curl http://127.0.0.1:11434/api/tags
```

### `ollama serve` works only while a terminal is open

Use Homebrew services instead:

```bash
brew services start ollama
```

### Qdrant connection refused

Check Docker Desktop is running and container exists:

```bash
docker ps --filter name=hermes-brain-qdrant
curl -s http://127.0.0.1:6333/healthz
```

Check logs:

```bash
docker logs --tail=100 hermes-brain-qdrant
```

### Port already allocated

Another Qdrant instance is probably running.

```bash
docker ps | grep qdrant
lsof -i :6333
lsof -i :6334
```

Stop the duplicate container or change ports consistently in Docker and `.env`.

### Retrieval returns irrelevant chunks

Likely causes:

- The wrong source paths are configured.
- The collection was built with stale content.
- The query needs better compiled wiki pages.
- Chunk size/overlap needs tuning.
- The embedding model was changed without rebuilding.

First rebuild the collection:

```bash
curl -X DELETE http://127.0.0.1:6333/collections/hermes_brain
cd /gdrive/hermes-brain/rag/obsidian-rag
source .venv/bin/activate
python -m deep_notes.ingest
```

### DeepSeek auth or model error

Check `.env`:

```env
LLM_PROVIDER=deepseek
LLM_MODEL=<exact model id from provider>
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_API_KEY=<real key>
```

If your DeepSeek V4 Pro access is through a non-official provider, the base URL and model ID may differ. Use the provider's OpenAI-compatible base URL and exact model ID.

### Ingest does not include PDFs or scans

The current loader indexes text-like files only. Extract PDFs/scans into markdown or text first, then point `SOURCE_PATHS` at those extracted files.

### Hermes Docker backend cannot run the full stack

This is expected in the current environment. The Docker-backed Hermes tools may see `/gdrive/hermes-brain`, but not the Mac host vault `/Users/denishlinka/hermes`, and may not have Docker access. Run Qdrant, Ollama, ingestion, and query verification on the Mac host.

## Operating principle

Use vector retrieval as an accelerator, not as the brain.

The durable knowledge workflow remains:

```text
source lands in Drive
→ source is extracted/normalized if needed
→ lightweight raw/source card or compiled wiki note is created when appropriate
→ RAG ingest indexes the resulting text
→ retrieval helps find evidence
→ answer generation cites retrieved files
```

Do not dump huge source files directly into Obsidian just to improve RAG. Keep Obsidian readable. Use Drive for originals and extracted source material, Obsidian for durable compiled knowledge, and Qdrant for derived retrieval.
