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

`brain_lab_core.registry` adds the first metadata registry surface:

- `ToolRegistry` registers `ToolManifest` declarations, validates package/CLI/container entrypoints, and indexes tools by capability plus input/output artifact type.
- `AdapterRegistry` registers `ProviderSpec` declarations and indexes providers by capability/version plus input/output artifact type.
- `fixture_tool_manifest()`, `fixture_provider_spec()`, and `register_fixture_tool()` provide a fake tool/provider seam for downstream integration tests.

`brain_lab_core.orchestration` adds the generic local job-runner surface:

- `JobPlan`, `StagePlan`, and `ArtifactContract` validate explicit stage input/output contracts before execution.
- `JobRunner` persists job/stage lifecycle through the SQLite ledger, including `pending`, `running`, `completed`, `failed`, `stale`, `canceled`, and `skipped` stage states.
- `RetryPolicy` classifies retryable/non-retryable exact or prefix-wildcard error codes and honors normalized `ErrorEnvelope.retryable` flags.
- `StageContext` gives concrete handlers a safe way to register declared outputs, record progress/lease updates, and cooperatively cancel without deleting inspectable state/artifacts.
- `JobRunner.list_job_events(job_id)` returns append-only job/stage events from the ledger for API/MCP consumers.

Every public contract is a frozen dataclass with constructor-time validation and deterministic JSON support:

```python
from brain_lab_core.contracts import ArtifactId

artifact_id = ArtifactId("transcript-001", namespace="video-intel")
loaded = ArtifactId.from_json(artifact_id.to_json())
assert loaded == artifact_id
```

## Registry discovery

The registry layer is intentionally metadata-only: it stores manifests/specs and exposes JSON-safe discovery documents without importing package entrypoints, executing CLIs, or inspecting container images.

```python
from brain_lab_core.registry import ToolRegistry, fixture_tool_manifest

registry = ToolRegistry()
registry.register(fixture_tool_manifest())
discovery = registry.discovery_document()
assert discovery["capabilities"][0]["tool_id"] == "fixture-tool"
```

`ToolRegistry` accepts package (`python` or `package`), `cli`, and optional `container_image` entrypoints. `AdapterRegistry` exposes provider capabilities by name/version for API and MCP consumers.

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

- `brain_lab_core.registry` — tool/provider registry (metadata-only capability discovery)
- `brain_lab_core.orchestration` — job runner lifecycle, retries, resume/stale handling, leases, cancellation, and event stream
- `brain_lab_core.retrieval` — retrieval facade
- `brain_lab_core.api` — control-plane/API surfaces
- `brain_lab_core.security` — security, secrets, and sandbox gates
- `brain_lab_core.observability` — structured events and diagnostics

Registry metadata discovery, the state ledger, and the generic job runner are implemented. The remaining extension namespaces stay placeholders until their owning issues; DH-203 does not implement retrieval indexing, API services, security gates, or domain-specific ingest logic.

## Development verification

From this directory:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
python -m compileall -q src tests
python -m pip wheel . --no-deps --no-build-isolation -w /tmp/brain-lab-core-wheel
```

`pyproject.toml` includes the intended Ruff config for environments that have `ruff` installed.
