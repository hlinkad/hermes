# Live Hermes Brain RAG environment

DH-224 intentionally enables the Obsidian Core parser for the live Hermes Brain RAG runtime without changing the safe code default. `OBSIDIAN_CORE_ENABLED` remains disabled in `deep_notes.config.Settings` unless the runtime environment opts in.

## Canonical runtime values

For the Hermes Docker-backed runtime used from this workspace, keep the Obsidian Core checkout mounted at:

```env
OBSIDIAN_CORE_ENABLED=true
OBSIDIAN_CORE_PATH=/workspace/obsidian-intelligence-core/src
```

`/workspace/obsidian-intelligence-core/src` is the canonical container path verified for live smoke runs. If running the RAG app directly on the Mac host instead of inside Hermes Docker, either install `obsidian-intelligence-core` into that Python environment or set `OBSIDIAN_CORE_PATH` to the host checkout's repo root or `src/` directory.

## Where to put the values

Put RAG ingest/runtime settings in the ignored project-local file:

```text
/workspace/hermes-related-code/rag/obsidian-rag/deep_notes/.env
```

Do not use the global Hermes env as the primary home for these values. `~/.hermes/.env` should stay focused on Hermes gateway/plugin/API settings such as provider keys, gateway tokens, and plugin endpoint configuration. Only duplicate the Obsidian Core values there if a deliberate host-level deployment needs the gateway process itself to export them.

Settings precedence is:

```text
explicit Settings(...) overrides > OS env > deep_notes/.env > ~/.hermes/.env > code defaults
```

If an already-running API, worker, or plugin process loaded settings before this change, restart that process so it reloads `deep_notes/.env`.

## Verification commands

From `/workspace/hermes-related-code/rag/obsidian-rag`, first confirm the project env resolves to the intended core path:

```bash
UV_CACHE_DIR=/workspace/tmp/uv-cache TMPDIR=/workspace/tmp/uv-tmp \
uv run --no-project --with-requirements requirements-dev.txt python - <<'PY'
from pathlib import Path
from deep_notes.config import get_settings

settings = get_settings()
print(f"obsidian_core_enabled={settings.obsidian_core_enabled}")
print(f"obsidian_core_path={settings.obsidian_core_path}")
core_path = Path(settings.obsidian_core_path).resolve(strict=True)
assert settings.obsidian_core_enabled is True
assert core_path == Path("/workspace/obsidian-intelligence-core/src")
assert (core_path / "obsidian_intelligence_core").is_dir()
PY
```

Then run the scoped live smoke. This uses a temporary fixture vault and temporary Qdrant collection; it does not mutate the persistent `hermes_brain` collection:

```bash
UV_CACHE_DIR=/workspace/tmp/uv-cache TMPDIR=/workspace/tmp/uv-tmp \
uv run --no-project --with-requirements requirements-dev.txt \
  python -m deep_notes.live_smoke \
  --qdrant-url http://host.docker.internal:6333 \
  --ollama-base-url http://host.docker.internal:11434 \
  --json
```

The JSON report should include `metadata_checks.obsidian_metadata_schema=hermes_brain.rag_metadata.v1`, rich Obsidian metadata fields such as aliases/links/embeds/block IDs/callouts, positive retrieval for the fixture phrase, negative-query filtering, and verified cleanup for the temporary collection and vault.

## Production collection boundary

This DH-224 rollout only enables the parser in the RAG runtime and verifies it against a temporary collection. Rebuilding or replacing the persistent `hermes_brain` Qdrant collection remains a separate, explicitly confirmed rollout step.
