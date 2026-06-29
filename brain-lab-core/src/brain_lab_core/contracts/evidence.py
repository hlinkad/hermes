"""Evidence, source-span, and citation contracts."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, ClassVar, Mapping

from .artifacts import ArtifactId, Provenance
from .base import (
    CONTRACT_SCHEMA_VERSION,
    ContractValidationError,
    JsonValue,
    _confidence,
    _metadata,
    _optional_text,
    _required_text,
    _schema_version,
    _validate_contract_type,
    contract_header,
    load_json_object,
    to_json,
)

_VALID_SPAN_KINDS = {"text", "time", "page", "frame", "byte", "unknown"}


def _span_boundary(value: Any, field_name: str) -> int | float | str | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ContractValidationError(f"{field_name} must be a finite number, string label, or null")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ContractValidationError(f"{field_name} must be finite")
        return value
    if isinstance(value, str):
        return value
    raise ContractValidationError(f"{field_name} must be a finite number, string label, or null")


def _numeric_boundary(value: int | float | str | None) -> float | None:
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return None
    return float(value)


@dataclass(frozen=True)
class SourceSpan:
    """Location inside a source artifact, such as text offsets or media timestamps."""

    kind: str = "unknown"
    start: int | float | str | None = None
    end: int | float | str | None = None
    unit: str = ""
    label: str = ""
    schema_version: str = CONTRACT_SCHEMA_VERSION

    contract_type: ClassVar[str] = "brain_lab.source_span"

    def __post_init__(self) -> None:
        kind = _optional_text(self.kind) or "unknown"
        if kind not in _VALID_SPAN_KINDS:
            valid = ", ".join(sorted(_VALID_SPAN_KINDS))
            raise ContractValidationError(f"source_span.kind must be one of: {valid}")
        object.__setattr__(self, "kind", kind)
        start = _span_boundary(self.start, "source_span.start")
        end = _span_boundary(self.end, "source_span.end")
        numeric_start = _numeric_boundary(start)
        numeric_end = _numeric_boundary(end)
        if numeric_start is not None and numeric_end is not None and numeric_end < numeric_start:
            raise ContractValidationError("source_span.end must be greater than or equal to source_span.start")
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)
        object.__setattr__(self, "unit", _optional_text(self.unit))
        object.__setattr__(self, "label", _optional_text(self.label))
        object.__setattr__(self, "schema_version", _schema_version(self.schema_version))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            **contract_header(self.contract_type, self.schema_version),
            "kind": self.kind,
            "start": self.start,
            "end": self.end,
            "unit": self.unit,
            "label": self.label,
        }

    def to_json(self) -> str:
        return to_json(self.to_dict())

    @classmethod
    def from_json(cls, text: str) -> "SourceSpan":
        return cls.from_dict(load_json_object(text, cls.contract_type))

    @classmethod
    def from_dict(cls, data: Any) -> "SourceSpan":
        if isinstance(data, SourceSpan):
            return data
        if data is None:
            return cls()
        if not isinstance(data, Mapping):
            raise ContractValidationError("source_span must be a mapping")
        _validate_contract_type(data, cls.contract_type)
        return cls(
            kind=data.get("kind", "unknown"),
            start=data.get("start"),
            end=data.get("end"),
            unit=data.get("unit", ""),
            label=data.get("label", ""),
            schema_version=data.get("schema_version", CONTRACT_SCHEMA_VERSION),
        )


@dataclass(frozen=True)
class Citation:
    """Human-readable citation pointing back to a source artifact span."""

    citation_id: str
    label: str
    artifact_id: ArtifactId
    span: SourceSpan = field(default_factory=SourceSpan)
    quote: str = ""
    confidence: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = CONTRACT_SCHEMA_VERSION

    contract_type: ClassVar[str] = "brain_lab.citation"

    def __post_init__(self) -> None:
        object.__setattr__(self, "citation_id", _required_text(self.citation_id, "citation.citation_id"))
        object.__setattr__(self, "label", _required_text(self.label, "citation.label"))
        object.__setattr__(self, "artifact_id", ArtifactId.from_dict(self.artifact_id))
        object.__setattr__(self, "span", SourceSpan.from_dict(self.span))
        object.__setattr__(self, "quote", str(self.quote or ""))
        object.__setattr__(self, "confidence", _confidence(self.confidence, "citation.confidence"))
        object.__setattr__(self, "metadata", _metadata(self.metadata))
        object.__setattr__(self, "schema_version", _schema_version(self.schema_version))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            **contract_header(self.contract_type, self.schema_version),
            "citation_id": self.citation_id,
            "label": self.label,
            "artifact_id": self.artifact_id.to_dict(),
            "span": self.span.to_dict(),
            "quote": self.quote,
            "confidence": self.confidence,
            "metadata": dict(self.metadata),
        }

    def to_json(self) -> str:
        return to_json(self.to_dict())

    @classmethod
    def from_json(cls, text: str) -> "Citation":
        return cls.from_dict(load_json_object(text, cls.contract_type))

    @classmethod
    def from_dict(cls, data: Any) -> "Citation":
        if isinstance(data, Citation):
            return data
        if not isinstance(data, Mapping):
            raise ContractValidationError("citation must be a mapping")
        _validate_contract_type(data, cls.contract_type)
        return cls(
            citation_id=data.get("citation_id", ""),
            label=data.get("label", ""),
            artifact_id=ArtifactId.from_dict(data.get("artifact_id")),
            span=SourceSpan.from_dict(data.get("span", {})),
            quote=data.get("quote", ""),
            confidence=data.get("confidence"),
            metadata=data.get("metadata", {}),
            schema_version=data.get("schema_version", CONTRACT_SCHEMA_VERSION),
        )


@dataclass(frozen=True)
class EvidenceRef:
    """Cross-tool citation primitive used by retrieval and answer generation."""

    evidence_id: str
    source_artifact_id: ArtifactId
    source_type: str
    span: SourceSpan = field(default_factory=SourceSpan)
    quote: str = ""
    confidence: float | None = None
    provenance: Provenance = field(default_factory=Provenance)
    citations: tuple[Citation, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = CONTRACT_SCHEMA_VERSION

    contract_type: ClassVar[str] = "brain_lab.evidence_ref"

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_id", _required_text(self.evidence_id, "evidence_ref.evidence_id"))
        object.__setattr__(self, "source_artifact_id", ArtifactId.from_dict(self.source_artifact_id))
        object.__setattr__(self, "source_type", _required_text(self.source_type, "evidence_ref.source_type"))
        object.__setattr__(self, "span", SourceSpan.from_dict(self.span))
        object.__setattr__(self, "quote", str(self.quote or ""))
        object.__setattr__(self, "confidence", _confidence(self.confidence, "evidence_ref.confidence"))
        object.__setattr__(self, "provenance", Provenance.from_dict(self.provenance))
        object.__setattr__(self, "citations", tuple(Citation.from_dict(value) for value in self.citations))
        object.__setattr__(self, "metadata", _metadata(self.metadata))
        object.__setattr__(self, "schema_version", _schema_version(self.schema_version))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            **contract_header(self.contract_type, self.schema_version),
            "evidence_id": self.evidence_id,
            "source_artifact_id": self.source_artifact_id.to_dict(),
            "source_type": self.source_type,
            "span": self.span.to_dict(),
            "quote": self.quote,
            "confidence": self.confidence,
            "provenance": self.provenance.to_dict(),
            "citations": [citation.to_dict() for citation in self.citations],
            "metadata": dict(self.metadata),
        }

    def to_json(self) -> str:
        return to_json(self.to_dict())

    @classmethod
    def from_json(cls, text: str) -> "EvidenceRef":
        return cls.from_dict(load_json_object(text, cls.contract_type))

    @classmethod
    def from_dict(cls, data: Any) -> "EvidenceRef":
        if isinstance(data, EvidenceRef):
            return data
        if not isinstance(data, Mapping):
            raise ContractValidationError("evidence_ref must be a mapping")
        _validate_contract_type(data, cls.contract_type)
        return cls(
            evidence_id=data.get("evidence_id", ""),
            source_artifact_id=ArtifactId.from_dict(data.get("source_artifact_id")),
            source_type=data.get("source_type", ""),
            span=SourceSpan.from_dict(data.get("span", {})),
            quote=data.get("quote", ""),
            confidence=data.get("confidence"),
            provenance=Provenance.from_dict(data.get("provenance", {})),
            citations=tuple(Citation.from_dict(value) for value in data.get("citations", ())),
            metadata=data.get("metadata", {}),
            schema_version=data.get("schema_version", CONTRACT_SCHEMA_VERSION),
        )
