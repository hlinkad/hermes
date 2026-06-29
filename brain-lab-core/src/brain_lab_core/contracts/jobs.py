"""Job, stage lifecycle, and retry contracts."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Mapping

from .artifacts import ArtifactId
from .base import (
    CONTRACT_SCHEMA_VERSION,
    ContractValidationError,
    JsonValue,
    _bool_value,
    _enum_value,
    _metadata,
    _non_negative_int,
    _optional_text,
    _positive_int,
    _required_text,
    _schema_version,
    _unit_interval,
    _validate_contract_type,
    contract_header,
    load_json_object,
    to_json,
)


class LifecycleState(str, Enum):
    """Foundation-owned lifecycle states for jobs and stages."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STALE = "stale"
    CANCELED = "canceled"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class RetryMetadata:
    """Retry state and classification for a job stage."""

    attempt: int = 0
    max_attempts: int = 1
    retryable: bool = False
    next_retry_at: str = ""
    last_error_code: str = ""
    schema_version: str = CONTRACT_SCHEMA_VERSION

    contract_type: ClassVar[str] = "brain_lab.retry_metadata"

    def __post_init__(self) -> None:
        attempt = _non_negative_int(self.attempt, "retry.attempt")
        max_attempts = _positive_int(self.max_attempts, "retry.max_attempts")
        if attempt > max_attempts:
            raise ContractValidationError("retry.attempt must be less than or equal to retry.max_attempts")
        object.__setattr__(self, "attempt", attempt)
        object.__setattr__(self, "max_attempts", max_attempts)
        object.__setattr__(self, "retryable", _bool_value(self.retryable, "retry.retryable"))
        object.__setattr__(self, "next_retry_at", _optional_text(self.next_retry_at))
        object.__setattr__(self, "last_error_code", _optional_text(self.last_error_code))
        object.__setattr__(self, "schema_version", _schema_version(self.schema_version))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            **contract_header(self.contract_type, self.schema_version),
            "attempt": self.attempt,
            "max_attempts": self.max_attempts,
            "retryable": self.retryable,
            "next_retry_at": self.next_retry_at,
            "last_error_code": self.last_error_code,
        }

    def to_json(self) -> str:
        return to_json(self.to_dict())

    @classmethod
    def from_json(cls, text: str) -> "RetryMetadata":
        return cls.from_dict(load_json_object(text, cls.contract_type))

    @classmethod
    def from_dict(cls, data: Any) -> "RetryMetadata":
        if isinstance(data, RetryMetadata):
            return data
        if data is None:
            return cls()
        if not isinstance(data, Mapping):
            raise ContractValidationError("retry metadata must be a mapping")
        _validate_contract_type(data, cls.contract_type)
        return cls(
            attempt=data.get("attempt", 0),
            max_attempts=data.get("max_attempts", 1),
            retryable=data.get("retryable", False),
            next_retry_at=data.get("next_retry_at", ""),
            last_error_code=data.get("last_error_code", ""),
            schema_version=data.get("schema_version", CONTRACT_SCHEMA_VERSION),
        )


@dataclass(frozen=True)
class StageRun:
    """One executable stage within a job."""

    stage_id: str
    state: LifecycleState
    started_at: str = ""
    completed_at: str = ""
    input_artifact_ids: tuple[ArtifactId, ...] = field(default_factory=tuple)
    output_artifact_ids: tuple[ArtifactId, ...] = field(default_factory=tuple)
    retry: RetryMetadata = field(default_factory=RetryMetadata)
    lease_id: str = ""
    progress: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = CONTRACT_SCHEMA_VERSION

    contract_type: ClassVar[str] = "brain_lab.stage_run"

    def __post_init__(self) -> None:
        object.__setattr__(self, "stage_id", _required_text(self.stage_id, "stage_run.stage_id"))
        object.__setattr__(self, "state", _enum_value(LifecycleState, self.state, "stage_run.state"))
        object.__setattr__(self, "started_at", _optional_text(self.started_at))
        object.__setattr__(self, "completed_at", _optional_text(self.completed_at))
        object.__setattr__(
            self,
            "input_artifact_ids",
            tuple(ArtifactId.from_dict(value) for value in self.input_artifact_ids),
        )
        object.__setattr__(
            self,
            "output_artifact_ids",
            tuple(ArtifactId.from_dict(value) for value in self.output_artifact_ids),
        )
        object.__setattr__(self, "retry", RetryMetadata.from_dict(self.retry))
        object.__setattr__(self, "lease_id", _optional_text(self.lease_id))
        object.__setattr__(self, "progress", _unit_interval(self.progress, "stage_run.progress"))
        object.__setattr__(self, "metadata", _metadata(self.metadata))
        object.__setattr__(self, "schema_version", _schema_version(self.schema_version))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            **contract_header(self.contract_type, self.schema_version),
            "stage_id": self.stage_id,
            "state": self.state.value,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "input_artifact_ids": [artifact_id.to_dict() for artifact_id in self.input_artifact_ids],
            "output_artifact_ids": [artifact_id.to_dict() for artifact_id in self.output_artifact_ids],
            "retry": self.retry.to_dict(),
            "lease_id": self.lease_id,
            "progress": self.progress,
            "metadata": dict(self.metadata),
        }

    def to_json(self) -> str:
        return to_json(self.to_dict())

    @classmethod
    def from_json(cls, text: str) -> "StageRun":
        return cls.from_dict(load_json_object(text, cls.contract_type))

    @classmethod
    def from_dict(cls, data: Any) -> "StageRun":
        if isinstance(data, StageRun):
            return data
        if not isinstance(data, Mapping):
            raise ContractValidationError("stage_run must be a mapping")
        _validate_contract_type(data, cls.contract_type)
        return cls(
            stage_id=data.get("stage_id", ""),
            state=data.get("state", ""),
            started_at=data.get("started_at", ""),
            completed_at=data.get("completed_at", ""),
            input_artifact_ids=tuple(ArtifactId.from_dict(value) for value in data.get("input_artifact_ids", ())),
            output_artifact_ids=tuple(ArtifactId.from_dict(value) for value in data.get("output_artifact_ids", ())),
            retry=RetryMetadata.from_dict(data.get("retry", {})),
            lease_id=data.get("lease_id", ""),
            progress=data.get("progress"),
            metadata=data.get("metadata", {}),
            schema_version=data.get("schema_version", CONTRACT_SCHEMA_VERSION),
        )


@dataclass(frozen=True)
class Job:
    """A tool-neutral unit of work made of ordered stage runs."""

    job_id: str
    tool_id: str
    state: LifecycleState
    created_at: str
    stages: tuple[StageRun, ...] = field(default_factory=tuple)
    input_artifact_ids: tuple[ArtifactId, ...] = field(default_factory=tuple)
    config_fingerprint: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = CONTRACT_SCHEMA_VERSION

    contract_type: ClassVar[str] = "brain_lab.job"

    def __post_init__(self) -> None:
        object.__setattr__(self, "job_id", _required_text(self.job_id, "job.job_id"))
        object.__setattr__(self, "tool_id", _required_text(self.tool_id, "job.tool_id"))
        object.__setattr__(self, "state", _enum_value(LifecycleState, self.state, "job.state"))
        object.__setattr__(self, "created_at", _required_text(self.created_at, "job.created_at"))
        object.__setattr__(self, "stages", tuple(StageRun.from_dict(value) for value in self.stages))
        object.__setattr__(
            self,
            "input_artifact_ids",
            tuple(ArtifactId.from_dict(value) for value in self.input_artifact_ids),
        )
        object.__setattr__(self, "config_fingerprint", _optional_text(self.config_fingerprint))
        object.__setattr__(self, "metadata", _metadata(self.metadata))
        object.__setattr__(self, "schema_version", _schema_version(self.schema_version))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            **contract_header(self.contract_type, self.schema_version),
            "job_id": self.job_id,
            "tool_id": self.tool_id,
            "state": self.state.value,
            "created_at": self.created_at,
            "stages": [stage.to_dict() for stage in self.stages],
            "input_artifact_ids": [artifact_id.to_dict() for artifact_id in self.input_artifact_ids],
            "config_fingerprint": self.config_fingerprint,
            "metadata": dict(self.metadata),
        }

    def to_json(self) -> str:
        return to_json(self.to_dict())

    @classmethod
    def from_json(cls, text: str) -> "Job":
        return cls.from_dict(load_json_object(text, cls.contract_type))

    @classmethod
    def from_dict(cls, data: Any) -> "Job":
        if isinstance(data, Job):
            return data
        if not isinstance(data, Mapping):
            raise ContractValidationError("job must be a mapping")
        _validate_contract_type(data, cls.contract_type)
        return cls(
            job_id=data.get("job_id", ""),
            tool_id=data.get("tool_id", ""),
            state=data.get("state", ""),
            created_at=data.get("created_at", ""),
            stages=tuple(StageRun.from_dict(value) for value in data.get("stages", ())),
            input_artifact_ids=tuple(ArtifactId.from_dict(value) for value in data.get("input_artifact_ids", ())),
            config_fingerprint=data.get("config_fingerprint", ""),
            metadata=data.get("metadata", {}),
            schema_version=data.get("schema_version", CONTRACT_SCHEMA_VERSION),
        )
