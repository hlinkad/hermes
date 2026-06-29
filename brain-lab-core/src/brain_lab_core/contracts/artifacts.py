"""Artifact, checksum, freshness, and provenance contracts."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Mapping

from .base import (
    CONTRACT_SCHEMA_VERSION,
    ContractValidationError,
    JsonValue,
    _enum_value,
    _metadata,
    _non_negative_int,
    _optional_text,
    _required_text,
    _schema_version,
    _string_tuple,
    _validate_contract_type,
    contract_header,
    load_json_object,
    to_json,
)


class FreshnessState(str, Enum):
    """Whether a persisted artifact is current for its inputs/configuration."""

    CURRENT = "current"
    STALE = "stale"
    SUPERSEDED = "superseded"
    UNKNOWN = "unknown"


@dataclass(frozen=True, order=True)
class ArtifactId:
    """Stable identifier for a persisted artifact within a tool namespace."""

    value: str
    namespace: str = "default"
    schema_version: str = CONTRACT_SCHEMA_VERSION

    contract_type: ClassVar[str] = "brain_lab.artifact_id"

    def __post_init__(self) -> None:
        value = _required_text(self.value, "artifact_id.value")
        namespace = _required_text(self.namespace, "artifact_id.namespace")
        if ":" in value:
            raise ContractValidationError("artifact_id.value must not contain ':'")
        if ":" in namespace:
            raise ContractValidationError("artifact_id.namespace must not contain ':'")
        object.__setattr__(self, "value", value)
        object.__setattr__(self, "namespace", namespace)
        object.__setattr__(self, "schema_version", _schema_version(self.schema_version))

    @property
    def qualified(self) -> str:
        return f"{self.namespace}:{self.value}"

    def __str__(self) -> str:
        return self.qualified

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            **contract_header(self.contract_type, self.schema_version),
            "namespace": self.namespace,
            "value": self.value,
        }

    def to_json(self) -> str:
        return to_json(self.to_dict())

    @classmethod
    def from_json(cls, text: str) -> "ArtifactId":
        return cls.from_dict(load_json_object(text, cls.contract_type))

    @classmethod
    def from_dict(cls, data: Any) -> "ArtifactId":
        if isinstance(data, ArtifactId):
            return data
        if data is None:
            raise ContractValidationError("artifact_id.value is required")
        if isinstance(data, str):
            if ":" in data:
                namespace, value = data.split(":", 1)
                return cls(value=value, namespace=namespace)
            return cls(value=data)
        if not isinstance(data, Mapping):
            raise ContractValidationError("artifact_id must be a string or mapping")
        _validate_contract_type(data, cls.contract_type)
        return cls(
            value=data.get("value", ""),
            namespace=data.get("namespace", "default"),
            schema_version=data.get("schema_version", CONTRACT_SCHEMA_VERSION),
        )


@dataclass(frozen=True, order=True)
class Checksum:
    """Checksum attached to an artifact payload."""

    algorithm: str
    value: str
    schema_version: str = CONTRACT_SCHEMA_VERSION

    contract_type: ClassVar[str] = "brain_lab.checksum"

    def __post_init__(self) -> None:
        object.__setattr__(self, "algorithm", _required_text(self.algorithm, "checksum.algorithm"))
        object.__setattr__(self, "value", _required_text(self.value, "checksum.value"))
        object.__setattr__(self, "schema_version", _schema_version(self.schema_version))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            **contract_header(self.contract_type, self.schema_version),
            "algorithm": self.algorithm,
            "value": self.value,
        }

    def to_json(self) -> str:
        return to_json(self.to_dict())

    @classmethod
    def from_json(cls, text: str) -> "Checksum":
        return cls.from_dict(load_json_object(text, cls.contract_type))

    @classmethod
    def from_dict(cls, data: Any) -> "Checksum":
        if isinstance(data, Checksum):
            return data
        if not isinstance(data, Mapping):
            raise ContractValidationError("checksum must be a mapping")
        _validate_contract_type(data, cls.contract_type)
        return cls(
            algorithm=data.get("algorithm", ""),
            value=data.get("value", ""),
            schema_version=data.get("schema_version", CONTRACT_SCHEMA_VERSION),
        )


@dataclass(frozen=True)
class Provenance:
    """Who/what produced a contract record and from which upstream source refs."""

    tool_id: str = ""
    stage_id: str = ""
    provider_id: str = ""
    provider_version: str = ""
    source_refs: tuple[str, ...] = field(default_factory=tuple)
    created_at: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = CONTRACT_SCHEMA_VERSION

    contract_type: ClassVar[str] = "brain_lab.provenance"

    def __post_init__(self) -> None:
        object.__setattr__(self, "tool_id", _optional_text(self.tool_id))
        object.__setattr__(self, "stage_id", _optional_text(self.stage_id))
        object.__setattr__(self, "provider_id", _optional_text(self.provider_id))
        object.__setattr__(self, "provider_version", _optional_text(self.provider_version))
        object.__setattr__(self, "source_refs", _string_tuple(self.source_refs))
        object.__setattr__(self, "created_at", _optional_text(self.created_at))
        object.__setattr__(self, "metadata", _metadata(self.metadata))
        object.__setattr__(self, "schema_version", _schema_version(self.schema_version))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            **contract_header(self.contract_type, self.schema_version),
            "tool_id": self.tool_id,
            "stage_id": self.stage_id,
            "provider_id": self.provider_id,
            "provider_version": self.provider_version,
            "source_refs": list(self.source_refs),
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }

    def to_json(self) -> str:
        return to_json(self.to_dict())

    @classmethod
    def from_json(cls, text: str) -> "Provenance":
        return cls.from_dict(load_json_object(text, cls.contract_type))

    @classmethod
    def from_dict(cls, data: Any) -> "Provenance":
        if isinstance(data, Provenance):
            return data
        if data is None:
            return cls()
        if not isinstance(data, Mapping):
            raise ContractValidationError("provenance must be a mapping")
        _validate_contract_type(data, cls.contract_type)
        return cls(
            tool_id=data.get("tool_id", ""),
            stage_id=data.get("stage_id", ""),
            provider_id=data.get("provider_id", ""),
            provider_version=data.get("provider_version", ""),
            source_refs=tuple(data.get("source_refs", ())),
            created_at=data.get("created_at", ""),
            metadata=data.get("metadata", {}),
            schema_version=data.get("schema_version", CONTRACT_SCHEMA_VERSION),
        )


@dataclass(frozen=True)
class ArtifactRef:
    """Serializable reference to a canonical filesystem/object artifact."""

    artifact_id: ArtifactId
    artifact_type: str
    artifact_schema_version: str
    uri: str
    checksum: Checksum
    size_bytes: int = 0
    producer_tool_id: str = ""
    producer_stage_id: str = ""
    created_at: str = ""
    input_artifact_ids: tuple[ArtifactId, ...] = field(default_factory=tuple)
    config_fingerprint: str = ""
    freshness: FreshnessState = FreshnessState.UNKNOWN
    provenance: Provenance = field(default_factory=Provenance)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = CONTRACT_SCHEMA_VERSION

    contract_type: ClassVar[str] = "brain_lab.artifact_ref"

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact_id", ArtifactId.from_dict(self.artifact_id))
        object.__setattr__(self, "artifact_type", _required_text(self.artifact_type, "artifact_ref.artifact_type"))
        object.__setattr__(
            self,
            "artifact_schema_version",
            _required_text(self.artifact_schema_version, "artifact_ref.artifact_schema_version"),
        )
        object.__setattr__(self, "uri", _required_text(self.uri, "artifact_ref.uri"))
        object.__setattr__(self, "checksum", Checksum.from_dict(self.checksum))
        object.__setattr__(self, "size_bytes", _non_negative_int(self.size_bytes, "artifact_ref.size_bytes"))
        object.__setattr__(self, "producer_tool_id", _optional_text(self.producer_tool_id))
        object.__setattr__(self, "producer_stage_id", _optional_text(self.producer_stage_id))
        object.__setattr__(self, "created_at", _optional_text(self.created_at))
        object.__setattr__(
            self,
            "input_artifact_ids",
            tuple(ArtifactId.from_dict(value) for value in self.input_artifact_ids),
        )
        object.__setattr__(self, "config_fingerprint", _optional_text(self.config_fingerprint))
        object.__setattr__(self, "freshness", _enum_value(FreshnessState, self.freshness, "artifact_ref.freshness"))
        object.__setattr__(self, "provenance", Provenance.from_dict(self.provenance))
        object.__setattr__(self, "metadata", _metadata(self.metadata))
        object.__setattr__(self, "schema_version", _schema_version(self.schema_version))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            **contract_header(self.contract_type, self.schema_version),
            "artifact_id": self.artifact_id.to_dict(),
            "artifact_type": self.artifact_type,
            "artifact_schema_version": self.artifact_schema_version,
            "uri": self.uri,
            "checksum": self.checksum.to_dict(),
            "size_bytes": self.size_bytes,
            "producer_tool_id": self.producer_tool_id,
            "producer_stage_id": self.producer_stage_id,
            "created_at": self.created_at,
            "input_artifact_ids": [artifact_id.to_dict() for artifact_id in self.input_artifact_ids],
            "config_fingerprint": self.config_fingerprint,
            "freshness": self.freshness.value,
            "provenance": self.provenance.to_dict(),
            "metadata": dict(self.metadata),
        }

    def to_json(self) -> str:
        return to_json(self.to_dict())

    @classmethod
    def from_json(cls, text: str) -> "ArtifactRef":
        return cls.from_dict(load_json_object(text, cls.contract_type))

    @classmethod
    def from_dict(cls, data: Any) -> "ArtifactRef":
        if isinstance(data, ArtifactRef):
            return data
        if not isinstance(data, Mapping):
            raise ContractValidationError("artifact_ref must be a mapping")
        _validate_contract_type(data, cls.contract_type)
        return cls(
            artifact_id=ArtifactId.from_dict(data.get("artifact_id")),
            artifact_type=data.get("artifact_type", ""),
            artifact_schema_version=data.get("artifact_schema_version", ""),
            uri=data.get("uri", ""),
            checksum=Checksum.from_dict(data.get("checksum", {})),
            size_bytes=data.get("size_bytes", 0),
            producer_tool_id=data.get("producer_tool_id", ""),
            producer_stage_id=data.get("producer_stage_id", ""),
            created_at=data.get("created_at", ""),
            input_artifact_ids=tuple(ArtifactId.from_dict(value) for value in data.get("input_artifact_ids", ())),
            config_fingerprint=data.get("config_fingerprint", ""),
            freshness=data.get("freshness", FreshnessState.UNKNOWN.value),
            provenance=Provenance.from_dict(data.get("provenance", {})),
            metadata=data.get("metadata", {}),
            schema_version=data.get("schema_version", CONTRACT_SCHEMA_VERSION),
        )
