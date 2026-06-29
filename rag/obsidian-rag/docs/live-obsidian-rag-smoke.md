# Live Obsidian RAG smoke test

This smoke verifies the Obsidian-aware Hermes Brain RAG path against the real runtime stack:
fixture Obsidian vault → core-backed ingest → live Qdrant collection → retrieval → score-filtered negative query.

It is designed for scoped verification. By default it creates a unique temporary fixture vault and a unique temporary
Qdrant collection, then deletes both before exiting. The smoke explicitly clears `SOURCE_PATHS` and `BOOK_PATHS`
and forces auto-context on for the run so environment or `.env` settings cannot skip the scoped negative-path check
or pull real source material into the smoke collection.

## Command used for DH-223

From `/workspace/hermes-related-code/rag/obsidian-rag`:

```bash
UV_CACHE_DIR=/workspace/tmp/uv-cache TMPDIR=/workspace/tmp/uv-tmp \
uv run --no-project --with-requirements requirements-dev.txt \
  python -m deep_notes.live_smoke \
  --qdrant-url http://host.docker.internal:6333 \
  --ollama-base-url http://host.docker.internal:11434 \
  --obsidian-core-path /workspace/obsidian-intelligence-core/src \
  --embed-provider ollama \
  --embed-model bge-m3 \
  --json
```

Use `host.docker.internal` from the Hermes Docker sandbox. On the Mac host itself, `localhost` is normally correct.

## What the smoke proves

- Controlled re-ingest: writes a fixture vault containing `wiki/dh223-live-smoke.md` and indexes exactly that one document.
- Qdrant live write: asserts the temporary collection has a non-zero point count after ingest.
- Scoped payloads: checks every payload in the temporary collection belongs to the generated fixture vault and fixture file.
- Payload metadata: checks legacy Hermes fields plus Obsidian-native fields such as aliases, links, embeds, block IDs, callouts, and `obsidian_summary`.
- Embedding/LLM hygiene: verifies structural Obsidian metadata remains payload-only and that semantic node text does not contain embed syntax, block IDs, or callout markers.
- Positive retrieval: queries the unique phrase `cobalt-lantern-walrus-DH223` and requires the expected note/chunk with readable citation metadata.
- Negative retrieval: runs an unrelated query and verifies the top score stays below the configured threshold and forced-on auto-context injection returns nothing.

## Cleanup and rollback

Default cleanup is automatic:

- The Qdrant collection is deleted at the end of the run.
- The temporary fixture vault workspace is removed at the end of the run. If `--fixture-root` is supplied, the smoke creates and cleans a unique child under that root rather than writing directly into the root.

If a run is interrupted, clean up manually:

```bash
UV_CACHE_DIR=/workspace/tmp/uv-cache TMPDIR=/workspace/tmp/uv-tmp \
uv run --no-project --with-requirements requirements-dev.txt python - <<'PY'
from qdrant_client import QdrantClient
client = QdrantClient(url="http://host.docker.internal:6333")
for collection in client.get_collections().collections:
    if collection.name.startswith("dh223_obsidian_live_smoke_"):
        client.delete_collection(collection.name)
        print(f"deleted {collection.name}")
PY
rm -rf /workspace/tmp/dh223_obsidian_live_smoke_*
```

For debugging only, use `--keep-collection` or `--keep-vault`; do not use those flags for routine verification. If `--collection-name` points at an existing collection, the smoke refuses to start unless `--replace-existing-collection` is also passed. The persistent `hermes_brain` collection name is reserved: the smoke refuses to use it even when absent unless `--replace-existing-collection` is passed. That explicit flag deletes the existing collection before ingest, so never use it on the persistent Hermes Brain collection unless a rebuild is truly intended.

## Feature gates

`OBSIDIAN_CORE_ENABLED` stays disabled by default in code defaults. The DH-224 live Hermes Brain RAG runtime opt-in belongs in the ignored project-local `deep_notes/.env`; see [`live-hermes-brain-rag-env.md`](live-hermes-brain-rag-env.md) for the exact values, host/container path boundary, and verification sequence.

This smoke enables Obsidian Core explicitly for the scoped fixture run and does not confirm any persistent collection update unless `--collection-name` is intentionally set to a persistent target. Its JSON report includes `metadata_checks.obsidian_metadata_schema=hermes_brain.rag_metadata.v1` when the core-backed payload path is active.
