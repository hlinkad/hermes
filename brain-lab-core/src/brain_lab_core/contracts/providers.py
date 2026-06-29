"""Provider and adapter capability contracts."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar, Mapping

from .base import (
    CONTRACT_SCHEMA_VERSION,
    ContractDiagnostic,
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
class ProviderCapability:
    """One capability exposed by a concrete provider adapter."""

    name: str
    version: str = "v1"
    input_artifact_types: tuple[str, ...] = field(default_factory=tuple)
    output_artifact_types: tuple[str, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = CONTRACT_SCHEMA_VERSION

    contract_type: ClassVar[str] = "brain_lab.provider_capability"

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _required_text(self.name, "provider_capability.name"))
        object.__setattr__(self, "version", _required_text(self.version, "provider_capability.version"))
        object.__setattr__(self, "input_artifact_types", _string_tuple(self.input_artifact_types))
        object.__setattr__(self, "output_artifact_types", _string_tuple(self.output_artifact_types))
        object.__setattr__(self, "metadata", _metadata(self.metadata))
        object.__setattr__(self, "schema_version", _schema_version(self.schema_version))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            **contract_header(self.contract_type, self.schema_version),
            "name": self.name,
            "version": self.version,
            "input_artifact_types": list(self.input_artifact_types),
            "output_artifact_types": list(self.output_artifact_types),
            "metadata": dict(self.metadata),
        }

    def to_json(self) -> str:
        return to_json(self.to_dict())

    @classmethod
    def from_json(cls, text: str) -> "ProviderCapability":
        return cls.from_dict(load_json_object(text, cls.contract_type))

    @classmethod
    def from_dict(cls, data: Any) -> "ProviderCapability":
        if isinstance(data, ProviderCapability):
            return data
        if not isinstance(data, Mapping):
            raise ContractValidationError("provider_capability must be a mapping")
        _validate_contract_type(data, cls.contract_type)
        return cls(
            name=data.get("name", ""),
            version=data.get("version", "v1"),
            input_artifact_types=tuple(data.get("input_artifact_types", ())),
            output_artifact_types=tuple(data.get("output_artifact_types", ())),
            metadata=data.get("metadata", {}),
            schema_version=data.get("schema_version", CONTRACT_SCHEMA_VERSION),
        )


@dataclass(frozen=True)
class ProviderSpec:
    """Adapter metadata for LLM, ASR, vector, parser, or storage providers."""

    provider_id: str
    provider_type: str
    capabilities: tuple[ProviderCapability, ...]
    adapter_module: str = ""
    provider_version: str = ""
    resource_profile: Mapping[str, Any] = field(default_factory=dict)
    required_secret_names: tuple[str, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = CONTRACT_SCHEMA_VERSION

    contract_type: ClassVar[str] = "brain_lab.provider_spec"

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider_id", _required_text(self.provider_id, "provider_spec.provider_id"))
        object.__setattr__(self, "provider_type", _required_text(self.provider_type, "provider_spec.provider_type"))
        capabilities = tuple(ProviderCapability.from_dict(value) for value in self.capabilities)
        if not capabilities:
            _required_tuple((), "provider_spec.capabilities")
        object.__setattr__(self, "capabilities", capabilities)
        object.__setattr__(self, "adapter_module", _optional_text(self.adapter_module))
        object.__setattr__(self, "provider_version", _optional_text(self.provider_version))
        object.__setattr__(self, "resource_profile", _metadata(self.resource_profile))
        object.__setattr__(self, "required_secret_names", _string_tuple(self.required_secret_names))
        object.__setattr__(self, "metadata", _metadata(self.metadata))
        object.__setattr__(self, "schema_version", _schema_version(self.schema_version))

    def validate(self) -> tuple[ContractDiagnostic, ...]:
        return ()

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            **contract_header(self.contract_type, self.schema_version),
            "provider_id": self.provider_id,
            "provider_type": self.provider_type,
            "capabilities": [capability.to_dict() for capability in self.capabilities],
            "adapter_module": self.adapter_module,
            "provider_version": self.provider_version,
            "resource_profile": dict(self.resource_profile),
            "required_secret_names": list(self.required_secret_names),
            "metadata": dict(self.metadata),
        }

    def to_json(self) -> str:
        return to_json(self.to_dict())

    @classmethod
    def from_json(cls, text: str) -> "ProviderSpec":
        return cls.from_dict(load_json_object(text, cls.contract_type))

    @classmethod
    def from_dict(cls, data: Any) -> "ProviderSpec":
        if isinstance(data, ProviderSpec):
            return data
        if not isinstance(data, Mapping):
            raise ContractValidationError("provider_spec must be a mapping")
        _validate_contract_type(data, cls.contract_type)
        return cls(
            provider_id=data.get("provider_id", ""),
            provider_type=data.get("provider_type", ""),
            capabilities=tuple(ProviderCapability.from_dict(value) for value in data.get("capabilities", ())),
            adapter_module=data.get("adapter_module", ""),
            provider_version=data.get("provider_version", ""),
            resource_profile=data.get("resource_profile", {}),
            required_secret_names=tuple(data.get("required_secret_names", ())),
            metadata=data.get("metadata", {}),
            schema_version=data.get("schema_version", CONTRACT_SCHEMA_VERSION),
        )
