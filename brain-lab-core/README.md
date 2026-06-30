# brain-lab-core

Generic AI Lab foundation contracts and package skeleton.

`brain_lab_core` is intentionally tool-neutral. It defines the stable data contracts that concrete tools can import for artifact references, evidence, jobs, tool/provider declarations, normalized errors, and schema extension declarations. Domain-specific tools own their own schemas and behavior; this package only provides shared contract shapes and package boundaries.

## Contract surface

- `ArtifactId`, `ArtifactRef`, `Checksum`, `FreshnessState`, `Provenance`
- `EvidenceRef`, `Citation`, `SourceSpan`
- `Job`, `StageRun`, `LifecycleState`, `RetryMetadata`
- `ToolManifest`, `ResourceProfile`
- `DocumentExtractionResult`, `PdfExtractionResult`, `DocumentPage`, `PdfPageResult`, `DocumentBlock`, `PdfBlock`, `DocumentProvenance`
- `ProviderSpec`, `ProviderCapability`
- `ErrorEnvelope`, `ContractDiagnostic`, `ContractValidationError`
- `SchemaExtensionPoint` for concrete tool-owned schemas

`brain_lab_core.registry` adds the first metadata registry surface:

- `ToolRegistry` registers `ToolManifest` declarations, validates package/CLI/container entrypoints, and indexes tools by capability plus input/output artifact type.
- `AdapterRegistry` registers `ProviderSpec` declarations and indexes providers by capability/version plus input/output artifact type.
- `fixture_tool_manifest()`, `fixture_provider_spec()`, and `register_fixture_tool()` provide a fake tool/provider seam for downstream integration tests.
- `video_intel_tool_manifest()` publishes the video-intel DH-94..DH-103 integration boundary as metadata-only discovery: capabilities, artifact types, optional secret declaration, sandbox/network requirements, dependency metadata, and stage-contract mapping without importing or executing video-intel.
- `mineru_document_extraction_manifest()` publishes the DH-228 document/PDF extraction boundary for the approved MinerU API service: `document.extract`, `pdf.extract`, `ocr.extract`, and output artifact types `document.extraction`, `pdf.extraction`, `document.markdown`, and `document.assets`, without importing or executing MinerU.

`brain_lab_core.orchestration` adds the generic local job-runner surface:

- `JobPlan`, `StagePlan`, and `ArtifactContract` validate explicit stage input/output contracts before execution.
- `JobRunner` persists job/stage lifecycle through the SQLite ledger, including `pending`, `running`, `completed`, `failed`, `stale`, `canceled`, and `skipped` stage states.
- `RetryPolicy` classifies retryable/non-retryable exact or prefix-wildcard error codes and honors normalized `ErrorEnvelope.retryable` flags.
- `StageContext` gives concrete handlers a safe way to register declared outputs and evidence refs, record progress/lease updates, and cooperatively cancel without deleting inspectable state/artifacts.
- `JobRunner.list_job_events(job_id)` returns append-only job/stage events from the ledger for API/MCP consumers.

`brain_lab_core.retrieval` adds the dependency-free Qdrant-style retrieval facade:

- `QdrantRetrievalFacade` manages vector collections over an injected Qdrant-like backend and embedding provider.
- `RetrievalChunk` defines the chunk payload shape with canonical `ArtifactRef`, `EvidenceRef` citations, freshness state, and flat namespaced tool fields such as `video.t_start`.
- `SearchFreshnessPolicy.CURRENT_ONLY` excludes stale/superseded artifacts by default; `INCLUDE_WITH_FLAGS` returns them with freshness flags for review/debug flows. `sqlite_artifact_freshness_resolver(ledger)` adapts the canonical SQLite ledger so search does not trust stale vector payload snapshots.
- `tool_filter={"video.t_start": {"gte": ...}}`-style filters target flat namespaced tool fields without embedding tool-specific schemas into the core package. The dependency-free in-memory backend supports equality, `in`, range (`gt`/`gte`/`lt`/`lte`), and `exists` operators.
- Collection config metadata binds the retrieval payload contract, embedding provider, vector dimension, and distance metric so incompatible same-dimensional embedders are rejected instead of silently reusing an index.
- `retrieval_embedding_provider_spec(...)` registers embedding providers through the generic `AdapterRegistry` without making concrete tools own vector-store code.

`brain_lab_core.api` adds a generic control plane for HTTP/OpenAPI and MCP surfaces:

- `FoundationControlPlane` exposes tool-neutral operations for registered tools, job create/poll/resume/cancel, job artifacts, artifact metadata/content, search, answer stubs with citations, health, and secret-safe config/status.
- `FoundationMCPTools` is a thin MCP-facing facade over the same control plane, so Hermes integrations do not bypass the canonical SQLite ledger or provenance contracts.
- `foundation_openapi_schema(...)` generates a deterministic OpenAPI document without importing a web framework.
- `create_fastapi_app(...)` lazily imports FastAPI only when callers install `brain-lab-core[api]`; importing `brain_lab_core.api` itself has no web dependency.
- `create_fixture_control_plane(...)` and `create_video_intel_fixture_control_plane(...)` build deterministic local fixtures that exercise the same API/MCP, ledger, artifact, evidence, and redaction paths concrete tools use.

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

## Document/PDF extraction contracts

DH-228 adds the foundation-owned extraction artifact shape that downstream PDF work should consume through the facade instead of coupling to MinerU internals.

```python
from brain_lab_core.contracts import (
    Checksum,
    DocumentBlock,
    DocumentBlockKind,
    DocumentExtractionResult,
    DocumentPage,
)

result = DocumentExtractionResult(
    document_id="sample",
    source_uri="file:///data/sample.pdf",
    content_hash=Checksum("sha256", "a" * 64),
    mime_type="application/pdf",
    pages=(
        DocumentPage(
            page_number=1,
            blocks=(DocumentBlock("p1-b001", DocumentBlockKind.TEXT, order=0, text="hello"),),
            markdown="hello",
        ),
    ),
)
loaded = DocumentExtractionResult.from_json(result.to_json())
assert loaded.pages[0].blocks[0].text == "hello"
```

The contracts can carry born-digital text, OCR text, tables, image/figure asset metadata, formulas, empty pages, partial page failures, and document-level diagnostics. `DocumentProvenance` records the source URI/path, source content hash, page number/span, block ID/span, extractor name/version, extraction timestamp, and diagnostics. `PdfExtractionResult`, `PdfPageResult`, and `PdfBlock` are PDF-specific contract aliases with their own contract headers for serialized artifacts.

DH-211 should use these artifacts as follows:

1. Submit a foundation job or API/MCP request against a tool that advertises `document.extract` / `pdf.extract`.
2. Read the resulting `document.extraction` JSON artifact as `DocumentExtractionResult` or the `pdf.extraction` JSON artifact as `PdfExtractionResult`.
3. Use `document.markdown` and `document.assets` artifact refs for human-readable text and extracted files.
4. Build downstream chunks/citations from page/block IDs, page spans, block spans, and diagnostics preserved in the extraction result.
5. Keep Obsidian vault writes and Qdrant indexing downstream of this contract; neither is part of the extraction artifact schema.

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

## Retrieval facade

Concrete tools such as video-intel create chunks and evidence refs, then call the generic facade rather than owning Qdrant payload or freshness logic:

```python
from brain_lab_core.retrieval import (
    DeterministicEmbeddingProvider,
    InMemoryQdrantBackend,
    QdrantRetrievalFacade,
    RetrievalChunk,
    sqlite_artifact_freshness_resolver,
)

facade = QdrantRetrievalFacade(
    vector_store=InMemoryQdrantBackend(),
    embedding_provider=DeterministicEmbeddingProvider(dimension=16),
)
facade.index_chunks(
    "video-intel.chunks",
    [
        RetrievalChunk(
            chunk_id="video-001:0001",
            text="The generic facade stores cited retrieval payloads.",
            artifact_ref=artifact_ref,
            evidence_refs=(evidence_ref,),
            tool_fields={"video.t_start": 0.0, "video.t_end": 4.2},
        )
    ],
    recreate=True,
)
hits = facade.search(
    "video-intel.chunks",
    "cited retrieval",
    limit=3,
    tool_filter={"video.t_start": {"gte": 0.0}, "video.t_end": {"lte": 10.0}},
    freshness_resolver=sqlite_artifact_freshness_resolver(ledger),
).hits
assert hits[0].evidence_refs[0].source_type == "transcript"
```

## Generic API/MCP control plane

The API layer is transport-neutral first: concrete HTTP or MCP servers inject registries, a `SQLiteArtifactLedger`, and job-plan factories, then route every operation through `FoundationControlPlane`.

```python
from pathlib import Path
from brain_lab_core.api import FoundationMCPTools, create_fixture_control_plane, foundation_openapi_schema

plane = create_fixture_control_plane(state_root=Path(".brain-lab-state"), config={"API_KEY": "secret"})
mcp = FoundationMCPTools(plane)

created = mcp.create_job({"tool_id": "fixture-tool", "job_id": "fixture-smoke"})
polled = mcp.get_job("fixture-smoke")
artifacts = mcp.list_job_artifacts("fixture-smoke")
schema = foundation_openapi_schema(plane)

assert created["job"]["state"] == "completed"
assert polled["events"]
assert artifacts["artifacts"][0]["producer_tool_id"] == "fixture-tool"
assert schema["paths"]["/jobs/{job_id}"]["get"]["operationId"] == "getJob"
assert plane.config_status()["config"]["API_KEY"] == "[REDACTED]"
```

The video-intel integration fixture exercises the same foundation seam without
requiring media downloads, ASR binaries, frame models, or Qdrant:

```python
from pathlib import Path
from brain_lab_core.api import FoundationMCPTools, create_video_intel_fixture_control_plane

plane = create_video_intel_fixture_control_plane(state_root=Path(".brain-lab-video-fixture"))
mcp = FoundationMCPTools(plane)
created = mcp.create_job({"tool_id": "video-intel", "job_id": "video-smoke"})
artifacts = mcp.list_job_artifacts("video-smoke")
search = mcp.search({"query": "evidence", "collection_name": "video-intel.reports"})

assert created["job"]["state"] == "completed"
assert {artifact["artifact_type"] for artifact in artifacts["artifacts"]} >= {
    "video.transcript",
    "retrieval.chunks",
    "report.markdown",
}
assert search["hits"][0]["artifact_ref"]["producer_tool_id"] == "video-intel"
```

FastAPI remains optional:

```python
from brain_lab_core.api import create_fastapi_app

app = create_fastapi_app(plane)  # requires: pip install brain-lab-core[api]
```

## Extension-point packages

The package also exposes importable namespaces for later foundation work:

- `brain_lab_core.registry` — tool/provider registry (metadata-only capability discovery)
- `brain_lab_core.orchestration` — job runner lifecycle, retries, resume/stale handling, leases, cancellation, and event stream
- `brain_lab_core.retrieval` — Qdrant-style retrieval facade with cited payloads and freshness-aware search
- `brain_lab_core.api` — generic control plane, MCP facade, OpenAPI schema, and optional FastAPI adapter
- `brain_lab_core.security` — security, secrets, and sandbox gates
- `brain_lab_core.observability` — structured events and diagnostics

Registry metadata discovery, the state ledger, generic job runner, retrieval facade, and generic API/MCP control plane are implemented. The remaining extension namespaces stay placeholders until their owning issues; this package still does not implement concrete Qdrant client wiring, production auth/sandbox gates, or domain-specific ingest/chunk generation logic.

## Development verification

From this directory:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
python -m compileall -q src tests
python -m pip wheel . --no-deps --no-build-isolation -w /tmp/brain-lab-core-wheel
```

`pyproject.toml` includes the intended Ruff config for environments that have `ruff` installed.
