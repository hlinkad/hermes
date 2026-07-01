# DH-199 AI Lab Foundation Architecture: RagFlow API + Foundation-Owned Qdrant Adapter + Obsidian Vault Materialization

Status: intended architecture, evidence-backed draft for external review  
Audience: GPT Pro / senior architecture review  
Primary project: Linear `AI Lab Foundation Framework`  
Primary epic/anchor: `DH-199`  
Decision anchor: `DH-237`  
Implementation issues: `DH-236`, `DH-238`, `DH-233`, `DH-235`, `DH-231`, `DH-204`  
Repository inspected: `/workspace/hermes-related-code/brain-lab-core`  
RagFlow source inspected: `/workspace/tmp/ragflow-inspect`  
Last updated: 2026-07-01

## 1. Executive summary

The intended architecture is a local-first, foundation-orchestrated AI Lab framework where Hermes reaches concrete tools through one stable `brain_lab_core` control plane. For the RagFlow/Qdrant/Obsidian lane, the system must integrate **two external method surfaces** at the foundation layer:

1. **RagFlow HTTP/REST API** for dataset/document ingestion, parsing/ingestion status, chunk/list/retrieval surfaces, and RagFlow-specific workflow behavior.
2. **Qdrant HTTP/REST API** for the required vector/index backend through a **foundation-owned Qdrant adapter**.

The critical corrected decision is:

```text
We are not extending or forking the RagFlow repository.
We are not implementing DOC_ENGINE=qdrant inside upstream RagFlow as the default plan.
We are building a foundation-owned Qdrant adapter in/around brain-lab-core.
FoundationControlPlane orchestrates RagFlowAdapter + QdrantAdapter + ObsidianAdapter.
```

Canonical first-pass shape:

```text
Hermes
  -> MCP
    -> FoundationControlPlane / brain_lab_core facade
      -> RAGWorkflowPort
        -> RagFlowAdapter
          -> RagFlow HTTP/REST API
      -> QdrantAdapter
        -> Qdrant HTTP/REST API
      -> ObsidianAdapter / KnowledgeVault materialization
        -> Markdown/Obsidian vault
```

Short form:

```text
FoundationControlPlane
  -> RagFlowAdapter -> RagFlow API
  -> QdrantAdapter  -> Qdrant API
  -> ObsidianAdapter -> vault
```

Data path, stated explicitly:

```text
source document/PDF/book/web input
  -> FoundationControlPlane job
  -> RagFlowAdapter calls RagFlow API for dataset/document ingest + parse/retrieval/chunk surfaces
  -> foundation normalizes RagFlow-visible IDs, chunks, text, metadata, provenance, embeddings/embedding-inputs as available
  -> QdrantAdapter creates/upserts/searches Qdrant collections and points
  -> ObsidianAdapter materializes safe markdown/vault notes from the same canonical provenance
  -> query path returns Qdrant-backed cited/provenanced retrieval results
```

The architecture is intentionally **foundation-owned**, **Qdrant-required**, and **RagFlow-repository-neutral**:

- RagFlow is an external tool/service reached through HTTP/REST.
- Qdrant is a required backend reached through the foundation-owned adapter.
- Obsidian vault writes are materialization outputs from the foundation workflow, not a competing retrieval/indexing pipeline.
- SQLite + filesystem artifact state in `brain_lab_core` remain canonical for foundation jobs/artifacts; Qdrant stores vectors and retrieval payloads, not the source-of-truth ledger.

This partially aligns with the retrieved architecture guidance from `Guide To Context Engineering` pp. 19-21: production agents need both historical depth and current operational context, with a runtime that captures changes, transforms/enriches them into structured facts, and serves low-latency context. In this design, the foundation ledger preserves durable history/provenance, RagFlow contributes ingestion/RAG workflow capability, Qdrant serves low-latency vector context, and Obsidian materializes human-inspectable knowledge artifacts. MVP currentness is provided by reruns, freshness state, and reconciliation; it is **not** yet a Kafka/Flink-style streaming real-time context engine.

## 2. Non-negotiable decisions

### 2.1 Required decisions

1. **Qdrant is required.**
   - The accepted production path cannot silently use Elasticsearch, Infinity, OpenSearch, OceanBase, SeekDB, or any other backend in place of Qdrant.
   - Non-Qdrant backends may appear only as facts about upstream RagFlow internals or as explicit non-production/diagnostic context.

2. **Qdrant integration is foundation-owned.**
   - The Qdrant adapter belongs to `brain_lab_core` / the AI Lab Foundation layer.
   - It is not implemented by modifying upstream RagFlow as the default architecture.

3. **RagFlow stays external.**
   - `RagFlowAdapter` calls RagFlow over its published/usable API surface.
   - The architecture must prefer HTTP/REST integration seams before any invasive repository changes.

4. **The integration is between RagFlow methods and Qdrant methods.**
   - RagFlow API output must be normalized by the foundation.
   - Qdrant API writes/searches must happen through a foundation-owned adapter.

5. **Obsidian is materialization, not an alternate index.**
   - `ObsidianAdapter`, `MarkdownVaultAdapter`, or `KnowledgeVaultPort` writes markdown/vault artifacts from canonical provenance.
   - It does not replace Qdrant retrieval.
   - It should delegate to `obsidian-intelligence-core` where practical, per prior architecture decision.

6. **MCP stays thin.**
   - MCP exposes/forwards operations to `FoundationControlPlane`.
   - MCP must not bypass the canonical ledger, provenance, or redaction paths.

7. **No generic service-layer detour.**
   - Do not introduce `IngestionService` or `RetrievalService` as architecture layers.
   - Keep the pattern: facade/control-plane -> capability port -> concrete adapter.

8. **No vague universal execute adapter.**
   - Avoid a single `execute(any)` abstraction.
   - Use explicit adapter methods and typed contracts for ingestion, chunk normalization, Qdrant upsert/search, and vault materialization.

### 2.2 Rejected alternatives

Rejected:

```text
RagFlow repository fork/extension
  -> implement DOC_ENGINE=qdrant in upstream RagFlow
  -> call that the accepted architecture
```

Rejected:

```text
RagFlow internal Elasticsearch/Infinity/OpenSearch/OceanBase/SeekDB backend
  -> accepted as equivalent to Qdrant
```

Rejected:

```text
MCP
  -> direct tool calls to RagFlow/Qdrant/Obsidian
  -> no FoundationControlPlane ledger/provenance/redaction boundary
```

Rejected:

```text
RagFlow pipeline
  -> Obsidian notes only
  -> search Obsidian as primary retrieval backend
```

Accepted:

```text
FoundationControlPlane
  -> RagFlowAdapter -> RagFlow HTTP/REST API
  -> QdrantAdapter -> Qdrant HTTP/REST API
  -> ObsidianAdapter -> vault materialization
```

## 3. Evidence base

This document distinguishes confirmed facts from target architecture and open assumptions.

### 3.1 Linear/project evidence

Linear project and issue context was inspected via Linear MCP tools:

- `AI Lab Foundation Framework` project.
- `DH-199`: architecture consolidation / generic foundation anchor.
- `DH-235`: consolidate generic architecture and RagFlow/Qdrant/Obsidian adapter vocabulary.
- `DH-237`: locked decision for RagFlow + foundation-owned Qdrant adapter + Obsidian architecture.
- `DH-236`: foundation-owned Qdrant adapter + HTTP/REST integration with RagFlow.
- `DH-238`: Obsidian/vault materialization adapter.
- `DH-233`: end-to-end smoke proof for RagFlow API + Qdrant adapter + Obsidian vault path.
- `DH-231` and `DH-204`: prior/related Qdrant indexing/retrieval/evidence work to align with or reuse.

The remembered corrective decision from the prior session is explicit: do not extend/fork the RagFlow repository; Qdrant remains required; integration is owned by the foundation.

### 3.2 Repository facts: `brain-lab-core`

Inspected repository: `/workspace/hermes-related-code/brain-lab-core`.

Repository branch/status at inspection:

```text
branch: main
HEAD short SHA: 5522230
local branch: ahead of origin/main by 16 commits
current worktree after this document write: untracked docs/architecture artifact present
```

Package facts from `pyproject.toml`:

- Package name: `brain-lab-core`.
- Python requirement: `>=3.11`.
- Runtime dependencies: `[]`.
- Optional dependency group: `api = ["fastapi"]`.
- Ruff configured with line length 100, target `py311`, lint select `E`, `F`, `I`, `W`, `UP`, `B`, ignore `E501`.

Current source inventory:

- `src/brain_lab_core/contracts/*`
- `src/brain_lab_core/state/*`
- `src/brain_lab_core/orchestration/*`
- `src/brain_lab_core/registry/*`
- `src/brain_lab_core/retrieval/qdrant.py`
- `src/brain_lab_core/api/*`
- `src/brain_lab_core/security/*`
- `src/brain_lab_core/observability/*`
- Tests under `tests/` for contracts, state ledger, job runner, registry, retrieval, API control plane, document extraction contracts, security/observability.

Current README states these implemented surfaces:

- Generic contracts: artifacts, evidence, jobs, tools, providers, errors, document extraction, extension points.
- Registry: `ToolRegistry`, `AdapterRegistry`, fixture manifests, `video_intel_tool_manifest`, `mineru_document_extraction_manifest`.
- Orchestration: `JobPlan`, `StagePlan`, `ArtifactContract`, `JobRunner`, `RetryPolicy`, `StageContext`.
- State: `SQLiteArtifactLedger`, filesystem artifact registration, checksums, freshness states, schema migrations.
- Retrieval: dependency-free Qdrant-style facade with `QdrantRetrievalFacade`, `RetrievalChunk`, `SearchFreshnessPolicy`, tool filters, collection metadata binding.
- API: `FoundationControlPlane`, `FoundationMCPTools`, deterministic OpenAPI, optional FastAPI.

Important current limitation in README:

> The package implements generic registry/state/job/retrieval/API surfaces, but does not yet implement concrete Qdrant client wiring, production auth/sandbox gates, or domain-specific ingest/chunk generation logic.

This means the present code contains a **Qdrant-style contract/facade**, but the production Qdrant HTTP adapter is still target work for `DH-236`.

### 3.3 Current `brain_lab_core` retrieval facts

`src/brain_lab_core/retrieval/qdrant.py` currently defines:

- `EmbeddingProvider` protocol:
  - `provider_id`
  - `dimension`
  - `embed_texts(texts) -> tuple[tuple[float, ...], ...]`
- `VectorStoreBackend` protocol:
  - `ensure_collection(collection_name, vector_size, distance="cosine", metadata=None, recreate=False)`
  - `count_points(collection_name, payload_filter=None)`
  - `upsert_points(collection_name, points)`
  - `search_points(collection_name, query_vector, limit, payload_filter=None)`
- `QdrantPoint` and `QdrantScoredPoint` as dependency-free point/search-result representations.
- `RetrievalChunk` payload contract with:
  - `chunk_id`
  - `text`
  - `artifact_ref`
  - `evidence_refs`
  - `tool_fields`
  - `metadata`
  - deterministic JSON/contract headers.
- `RetrievalIndexResult`, `RetrievalHit`, `RetrievalSearchResult`.
- `DeterministicEmbeddingProvider` for tests/fixtures.
- `InMemoryQdrantBackend` for tests/local fixtures.
- `QdrantRetrievalFacade` that indexes chunks and performs vector search over an injected backend.
- `retrieval_embedding_provider_spec(...)` for `AdapterRegistry` registration.
- `sqlite_artifact_freshness_resolver(ledger)` to resolve artifact freshness from the canonical ledger during search.

`RetrievalChunk.to_payload()` writes these canonical payload fields:

- `contract_type`
- `schema_version`
- `chunk_id`
- `text`
- `artifact_id`
- `artifact_freshness`
- `artifact_ref`
- `evidence_refs`
- `tool_fields`
- `metadata`
- flat namespaced tool fields copied into top-level payload.

Tool-specific payload keys must be namespaced with a dot, e.g. `video.t_start`; keys colliding with reserved retrieval payload fields are rejected.

`QdrantRetrievalFacade.collection_metadata()` binds collection reuse to:

- `distance`
- `embedding_dimension`
- `embedding_provider_id`
- `embedding_provider_version`
- `payload_contract_schema_version`
- `payload_contract_type`

This prevents accidental reuse of a collection with the wrong embedding provider or payload contract.

Current supported distance metric in the dependency-free facade: `cosine`.

Current in-memory filter support:

- equality through direct expected values or `{ "eq": value }`
- existence: `{ "exists": true|false }`
- membership: `{ "in": [...] }`
- numeric comparisons: `gt`, `gte`, `lt`, `lte`

Current freshness behavior:

- `SearchFreshnessPolicy.CURRENT_ONLY` excludes stale/superseded artifacts by default.
- `SearchFreshnessPolicy.INCLUDE_WITH_FLAGS` returns them with freshness flags.
- With a `freshness_resolver`, search uses canonical ledger state instead of trusting stale vector payload snapshots.
- Missing canonical artifacts resolve to `unknown` so orphaned vector payloads are not treated as decision-grade evidence.

### 3.4 Current `brain_lab_core` state/ledger facts

`SQLiteArtifactLedger` is the canonical local source of truth for jobs, stages, artifacts, and evidence.

Confirmed behavior from code:

- SQLite is canonical; filesystem is a measured payload read model.
- `register_artifact_from_file(...)` records:
  - artifact ID
  - artifact type/schema version
  - filesystem path/URI
  - checksum
  - size
  - producer tool/stage
  - input artifact IDs
  - config fingerprint
  - provenance
  - metadata
  - current freshness
- Duplicate registration of the same canonical payload is idempotent.
- Reusing the same artifact ID for a different canonical payload raises `ArtifactConflictError`.
- Changed producer/stage input/config derivations can mark previous derivations stale.
- Freshness values include `current`, `stale`, `superseded`, `unknown` via `FreshnessState`.
- Events are append-only ledger records.
- Foreign keys and WAL are enabled.

This matters because Qdrant must not become the authority for artifact lifecycle. Qdrant can hold payload snapshots and vector search state; the ledger decides canonical freshness/provenance.

### 3.5 Current `brain_lab_core` orchestration facts

`JobPlan` and `StagePlan` provide ordered local job execution with explicit artifact dependencies.

Confirmed behavior:

- A `JobPlan` validates at construction time that each stage input is either a job input or produced by an earlier stage.
- Duplicate stage IDs and duplicate output artifacts are rejected.
- `StagePlan.output_contract_for(...)` rejects undeclared output artifacts.
- `StageContext.register_output(...)` delegates to the SQLite ledger and applies redaction policy.
- `StageContext.register_evidence_ref(...)` persists evidence refs through the ledger and applies redaction.
- `StageContext.record_progress(...)` writes running stage state/progress and stage events.
- Cancellation is cooperative through `JobCancellationRequested`.
- `JobRunner` is the local-first runner backed by `SQLiteArtifactLedger`.

Architecture consequence: RagFlow/Qdrant/Obsidian integration should be expressed as foundation stages in a `JobPlan`, not as ad-hoc tool calls that bypass the ledger.

### 3.6 Current `brain_lab_core` API/MCP facts

`FoundationControlPlane` is a tool-neutral API/MCP boundary.

Confirmed constructor dependencies:

- `ToolRegistry`
- optional `AdapterRegistry`
- `SQLiteArtifactLedger`
- optional `JobRunner`
- config mapping
- job plan factories keyed by tool ID
- optional search handlers keyed by collection
- optional answer handler

Confirmed public operations:

- `healthz()`
- `config_status()`
- `list_tools()`
- `create_job(payload)`
- `get_job(job_id)`
- `resume_job(job_id)`
- `cancel_job(job_id)`
- `list_job_artifacts(job_id)`
- `get_artifact(artifact_id, include_content=False)`
- `search(payload)`
- `answer(payload)`
- `openapi_schema()`

`FoundationMCPTools` is intentionally thin and forwards operations to `FoundationControlPlane`.

Generated OpenAPI paths include:

- `GET /tools`
- `POST /jobs`
- `GET /jobs/{job_id}`
- `POST /jobs/{job_id}/resume`
- `POST /jobs/{job_id}/cancel`
- `GET /jobs/{job_id}/artifacts`
- `GET /artifacts/{artifact_id}`
- `POST /search`
- `POST /answers`
- `GET /healthz`
- `GET /config`

Architecture consequence: external HTTP and MCP surfaces should converge here; adapters must not implement a parallel control plane.

### 3.7 RagFlow repository facts

Inspected local RagFlow copy: `/workspace/tmp/ragflow-inspect`.

Confirmed from `common/settings.py`:

- `DOC_ENGINE = os.environ.get("DOC_ENGINE", "elasticsearch").strip()`.
- Supported branches instantiate `docStoreConn` for:
  - `elasticsearch` -> `rag.utils.es_conn.ESConnection()`
  - `infinity` -> `rag.utils.infinity_conn.InfinityConnection()`
  - `opensearch` -> `rag.utils.opensearch_conn.OSConnection()`
  - `oceanbase` -> `rag.utils.ob_conn.OBConnection()`
  - `seekdb` -> `rag.utils.ob_conn.OBConnection()`
- Otherwise RagFlow raises `Exception(f"Not supported doc engine: {DOC_ENGINE}")`.

Search result from the local inspected RagFlow source:

- No active Python `DOC_ENGINE` branch/config/implementation for Qdrant was found in RagFlow's runtime settings or connection code.
- `internal/engine/README.md:179` mentions Qdrant only as an example of a future/new document engine extension, not as an implemented active backend in the inspected runtime path.
- The inspected RagFlow checkout is `https://github.com/infiniflow/ragflow.git`, branch `main`, commit `81cfcdf`.
- This supports the corrective conclusion: unchanged RagFlow does not currently expose native active Qdrant integration in the inspected source, so Qdrant must be integrated at the foundation boundary.

Operational implication:

- Running RagFlow unchanged still requires one of RagFlow's supported internal `DOC_ENGINE` backends for RagFlow's own parsing/indexing/retrieval internals.
- That backend is an upstream RagFlow runtime dependency only; it is **not** accepted as the AI Lab foundation retrieval backend.
- MVP likely performs duplicate indexing/embedding work: RagFlow's internal backend for RagFlow operation plus foundation-owned Qdrant for the accepted retrieval surface.

Confirmed from `common/doc_store/doc_store_base.py`:

- RagFlow has a `DocStoreConnection` abstraction with methods such as:
  - `db_type()`
  - `health()`
  - `create_idx(...)`
  - `delete_idx(...)`
  - `index_exist(...)`
  - `search(...)`
  - `get(...)`
  - `insert(...)`
  - `update(...)`
  - `delete(...)`
  - helper methods for totals, doc IDs, fields, highlights, aggregation
  - `sql(...)`
- It defines search expressions including `MatchTextExpr`, `MatchDenseExpr`, `MatchSparseExpr`, `MatchTensorExpr`, and `FusionExpr`.

This confirms RagFlow has its own internal doc engine abstraction, but the accepted architecture does **not** extend that abstraction as the default plan.

### 3.8 RagFlow HTTP API facts

Confirmed from `/workspace/tmp/ragflow-inspect/docs/references/http_api_reference.md`:

Dataset management:

- `POST /api/v1/datasets` creates a dataset.
- Request fields include `name`, `avatar`, `description`, `embedding_model`, `permission`, `chunk_method`, `parser_config`, `parse_type`, `pipeline_id`.
- `chunk_method` is mutually exclusive with `parse_type` and `pipeline_id`.
- `GET /api/v1/datasets?...` lists datasets and can include parsing status counts.
- `PUT /api/v1/datasets/{dataset_id}` updates dataset configuration.
- `DELETE /api/v1/datasets` deletes datasets.

Document management:

- `POST /api/v1/datasets/{dataset_id}/documents` uploads documents.
- Supports `type=local`, `type=web`, `type=empty`.
- Local upload uses multipart field `file=@...`.
- Web mode uses form fields `name` and `url`.
- Empty mode uses JSON body with `name`.
- Success response includes document IDs, names, dataset ID, parser config, run status, size, etc.
- `GET /api/v1/datasets/{dataset_id}/documents?...` lists documents, with filters for IDs, names, suffixes, run status, timestamps, and metadata conditions.

Parse/ingest:

- `POST /api/v1/datasets/{dataset_id}/chunks` parses documents for datasets using the built-in chunking pipeline.
- Request body: `document_ids`.
- `POST /api/v1/documents/ingest` starts/cancels/reruns ingestion for documents in datasets configured with an ingestion pipeline.
- Request body: `doc_ids`, `run`, `delete`; `run="1"` starts ingestion and `run="2"` cancels ingestion.
- `DELETE /api/v1/datasets/{dataset_id}/chunks` stops parsing specified documents.

Chunk management:

- `POST /api/v1/datasets/{dataset_id}/documents/{document_id}/chunks` adds a chunk.
- Body can include `content`, `important_keywords`, `tag_kwd`, `questions`, `image_base64`.
- `GET /api/v1/datasets/{dataset_id}/documents/{document_id}/chunks?...` lists chunks.
- List response includes fields such as `available`, `content`, `docnm_kwd`, `document_id`, `id`, `image_id`, `important_keywords`, `tag_kwd`, `positions`.
- `GET /api/v1/datasets/{dataset_id}/documents/{document_id}/chunks/{chunk_id}` retrieves a chunk, but docs note runtime fields such as vector/token fields are not returned.
- `DELETE /api/v1/datasets/{dataset_id}/documents/{document_id}/chunks` deletes chunks by IDs or `delete_all`.
- `PATCH /api/v1/datasets/{dataset_id}/documents/{document_id}/chunks/{chunk_id}` updates chunks; the older `PUT` update form is deprecated in the inspected RagFlow API reference.

Retrieval:

- `POST /api/v1/retrieval` retrieves chunks from specified datasets.
- Request fields include `question`, `dataset_ids`, `document_ids`, `page`, `page_size`, `similarity_threshold`, `vector_similarity_weight`, `top_k`, `rerank_id`, `keyword`, `highlight`, `cross_languages`, `metadata_condition`, `use_kg`, `toc_enhance`.
- Retrieval response chunks include fields such as:
  - `content`
  - `content_ltks`
  - `document_id`
  - `document_keyword`
  - `highlight`
  - `id`
  - `image_id`
  - `important_keywords`
  - `tag_kwd`
  - `kb_id`
  - `positions`
  - `similarity`
  - `term_similarity`
  - `vector_similarity`
- Response includes `doc_aggs` and `total`.

Health:

- `GET /api/v1/system/healthz` checks database, Redis, document engine, object storage, and overall status.

Architecture consequence: The foundation can use RagFlow's documented API to create/list datasets, upload/list documents, trigger parsing/ingestion, list chunks, retrieve chunks, and check health. Missing/insufficient API fields must be handled at the foundation seam by explicit normalization rules or documented MVP limits, not by forking RagFlow.

### 3.9 Qdrant HTTP API facts

Fetched official Qdrant API markdown pages from the concrete endpoint URLs listed in Section 3.11.

Confirmed endpoints:

- `PUT /collections/{collection_name}` creates a collection.
  - Request body uses `CreateCollection`.
  - Distance enum includes `Cosine`, `Euclid`, `Dot`, `Manhattan`.
  - Collection config supports dense vectors and sparse vectors.
- `GET /collections/{collection_name}` retrieves collection details and is required for configuration validation.
- `DELETE /collections/{collection_name}` deletes a collection.
- `PUT /collections/{collection_name}/points` upserts points.
  - Description: insert + update action; existing point ID is overwritten.
  - Qdrant point IDs are integer `uint64` or string `uuid`, not arbitrary strings.
  - Write calls expose `wait`, `ordering`, and `timeout` controls; live smokes should use `wait=true` or otherwise reconcile operation completion before count/query assertions.
- `POST /collections/{collection_name}/points/count` counts points matching a filter.
- `POST /collections/{collection_name}/points/delete` deletes points.
- `POST /collections/{collection_name}/points/scroll` scrolls all points page-by-page and supports filters/sorting.
- `POST /collections/{collection_name}/points/query` universally queries points; official description says it covers search, recommend, discover, filters, and enables hybrid and multi-stage queries.
- `PUT /collections/{collection_name}/index` creates a payload index for a field.
- `GET /healthz` checks individual Qdrant instance health.

Architecture consequence: A foundation-owned Qdrant HTTP adapter can be built directly against official REST endpoints without needing the `qdrant-client` Python dependency in the core package. A higher-level client can be optional later, but the required contract should map cleanly to REST.

### 3.10 Prior DH-199 architecture draft facts

Existing file `/workspace/dh199/dh199_generic_foundation_architecture.md` already states the generic foundation intent:

- `brain_lab_core` is the generic AI Lab foundation layer.
- Concrete tools such as video-intel integrate with the foundation instead of rebuilding generic facades, job runners, artifact ledgers, provider registries, or retrieval layers.
- Foundation owns common contracts, artifact/provenance handling, job/state/resume semantics, retrieval/evidence handling, Hermes/API/MCP control plane, security, and observability hooks.
- SQLite plus filesystem artifact manifests are canonical runtime state.
- Qdrant is a retrieval service boundary, not the source of truth.
- Concrete tools may run as packages, CLIs, workers, or Docker containers, but must register contracts and emit artifacts through the foundation.

This document extends and corrects that architecture for the RagFlow/Qdrant/Obsidian lane.

### 3.11 Source citation index

Primary local code/source citations used for factual claims:

- `pyproject.toml:6`, `:10`, `:13`, `:22`, `:34-35` — package name, Python requirement, runtime dependencies, optional FastAPI extra, Ruff config.
- `README.md:34-48` — Qdrant-style retrieval facade, freshness policies, collection metadata binding, `FoundationControlPlane`, `FoundationMCPTools`, OpenAPI/FastAPI behavior.
- `README.md:241-252` — extension namespaces and explicit limitation that concrete Qdrant client wiring, production auth/sandbox gates, and domain-specific ingest/chunk generation are not implemented yet.
- `src/brain_lab_core/retrieval/qdrant.py:61-88` — `SearchFreshnessPolicy`, `EmbeddingProvider`, `VectorStoreBackend` protocols.
- `src/brain_lab_core/retrieval/qdrant.py:145-214` — `RetrievalChunk` fields and payload serialization.
- `src/brain_lab_core/retrieval/qdrant.py:446-552` — dependency-free in-memory Qdrant-like backend and filter behavior.
- `src/brain_lab_core/retrieval/qdrant.py:553-714` — `QdrantRetrievalFacade`, collection metadata binding, index/search methods.
- `src/brain_lab_core/retrieval/qdrant.py:715-780` — SQLite-backed artifact freshness resolver.
- `src/brain_lab_core/api/control_plane.py:128-373` — `FoundationControlPlane` operations including health, config status, job creation, search, answers, and OpenAPI schema.
- `src/brain_lab_core/api/mcp_tools.py:15-64` — `FoundationMCPTools` as thin MCP-facing forwarding facade.
- `src/brain_lab_core/state/sqlite_store.py:57-180` and related methods — `SQLiteArtifactLedger`, file artifact registration, PRAGMA foreign keys, ledger-backed state.
- `src/brain_lab_core/orchestration/job_runner.py:74-233` — `StageContext`, output/evidence registration, `JobRunner` setup.
- `src/brain_lab_core/orchestration/planner.py:124-207` — `StagePlan`, `JobPlan`, stage input/output validation.

Primary RagFlow citations:

- `/workspace/tmp/ragflow-inspect/common/settings.py:300-325` — `DOC_ENGINE` env var and supported document engines: Elasticsearch, Infinity, OpenSearch, OceanBase, SeekDB; unsupported engine raises.
- `/workspace/tmp/ragflow-inspect/common/doc_store/doc_store_base.py:70-120` — dense/sparse/fusion search expression classes.
- `/workspace/tmp/ragflow-inspect/common/doc_store/doc_store_base.py:143-260` — `DocStoreConnection` abstract methods including index, search, insert/update/delete.
- `/workspace/tmp/ragflow-inspect/docs/references/http_api_reference.md:474-589` — create dataset endpoint and dataset fields.
- `/workspace/tmp/ragflow-inspect/docs/references/http_api_reference.md:889-979` — list datasets endpoint and parsing status counts.
- `/workspace/tmp/ragflow-inspect/docs/references/http_api_reference.md:1404-1523` — upload documents endpoint and local/web/empty modes.
- `/workspace/tmp/ragflow-inspect/docs/references/http_api_reference.md:1951-2110` — parse and ingest document endpoints.
- `/workspace/tmp/ragflow-inspect/docs/references/http_api_reference.md:2223-2538` — chunk list/retrieve/update/delete surfaces, including current `PATCH` chunk update and deprecated `PUT` update form.
- `/workspace/tmp/ragflow-inspect/docs/references/http_api_reference.md:2790-2949` — retrieval endpoint request and response fields.
- `/workspace/tmp/ragflow-inspect/docs/references/http_api_reference.md:6843-6932` — system health endpoint.

Primary external/API citations:

- `https://api.qdrant.tech/api-reference/collections/get-collection.md` — `GET /collections/{collection_name}` collection detail/config retrieval.
- `https://api.qdrant.tech/api-reference/collections/create-collection.md` — `PUT /collections/{collection_name}`, distance enum, collection config including vector/sparse vector support.
- `https://api.qdrant.tech/api-reference/points/upsert-points.md` — `PUT /collections/{collection_name}/points`, insert/update upsert semantics, Qdrant-compatible point IDs, write wait/ordering/timeout controls.
- `https://api.qdrant.tech/api-reference/points/count-points.md` — `POST /collections/{collection_name}/points/count` filtered point counts.
- `https://api.qdrant.tech/api-reference/search/query-points.md` — `POST /collections/{collection_name}/points/query`, universal query endpoint including filters, hybrid and multi-stage query capability.
- `https://api.qdrant.tech/api-reference/indexes/create-field-index.md` — `PUT /collections/{collection_name}/index` payload index creation.
- `https://api.qdrant.tech/api-reference/points/scroll-points.md` — `POST /collections/{collection_name}/points/scroll` page-by-page point scan.
- `https://api.qdrant.tech/api-reference/points/delete-points.md` — `POST /collections/{collection_name}/points/delete` point deletion.
- `https://api.qdrant.tech/api-reference/service/healthz.md` — `GET /healthz` Qdrant health check.

Linear/session citations:

- Linear MCP retrieval in this session confirmed project `AI Lab Foundation Framework` and issues `DH-199`, `DH-235`, `DH-237`, `DH-236`, `DH-238`, `DH-233`, `DH-231`, and `DH-204`.
- Recovered prior-session context established the corrected decision vocabulary: `FoundationControlPlane -> RAGWorkflowPort -> RagFlowAdapter -> RagFlow HTTP API`, plus foundation-owned `QdrantAdapter -> Qdrant HTTP API`, plus `ObsidianAdapter` for vault materialization.
- Hermes Brain retrieved `Guide To Context Engineering`, pp. 19-21, for the continuous-context requirement: historical depth, real-time/current updates, stream processing/enrichment, and low-latency context serving.

### 3.12 Fact classification

Confirmed facts:

- `brain_lab_core` currently has generic contracts, registry, orchestration, ledger, retrieval facade, API/MCP surfaces, and tests.
- The repository currently lacks production `RagFlowAdapter`, production Qdrant HTTP adapter, and Obsidian/vault adapter implementations.
- The inspected RagFlow source supports `DOC_ENGINE` values for Elasticsearch, Infinity, OpenSearch, OceanBase, and SeekDB, not Qdrant, in the active runtime settings path.
- Running unchanged RagFlow still requires one supported internal RagFlow document engine; that upstream dependency does not satisfy the foundation requirement for Qdrant-backed retrieval.
- RagFlow exposes documented HTTP endpoints for datasets, documents, parse/ingest, chunks, retrieval, and health.
- Qdrant exposes official REST endpoints for collection creation/deletion/details, point upsert/delete/count/scroll/query, payload indexes, and health.
- Qdrant point IDs accepted by the REST schema are `uint64` integers or UUID strings; arbitrary SHA-256 hex strings must be stored in payload, not used directly as point IDs.

Architecture decisions:

- Qdrant is required and cannot be replaced by RagFlow's current non-Qdrant document engines.
- Qdrant integration belongs at the foundation layer, not as a default upstream RagFlow fork.
- Obsidian is a materialization surface, not the primary retrieval backend.
- `FoundationControlPlane` remains the orchestration boundary for MCP/HTTP users.

Open assumptions to validate during implementation:

- RagFlow list-chunks output is sufficient to reconstruct all chunk text needed for foundation-owned Qdrant embeddings.
- Foundation-owned embeddings are acceptable even though RagFlow may already embed internally.
- Dense-first Qdrant retrieval is an acceptable MVP before sparse/hybrid implementation.
- Qdrant payload text size remains acceptable for the initial corpus; larger corpora may need bounded text plus ledger lookup.
- `obsidian-intelligence-core` integration is available and worth delegating to; if its repo/API is unavailable during DH-238, implement a direct minimal `MarkdownVaultAdapter` fallback with the same safety/path/provenance contracts.

## 4. Architecture goals

### 4.1 Product/system goals

The architecture must support:

- Hermes-driven knowledge work over documents, PDFs, books, web pages, videos, and future tools.
- Local-first operation with durable state and provenance.
- Foundation-level orchestration of concrete tools.
- Vector retrieval through Qdrant with citation-quality payloads.
- Human-readable Obsidian/Markdown materialization for review and durable notes.
- MCP and optional HTTP access without duplicating orchestration logic.
- Testable smoke paths using disposable state, disposable Qdrant collections, and temp vaults.

### 4.2 Context-engineering goals

From the retrieved `Guide To Context Engineering` pp. 19-21, reliable AI systems need:

- historical depth;
- current updates;
- stream/processing style enrichment;
- low-latency context serving;
- governed, trustworthy, derived data.

The foundation maps those requirements as follows:

- Historical depth: `SQLiteArtifactLedger`, filesystem artifacts, Obsidian materialization, provenance/evidence refs.
- Current updates in MVP: explicit job/stage reruns, freshness states, stale/superseded marking, idempotent Qdrant upserts, and reconciliation; not continuous event streaming yet.
- Enrichment: RagFlow ingestion/chunk/retrieval surfaces plus foundation normalization.
- Low-latency serving: Qdrant collection/point/query APIs.
- Governance/trust: artifact checksums, evidence refs, citations, redaction, config fingerprints, explicit environment gating.

## 5. Current-state vs target-state matrix

### 5.1 Already implemented in `brain_lab_core`

Implemented today:

- Frozen dataclass contracts with deterministic JSON support.
- Artifact/evidence/job/provider/tool/document extraction contracts.
- SQLite artifact ledger with checksum/provenance/freshness/config fingerprint handling.
- Generic local job runner with explicit stage plans and output contracts.
- Tool and adapter registries.
- Dependency-free Qdrant-style retrieval contracts/facade.
- In-memory Qdrant-like backend for tests/fixtures.
- Thin MCP wrapper over `FoundationControlPlane`.
- Deterministic OpenAPI schema generation.
- Optional FastAPI adapter.
- Secret redaction policies and security/observability contracts.

### 5.2 Not yet implemented / target work

Not implemented yet, based on inspected source and README:

- Production `RagFlowAdapter`.
- Production `QdrantAdapter` over Qdrant HTTP/REST.
- Production `ObsidianAdapter` / `KnowledgeVaultPort` implementation.
- Production auth/sandbox enforcement beyond policy contracts/redaction helpers.
- Concrete RagFlow->Qdrant normalization stages.
- Live Qdrant smoke with disposable collections.
- Live RagFlow smoke.
- Temp vault materialization smoke.
- Unified end-to-end smoke proving RagFlow API + Qdrant API + Obsidian vault path.

### 5.3 Crucial interpretation

The current `QdrantRetrievalFacade` is a useful foundation contract, but it is not enough for the intended architecture because:

- It depends on an injected `VectorStoreBackend` protocol.
- The only concrete backend in the repository is `InMemoryQdrantBackend`.
- There is no Qdrant HTTP client/adapter in runtime dependencies.
- It does not call RagFlow.
- It does not materialize Obsidian notes.

Therefore `DH-236` must implement the concrete Qdrant adapter and the foundation integration seam with RagFlow outputs.

## 6. Component model

### 6.1 Hermes

Role:

- User-facing AI agent/runtime.
- Calls MCP tools or HTTP endpoints exposed by the foundation service.
- Does not directly own RagFlow/Qdrant/Obsidian orchestration.

Responsibilities:

- Submit jobs/queries.
- Inspect job status/artifacts/results.
- Receive cited answers and evidence paths.

Non-responsibilities:

- No direct Qdrant schema decisions.
- No direct RagFlow lifecycle management outside the foundation adapter.
- No direct vault writes except through the foundation-controlled tool.

### 6.2 MCP boundary

Role:

- Thin tool protocol boundary between Hermes and the foundation.

Required behavior:

- Expose `FoundationMCPTools` or equivalent generated tool methods.
- Forward calls to `FoundationControlPlane`.
- Preserve redaction and provenance behavior.

Non-responsibilities:

- No independent job runner.
- No independent vector-store client.
- No independent vault materializer.

### 6.3 FoundationControlPlane

Role:

- Canonical orchestration facade.
- Single point for job creation/poll/resume/cancel, artifacts, search, answers, health, config.

Current code already supports:

- registry-backed tool/provider discovery;
- ledger-backed job/artifact operations;
- redacted config/status;
- search handlers by collection;
- answer handler injection;
- OpenAPI/MCP surfaces.

Target additions:

- Register a RagFlow workflow tool/adapter.
- Register Qdrant provider/adapter metadata.
- Register Obsidian/vault provider/adapter metadata.
- Build job plan factories for RagFlow/Qdrant/Obsidian workflows.
- Provide search handler that routes to `QdrantAdapter` for Qdrant-backed collections.

### 6.4 RAGWorkflowPort

Role:

- Capability boundary for RAG workflow operations.
- It should describe the foundation-level operation, not the implementation details of RagFlow internals.

Candidate method families:

- `ensure_dataset(...)`
- `submit_documents(...)`
- `start_ingestion_or_parse(...)`
- `poll_ingestion_status(...)`
- `list_documents(...)`
- `list_chunks(...)`
- `retrieve_context(...)`
- `normalize_chunks_for_indexing(...)`

This port may be expressed as Python protocols/classes or as job-stage contracts. The key requirement is explicit typed behavior, not a vague `execute(any)` method.

### 6.5 RagFlowAdapter

Role:

- Concrete adapter for RagFlow HTTP/REST.
- Owns RagFlow-specific API calls and response normalization.
- Does not own Qdrant writes.
- Does not write Obsidian vault notes directly.

Required responsibilities:

- Health check using `GET /api/v1/system/healthz`.
- Create/list/update datasets using `/api/v1/datasets` endpoints.
- Upload documents using `POST /api/v1/datasets/{dataset_id}/documents`.
- Trigger built-in parse using `POST /api/v1/datasets/{dataset_id}/chunks`.
- Trigger ingestion pipeline using `POST /api/v1/documents/ingest` when configured for ingestion pipeline datasets.
- Poll dataset/document parsing status via list datasets/documents endpoints.
- List/get chunks via `/api/v1/datasets/{dataset_id}/documents/{document_id}/chunks`.
- Optionally call `POST /api/v1/retrieval` for RagFlow-native retrieval/context inspection.
- Normalize RagFlow IDs and response fields into foundation contracts.
- Preserve raw RagFlow response snippets as artifacts when useful for auditability.

Required outputs into foundation:

- dataset IDs / names / embedding model / parser config;
- document IDs / names / run status / source type / size;
- chunk IDs / text/content / positions / page numbers where available;
- retrieval response fields such as `kb_id`, `document_id`, `id`, `similarity`, `term_similarity`, `vector_similarity`;
- source metadata and provenance;
- diagnostic/status artifacts.

### 6.6 QdrantAdapter

Role:

- Concrete foundation-owned adapter for Qdrant HTTP/REST.
- Owns collection creation, payload indexes, upsert, delete, scroll, query/search, and health.
- Enforces foundation payload schema and collection naming safety.

Required responsibilities:

- Health check using `GET /healthz`.
- Create/validate collections via `PUT /collections/{collection_name}`.
- Delete only disposable/test collections unless explicitly approved.
- Upsert points via `PUT /collections/{collection_name}/points` with idempotent point IDs.
- Delete points via `POST /collections/{collection_name}/points/delete` for stale/removed chunks when needed.
- Scroll points via `POST /collections/{collection_name}/points/scroll` for verification/reconciliation.
- Query points via `POST /collections/{collection_name}/points/query`.
- Create payload indexes via `PUT /collections/{collection_name}/index` for fields used in filters.
- Redact secrets from logs/errors.
- Emit visible evidence in smokes: collection name, point count, sample point IDs, query result IDs/scores.

Adapter interface should align with the existing `VectorStoreBackend` protocol where practical:

- `ensure_collection(...)`
- `count_points(...)`
- `upsert_points(...)`
- `search_points(...)`

But production adapter likely needs extra methods:

- `healthz()`
- `delete_collection(...)`
- `create_payload_index(...)`
- `delete_points(...)`
- `scroll_points(...)`
- `query_points(...)`
- `collection_info(...)`

### 6.7 ObsidianAdapter / KnowledgeVaultPort

Role:

- Materialize foundation artifacts into markdown/vault notes.
- Use `obsidian-intelligence-core` where practical.
- Preserve provenance and backlinks to source artifacts/Qdrant payloads/RagFlow IDs.

Required responsibilities:

- Write only to temp/fixture vaults by default in tests/smokes.
- Require explicit approval/config for live vault writes.
- Generate deterministic note paths from source IDs/config.
- Avoid duplicate unmanaged content on rerun.
- Preserve source metadata, artifact IDs, Qdrant collection/point IDs, RagFlow dataset/document IDs, and evidence refs in markdown frontmatter/body.
- Never become primary vector index or retrieval authority.

Potential materialized note types:

- source document note;
- chunk/evidence note;
- retrieval result note;
- synthesis/answer note;
- job audit/status note.

### 6.8 SQLiteArtifactLedger

Role:

- Canonical state/provenance/freshness ledger.

Responsibilities in this architecture:

- Record every foundation stage artifact.
- Store raw RagFlow responses when useful.
- Store normalized chunk artifacts.
- Store Qdrant indexing result artifacts.
- Store vault materialization result artifacts.
- Mark stale/superseded artifacts when source/config changes.
- Provide canonical freshness to Qdrant search via resolver.

### 6.9 Provider/Tool registries

Role:

- Metadata-only discovery of tool/provider capabilities.

Target registrations:

- `ragflow` or `ragflow-workflow` tool manifest.
- Qdrant adapter/provider spec for vector store capability.
- Embedding provider specs where embeddings are foundation-owned.
- Obsidian/vault adapter manifest/provider spec.

Registry metadata should not import/execute heavy dependencies during discovery.

## 7. End-to-end data and control flows

### 7.1 Ingestion/index/materialization flow

Target stage sequence:

1. `submit-source`
   - Accept source document/PDF/book/web URL or file artifact.
   - Register source artifact in `SQLiteArtifactLedger`.
   - Compute checksum and config fingerprint.

2. `ensure-ragflow-dataset`
   - `RagFlowAdapter` creates or finds a dataset.
   - Records dataset ID/name/config as an artifact.

3. `upload-ragflow-document`
   - `RagFlowAdapter` uploads file/web/empty document.
   - Records document ID/name/run status/source metadata.

4. `parse-or-ingest-ragflow-document`
   - For built-in chunking dataset: call `POST /api/v1/datasets/{dataset_id}/chunks`.
   - For ingestion pipeline dataset: call `POST /api/v1/documents/ingest`.
   - Poll list datasets/documents until done/fail/cancel or timeout.

5. `collect-ragflow-chunks`
   - List documents and chunks.
   - Optionally call retrieval endpoint for additional similarity/context fields.
   - Preserve raw response artifacts for audit.

6. `normalize-retrieval-chunks`
   - Convert RagFlow chunk/document/dataset data into `RetrievalChunk`-compatible contracts.
   - Attach `ArtifactRef` and `EvidenceRef` objects.
   - Add payload fields needed for Qdrant filters and citations.

7. `ensure-qdrant-collection`
   - `QdrantAdapter` creates/validates collection with vector config and metadata.
   - Creates payload indexes for high-cardinality/filter fields.

8. `upsert-qdrant-points`
   - Embed text if embeddings are foundation-owned, or use RagFlow-visible vectors only if safely exposed and compatible.
   - Upsert idempotent points into Qdrant.
   - Record `RetrievalIndexResult` or richer `QdrantIndexResult` artifact.

9. `materialize-vault-notes`
   - `ObsidianAdapter` writes temp/fixture vault notes from normalized artifacts and Qdrant index results.
   - Record note paths and checksums.

10. `verify-smoke-query`
   - Query Qdrant through foundation adapter.
   - Return cited/provenanced retrieval hits.
   - Optionally compare/augment with RagFlow retrieval endpoint output.

### 7.2 Query flow

Target query path:

```text
Hermes/MCP/HTTP request
  -> FoundationControlPlane.search/answer
  -> Qdrant search handler
  -> QdrantAdapter.query_points/search_points
  -> resolve artifact freshness from SQLiteArtifactLedger
  -> filter stale/superseded by default
  -> return RetrievalSearchResult with hits, evidence refs, artifact refs, payloads
  -> optional answer handler synthesizes answer with citations
```

RagFlow may participate in query flow in two ways:

1. As a comparison/augmentation surface through `POST /api/v1/retrieval`.
2. As the upstream workflow source for chunks/metadata already normalized into Qdrant.

The accepted Qdrant-backed path must not be satisfied only by RagFlow native retrieval unless Qdrant participation is separately proven.

### 7.3 Re-index/rerun flow

On source/config changes:

1. Foundation reruns source/RagFlow stages.
2. Ledger detects changed derivation/config fingerprints.
3. Previous artifacts become `stale` or `superseded`.
4. Normalized chunks get new or updated IDs/fingerprints.
5. Qdrant points are upserted with idempotent IDs.
6. Removed chunks are deleted or marked stale depending on chosen policy.
7. Search defaults to current-only via ledger freshness resolver.
8. Vault notes update deterministically or create superseding notes with provenance.

## 8. Qdrant collection and payload design

### 8.1 Collection naming

Collection names must be deterministic, environment-safe, and non-production-safe by default.

Suggested pattern:

```text
{collection_prefix}{workspace_or_profile}_{corpus_slug}_{embedding_provider_id}_{embedding_dim}_v{schema_major}
```

Examples with an explicit disposable prefix:

```text
dh233_test_default_ragflow_docs_openai_text_embedding_3_large_3072_v1
dh236_test_default_smoke_fixture_embed_384_v1
```

Rules:

- Default test/smoke collection prefix must be disposable, e.g. `dh233_test_`, `dh236_test_`, or another configured test prefix.
- Destructive-operation gates must compare collection names against the configured disposable prefix exactly, e.g. `collection_name.startswith(BRAIN_LAB_TEST_QDRANT_COLLECTION_PREFIX)`.
- Production collection prefixes require explicit config.
- Destructive operations must reject collections outside the allowed disposable prefix unless an explicit approval/config flag is set.
- Collection metadata must bind embedding provider, dimension, distance metric, and payload schema version.

### 8.2 Point IDs

Point IDs should be deterministic and idempotent.

Suggested point ID input fields:

- foundation artifact namespace/value;
- RagFlow `kb_id` / dataset ID;
- RagFlow `document_id`;
- RagFlow chunk ID;
- chunk text hash;
- embedding provider ID/version/dimension if embeddings can change independently;
- schema version.

Canonical point identity input:

```text
brainlab:qdrant-point:v1\n{dataset_id}\n{document_id}\n{chunk_id}\n{text_hash}\n{embedding_provider_id}\n{embedding_provider_version}\n{dimension}
```

Qdrant-compatible ID rule:

- Qdrant REST point IDs are `uint64` integers or UUID strings.
- Do **not** send raw SHA-256 hex as the Qdrant point ID.
- Recommended MVP: derive deterministic UUIDv5 from the canonical identity string and store the full SHA-256 hash in payload as `source.text_hash` and/or `qdrant.point_hash`.
- The HTTP adapter must validate/coerce point IDs before sending them to Qdrant, because the existing in-memory backend is more permissive than production Qdrant.

### 8.3 Required payload fields

Minimum payload at initial Qdrant upsert:

```json
{
  "contract_type": "brain_lab.retrieval.chunk",
  "schema_version": "brain_lab.contracts.v1",
  "chunk_id": "...",
  "text": "...",
  "artifact_id": "namespace:value",
  "artifact_freshness": "current",
  "artifact_ref": { "...": "canonical ArtifactRef" },
  "evidence_refs": [{ "...": "canonical EvidenceRef" }],
  "metadata": {},
  "tool_fields": {},

  "qdrant.point_hash": "sha256:...",
  "ragflow.kb_id": "...",
  "ragflow.dataset_id": "...",
  "ragflow.document_id": "...",
  "ragflow.chunk_id": "...",
  "ragflow.document_name": "...",
  "ragflow.chunk_method": "...",
  "ragflow.parser_config_hash": "sha256:...",

  "source.uri": "...",
  "source.name": "...",
  "source.mime_type": "...",
  "source.page_number": 1,
  "source.position_json": "...",
  "source.text_hash": "sha256:...",

  "embedding.provider_id": "...",
  "embedding.provider_version": "...",
  "embedding.dimension": 1536,
  "embedding.distance": "Cosine"
}
```

Optional enrichment fields:

```json
{
  "ragflow.similarity": 0.0,
  "ragflow.term_similarity": 0.0,
  "ragflow.vector_similarity": 0.0,
  "vault.note_path": "...",
  "vault.materialized": true
}
```

Notes:

- The existing `RetrievalChunk` payload already supports canonical fields and flat namespaced tool fields.
- Use namespaced keys (`qdrant.*`, `ragflow.*`, `source.*`, `embedding.*`, `vault.*`) to satisfy current `brain_lab_core` tool-field constraints. Do not add un-namespaced fields such as `text_hash` unless the core contract is intentionally extended.
- `ragflow.*similarity` fields are available only when a RagFlow retrieval response participated in the workflow; list-chunks extraction alone should not require them.
- `vault.*` fields are optional because the preferred stage order indexes Qdrant before vault materialization. If vault fields are needed in Qdrant, add a later payload update after materialization rather than making them initial upsert requirements.
- Keep fields used in Qdrant filters top-level, not buried only inside nested `metadata`.
- Store full canonical `ArtifactRef`/`EvidenceRef` for cited output, but keep query filters on simple scalar payload fields.

### 8.4 Payload indexes

Create Qdrant payload indexes for fields used in filters/reconciliation. Candidate fields:

- `artifact_id`
- `artifact_freshness`
- `chunk_id`
- `ragflow.kb_id`
- `ragflow.dataset_id`
- `ragflow.document_id`
- `ragflow.chunk_id`
- `qdrant.point_hash`
- `source.uri`
- `source.text_hash`
- `source.mime_type`
- `source.page_number`
- `embedding.provider_id`
- `embedding.dimension`
- `vault.note_path`

Exact Qdrant field-index types must be chosen during implementation based on Qdrant API docs and field values.

### 8.5 Vector configuration

MVP dense vector configuration:

- Distance: `Cosine`.
- Vector size: embedding provider dimension.
- Named vector: optional; if using named vectors, choose stable name such as `dense`.

Hybrid-ready configuration:

- Dense vector for semantic search.
- Optional sparse/hybrid retrieval through externally generated sparse vectors, for example SPLADE or BM25-weighted sparse representations, combined with Qdrant's Universal Query API. Qdrant should not be assumed to compute BM25 automatically over payload text.
- If hybrid is not included in MVP, document explicitly that MVP retrieval is dense-vector-first with payload filters, and preserve RagFlow `term_similarity`/`vector_similarity` when available for audit/comparison.

### 8.6 Freshness policy

Default query behavior:

- Use ledger-backed freshness resolution.
- Return only `current` artifacts unless caller requests review/debug mode.
- Treat missing ledger artifacts as `unknown` and exclude under `CURRENT_ONLY`.

Point update/delete policy options:

1. **Upsert + freshness filter**
   - Keep stale point payloads but mark or resolve them stale.
   - Simpler audit history.
   - Requires query filter/resolver correctness.

2. **Upsert + delete removed points**
   - Delete points for chunks no longer present.
   - Cleaner index.
   - Requires reconciliation via scroll/list.

Recommended MVP:

- Use deterministic upsert.
- Preserve freshness in payload.
- Apply a coarse Qdrant payload filter for `artifact_freshness=current` when the payload snapshot is available.
- Overfetch with a bounded `candidate_limit` before ledger verification, so stale top-K candidates do not hide current results.
- Resolve final freshness from the SQLite ledger at query time; ledger state wins over payload snapshots.
- Add reconciliation/delete in a later hardening pass to update or remove stale Qdrant payloads so payload freshness does not drift indefinitely.

## 9. RagFlow normalization contract

### 9.1 Inputs from RagFlow

Potential RagFlow inputs to foundation normalization:

- Dataset object from create/list dataset APIs.
- Document object from upload/list document APIs.
- Chunk object from list/get chunk APIs.
- Retrieval chunk object from `/api/v1/retrieval`.
- Parse/ingest status from dataset/document listing APIs.
- Raw API responses for audit artifacts.

### 9.2 Normalized chunk contract

A normalized chunk should become a foundation `RetrievalChunk` or equivalent. Required mapping:

- `RetrievalChunk.chunk_id`
  - Prefer stable composite `{dataset_id}:{document_id}:{ragflow_chunk_id}` or deterministic hash.
- `RetrievalChunk.text`
  - From RagFlow chunk `content`, `content_with_weight`, or retrieval `content`.
- `RetrievalChunk.artifact_ref`
  - Reference to the normalized chunk artifact or source document artifact in `SQLiteArtifactLedger`.
- `RetrievalChunk.evidence_refs`
  - Evidence ref to source document/page/position if available.
- `RetrievalChunk.tool_fields`
  - Namespaced RagFlow/source/embedding/vault fields.
- `RetrievalChunk.metadata`
  - Additional non-filter metadata and raw response hashes.

### 9.3 Evidence mapping

EvidenceRef should preserve:

- `source_artifact_id`: canonical source document or normalized chunk artifact.
- `source_type`: e.g. `ragflow.chunk`, `document.page`, `pdf.block`, `web.page`.
- `span`: page number, position, character span, or time span depending on source.
- `quote`: exact chunk text or excerpt.
- `confidence`: 1.0 for deterministic extracted chunks unless RagFlow returns confidence.
- `provenance`: tool ID `ragflow`, stage ID, source refs, source name/URL.

### 9.4 Handling missing vectors

RagFlow chunk APIs explicitly note runtime vector/token fields are not returned for `GET chunk`. Therefore the foundation must not assume it can reuse RagFlow's internal vectors.

MVP options:

1. **Foundation-owned embeddings**
   - Use an embedding provider registered in `AdapterRegistry`.
   - Embed normalized chunk text in the foundation.
   - Store vectors in Qdrant.
   - Best alignment with foundation-owned Qdrant.

2. **RagFlow retrieval response as metadata only**
   - Use RagFlow `/api/v1/retrieval` to get retrieval scores/context.
   - Store those scores/IDs as payload metadata.
   - Still generate/store foundation-owned embeddings for Qdrant.

3. **Future advanced seam**
   - If RagFlow later exposes embeddings/vectors through a stable API, add explicit compatibility checks for provider ID/version/dimension before indexing in Qdrant.

Recommended MVP: foundation-owned embeddings.

## 10. Configuration and environment model

### 10.1 RagFlow config

Suggested config keys:

```text
BRAIN_LAB_RAGFLOW_BASE_URL
BRAIN_LAB_RAGFLOW_API_KEY
BRAIN_LAB_RAGFLOW_TIMEOUT_SECONDS
BRAIN_LAB_RAGFLOW_DEFAULT_DATASET_ID
BRAIN_LAB_RAGFLOW_DEFAULT_DATASET_NAME
BRAIN_LAB_TEST_RAGFLOW_DATASET_PREFIX=dh233_test_
BRAIN_LAB_RAGFLOW_POLL_INTERVAL_SECONDS
BRAIN_LAB_RAGFLOW_POLL_TIMEOUT_SECONDS
BRAIN_LAB_RAGFLOW_ALLOW_DELETE=false
BRAIN_LAB_TEST_RAGFLOW_ALLOW_DELETE=0
```

Rules:

- API key must be declared in secret policy and redacted.
- Base URL is non-secret but should be included in config status only if safe.
- Polling must time out with a clear stage failure artifact.
- Dataset creation must avoid accidental production dataset pollution unless explicitly configured.
- Test datasets must use a configured disposable prefix such as `dh233_test_`.
- RagFlow dataset/document deletion is disabled by default and allowed only for disposable test prefixes when `BRAIN_LAB_TEST_RAGFLOW_ALLOW_DELETE=1` or an equivalent explicit live-delete approval is set.

### 10.2 Qdrant config

Suggested config keys:

```text
BRAIN_LAB_QDRANT_URL
BRAIN_LAB_QDRANT_API_KEY
BRAIN_LAB_QDRANT_COLLECTION_PREFIX
BRAIN_LAB_QDRANT_TIMEOUT_SECONDS
BRAIN_LAB_QDRANT_DISTANCE
BRAIN_LAB_QDRANT_VECTOR_NAME
BRAIN_LAB_QDRANT_ALLOW_DESTRUCTIVE=false
BRAIN_LAB_QDRANT_REQUIRE_DISPOSABLE_PREFIX=true
```

Rules:

- API key must be redacted.
- Collection prefix must be required for live Qdrant tests.
- Destructive operations only on disposable prefixes unless explicit override.
- Live checks must skip with reasons when env is absent.

### 10.3 Embedding config

Suggested config keys:

```text
BRAIN_LAB_EMBEDDING_PROVIDER_ID
BRAIN_LAB_EMBEDDING_PROVIDER_VERSION
BRAIN_LAB_EMBEDDING_DIMENSION
BRAIN_LAB_EMBEDDING_API_KEY
BRAIN_LAB_EMBEDDING_MODEL
```

Rules:

- Provider ID/version/dimension are part of collection metadata.
- Incompatible dimensions/providers must fail before upsert/search.
- Secrets redacted.

### 10.4 Obsidian/vault config

Suggested config keys:

```text
BRAIN_LAB_VAULT_ROOT
BRAIN_LAB_VAULT_ALLOW_LIVE_WRITES=false
BRAIN_LAB_VAULT_NOTE_PREFIX
BRAIN_LAB_VAULT_TEMP_ONLY=true
```

Rules:

- Default smokes write only to temp/fixture vaults.
- Live vault writes require explicit approval/config.
- Note paths must be normalized and prevented from escaping vault root.

## 11. Error handling and safety

### 11.1 Error envelope behavior

Use `ErrorEnvelope` / `ContractValidationError` patterns already present in `brain_lab_core`.

Adapter errors should include:

- normalized error code;
- retryable flag;
- HTTP method/path, but never secret headers;
- upstream status code;
- redacted upstream response excerpt;
- operation context such as dataset/document/collection names when safe.

### 11.2 Retry policy

Recommended retryable cases:

- transient HTTP connection errors;
- 429/rate limit with backoff;
- 502/503/504 upstream service errors;
- Qdrant write timeout if operation status can be reconciled;
- RagFlow parse polling transient failures.

Non-retryable cases:

- contract validation errors;
- missing required config;
- unsupported RagFlow dataset/parser mode;
- embedding dimension mismatch;
- collection config mismatch;
- unsafe destructive collection operation;
- path traversal in vault materialization;
- unauthorized live vault writes.

### 11.3 Secret handling

Secrets must be declared so `FoundationControlPlane.config_status()` and job/artifact/event surfaces redact:

- RagFlow API key/token.
- Qdrant API key.
- Embedding provider API keys.
- Any vault tokens if introduced.

Never log full authorization headers.

### 11.4 Destructive operation safety

Qdrant collection deletion, RagFlow test dataset/document cleanup, and vault writes are the main hazards.

Required safeguards:

- test/smoke Qdrant collection prefix required;
- destructive Qdrant operations disabled by default for non-disposable prefixes;
- RagFlow cleanup/deletion disabled by default and allowed only for disposable test dataset prefixes unless explicitly approved;
- temp vault root required for tests;
- live vault writes require explicit config and user approval;
- no production collection, dataset, document, or vault cleanup in unit tests.

## 12. Test and smoke strategy

### 12.1 Unit tests

Existing unit tests should continue to pass:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
python -m compileall -q src tests
```

New unit tests for `QdrantAdapter` should use fake HTTP transport or a small adapter boundary, not live Qdrant by default.

Required unit tests:

- collection config creation payload includes vector size/distance/schema metadata;
- incompatible collection config fails;
- point upsert maps `RetrievalChunk` payload correctly;
- deterministic point ID generation;
- payload filters map to Qdrant filter JSON;
- query result maps to `RetrievalHit` with evidence/artifact refs;
- API key redaction in errors/logs;
- unsafe collection delete rejected;
- disposable delete allowed with explicit prefix/config;
- stale/fresh policy excludes stale artifacts by default.

### 12.2 Integration tests: live Qdrant, env-gated

Live Qdrant tests must require env, for example:

```text
BRAIN_LAB_TEST_QDRANT_URL
BRAIN_LAB_TEST_QDRANT_API_KEY
BRAIN_LAB_TEST_QDRANT_COLLECTION_PREFIX=dh236_test_
BRAIN_LAB_RUN_LIVE_QDRANT=1
```

Test behavior:

1. Create disposable collection.
2. Create payload indexes.
3. Upsert two or more points with evidence payloads.
4. Query by vector and payload filters.
5. Scroll collection to verify point count/payloads.
6. Delete points or collection.
7. Report visible collection/point/search evidence.

Skip behavior:

- If env not present, skip with explicit reason.
- Do not silently run against default localhost unless configured as disposable.

### 12.3 Integration tests: RagFlow, env-gated

Live RagFlow tests should require env:

```text
BRAIN_LAB_TEST_RAGFLOW_BASE_URL
BRAIN_LAB_TEST_RAGFLOW_API_KEY
BRAIN_LAB_RUN_LIVE_RAGFLOW=1
```

Test behavior:

1. Health check.
2. Create/find disposable dataset.
3. Upload small fixture document.
4. Trigger parse/ingest.
5. Poll until done or timeout.
6. List documents/chunks.
7. Record dataset/document/chunk IDs.
8. Clean up if safe and configured.

### 12.4 End-to-end smoke: DH-233

Minimum accepted smoke:

```text
fixture source document
  -> FoundationControlPlane.create_job
  -> RagFlowAdapter health/create/upload/parse/list chunks
  -> foundation normalizes chunks and evidence
  -> QdrantAdapter creates disposable collection/upserts/searches
  -> ObsidianAdapter writes temp-vault note if available
  -> FoundationControlPlane.search/answer returns cited Qdrant-backed hit
```

Required smoke output:

- command executed;
- state root;
- RagFlow base URL redacted if needed;
- RagFlow dataset ID;
- RagFlow document ID;
- number of chunks normalized;
- Qdrant URL redacted if needed;
- Qdrant collection name;
- point IDs upserted;
- query text;
- top hit IDs/scores;
- artifact IDs/evidence IDs;
- vault note paths if materialized;
- cleanup actions or retained disposable collection reason.

A smoke that only calls RagFlow retrieval does not satisfy DH-233. A smoke that only uses in-memory Qdrant also does not satisfy live Qdrant proof unless it is explicitly marked fixture-only.

## 13. Open design questions for GPT Pro review

Please review these questions carefully.

### 13.1 RagFlow chunk source of truth

Question:

- Should the foundation index Qdrant from RagFlow **list chunks** output, RagFlow **retrieval** output, or both?

Facts:

- List chunks returns chunk content and IDs.
- Retrieval returns `kb_id`, chunk/document IDs, content, and similarity/term/vector scores.
- Get chunk docs say runtime vector/token fields are not returned.

Recommended answer:

- Use list chunks for complete post-ingestion corpus extraction.
- Use retrieval output for query-time comparison/enrichment and metadata validation.
- Do not rely on RagFlow internal vectors.

### 13.2 Embeddings ownership

Question:

- Should foundation generate embeddings itself for Qdrant, or attempt to reuse RagFlow embeddings?

Facts:

- Current RagFlow public chunk API does not expose vectors.
- `brain_lab_core` already has embedding provider registry surfaces and collection metadata binding.

Recommended answer:

- Foundation-owned embeddings for MVP.
- Reuse RagFlow embeddings only if a future stable API exposes provider ID/version/dimension and vectors safely.

### 13.3 Dense vs hybrid search

Question:

- Should MVP implement dense-only Qdrant search or hybrid search?

Facts:

- Existing `QdrantRetrievalFacade` is dense cosine only.
- Official Qdrant query endpoint supports filters and hybrid/multi-stage queries.
- RagFlow retrieval exposes vector and term similarity fields for its own retrieval path.

Recommended answer:

- MVP: dense Qdrant + payload filters + citations, with explicit limitation.
- Next: Qdrant sparse/hybrid search using named sparse vectors or Qdrant's Universal Query API.
- Do not silently claim hybrid unless tested.

### 13.4 Payload text storage

Question:

- Should full chunk text be stored in Qdrant payload?

Trade-off:

- Full text in payload improves retrieval result completeness and simplifies MCP responses.
- It duplicates ledger artifacts and may increase Qdrant memory/storage.

Recommended answer:

- Store chunk text or bounded chunk text in payload for MVP, plus text hash and artifact refs.
- For large chunks, enforce max text size and rely on ledger artifact content for full source.

### 13.5 Vault materialization timing

Question:

- Should Obsidian materialization happen before or after Qdrant indexing?

Recommended answer:

- After normalization and Qdrant index result so vault notes can include Qdrant collection/point metadata.
- If vault notes are used as source artifacts in future workflows, treat that as a separate explicit stage.

### 13.6 Adapter placement

Question:

- Should adapters live in `brain_lab_core` itself or separate packages that depend on `brain_lab_core`?

Facts:

- `brain_lab_core` currently has zero runtime dependencies and optional FastAPI only.
- Qdrant/RagFlow HTTP can be implemented with stdlib or optional deps.

Recommended answer:

- Keep core contracts/protocols in `brain_lab_core`.
- Implement low-dependency HTTP adapters either inside `brain_lab_core.adapters` using stdlib HTTP, or in thin extension packages if dependencies grow.
- Do not force heavy optional dependencies into core import path.

## 14. Implementation issue mapping

### 14.1 DH-236: foundation-owned Qdrant adapter + RagFlow integration

Scope:

- Concrete Qdrant HTTP adapter.
- Normalization seam from RagFlow adapter outputs to Qdrant payloads.
- Live Qdrant env-gated tests with disposable collections.
- Dense search with cited payloads.
- Fresh/stale handling.

Acceptance:

- Qdrant collection/point/query evidence is visible.
- No non-Qdrant fallback accepted.
- No RagFlow repository modification required.

### 14.2 DH-238: Obsidian adapter / vault materialization

Scope:

- Temp/fixture vault writes.
- Integration with `obsidian-intelligence-core` where practical.
- Deterministic note paths.
- Provenance-preserving markdown/frontmatter.
- Safety gates for live vault writes.

Acceptance:

- Fixture vault note generated from normalized artifacts/Qdrant results.
- Rerun idempotence or explicit supersession behavior.
- No live vault writes without approval/config.

### 14.3 DH-233: E2E smoke

Scope:

- Prove the full architecture through FoundationControlPlane.
- Include RagFlow API participation and Qdrant API participation.
- Include Obsidian temp vault if DH-238 is available.

Acceptance:

- The smoke cannot pass by using RagFlow-only retrieval.
- The smoke cannot pass by using in-memory Qdrant only unless marked fixture-only and not accepted as live Qdrant proof.
- Output contains IDs/evidence for all major surfaces.

### 14.4 DH-235: architecture consolidation

Scope:

- Keep this document or a refined version as project-local architecture anchor.
- Keep vocabulary consistent: `FoundationControlPlane`, `RAGWorkflowPort`, `RagFlowAdapter`, `QdrantAdapter`, `ObsidianAdapter`.

### 14.5 DH-231 / DH-204 reuse

Scope:

- Align prior Qdrant indexing/upsert and retrieval/evidence behavior with this architecture.
- Reuse existing `RetrievalChunk`, `RetrievalHit`, `RetrievalSearchResult`, freshness resolver, and tool-filter constraints where practical.

## 15. Suggested package/API shape

### 15.1 Module layout option

```text
src/brain_lab_core/
  adapters/
    __init__.py
    ragflow.py
    qdrant_http.py
    obsidian.py
  workflows/
    __init__.py
    ragflow_qdrant.py
  retrieval/
    qdrant.py              # existing contracts/facade
    qdrant_http.py         # optional if not under adapters
```

If avoiding new top-level packages for now:

```text
src/brain_lab_core/retrieval/qdrant_http.py
src/brain_lab_core/api/ragflow_workflow.py
```

### 15.2 RagFlowAdapter candidate interface

```python
class RagFlowAdapter:
    def healthz(self) -> RagFlowHealth: ...
    def create_dataset(self, request: RagFlowDatasetCreate) -> RagFlowDataset: ...
    def list_datasets(self, filters: RagFlowDatasetFilters) -> tuple[RagFlowDataset, ...]: ...
    def upload_document(self, dataset_id: str, source: DocumentSource) -> RagFlowDocument: ...
    def start_parse(self, dataset_id: str, document_ids: Sequence[str]) -> RagFlowOperation: ...
    def start_ingest(self, doc_ids: Sequence[str], *, delete: bool = False) -> RagFlowOperation: ...
    def list_documents(self, dataset_id: str, filters: RagFlowDocumentFilters) -> tuple[RagFlowDocument, ...]: ...
    def list_chunks(self, dataset_id: str, document_id: str, page: int = 1, page_size: int = 100) -> RagFlowChunkPage: ...
    def retrieve(self, request: RagFlowRetrievalRequest) -> RagFlowRetrievalResult: ...
```

### 15.3 QdrantAdapter candidate interface

```python
class QdrantHttpAdapter(VectorStoreBackend):
    def healthz(self) -> QdrantHealth: ...
    def ensure_collection(self, collection_name: str, *, vector_size: int, distance: str, metadata: Mapping[str, Any] | None = None, recreate: bool = False) -> None: ...
    def create_payload_index(self, collection_name: str, field_name: str, field_schema: str) -> None: ...
    def count_points(self, collection_name: str, *, payload_filter: Mapping[str, Any] | None = None) -> int: ...
    def upsert_points(self, collection_name: str, points: Sequence[QdrantPoint]) -> None: ...
    def search_points(self, collection_name: str, query_vector: Sequence[float], *, limit: int, payload_filter: Mapping[str, Any] | None = None) -> tuple[QdrantScoredPoint, ...]: ...
    def scroll_points(self, collection_name: str, *, payload_filter: Mapping[str, Any] | None = None, limit: int = 100) -> tuple[QdrantPoint, ...]: ...
    def delete_points(self, collection_name: str, point_ids: Sequence[str]) -> None: ...
    def delete_collection(self, collection_name: str, *, require_disposable: bool = True) -> None: ...
```

### 15.4 Workflow factory candidate

```python
def ragflow_qdrant_job_factory(submission: JobSubmission) -> JobPlan:
    return JobPlan(
        job_id=submission.job_id,
        tool_id=submission.tool_id,
        config=submission.config,
        stages=(
            StagePlan("register-source", ...),
            StagePlan("ragflow-ensure-dataset", ...),
            StagePlan("ragflow-upload-document", ...),
            StagePlan("ragflow-parse-or-ingest", ...),
            StagePlan("ragflow-collect-chunks", ...),
            StagePlan("normalize-retrieval-chunks", ...),
            StagePlan("qdrant-upsert", ...),
            StagePlan("obsidian-materialize", ...),
            StagePlan("verify-query", ...),
        ),
    )
```

## 16. Review checklist for GPT Pro

Please review this architecture against the following criteria:

1. **Correctness of boundary decision**
   - Does the foundation-owned Qdrant adapter correctly avoid extending RagFlow while still integrating RagFlow's useful API surface?

2. **Completeness of data flow**
   - Are all necessary IDs and artifacts preserved from source -> RagFlow -> foundation -> Qdrant -> vault -> retrieval?

3. **Qdrant payload design**
   - Are the required fields sufficient for citations, filtering, freshness, and replay/debugging?
   - Are any fields missing for future hybrid search or document/page provenance?

4. **Embedding ownership**
   - Is foundation-owned embedding the right MVP given RagFlow public APIs do not expose vectors?
   - What compatibility checks are needed if RagFlow embeddings are later reused?

5. **Freshness and idempotence**
   - Is ledger-backed freshness resolution enough for MVP?
   - Should stale Qdrant points be deleted or retained with filters?

6. **RagFlow API sufficiency**
   - Are the documented RagFlow endpoints enough to extract chunks and metadata reliably?
   - What should happen when list chunks and retrieval outputs disagree?

7. **Safety**
   - Are the destructive-operation gates sufficient for Qdrant and vault writes?
   - Are live tests adequately env-gated?

8. **Package design**
   - Should concrete adapters live in `brain_lab_core`, optional extras, or separate packages?
   - How can we preserve zero mandatory runtime dependencies?

9. **Smoke validity**
   - Does the DH-233 smoke prove real integration, or can it pass through a loophole?
   - What exact output evidence should be mandatory?

10. **Long-term architecture**
    - Does this design support continuous context: historical artifacts, current updates, enrichment, low-latency serving, and governance?

## 17. Known risks

### 17.1 RagFlow API incompleteness

Risk:

- RagFlow may not expose every artifact needed for perfect chunk/vector provenance.

Mitigation:

- Use list chunks + retrieval API + raw response artifacts.
- Foundation-owned embeddings avoid needing RagFlow vectors.
- Document exact MVP limitations.

### 17.2 Duplicate embedding work

Risk:

- RagFlow embeds internally, then foundation embeds again for Qdrant.

Mitigation:

- Accept duplicate embeddings for correctness and boundary cleanliness in MVP.
- Later optimize only if RagFlow exposes vectors/model metadata safely.

### 17.3 Qdrant payload bloat

Risk:

- Storing full text and nested refs in payload could grow Qdrant storage.

Mitigation:

- Store bounded text with hash and artifact refs.
- Keep full canonical content in ledger/filesystem.

### 17.4 Split-brain freshness

Risk:

- Qdrant payload freshness snapshots can become stale.

Mitigation:

- Resolve freshness from SQLite ledger at query time.
- Add reconciliation/delete stage later.

### 17.5 Unsafe live writes

Risk:

- Tests or smokes could delete non-test Qdrant collections or write into a live vault.

Mitigation:

- Disposable prefixes required.
- Live writes disabled by default.
- Explicit env/approval gates.

### 17.6 Scope creep into generic service layers

Risk:

- Implementation may introduce generic `IngestionService` / `RetrievalService` layers and obscure the adapter pattern.

Mitigation:

- Keep job stages and adapter methods explicit.
- Enforce vocabulary in issue acceptance criteria.

## 18. Definition of architecture done

This architecture is ready to implement when:

- `DH-237` decision is treated as authoritative.
- The project-local architecture document is linked from `DH-235` or project resources.
- `DH-236` has an implementation plan that maps exact Qdrant HTTP endpoints to adapter methods.
- `DH-236` defines exact RagFlow fields used for Qdrant payload construction.
- `DH-238` defines exact vault note schema/path rules and live-write gates.
- `DH-233` defines commands and mandatory evidence for the smoke.
- Review resolves the open questions in Section 13.

## 19. Proposed next implementation sequence

1. Add concrete `QdrantHttpAdapter` behind the existing `VectorStoreBackend` protocol.
2. Add fake transport unit tests for Qdrant REST request/response mapping.
3. Add env-gated live Qdrant disposable collection smoke.
4. Add `RagFlowAdapter` with health/dataset/document/parse/list-chunks/retrieval calls.
5. Add fake RagFlow response tests and env-gated RagFlow smoke.
6. Add normalization stage from RagFlow chunk/retrieval responses to `RetrievalChunk` artifacts.
7. Wire `FoundationControlPlane` job factory for RagFlow->Qdrant indexing.
8. Add `ObsidianAdapter` temp-vault materialization.
9. Add DH-233 E2E smoke.
10. Update Linear issue status/comments with smoke artifacts and exact outputs.

## 20. Verification performed for this document

Mechanical checks performed before handoff:

```bash
python - <<'PY'
from pathlib import Path
# counted lines/bytes/headings/code fences, checked required sections,
# searched for common draft markers and uncertainty words,
# extracted URLs, and verified code-fence balance.
PY
```

Observed results at handoff:

- Final document length after verification appendix: 1,916 lines / 81,078 bytes.
- Code fences: balanced.
- Draft-marker scan: clean for the common marker and filler patterns checked by the verification script.
- Diagram syntax: no generated diagram block found; this remains markdown-only prose and code blocks.
- Required review sections present: executive summary, decisions, evidence base, source citation index, current/target state, component model, end-to-end flows, Qdrant design, RagFlow normalization, config/env model, tests/smokes, GPT Pro questions, risks, verification appendix, handoff summary, implementation sequence, bottom line.
- Markdown table scan: no table rows outside code fences.
- URL validation: all 10 external URLs in the final document returned HTTP 200 during verification.
- Git state observed during verification: repo on `main`, `HEAD` short SHA `5522230`, local branch ahead of origin/main by 16, document untracked under `docs/`.

External review pass:

- A delegated critical review found useful corrections, including Qdrant point ID compatibility, Qdrant count/get-collection/wait controls, RagFlow internal `DOC_ENGINE` runtime dependency, deprecated/current RagFlow chunk update method, and freshness overfetch/reconciliation nuance.
- Those corrections were applied in Sections 3, 4, 8, 10, 11, 12, 13, and this handoff appendix.

Known verification limits:

- No live RagFlow or Qdrant service was called for this document.
- No code tests were required by this documentation-only change; implementation smokes are specified but not executed here.
- The architecture uses inspected local source, Linear issue context, retrieved knowledge-base context, and official Qdrant API docs; future upstream RagFlow/Qdrant changes should be rechecked before implementation.

## 21. Handoff summary for GPT Pro review

Ask GPT Pro to review this document as an architecture decision package, not just prose. The most important review questions are:

1. Is the foundation-owned Qdrant adapter the correct boundary given the non-negotiable decision not to fork or extend RagFlow?
2. Does the design preserve all IDs/provenance needed for source -> RagFlow -> foundation -> Qdrant -> vault -> cited answer?
3. Are deterministic UUIDv5 Qdrant point IDs plus SHA-256 payload hashes sufficient for idempotence and reconciliation?
4. Is dense-first Qdrant retrieval acceptable for MVP, with sparse/hybrid explicitly deferred?
5. Does ledger-backed freshness with Qdrant overfetch avoid stale-result failure modes well enough before full reconciliation/delete support?
6. Are destructive-operation gates strict enough for Qdrant collections, RagFlow disposable datasets, and vault writes?
7. Can DH-233's smoke prove real architecture participation without loopholes through RagFlow-only retrieval or in-memory-only Qdrant?
8. Should concrete adapters live in `brain_lab_core`, optional extras, or separate packages while preserving the current zero-heavy-dependency core?

Expected GPT Pro output:

- Identify any incorrect factual claims.
- Identify missing architecture risks or hidden implementation dependencies.
- Challenge any over-scoped generic abstractions.
- Recommend exact changes to DH-236, DH-238, and DH-233 acceptance criteria.
- Propose a minimal implementation sequence that proves Qdrant participation quickly and safely.

## 22. Bottom line

The intended architecture is not a RagFlow fork and not a substitution of RagFlow's current doc engine. It is a foundation-owned orchestration layer that integrates RagFlow's external workflow/RAG API with Qdrant's external vector database API and Obsidian/vault materialization, all under `FoundationControlPlane`, `SQLiteArtifactLedger`, canonical artifact/evidence contracts, redaction, freshness, and testable smokes.

The decisive implementation requirement is to make Qdrant participation explicit and verifiable while keeping RagFlow external and unmodified.
