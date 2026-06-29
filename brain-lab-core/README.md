# brain-lab-core

Generic AI Lab foundation contracts and package skeleton.

`brain_lab_core` is intentionally tool-neutral. It defines the stable data contracts that concrete tools can import for artifact references, evidence, jobs, tool/provider declarations, normalized errors, and schema extension declarations. Domain-specific tools own their own schemas and behavior; this package only provides shared contract shapes and package boundaries.

## Contract surface

- `ArtifactId`, `ArtifactRef`, `Checksum`, `FreshnessState`, `Provenance`
- `EvidenceRef`, `Citation`, `SourceSpan`
- `Job`, `StageRun`, `LifecycleState`, `RetryMetadata`
- `ToolManifest`, `ResourceProfile`
- `ProviderSpec`, `ProviderCapability`
- `ErrorEnvelope`, `ContractDiagnostic`, `ContractValidationError`
- `SchemaExtensionPoint` for concrete tool-owned schemas

Every public contract is a frozen dataclass with constructor-time validation and deterministic JSON support:

```python
from brain_lab_core.contracts import ArtifactId

artifact_id = ArtifactId("transcript-001", namespace="video-intel")
loaded = ArtifactId.from_json(artifact_id.to_json())
assert loaded == artifact_id
```

## State ledger

`brain_lab_core.state` implements the generic local source of truth for artifacts and runtime state:

- `SQLiteArtifactLedger` owns canonical SQLite tables for artifacts, artifact input edges, jobs, stage runs, evidence refs, append-only events, and schema migrations.
- `register_artifact_from_file(...)` measures filesystem payloads, stores checksum/size/path/URI, producer/stage provenance, input artifact IDs, schema version, metadata, and config fingerprints.
- Duplicate artifact registration is idempotent; reusing an artifact ID for a different canonical payload raises `ArtifactConflictError`.
- `ArtifactId` namespace/value components reserve `:` so qualified IDs remain unambiguous.
- Freshness states include `current`, `stale`, `superseded`, and `unknown`; config/input changes, explicit input changes, and superseding artifacts mark dependents stale transitively.
- SQLite is canonical. The filesystem helper only measures payloads and derives stable URIs relative to the configured artifact root.
- Schema migrations are recorded in `schema_migrations` and guarded by `PRAGMA user_version`; evidence refs enforce a foreign key to their source artifact.

Minimal example:

```python
from pathlib import Path
from brain_lab_core.contracts import ArtifactId
from brain_lab_core.state import SQLiteArtifactLedger

ledger = SQLiteArtifactLedger("state/ledger.sqlite", artifact_root=Path.cwd())
result = ledger.register_artifact_from_file(
    artifact_id=ArtifactId("report-001", namespace="fixture"),
    artifact_type="report.markdown",
    artifact_schema_version="report.v1",
    file_path="artifacts/report.md",
    producer_tool_id="fixture-tool",
    producer_stage_id="summarize",
    config={"prompt": "v1"},
)
assert result.artifact.freshness.value == "current"
```

## Extension-point packages

The package also exposes importable namespaces for later foundation work:

- `brain_lab_core.registry` — tool/provider registry
- `brain_lab_core.orchestration` — job runner lifecycle
- `brain_lab_core.retrieval` — retrieval facade
- `brain_lab_core.api` — control-plane/API surfaces
- `brain_lab_core.security` — security, secrets, and sandbox gates
- `brain_lab_core.observability` — structured events and diagnostics

These modules remain placeholders until their owning issues. DH-201 does not implement a job runner, retrieval index, API service, or domain-specific ingest logic.

## Development verification

From this directory:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
python -m compileall -q src tests
python -m pip wheel . --no-deps --no-build-isolation -w /tmp/brain-lab-core-wheel
```

`pyproject.toml` includes the intended Ruff config for environments that have `ruff` installed.
