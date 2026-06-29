"""Extension points for concrete tool-owned schemas."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar, Mapping

from .base import (
    CONTRACT_SCHEMA_VERSION,
    ContractValidationError,
    JsonValue,
    _metadata,
    _optional_text,
    _required_text,
    _required_tuple,
    _schema_version,
    _string_tuple,
    _validate_contract_type,
    contract_header,
    load_json_object,
    to_json,
)


@dataclass(frozen=True)
class SchemaExtensionPoint:
    """Namespaced schema declarations owned by concrete tools.

    The foundation validates and stores this declaration, but the concrete tool
    owns the domain-specific schema behind the declared namespace/prefix. This
    prevents generic contracts from accumulating video-, PDF-, or web-specific
    fields while still making extension metadata discoverable.
    """

    namespace: str
    owner_tool_id: str
    artifact_types: tuple[str, ...] = field(default_factory=tuple)
    evidence_types: tuple[str, ...] = field(default_factory=tuple)
    field_prefixes: tuple[str, ...] = field(default_factory=tuple)
    metadata_schema_uris: tuple[str, ...] = field(default_factory=tuple)
    compatibility_notes: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = CONTRACT_SCHEMA_VERSION

    contract_type: ClassVar[str] = "brain_lab.schema_extension_point"

    def __post_init__(self) -> None:
        object.__setattr__(self, "namespace", _required_text(self.namespace, "schema_extension.namespace"))
        object.__setattr__(self, "owner_tool_id", _required_text(self.owner_tool_id, "schema_extension.owner_tool_id"))
        artifact_types = _string_tuple(self.artifact_types)
        evidence_types = _string_tuple(self.evidence_types)
        field_prefixes = _string_tuple(self.field_prefixes)
        metadata_schema_uris = _string_tuple(self.metadata_schema_uris)
        if not any((artifact_types, evidence_types, field_prefixes, metadata_schema_uris)):
            _required_tuple((), "schema_extension.extension_declarations")
        object.__setattr__(self, "artifact_types", artifact_types)
        object.__setattr__(self, "evidence_types", evidence_types)
        object.__setattr__(self, "field_prefixes", field_prefixes)
        object.__setattr__(self, "metadata_schema_uris", metadata_schema_uris)
        object.__setattr__(self, "compatibility_notes", _optional_text(self.compatibility_notes))
        object.__setattr__(self, "metadata", _metadata(self.metadata))
        object.__setattr__(self, "schema_version", _schema_version(self.schema_version))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            **contract_header(self.contract_type, self.schema_version),
            "namespace": self.namespace,
            "owner_tool_id": self.owner_tool_id,
            "artifact_types": list(self.artifact_types),
            "evidence_types": list(self.evidence_types),
            "field_prefixes": list(self.field_prefixes),
            "metadata_schema_uris": list(self.metadata_schema_uris),
            "compatibility_notes": self.compatibility_notes,
            "metadata": dict(self.metadata),
        }

    def to_json(self) -> str:
        return to_json(self.to_dict())

    @classmethod
    def from_json(cls, text: str) -> "SchemaExtensionPoint":
        return cls.from_dict(load_json_object(text, cls.contract_type))

    @classmethod
    def from_dict(cls, data: Any) -> "SchemaExtensionPoint":
        if isinstance(data, SchemaExtensionPoint):
            return data
        if not isinstance(data, Mapping):
            raise ContractValidationError("schema_extension_point must be a mapping")
        _validate_contract_type(data, cls.contract_type)
        return cls(
            namespace=data.get("namespace", ""),
            owner_tool_id=data.get("owner_tool_id", ""),
            artifact_types=tuple(data.get("artifact_types", ())),
            evidence_types=tuple(data.get("evidence_types", ())),
            field_prefixes=tuple(data.get("field_prefixes", ())),
            metadata_schema_uris=tuple(data.get("metadata_schema_uris", ())),
            compatibility_notes=data.get("compatibility_notes", ""),
            metadata=data.get("metadata", {}),
            schema_version=data.get("schema_version", CONTRACT_SCHEMA_VERSION),
        )
