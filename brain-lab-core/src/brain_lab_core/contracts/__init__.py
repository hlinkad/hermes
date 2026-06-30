"""Public contract surface for the AI Lab Foundation Framework."""
from __future__ import annotations

from .artifacts import ArtifactId, ArtifactRef, Checksum, FreshnessState, Provenance
from .base import CONTRACT_SCHEMA_VERSION, ContractDiagnostic, ContractValidationError
from .documents import (
    DocumentBlock,
    DocumentBlockKind,
    DocumentExtractionResult,
    DocumentExtractionStatus,
    DocumentPage,
    DocumentPageStatus,
    DocumentProvenance,
    PdfBlock,
    PdfExtractionResult,
    PdfPageResult,
)
from .errors import ErrorEnvelope
from .evidence import Citation, EvidenceRef, SourceSpan
from .extensions import SchemaExtensionPoint
from .jobs import Job, LifecycleState, RetryMetadata, StageRun
from .providers import ProviderCapability, ProviderSpec
from .tools import ResourceProfile, ToolManifest

__all__ = [
    "CONTRACT_SCHEMA_VERSION",
    "ArtifactId",
    "ArtifactRef",
    "Checksum",
    "Citation",
    "ContractDiagnostic",
    "ContractValidationError",
    "DocumentBlock",
    "DocumentBlockKind",
    "DocumentExtractionResult",
    "DocumentExtractionStatus",
    "DocumentPage",
    "DocumentPageStatus",
    "DocumentProvenance",
    "ErrorEnvelope",
    "EvidenceRef",
    "FreshnessState",
    "Job",
    "LifecycleState",
    "Provenance",
    "ProviderCapability",
    "ProviderSpec",
    "PdfBlock",
    "PdfExtractionResult",
    "PdfPageResult",
    "ResourceProfile",
    "RetryMetadata",
    "SchemaExtensionPoint",
    "SourceSpan",
    "StageRun",
    "ToolManifest",
]
