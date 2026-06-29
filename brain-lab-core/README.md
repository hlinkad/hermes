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

## Extension-point packages

The package exposes empty, importable namespaces for later foundation work:

- `brain_lab_core.state` — artifact/state ledger
- `brain_lab_core.registry` — tool/provider registry
- `brain_lab_core.orchestration` — job runner lifecycle
- `brain_lab_core.retrieval` — retrieval facade
- `brain_lab_core.api` — control-plane/API surfaces
- `brain_lab_core.security` — security, secrets, and sandbox gates
- `brain_lab_core.observability` — structured events and diagnostics

These modules are placeholders by design. DH-200 does not implement a job runner, ledger, retrieval index, or domain-specific ingest logic.

## Development verification

From this directory:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
python -m compileall -q src tests
python -m pip wheel . --no-deps --no-build-isolation -w /tmp/brain-lab-core-wheel
```

`pyproject.toml` includes the intended Ruff config for environments that have `ruff` installed.
