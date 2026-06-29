"""Generic AI Lab foundation package.

`brain_lab_core` owns stable, tool-neutral contracts for artifacts, evidence,
jobs, tool manifests, providers, normalized errors, and the local SQLite-backed
artifact/state ledger. Concrete tools such as video-intel should import these
contracts and state helpers instead of redefining generic foundation behavior.
"""
from __future__ import annotations

from .contracts import (
    CONTRACT_SCHEMA_VERSION,
    ArtifactId,
    ArtifactRef,
    Checksum,
    Citation,
    ContractDiagnostic,
    ContractValidationError,
    ErrorEnvelope,
    EvidenceRef,
    FreshnessState,
    Job,
    LifecycleState,
    Provenance,
    ProviderCapability,
    ProviderSpec,
    ResourceProfile,
    RetryMetadata,
    SchemaExtensionPoint,
    SourceSpan,
    StageRun,
    ToolManifest,
)

__all__ = [
    "CONTRACT_SCHEMA_VERSION",
    "ArtifactId",
    "ArtifactRef",
    "Checksum",
    "Citation",
    "ContractDiagnostic",
    "ContractValidationError",
    "ErrorEnvelope",
    "EvidenceRef",
    "FreshnessState",
    "Job",
    "LifecycleState",
    "Provenance",
    "ProviderCapability",
    "ProviderSpec",
    "ResourceProfile",
    "RetryMetadata",
    "SchemaExtensionPoint",
    "SourceSpan",
    "StageRun",
    "ToolManifest",
]
