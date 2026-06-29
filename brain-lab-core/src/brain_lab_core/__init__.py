"""Generic AI Lab foundation package.

`brain_lab_core` owns stable, tool-neutral contracts for artifacts, evidence,
jobs, tool manifests, providers, and normalized errors. Concrete tools such as
video-intel should import these contracts instead of redefining generic state.
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
