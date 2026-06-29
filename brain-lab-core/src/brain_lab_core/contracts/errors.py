"""Normalized error envelope contracts."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar, Mapping

from .artifacts import Provenance
from .base import (
    CONTRACT_SCHEMA_VERSION,
    ContractValidationError,
    JsonValue,
    _bool_value,
    _diagnostic_tuple,
    _metadata,
    _non_negative_int,
    _optional_text,
    _required_text,
    _schema_version,
    _validate_contract_type,
    contract_header,
    load_json_object,
    to_json,
)

_VALID_SEVERITIES = {"error", "warning", "info"}


@dataclass(frozen=True)
class ErrorEnvelope:
    """Normalized error payload emitted by providers, stages, and contract validators."""

    code: str
    message: str
    category: str = "unknown"
    severity: str = "error"
    retryable: bool = False
    retry_after_seconds: int | None = None
    provenance: Provenance = field(default_factory=Provenance)
    context: Mapping[str, Any] = field(default_factory=dict)
    diagnostics: tuple[Any, ...] = field(default_factory=tuple)
    schema_version: str = CONTRACT_SCHEMA_VERSION

    contract_type: ClassVar[str] = "brain_lab.error_envelope"

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _required_text(self.code, "error.code"))
        object.__setattr__(self, "message", _required_text(self.message, "error.message"))
        object.__setattr__(self, "category", _optional_text(self.category) or "unknown")
        severity = _optional_text(self.severity).lower() or "error"
        if severity not in _VALID_SEVERITIES:
            severity = "error"
        object.__setattr__(self, "severity", severity)
        object.__setattr__(self, "retryable", _bool_value(self.retryable, "error.retryable"))
        if self.retry_after_seconds is not None:
            object.__setattr__(
                self,
                "retry_after_seconds",
                _non_negative_int(self.retry_after_seconds, "error.retry_after_seconds"),
            )
        object.__setattr__(self, "provenance", Provenance.from_dict(self.provenance))
        object.__setattr__(self, "context", _metadata(self.context))
        object.__setattr__(self, "diagnostics", _diagnostic_tuple(self.diagnostics))
        object.__setattr__(self, "schema_version", _schema_version(self.schema_version))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            **contract_header(self.contract_type, self.schema_version),
            "code": self.code,
            "message": self.message,
            "category": self.category,
            "severity": self.severity,
            "retryable": self.retryable,
            "retry_after_seconds": self.retry_after_seconds,
            "provenance": self.provenance.to_dict(),
            "context": dict(self.context),
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
        }

    def to_json(self) -> str:
        return to_json(self.to_dict())

    @classmethod
    def from_json(cls, text: str) -> "ErrorEnvelope":
        return cls.from_dict(load_json_object(text, cls.contract_type))

    @classmethod
    def from_dict(cls, data: Any) -> "ErrorEnvelope":
        if isinstance(data, ErrorEnvelope):
            return data
        if not isinstance(data, Mapping):
            raise ContractValidationError("error_envelope must be a mapping")
        _validate_contract_type(data, cls.contract_type)
        return cls(
            code=data.get("code", ""),
            message=data.get("message", ""),
            category=data.get("category", "unknown"),
            severity=data.get("severity", "error"),
            retryable=data.get("retryable", False),
            retry_after_seconds=data.get("retry_after_seconds"),
            provenance=Provenance.from_dict(data.get("provenance", {})),
            context=data.get("context", {}),
            diagnostics=tuple(data.get("diagnostics", ())),
            schema_version=data.get("schema_version", CONTRACT_SCHEMA_VERSION),
        )
