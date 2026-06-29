"""Stage plan contracts for the generic job runner."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from brain_lab_core.contracts import ArtifactId, ContractValidationError, ErrorEnvelope
from brain_lab_core.state import canonical_json


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ContractValidationError(f"{field_name} is required")
    return text


def _positive_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractValidationError(f"{field_name} must be an integer")
    if value < 1:
        raise ContractValidationError(f"{field_name} must be at least 1")
    return value


def _string_tuple(values: Any, field_name: str) -> tuple[str, ...]:
    if values is None or values == "":
        return ()
    if isinstance(values, str):
        raw_values = (values,)
    else:
        try:
            raw_values = tuple(values)
        except TypeError as exc:
            raise ContractValidationError(f"{field_name} must be an iterable of strings") from exc
    normalized: list[str] = []
    for value in raw_values:
        text = _required_text(value, field_name)
        normalized.append(text)
    return tuple(dict.fromkeys(normalized))


def _artifact_tuple(values: Any, field_name: str) -> tuple[ArtifactId, ...]:
    if values is None or values == "":
        return ()
    if isinstance(values, str | bytes | ArtifactId) or isinstance(values, Mapping):
        raise ContractValidationError(f"{field_name} must be an iterable of ArtifactId values")
    try:
        raw_values = tuple(values)
    except TypeError as exc:
        raise ContractValidationError(f"{field_name} must be an iterable of ArtifactId values") from exc
    normalized = tuple(ArtifactId.from_dict(value) for value in raw_values)
    by_qualified = {artifact_id.qualified: artifact_id for artifact_id in normalized}
    return tuple(by_qualified[key] for key in sorted(by_qualified))


@dataclass(frozen=True)
class ArtifactContract:
    """Declared stage output artifact contract.

    The runner uses these declarations to reject undeclared outputs and to decide
    whether a completed/stale stage already has current outputs that can be reused.
    """

    artifact_id: ArtifactId | str | Mapping[str, Any]
    artifact_type: str
    artifact_schema_version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact_id", ArtifactId.from_dict(self.artifact_id))
        object.__setattr__(self, "artifact_type", _required_text(self.artifact_type, "artifact_contract.artifact_type"))
        object.__setattr__(
            self,
            "artifact_schema_version",
            _required_text(self.artifact_schema_version, "artifact_contract.artifact_schema_version"),
        )


@dataclass(frozen=True)
class RetryPolicy:
    """Retry limits and error-code classification for one stage."""

    max_attempts: int = 1
    retryable_error_codes: tuple[str, ...] = field(default_factory=tuple)
    non_retryable_error_codes: tuple[str, ...] = field(default_factory=tuple)
    retry_all: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "max_attempts", _positive_int(self.max_attempts, "retry_policy.max_attempts"))
        object.__setattr__(
            self,
            "retryable_error_codes",
            _string_tuple(self.retryable_error_codes, "retry_policy.retryable_error_codes"),
        )
        object.__setattr__(
            self,
            "non_retryable_error_codes",
            _string_tuple(self.non_retryable_error_codes, "retry_policy.non_retryable_error_codes"),
        )
        if not isinstance(self.retry_all, bool):
            raise ContractValidationError("retry_policy.retry_all must be a boolean")

    def is_retryable(self, error: ErrorEnvelope) -> bool:
        """Classify an error envelope without looking at attempt count."""

        if _matches_error_code(error.code, self.non_retryable_error_codes):
            return False
        if _matches_error_code(error.code, self.retryable_error_codes):
            return True
        return bool(self.retry_all or error.retryable)


def _matches_error_code(code: str, patterns: tuple[str, ...]) -> bool:
    for pattern in patterns:
        if pattern.endswith("*") and code.startswith(pattern[:-1]):
            return True
        if code == pattern:
            return True
    return False


@dataclass(frozen=True)
class StagePlan:
    """Executable stage declaration with explicit artifact contracts."""

    stage_id: str
    handler: Callable[[Any], Any]
    input_artifact_ids: tuple[ArtifactId | str | Mapping[str, Any], ...] = field(default_factory=tuple)
    output_artifacts: tuple[ArtifactContract | Mapping[str, Any], ...] = field(default_factory=tuple)
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "stage_id", _required_text(self.stage_id, "stage_plan.stage_id"))
        if ":" in self.stage_id:
            raise ContractValidationError("stage_plan.stage_id must not contain ':'")
        if not callable(self.handler):
            raise ContractValidationError("stage_plan.handler must be callable")
        object.__setattr__(
            self,
            "input_artifact_ids",
            _artifact_tuple(self.input_artifact_ids, "stage_plan.input_artifact_ids"),
        )
        output_artifacts = tuple(
            artifact if isinstance(artifact, ArtifactContract) else ArtifactContract(**dict(artifact))
            for artifact in self.output_artifacts
        )
        by_qualified: dict[str, ArtifactContract] = {}
        for artifact in output_artifacts:
            qualified = artifact.artifact_id.qualified
            if qualified in by_qualified:
                raise ContractValidationError(f"duplicate output artifact declared by stage {self.stage_id}: {qualified}")
            by_qualified[qualified] = artifact
        object.__setattr__(self, "output_artifacts", tuple(by_qualified.values()))
        object.__setattr__(self, "retry_policy", RetryPolicy(**dict(self.retry_policy)) if isinstance(self.retry_policy, Mapping) else self.retry_policy)
        if not isinstance(self.retry_policy, RetryPolicy):
            raise ContractValidationError("stage_plan.retry_policy must be RetryPolicy")
        canonical_json(self.metadata if self.metadata is not None else {})
        if not isinstance(self.metadata, Mapping):
            raise ContractValidationError("stage_plan.metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def output_contract_for(self, artifact_id: ArtifactId | str | Mapping[str, Any]) -> ArtifactContract:
        normalized = ArtifactId.from_dict(artifact_id)
        for contract in self.output_artifacts:
            if contract.artifact_id == normalized:
                return contract
        raise ContractValidationError(
            f"undeclared output artifact {normalized.qualified!r} for stage {self.stage_id!r}"
        )


@dataclass(frozen=True)
class JobPlan:
    """Ordered local job plan validated before execution."""

    job_id: str
    tool_id: str
    stages: tuple[StagePlan | Mapping[str, Any], ...]
    input_artifact_ids: tuple[ArtifactId | str | Mapping[str, Any], ...] = field(default_factory=tuple)
    config: Any = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "job_id", _required_text(self.job_id, "job_plan.job_id"))
        if ":" in self.job_id:
            raise ContractValidationError("job_plan.job_id must not contain ':'")
        object.__setattr__(self, "tool_id", _required_text(self.tool_id, "job_plan.tool_id"))
        stages = tuple(stage if isinstance(stage, StagePlan) else StagePlan(**dict(stage)) for stage in self.stages)
        if not stages:
            raise ContractValidationError("job_plan.stages must contain at least one stage")
        seen_stage_ids: set[str] = set()
        known_artifacts = {artifact_id.qualified for artifact_id in _artifact_tuple(self.input_artifact_ids, "job_plan.input_artifact_ids")}
        output_artifacts: set[str] = set()
        for stage in stages:
            if stage.stage_id in seen_stage_ids:
                raise ContractValidationError(f"duplicate stage_id in job plan: {stage.stage_id}")
            seen_stage_ids.add(stage.stage_id)
            for input_id in stage.input_artifact_ids:
                if input_id.qualified not in known_artifacts:
                    raise ContractValidationError(
                        f"unknown input artifact {input_id.qualified!r} for stage {stage.stage_id!r}; "
                        "declare it as a job input or produce it in an earlier stage"
                    )
            for contract in stage.output_artifacts:
                qualified = contract.artifact_id.qualified
                if qualified in output_artifacts:
                    raise ContractValidationError(f"duplicate output artifact in job plan: {qualified}")
                output_artifacts.add(qualified)
                known_artifacts.add(qualified)
        object.__setattr__(self, "stages", stages)
        object.__setattr__(
            self,
            "input_artifact_ids",
            _artifact_tuple(self.input_artifact_ids, "job_plan.input_artifact_ids"),
        )
        canonical_json(self.config)
        canonical_json(self.metadata if self.metadata is not None else {})
        if not isinstance(self.metadata, Mapping):
            raise ContractValidationError("job_plan.metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))
