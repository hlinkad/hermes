"""Structured observability, trace, and evaluation event contracts."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, ClassVar

from brain_lab_core.contracts.base import (
    CONTRACT_SCHEMA_VERSION,
    ContractValidationError,
    JsonValue,
    _bool_value,
    _metadata,
    _non_negative_int,
    _optional_text,
    _schema_version,
    _string_tuple,
    _validate_contract_type,
    contract_header,
    load_json_object,
    to_json,
)

_VALID_EVENT_SEVERITIES = {"debug", "info", "warning", "error"}


@dataclass(frozen=True)
class TraceContext:
    """Transport-neutral trace/span metadata for later Langfuse/eval integration."""

    trace_id: str = ""
    span_id: str = ""
    parent_span_id: str = ""
    sampled: bool = True
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = CONTRACT_SCHEMA_VERSION

    contract_type: ClassVar[str] = "brain_lab.trace_context"

    def __post_init__(self) -> None:
        object.__setattr__(self, "trace_id", _optional_text(self.trace_id))
        object.__setattr__(self, "span_id", _optional_text(self.span_id))
        object.__setattr__(self, "parent_span_id", _optional_text(self.parent_span_id))
        object.__setattr__(self, "sampled", _bool_value(self.sampled, "trace.sampled"))
        object.__setattr__(self, "attributes", _metadata(self.attributes))
        object.__setattr__(self, "schema_version", _schema_version(self.schema_version))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            **contract_header(self.contract_type, self.schema_version),
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "sampled": self.sampled,
            "attributes": dict(self.attributes),
        }

    def to_json(self) -> str:
        return to_json(self.to_dict())

    @classmethod
    def from_json(cls, text: str) -> "TraceContext":
        return cls.from_dict(load_json_object(text, cls.contract_type))

    @classmethod
    def from_dict(cls, data: Any) -> "TraceContext":
        if isinstance(data, TraceContext):
            return data
        if data is None:
            return cls()
        if not isinstance(data, Mapping):
            raise ContractValidationError("trace context must be a mapping")
        _validate_contract_type(data, cls.contract_type)
        return cls(
            trace_id=data.get("trace_id", ""),
            span_id=data.get("span_id", ""),
            parent_span_id=data.get("parent_span_id", ""),
            sampled=data.get("sampled", True),
            attributes=data.get("attributes", {}),
            schema_version=data.get("schema_version", CONTRACT_SCHEMA_VERSION),
        )


@dataclass(frozen=True)
class EvaluationHook:
    """Declaration that an event/artifact can be consumed by an evaluator later."""

    evaluator_id: str
    metric_names: tuple[str, ...] = field(default_factory=tuple)
    artifact_ids: tuple[str, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = CONTRACT_SCHEMA_VERSION

    contract_type: ClassVar[str] = "brain_lab.evaluation_hook"

    def __post_init__(self) -> None:
        object.__setattr__(self, "evaluator_id", _required_text(self.evaluator_id, "evaluation_hook.evaluator_id"))
        object.__setattr__(self, "metric_names", _string_tuple(self.metric_names))
        object.__setattr__(self, "artifact_ids", _string_tuple(self.artifact_ids))
        object.__setattr__(self, "metadata", _metadata(self.metadata))
        object.__setattr__(self, "schema_version", _schema_version(self.schema_version))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            **contract_header(self.contract_type, self.schema_version),
            "evaluator_id": self.evaluator_id,
            "metric_names": list(self.metric_names),
            "artifact_ids": list(self.artifact_ids),
            "metadata": dict(self.metadata),
        }

    def to_json(self) -> str:
        return to_json(self.to_dict())

    @classmethod
    def from_json(cls, text: str) -> "EvaluationHook":
        return cls.from_dict(load_json_object(text, cls.contract_type))

    @classmethod
    def from_dict(cls, data: Any) -> "EvaluationHook":
        if isinstance(data, EvaluationHook):
            return data
        if not isinstance(data, Mapping):
            raise ContractValidationError("evaluation hook must be a mapping")
        _validate_contract_type(data, cls.contract_type)
        return cls(
            evaluator_id=data.get("evaluator_id", ""),
            metric_names=tuple(data.get("metric_names", ())),
            artifact_ids=tuple(data.get("artifact_ids", ())),
            metadata=data.get("metadata", {}),
            schema_version=data.get("schema_version", CONTRACT_SCHEMA_VERSION),
        )


@dataclass(frozen=True)
class ObservabilityEvent:
    """Structured event envelope for jobs, stages, artifacts, traces, and eval hooks."""

    event_type: str
    entity_type: str
    entity_id: str
    event_id: int = 0
    created_at: str = ""
    severity: str = "info"
    reason: str = ""
    payload: Mapping[str, Any] = field(default_factory=dict)
    trace: TraceContext = field(default_factory=TraceContext)
    evaluation_hooks: tuple[EvaluationHook, ...] = field(default_factory=tuple)
    schema_version: str = CONTRACT_SCHEMA_VERSION

    contract_type: ClassVar[str] = "brain_lab.observability_event"

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_type", _required_text(self.event_type, "event.event_type"))
        object.__setattr__(self, "entity_type", _required_text(self.entity_type, "event.entity_type"))
        object.__setattr__(self, "entity_id", _required_text(self.entity_id, "event.entity_id"))
        object.__setattr__(self, "event_id", _non_negative_int(self.event_id, "event.event_id"))
        object.__setattr__(self, "created_at", _optional_text(self.created_at))
        severity = _optional_text(self.severity).lower() or "info"
        if severity not in _VALID_EVENT_SEVERITIES:
            severity = "info"
        object.__setattr__(self, "severity", severity)
        object.__setattr__(self, "reason", _optional_text(self.reason))
        object.__setattr__(self, "payload", _metadata(self.payload))
        object.__setattr__(self, "trace", TraceContext.from_dict(self.trace))
        object.__setattr__(
            self,
            "evaluation_hooks",
            tuple(EvaluationHook.from_dict(value) for value in self.evaluation_hooks),
        )
        object.__setattr__(self, "schema_version", _schema_version(self.schema_version))

    @classmethod
    def from_ledger_event(cls, event: Any) -> "ObservabilityEvent":
        payload = dict(getattr(event, "payload", None) or {})
        trace = TraceContext(
            trace_id=str(payload.get("trace_id", "") or ""),
            span_id=str(payload.get("span_id", "") or ""),
            parent_span_id=str(payload.get("parent_span_id", "") or ""),
            attributes=_trace_attributes_from_payload(payload),
        )
        return cls(
            event_id=getattr(event, "event_id", 0),
            created_at=getattr(event, "created_at", ""),
            entity_type=getattr(event, "entity_type", ""),
            entity_id=getattr(event, "entity_id", ""),
            event_type=getattr(event, "event_type", ""),
            severity=_severity_for_event_type(str(getattr(event, "event_type", ""))),
            reason=getattr(event, "reason", ""),
            payload=payload,
            trace=trace,
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            **contract_header(self.contract_type, self.schema_version),
            "event_id": self.event_id,
            "created_at": self.created_at,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "event_type": self.event_type,
            "severity": self.severity,
            "reason": self.reason,
            "payload": dict(self.payload),
            "trace": self.trace.to_dict(),
            "evaluation_hooks": [hook.to_dict() for hook in self.evaluation_hooks],
        }

    def to_json(self) -> str:
        return to_json(self.to_dict())

    @classmethod
    def from_json(cls, text: str) -> "ObservabilityEvent":
        return cls.from_dict(load_json_object(text, cls.contract_type))

    @classmethod
    def from_dict(cls, data: Any) -> "ObservabilityEvent":
        if isinstance(data, ObservabilityEvent):
            return data
        if not isinstance(data, Mapping):
            raise ContractValidationError("observability event must be a mapping")
        _validate_contract_type(data, cls.contract_type)
        return cls(
            event_id=data.get("event_id", 0),
            created_at=data.get("created_at", ""),
            entity_type=data.get("entity_type", ""),
            entity_id=data.get("entity_id", ""),
            event_type=data.get("event_type", ""),
            severity=data.get("severity", "info"),
            reason=data.get("reason", ""),
            payload=data.get("payload", {}),
            trace=TraceContext.from_dict(data.get("trace", {})),
            evaluation_hooks=tuple(EvaluationHook.from_dict(value) for value in data.get("evaluation_hooks", ())),
            schema_version=data.get("schema_version", CONTRACT_SCHEMA_VERSION),
        )


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ContractValidationError(f"{field_name} is required")
    return text


def _severity_for_event_type(event_type: str) -> str:
    if ".failed" in event_type or event_type.endswith(".error"):
        return "error"
    if ".retry" in event_type or ".stale" in event_type or ".cancel" in event_type:
        return "warning"
    return "info"


def _trace_attributes_from_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key not in {"trace_id", "span_id", "parent_span_id"}
    }
