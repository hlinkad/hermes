"""Security, sandbox, source-policy, and redaction primitives.

The foundation stays stdlib-only and deliberately lightweight here: these classes
are declaration and validation hooks, not a full enterprise policy engine. Concrete
transports and tools can use them to publish resource requirements, redact status
surfaces, and attach source/license policy metadata before heavier enforcement is
added around concrete runners.
"""
from __future__ import annotations

import math
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar

from brain_lab_core.contracts.base import (
    CONTRACT_SCHEMA_VERSION,
    ContractDiagnostic,
    ContractValidationError,
    JsonValue,
    _bool_value,
    _enum_value,
    _metadata,
    _optional_text,
    _schema_version,
    _string_tuple,
    _validate_contract_type,
    contract_header,
    load_json_object,
    to_json,
)

REDACTED = "[REDACTED]"

_PUBLIC_SECRET_METADATA_KEYS = frozenset(
    {
        "redaction_hint",
        "redaction_marker",
        "required_secret_names",
        "secret_declarations",
        "secret_names",
        "secret_policy",
    }
)
_SENSITIVE_KEY_FRAGMENTS = (
    "api_key",
    "apikey",
    "auth_token",
    "authorization",
    "bearer",
    "client_secret",
    "credential",
    "password",
    "private_key",
    "refresh_token",
    "secret",
    "token",
)


class SandboxClass(str, Enum):
    """Coarse sandbox class advertised by a tool manifest."""

    LOCKED_DOWN = "locked_down"
    LOCAL_READ = "local_read"
    LOCAL_READ_WRITE = "local_read_write"
    NETWORKED = "networked"
    TRUSTED = "trusted"


class FileAccessMode(str, Enum):
    """Filesystem access requested by a tool or stage."""

    NONE = "none"
    READ = "read"
    WRITE = "write"
    READ_WRITE = "read_write"


class NetworkAccessMode(str, Enum):
    """Network access requested by a tool or stage."""

    NONE = "none"
    LOOPBACK = "loopback"
    OUTBOUND = "outbound"


class SourcePolicyStatus(str, Enum):
    """Tri-state-plus source permission status.

    ``UNKNOWN`` is intentionally distinct from ``DISALLOWED`` so unchecked source
    policies are not silently treated as either approved or blocked.
    """

    UNKNOWN = "unknown"
    ALLOWED = "allowed"
    DISALLOWED = "disallowed"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class SecretDeclaration:
    """Named secret required by a tool/provider without carrying its value."""

    name: str
    required: bool = True
    description: str = ""
    provider_id: str = ""
    redaction_hint: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = CONTRACT_SCHEMA_VERSION

    contract_type: ClassVar[str] = "brain_lab.secret_declaration"

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _required_identifier_text(self.name, "secret.name"))
        object.__setattr__(self, "required", _bool_value(self.required, "secret.required"))
        object.__setattr__(self, "description", _optional_text(self.description))
        object.__setattr__(self, "provider_id", _optional_text(self.provider_id))
        object.__setattr__(self, "redaction_hint", _optional_text(self.redaction_hint))
        object.__setattr__(self, "metadata", _metadata(self.metadata))
        object.__setattr__(self, "schema_version", _schema_version(self.schema_version))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            **contract_header(self.contract_type, self.schema_version),
            "name": self.name,
            "required": self.required,
            "description": self.description,
            "provider_id": self.provider_id,
            "redaction_hint": self.redaction_hint,
            "metadata": dict(self.metadata),
        }

    def to_json(self) -> str:
        return to_json(self.to_dict())

    @classmethod
    def from_json(cls, text: str) -> "SecretDeclaration":
        return cls.from_dict(load_json_object(text, cls.contract_type))

    @classmethod
    def from_dict(cls, data: Any) -> "SecretDeclaration":
        if isinstance(data, SecretDeclaration):
            return data
        if not isinstance(data, Mapping):
            raise ContractValidationError("secret declaration must be a mapping")
        _validate_contract_type(data, cls.contract_type)
        return cls(
            name=data.get("name", ""),
            required=data.get("required", True),
            description=data.get("description", ""),
            provider_id=data.get("provider_id", ""),
            redaction_hint=data.get("redaction_hint", ""),
            metadata=data.get("metadata", {}),
            schema_version=data.get("schema_version", CONTRACT_SCHEMA_VERSION),
        )


@dataclass(frozen=True)
class DependencyMetadata:
    """SBOM/dependency hook attached to manifests without resolving packages."""

    name: str
    version: str = ""
    package_url: str = ""
    license_name: str = ""
    supplier: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = CONTRACT_SCHEMA_VERSION

    contract_type: ClassVar[str] = "brain_lab.dependency_metadata"

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _required_identifier_text(self.name, "dependency.name"))
        object.__setattr__(self, "version", _optional_text(self.version))
        object.__setattr__(self, "package_url", _optional_text(self.package_url))
        object.__setattr__(self, "license_name", _optional_text(self.license_name))
        object.__setattr__(self, "supplier", _optional_text(self.supplier))
        object.__setattr__(self, "metadata", _metadata(self.metadata))
        object.__setattr__(self, "schema_version", _schema_version(self.schema_version))

    def validate(self) -> tuple[ContractDiagnostic, ...]:
        diagnostics: list[ContractDiagnostic] = []
        if not self.package_url:
            diagnostics.append(
                ContractDiagnostic(
                    code="dependency_metadata.package_url.missing",
                    message=f"dependency {self.name!r} has no package_url/SBOM package identifier",
                    severity="warning",
                    location="dependency_metadata.package_url",
                )
            )
        if not self.license_name:
            diagnostics.append(
                ContractDiagnostic(
                    code="dependency_metadata.license.missing",
                    message=f"dependency {self.name!r} has no declared license",
                    severity="warning",
                    location="dependency_metadata.license_name",
                )
            )
        return tuple(diagnostics)

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            **contract_header(self.contract_type, self.schema_version),
            "name": self.name,
            "version": self.version,
            "package_url": self.package_url,
            "license_name": self.license_name,
            "supplier": self.supplier,
            "metadata": dict(self.metadata),
        }

    def to_json(self) -> str:
        return to_json(self.to_dict())

    @classmethod
    def from_json(cls, text: str) -> "DependencyMetadata":
        return cls.from_dict(load_json_object(text, cls.contract_type))

    @classmethod
    def from_dict(cls, data: Any) -> "DependencyMetadata":
        if isinstance(data, DependencyMetadata):
            return data
        if not isinstance(data, Mapping):
            raise ContractValidationError("dependency metadata must be a mapping")
        _validate_contract_type(data, cls.contract_type)
        return cls(
            name=data.get("name", ""),
            version=data.get("version", ""),
            package_url=data.get("package_url", ""),
            license_name=data.get("license_name", ""),
            supplier=data.get("supplier", ""),
            metadata=data.get("metadata", {}),
            schema_version=data.get("schema_version", CONTRACT_SCHEMA_VERSION),
        )


@dataclass(frozen=True)
class FileAccessPolicy:
    """Filesystem access declaration for local-first tools."""

    mode: FileAccessMode = FileAccessMode.NONE
    allowed_paths: tuple[str, ...] = field(default_factory=tuple)
    denied_paths: tuple[str, ...] = field(default_factory=tuple)
    allow_temp: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = CONTRACT_SCHEMA_VERSION

    contract_type: ClassVar[str] = "brain_lab.file_access_policy"

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode", _enum_value(FileAccessMode, self.mode, "file_access.mode"))
        object.__setattr__(self, "allowed_paths", _string_tuple(self.allowed_paths))
        object.__setattr__(self, "denied_paths", _string_tuple(self.denied_paths))
        object.__setattr__(self, "allow_temp", _bool_value(self.allow_temp, "file_access.allow_temp"))
        object.__setattr__(self, "metadata", _metadata(self.metadata))
        object.__setattr__(self, "schema_version", _schema_version(self.schema_version))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            **contract_header(self.contract_type, self.schema_version),
            "mode": self.mode.value,
            "allowed_paths": list(self.allowed_paths),
            "denied_paths": list(self.denied_paths),
            "allow_temp": self.allow_temp,
            "metadata": dict(self.metadata),
        }

    def to_json(self) -> str:
        return to_json(self.to_dict())

    @classmethod
    def from_json(cls, text: str) -> "FileAccessPolicy":
        return cls.from_dict(load_json_object(text, cls.contract_type))

    @classmethod
    def from_dict(cls, data: Any) -> "FileAccessPolicy":
        if isinstance(data, FileAccessPolicy):
            return data
        if data is None:
            return cls()
        if not isinstance(data, Mapping):
            raise ContractValidationError("file access policy must be a mapping")
        _validate_contract_type(data, cls.contract_type)
        return cls(
            mode=data.get("mode", FileAccessMode.NONE.value),
            allowed_paths=tuple(data.get("allowed_paths", ())),
            denied_paths=tuple(data.get("denied_paths", ())),
            allow_temp=data.get("allow_temp", True),
            metadata=data.get("metadata", {}),
            schema_version=data.get("schema_version", CONTRACT_SCHEMA_VERSION),
        )


@dataclass(frozen=True)
class NetworkPolicy:
    """Network access declaration for local workers and future sandboxes."""

    mode: NetworkAccessMode = NetworkAccessMode.NONE
    allowed_hosts: tuple[str, ...] = field(default_factory=tuple)
    denied_hosts: tuple[str, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = CONTRACT_SCHEMA_VERSION

    contract_type: ClassVar[str] = "brain_lab.network_policy"

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode", _enum_value(NetworkAccessMode, self.mode, "network_policy.mode"))
        object.__setattr__(self, "allowed_hosts", _string_tuple(self.allowed_hosts))
        object.__setattr__(self, "denied_hosts", _string_tuple(self.denied_hosts))
        object.__setattr__(self, "metadata", _metadata(self.metadata))
        object.__setattr__(self, "schema_version", _schema_version(self.schema_version))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            **contract_header(self.contract_type, self.schema_version),
            "mode": self.mode.value,
            "allowed_hosts": list(self.allowed_hosts),
            "denied_hosts": list(self.denied_hosts),
            "metadata": dict(self.metadata),
        }

    def to_json(self) -> str:
        return to_json(self.to_dict())

    @classmethod
    def from_json(cls, text: str) -> "NetworkPolicy":
        return cls.from_dict(load_json_object(text, cls.contract_type))

    @classmethod
    def from_dict(cls, data: Any) -> "NetworkPolicy":
        if isinstance(data, NetworkPolicy):
            return data
        if data is None:
            return cls()
        if not isinstance(data, Mapping):
            raise ContractValidationError("network policy must be a mapping")
        _validate_contract_type(data, cls.contract_type)
        return cls(
            mode=data.get("mode", NetworkAccessMode.NONE.value),
            allowed_hosts=tuple(data.get("allowed_hosts", ())),
            denied_hosts=tuple(data.get("denied_hosts", ())),
            metadata=data.get("metadata", {}),
            schema_version=data.get("schema_version", CONTRACT_SCHEMA_VERSION),
        )


@dataclass(frozen=True)
class SandboxPolicy:
    """Sandbox/resource policy declaration attached to a tool manifest."""

    sandbox_class: SandboxClass = SandboxClass.LOCKED_DOWN
    filesystem: FileAccessPolicy = field(default_factory=FileAccessPolicy)
    network: NetworkPolicy = field(default_factory=NetworkPolicy)
    allow_subprocess: bool = False
    allow_gpu: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = CONTRACT_SCHEMA_VERSION

    contract_type: ClassVar[str] = "brain_lab.sandbox_policy"

    def __post_init__(self) -> None:
        object.__setattr__(self, "sandbox_class", _enum_value(SandboxClass, self.sandbox_class, "sandbox.class"))
        object.__setattr__(self, "filesystem", FileAccessPolicy.from_dict(self.filesystem))
        object.__setattr__(self, "network", NetworkPolicy.from_dict(self.network))
        object.__setattr__(self, "allow_subprocess", _bool_value(self.allow_subprocess, "sandbox.allow_subprocess"))
        object.__setattr__(self, "allow_gpu", _bool_value(self.allow_gpu, "sandbox.allow_gpu"))
        object.__setattr__(self, "metadata", _metadata(self.metadata))
        object.__setattr__(self, "schema_version", _schema_version(self.schema_version))

    def validate(self, *, resource_profile: Any | None = None) -> tuple[ContractDiagnostic, ...]:
        diagnostics: list[ContractDiagnostic] = []
        if self.sandbox_class == SandboxClass.LOCKED_DOWN:
            if self.filesystem.mode != FileAccessMode.NONE:
                diagnostics.append(_policy_error("sandbox.locked_down.filesystem", "locked_down sandbox cannot request filesystem access", "sandbox_policy.filesystem.mode"))
            if self.network.mode != NetworkAccessMode.NONE:
                diagnostics.append(_policy_error("sandbox.locked_down.network", "locked_down sandbox cannot request network access", "sandbox_policy.network.mode"))
            if self.allow_subprocess:
                diagnostics.append(_policy_error("sandbox.locked_down.subprocess", "locked_down sandbox cannot allow subprocess execution", "sandbox_policy.allow_subprocess"))
            if self.allow_gpu:
                diagnostics.append(_policy_error("sandbox.locked_down.gpu", "locked_down sandbox cannot allow GPU access", "sandbox_policy.allow_gpu"))

        if self.sandbox_class == SandboxClass.LOCAL_READ:
            if self.filesystem.mode not in {FileAccessMode.NONE, FileAccessMode.READ}:
                diagnostics.append(_policy_error("sandbox.local_read.filesystem", "local_read sandbox may only request read access", "sandbox_policy.filesystem.mode"))
            if self.network.mode != NetworkAccessMode.NONE:
                diagnostics.append(_policy_error("sandbox.local_read.network", "local_read sandbox cannot request network access", "sandbox_policy.network.mode"))

        if self.sandbox_class == SandboxClass.LOCAL_READ_WRITE and self.network.mode != NetworkAccessMode.NONE:
            diagnostics.append(_policy_error("sandbox.local_read_write.network", "local_read_write sandbox cannot request network access", "sandbox_policy.network.mode"))

        network_required = _resource_network_required(resource_profile)
        if network_required and self.network.mode == NetworkAccessMode.NONE:
            diagnostics.append(_policy_error("sandbox.network.required_but_denied", "resource_profile.network_required is true but sandbox denies network access", "sandbox_policy.network.mode"))
        gpu_required = _resource_gpu_required(resource_profile)
        if gpu_required and not self.allow_gpu:
            diagnostics.append(_policy_error("sandbox.gpu.required_but_denied", "resource_profile.gpu_required is true but sandbox denies GPU access", "sandbox_policy.allow_gpu"))
        if self.network.mode == NetworkAccessMode.OUTBOUND and not self.network.allowed_hosts and self.sandbox_class != SandboxClass.TRUSTED:
            diagnostics.append(
                ContractDiagnostic(
                    code="sandbox.network.allowed_hosts.missing",
                    message="outbound network access should declare allowed_hosts or use trusted sandbox class",
                    severity="warning",
                    location="sandbox_policy.network.allowed_hosts",
                )
            )
        if self.filesystem.mode in {FileAccessMode.WRITE, FileAccessMode.READ_WRITE} and not self.filesystem.allowed_paths and self.sandbox_class != SandboxClass.TRUSTED:
            diagnostics.append(
                ContractDiagnostic(
                    code="sandbox.filesystem.allowed_paths.missing",
                    message="write-capable filesystem access should declare allowed_paths or use trusted sandbox class",
                    severity="warning",
                    location="sandbox_policy.filesystem.allowed_paths",
                )
            )
        return tuple(diagnostics)

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            **contract_header(self.contract_type, self.schema_version),
            "sandbox_class": self.sandbox_class.value,
            "filesystem": self.filesystem.to_dict(),
            "network": self.network.to_dict(),
            "allow_subprocess": self.allow_subprocess,
            "allow_gpu": self.allow_gpu,
            "metadata": dict(self.metadata),
        }

    def to_json(self) -> str:
        return to_json(self.to_dict())

    @classmethod
    def from_json(cls, text: str) -> "SandboxPolicy":
        return cls.from_dict(load_json_object(text, cls.contract_type))

    @classmethod
    def from_dict(cls, data: Any) -> "SandboxPolicy":
        if isinstance(data, SandboxPolicy):
            return data
        if data is None:
            return cls()
        if not isinstance(data, Mapping):
            raise ContractValidationError("sandbox policy must be a mapping")
        _validate_contract_type(data, cls.contract_type)
        return cls(
            sandbox_class=data.get("sandbox_class", SandboxClass.LOCKED_DOWN.value),
            filesystem=FileAccessPolicy.from_dict(data.get("filesystem", {})),
            network=NetworkPolicy.from_dict(data.get("network", {})),
            allow_subprocess=data.get("allow_subprocess", False),
            allow_gpu=data.get("allow_gpu", False),
            metadata=data.get("metadata", {}),
            schema_version=data.get("schema_version", CONTRACT_SCHEMA_VERSION),
        )


@dataclass(frozen=True)
class SourceLicensePolicy:
    """Source/license permission metadata with explicit unknown states."""

    source_name: str = ""
    source_url: str = ""
    license_name: str = ""
    license_url: str = ""
    policy_status: SourcePolicyStatus = SourcePolicyStatus.UNKNOWN
    robots_allowed: bool | None = None
    api_allowed: bool | None = None
    terms_notes: str = ""
    attribution_required: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = CONTRACT_SCHEMA_VERSION

    contract_type: ClassVar[str] = "brain_lab.source_license_policy"

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_name", _optional_text(self.source_name))
        object.__setattr__(self, "source_url", _optional_text(self.source_url))
        object.__setattr__(self, "license_name", _optional_text(self.license_name))
        object.__setattr__(self, "license_url", _optional_text(self.license_url))
        object.__setattr__(self, "policy_status", _enum_value(SourcePolicyStatus, self.policy_status, "source_policy.status"))
        object.__setattr__(self, "robots_allowed", _optional_bool(self.robots_allowed, "source_policy.robots_allowed"))
        object.__setattr__(self, "api_allowed", _optional_bool(self.api_allowed, "source_policy.api_allowed"))
        object.__setattr__(self, "terms_notes", _optional_text(self.terms_notes))
        object.__setattr__(self, "attribution_required", _bool_value(self.attribution_required, "source_policy.attribution_required"))
        object.__setattr__(self, "metadata", _metadata(self.metadata))
        object.__setattr__(self, "schema_version", _schema_version(self.schema_version))

    @classmethod
    def from_provenance(
        cls,
        provenance: Any,
        *,
        robots_allowed: bool | None = None,
        api_allowed: bool | None = None,
        attribution_required: bool = False,
    ) -> "SourceLicensePolicy":
        getter = provenance.get if isinstance(provenance, Mapping) else lambda key, default="": getattr(provenance, key, default)
        return cls(
            source_name=getter("source_name", ""),
            source_url=getter("source_url", ""),
            license_name=getter("license_name", ""),
            license_url=getter("license_url", ""),
            policy_status=getter("source_policy_status", SourcePolicyStatus.UNKNOWN.value),
            terms_notes=getter("source_policy_notes", ""),
            robots_allowed=robots_allowed,
            api_allowed=api_allowed,
            attribution_required=attribution_required,
        )

    def validate(self) -> tuple[ContractDiagnostic, ...]:
        diagnostics: list[ContractDiagnostic] = []
        if self.policy_status == SourcePolicyStatus.DISALLOWED:
            diagnostics.append(_policy_error("source_policy.disallowed", "source policy is explicitly disallowed", "source_policy.status"))
        elif self.policy_status == SourcePolicyStatus.UNKNOWN:
            diagnostics.append(
                ContractDiagnostic(
                    code="source_policy.unknown",
                    message="source policy is unchecked/unknown; do not report it as allowed",
                    severity="warning",
                    location="source_policy.status",
                )
            )
        if self.robots_allowed is False:
            diagnostics.append(_policy_error("source_policy.robots_disallowed", "robots policy explicitly disallows this source", "source_policy.robots_allowed"))
        if self.api_allowed is False:
            diagnostics.append(_policy_error("source_policy.api_disallowed", "API/source policy explicitly disallows this source", "source_policy.api_allowed"))
        if self.policy_status == SourcePolicyStatus.ALLOWED and not (self.license_name or self.terms_notes):
            diagnostics.append(
                ContractDiagnostic(
                    code="source_policy.license_or_terms.missing",
                    message="allowed source policy should carry license_name or terms_notes",
                    severity="warning",
                    location="source_policy.license_name",
                )
            )
        return tuple(diagnostics)

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            **contract_header(self.contract_type, self.schema_version),
            "source_name": self.source_name,
            "source_url": self.source_url,
            "license_name": self.license_name,
            "license_url": self.license_url,
            "policy_status": self.policy_status.value,
            "robots_allowed": self.robots_allowed,
            "api_allowed": self.api_allowed,
            "terms_notes": self.terms_notes,
            "attribution_required": self.attribution_required,
            "metadata": dict(self.metadata),
        }

    def to_json(self) -> str:
        return to_json(self.to_dict())

    @classmethod
    def from_json(cls, text: str) -> "SourceLicensePolicy":
        return cls.from_dict(load_json_object(text, cls.contract_type))

    @classmethod
    def from_dict(cls, data: Any) -> "SourceLicensePolicy":
        if isinstance(data, SourceLicensePolicy):
            return data
        if data is None:
            return cls()
        if not isinstance(data, Mapping):
            raise ContractValidationError("source license policy must be a mapping")
        _validate_contract_type(data, cls.contract_type)
        return cls(
            source_name=data.get("source_name", ""),
            source_url=data.get("source_url", ""),
            license_name=data.get("license_name", ""),
            license_url=data.get("license_url", ""),
            policy_status=data.get("policy_status", SourcePolicyStatus.UNKNOWN.value),
            robots_allowed=data.get("robots_allowed"),
            api_allowed=data.get("api_allowed"),
            terms_notes=data.get("terms_notes", ""),
            attribution_required=data.get("attribution_required", False),
            metadata=data.get("metadata", {}),
            schema_version=data.get("schema_version", CONTRACT_SCHEMA_VERSION),
        )


def redact_secrets(
    value: Any,
    *,
    secret_names: Iterable[str] = (),
    secret_values: Iterable[str] = (),
) -> JsonValue:
    """Return a JSON-safe copy with secret-looking fields and known values redacted."""

    normalized_secret_names = {str(name).lower() for name in secret_names}
    normalized_secret_values = _normalize_secret_values(secret_values)
    return _redact_json(_json_safe(value), normalized_secret_names, normalized_secret_values)


def collect_secret_values(value: Any, secret_names: Collection[str], *, secret_context: bool = False) -> set[str]:
    """Collect configured secret values from known secret-bearing fields only."""

    normalized_names = {str(name).lower() for name in secret_names}
    values: set[str] = set()
    if isinstance(value, Mapping):
        for key, item in value.items():
            values.update(
                collect_secret_values(
                    item,
                    normalized_names,
                    secret_context=secret_context or is_secret_key(str(key), normalized_names),
                )
            )
        return values
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        for item in value:
            values.update(collect_secret_values(item, normalized_names, secret_context=secret_context))
        return values
    if secret_context and isinstance(value, str) and len(value) >= 4 and value != REDACTED:
        values.add(value)
    return values


def is_secret_key(key: str, secret_names: Collection[str]) -> bool:
    """Return whether a JSON key should be treated as secret-bearing."""

    lowered = str(key).lower()
    normalized_names = {str(name).lower() for name in secret_names}
    if lowered in _PUBLIC_SECRET_METADATA_KEYS:
        return False
    if lowered in normalized_names:
        return True
    return any(fragment in lowered for fragment in _SENSITIVE_KEY_FRAGMENTS)


def redact_error_payload(
    payload: Any,
    *,
    secret_names: Iterable[str] = (),
    secret_values: Iterable[str] = (),
) -> JsonValue:
    """Alias for redacting error envelopes/status payloads at API/MCP boundaries."""

    return redact_secrets(payload, secret_names=secret_names, secret_values=secret_values)


def _redact_json(value: JsonValue, secret_names: set[str], secret_values: tuple[str, ...]) -> JsonValue:
    if isinstance(value, dict):
        redacted: dict[str, JsonValue] = {}
        for key, item in value.items():
            if is_secret_key(key, secret_names):
                redacted[key] = REDACTED
            else:
                redacted[key] = _redact_json(item, secret_names, secret_values)
        return redacted
    if isinstance(value, list):
        return [_redact_json(item, secret_names, secret_values) for item in value]
    if isinstance(value, str):
        return _redact_secret_text(value, secret_values)
    return value


def _json_safe(value: Any) -> JsonValue:
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return str(value)
        return value
    if isinstance(value, Enum):
        return _json_safe(value.value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_json_safe(item) for item in value]
    if isinstance(value, set | frozenset):
        return [_json_safe(item) for item in sorted(value, key=str)]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_safe(to_dict())
    return str(value)


def _normalize_secret_values(secret_values: Iterable[str]) -> tuple[str, ...]:
    values = {
        str(value)
        for value in secret_values
        if isinstance(value, str) and len(value) >= 4 and value != REDACTED
    }
    return tuple(sorted(values, key=len, reverse=True))


def _redact_secret_text(value: str, secret_values: tuple[str, ...]) -> str:
    redacted = value
    for secret_value in secret_values:
        redacted = redacted.replace(secret_value, REDACTED)
    return redacted


def _optional_bool(value: Any, field_name: str) -> bool | None:
    if value is None or value == "":
        return None
    return _bool_value(value, field_name)


def _required_identifier_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ContractValidationError(f"{field_name} is required")
    return text


def _resource_network_required(resource_profile: Any | None) -> bool:
    if resource_profile is None:
        return False
    if isinstance(resource_profile, Mapping):
        return bool(resource_profile.get("network_required", False))
    return bool(getattr(resource_profile, "network_required", False))


def _resource_gpu_required(resource_profile: Any | None) -> bool:
    if resource_profile is None:
        return False
    if isinstance(resource_profile, Mapping):
        return bool(resource_profile.get("gpu_required", False))
    return bool(getattr(resource_profile, "gpu_required", False))


def _policy_error(code: str, message: str, location: str) -> ContractDiagnostic:
    return ContractDiagnostic(code=code, message=message, severity="error", location=location)
