"""Tool manifest and resource profile contracts."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar, Mapping

from .base import (
    CONTRACT_SCHEMA_VERSION,
    ContractDiagnostic,
    ContractValidationError,
    JsonValue,
    _bool_value,
    _metadata,
    _non_negative_float,
    _non_negative_int,
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


SUPPORTED_TOOL_ENTRYPOINT_KINDS = ("python", "package", "cli", "container_image")


@dataclass(frozen=True)
class ResourceProfile:
    """Portable resource declaration for local workers or containers."""

    cpu_cores: float = 1.0
    memory_mb: int = 0
    disk_mb: int = 0
    gpu_required: bool = False
    network_required: bool = False
    timeout_seconds: int = 0
    schema_version: str = CONTRACT_SCHEMA_VERSION

    contract_type: ClassVar[str] = "brain_lab.resource_profile"

    def __post_init__(self) -> None:
        object.__setattr__(self, "cpu_cores", _non_negative_float(self.cpu_cores, "resource_profile.cpu_cores"))
        object.__setattr__(self, "memory_mb", _non_negative_int(self.memory_mb, "resource_profile.memory_mb"))
        object.__setattr__(self, "disk_mb", _non_negative_int(self.disk_mb, "resource_profile.disk_mb"))
        object.__setattr__(self, "gpu_required", _bool_value(self.gpu_required, "resource_profile.gpu_required"))
        object.__setattr__(
            self,
            "network_required",
            _bool_value(self.network_required, "resource_profile.network_required"),
        )
        object.__setattr__(self, "timeout_seconds", _non_negative_int(self.timeout_seconds, "resource_profile.timeout_seconds"))
        object.__setattr__(self, "schema_version", _schema_version(self.schema_version))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            **contract_header(self.contract_type, self.schema_version),
            "cpu_cores": self.cpu_cores,
            "memory_mb": self.memory_mb,
            "disk_mb": self.disk_mb,
            "gpu_required": self.gpu_required,
            "network_required": self.network_required,
            "timeout_seconds": self.timeout_seconds,
        }

    def to_json(self) -> str:
        return to_json(self.to_dict())

    @classmethod
    def from_json(cls, text: str) -> "ResourceProfile":
        return cls.from_dict(load_json_object(text, cls.contract_type))

    @classmethod
    def from_dict(cls, data: Any) -> "ResourceProfile":
        if isinstance(data, ResourceProfile):
            return data
        if data is None:
            return cls()
        if not isinstance(data, Mapping):
            raise ContractValidationError("resource_profile must be a mapping")
        _validate_contract_type(data, cls.contract_type)
        return cls(
            cpu_cores=data.get("cpu_cores", 1.0),
            memory_mb=data.get("memory_mb", 0),
            disk_mb=data.get("disk_mb", 0),
            gpu_required=data.get("gpu_required", False),
            network_required=data.get("network_required", False),
            timeout_seconds=data.get("timeout_seconds", 0),
            schema_version=data.get("schema_version", CONTRACT_SCHEMA_VERSION),
        )


@dataclass(frozen=True)
class ToolManifest:
    """Declaration concrete tools use to register with the foundation."""

    tool_id: str
    tool_version: str
    capabilities: tuple[str, ...]
    input_artifact_types: tuple[str, ...]
    output_artifact_types: tuple[str, ...]
    entrypoints: Mapping[str, str]
    resource_profile: ResourceProfile = field(default_factory=ResourceProfile)
    license_notes: str = ""
    required_secret_names: tuple[str, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = CONTRACT_SCHEMA_VERSION

    contract_type: ClassVar[str] = "brain_lab.tool_manifest"

    def __post_init__(self) -> None:
        object.__setattr__(self, "tool_id", _required_text(self.tool_id, "tool_manifest.tool_id"))
        object.__setattr__(self, "tool_version", _required_text(self.tool_version, "tool_manifest.tool_version"))
        object.__setattr__(self, "capabilities", _required_tuple(self.capabilities, "tool_manifest.capabilities"))
        object.__setattr__(
            self,
            "input_artifact_types",
            _required_tuple(self.input_artifact_types, "tool_manifest.input_artifact_types"),
        )
        object.__setattr__(
            self,
            "output_artifact_types",
            _required_tuple(self.output_artifact_types, "tool_manifest.output_artifact_types"),
        )
        if not self.entrypoints:
            raise ContractValidationError("tool_manifest.entrypoints must contain at least one entrypoint")
        if not isinstance(self.entrypoints, Mapping):
            raise ContractValidationError("tool_manifest.entrypoints must be a mapping")
        entrypoints = {str(key): _required_text(value, f"tool_manifest.entrypoints.{key}") for key, value in self.entrypoints.items()}
        object.__setattr__(self, "entrypoints", dict(sorted(entrypoints.items())))
        object.__setattr__(self, "resource_profile", ResourceProfile.from_dict(self.resource_profile))
        object.__setattr__(self, "license_notes", _optional_text(self.license_notes))
        object.__setattr__(self, "required_secret_names", _string_tuple(self.required_secret_names))
        object.__setattr__(self, "metadata", _metadata(self.metadata))
        object.__setattr__(self, "schema_version", _schema_version(self.schema_version))

    def validate(self) -> tuple[ContractDiagnostic, ...]:
        supported_entrypoints = set(SUPPORTED_TOOL_ENTRYPOINT_KINDS)
        observed_entrypoints = set(self.entrypoints)
        diagnostics: list[ContractDiagnostic] = []

        unsupported = tuple(sorted(observed_entrypoints.difference(supported_entrypoints)))
        if unsupported:
            supported = ", ".join(SUPPORTED_TOOL_ENTRYPOINT_KINDS)
            diagnostics.append(
                ContractDiagnostic(
                    code="tool_manifest.entrypoints.unsupported",
                    message=(
                        "unsupported tool_manifest.entrypoints kind(s): "
                        f"{', '.join(unsupported)}; supported kinds: {supported}"
                    ),
                    severity="error",
                    location="entrypoints",
                )
            )

        if not observed_entrypoints.intersection(supported_entrypoints):
            supported = ", ".join(SUPPORTED_TOOL_ENTRYPOINT_KINDS)
            diagnostics.append(
                ContractDiagnostic(
                    code="tool_manifest.entrypoints.missing_supported",
                    message=(
                        "tool_manifest.entrypoints must include at least one supported "
                        f"entrypoint kind: {supported}"
                    ),
                    severity="error",
                    location="entrypoints",
                )
            )
        return tuple(diagnostics)

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            **contract_header(self.contract_type, self.schema_version),
            "tool_id": self.tool_id,
            "tool_version": self.tool_version,
            "capabilities": list(self.capabilities),
            "input_artifact_types": list(self.input_artifact_types),
            "output_artifact_types": list(self.output_artifact_types),
            "entrypoints": dict(self.entrypoints),
            "resource_profile": self.resource_profile.to_dict(),
            "license_notes": self.license_notes,
            "required_secret_names": list(self.required_secret_names),
            "metadata": dict(self.metadata),
        }

    def to_json(self) -> str:
        return to_json(self.to_dict())

    @classmethod
    def from_json(cls, text: str) -> "ToolManifest":
        return cls.from_dict(load_json_object(text, cls.contract_type))

    @classmethod
    def from_dict(cls, data: Any) -> "ToolManifest":
        if isinstance(data, ToolManifest):
            return data
        if not isinstance(data, Mapping):
            raise ContractValidationError("tool_manifest must be a mapping")
        _validate_contract_type(data, cls.contract_type)
        return cls(
            tool_id=data.get("tool_id", ""),
            tool_version=data.get("tool_version", ""),
            capabilities=tuple(data.get("capabilities", ())),
            input_artifact_types=tuple(data.get("input_artifact_types", ())),
            output_artifact_types=tuple(data.get("output_artifact_types", ())),
            entrypoints=data.get("entrypoints", {}),
            resource_profile=ResourceProfile.from_dict(data.get("resource_profile", {})),
            license_notes=data.get("license_notes", ""),
            required_secret_names=tuple(data.get("required_secret_names", ())),
            metadata=data.get("metadata", {}),
            schema_version=data.get("schema_version", CONTRACT_SCHEMA_VERSION),
        )
