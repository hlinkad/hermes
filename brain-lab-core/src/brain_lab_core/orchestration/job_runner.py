"""Generic local job runner lifecycle, resume, retry, leases, and cancellation."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from brain_lab_core.contracts import (
    ArtifactId,
    ArtifactRef,
    ContractValidationError,
    ErrorEnvelope,
    FreshnessState,
    Job,
    LifecycleState,
    Provenance,
    RetryMetadata,
    StageRun,
)
from brain_lab_core.state import LedgerEvent, SQLiteArtifactLedger, config_fingerprint

from .planner import ArtifactContract, JobPlan, StagePlan


@dataclass(frozen=True)
class StageExecutionResult:
    """Return value from a stage handler."""

    output_artifact_ids: tuple[ArtifactId | str | Mapping[str, Any], ...] = field(default_factory=tuple)
    progress: float | None = 1.0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        output_ids = tuple(ArtifactId.from_dict(value) for value in self.output_artifact_ids)
        object.__setattr__(self, "output_artifact_ids", output_ids)
        if self.progress is not None:
            if isinstance(self.progress, bool) or not isinstance(self.progress, int | float):
                raise ContractValidationError("stage result progress must be a number between 0 and 1")
            progress = float(self.progress)
            if progress < 0 or progress > 1:
                raise ContractValidationError("stage result progress must be a number between 0 and 1")
            object.__setattr__(self, "progress", progress)
        if not isinstance(self.metadata, Mapping):
            raise ContractValidationError("stage result metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))


class StageExecutionError(RuntimeError):
    """Stage failure with a normalized, retry-classifiable error envelope."""

    def __init__(self, error: ErrorEnvelope | Mapping[str, Any] | str) -> None:
        if isinstance(error, ErrorEnvelope):
            envelope = error
        elif isinstance(error, Mapping):
            envelope = ErrorEnvelope.from_dict(error)
        else:
            envelope = ErrorEnvelope(code="stage.execution_error", message=str(error), retryable=False)
        self.error = envelope
        super().__init__(envelope.message)


class JobCancellationRequested(RuntimeError):
    """Internal cooperative cancellation signal raised from StageContext."""

    def __init__(self, reason: str) -> None:
        self.reason = str(reason or "canceled")
        super().__init__(self.reason)


class StageContext:
    """Runtime context passed to concrete stage handlers."""

    def __init__(
        self,
        *,
        runner: "JobRunner",
        plan: JobPlan,
        stage_plan: StagePlan,
        attempt: int,
        lease_id: str,
        started_at: str,
    ) -> None:
        self.runner = runner
        self.ledger = runner.ledger
        self.plan = plan
        self.stage_plan = stage_plan
        self.attempt = attempt
        self.lease_id = lease_id
        self.started_at = started_at
        self._registered_output_ids: list[ArtifactId] = []
        self._progress: float | None = 0.0
        self._metadata: dict[str, Any] = dict(stage_plan.metadata)

    @property
    def registered_output_ids(self) -> tuple[ArtifactId, ...]:
        return tuple(dict.fromkeys(self._registered_output_ids))

    @property
    def progress(self) -> float | None:
        return self._progress

    def register_output(
        self,
        artifact_id: ArtifactId | str | Mapping[str, Any],
        file_path: str | Path,
        *,
        metadata: Mapping[str, Any] | None = None,
        provenance: Provenance | Mapping[str, Any] | None = None,
        artifact_uri: str | None = None,
        config: Any | None = None,
    ) -> ArtifactRef:
        """Measure/register a declared output artifact for the current stage.

        The output artifact must be declared in the stage plan. Registration is
        delegated to the SQLite ledger, so replaying the same output is idempotent
        and changed derivations stale previous current artifacts.
        """

        contract = self.stage_plan.output_contract_for(artifact_id)
        normalized_id = ArtifactId.from_dict(artifact_id)
        normalized_provenance = Provenance.from_dict(
            provenance
            if provenance is not None
            else Provenance(tool_id=self.plan.tool_id, stage_id=self.stage_plan.stage_id)
        )
        result = self.ledger.register_artifact_from_file(
            artifact_id=normalized_id,
            artifact_type=contract.artifact_type,
            artifact_schema_version=contract.artifact_schema_version,
            file_path=file_path,
            artifact_uri=artifact_uri,
            producer_tool_id=self.plan.tool_id,
            producer_stage_id=self.stage_plan.stage_id,
            input_artifact_ids=self.stage_plan.input_artifact_ids,
            config=self.plan.config if config is None else config,
            provenance=normalized_provenance,
            metadata=metadata or {},
        )
        self._registered_output_ids.append(result.artifact.artifact_id)
        self.runner._record_stage_event(
            self.plan.job_id,
            self.stage_plan.stage_id,
            "stage.output_registered",
            payload={
                "artifact_id": result.artifact.artifact_id.to_dict(),
                "artifact_type": result.artifact.artifact_type,
                "duplicate": result.duplicate,
                "inserted": result.inserted,
                "stale_count": result.stale_count,
            },
        )
        return result.artifact

    def record_progress(self, progress: float, *, message: str = "") -> None:
        """Persist worker lease/progress for long local stage jobs."""

        if isinstance(progress, bool) or not isinstance(progress, int | float):
            raise ContractValidationError("progress must be a number between 0 and 1")
        normalized = float(progress)
        if normalized < 0 or normalized > 1:
            raise ContractValidationError("progress must be a number between 0 and 1")
        self._progress = normalized
        if message:
            self._metadata["progress_message"] = str(message)
        stage = StageRun(
            stage_id=self.stage_plan.stage_id,
            state=LifecycleState.RUNNING,
            started_at=self.started_at,
            input_artifact_ids=self.stage_plan.input_artifact_ids,
            output_artifact_ids=self.registered_output_ids,
            retry=RetryMetadata(
                attempt=self.attempt,
                max_attempts=self.stage_plan.retry_policy.max_attempts,
            ),
            lease_id=self.lease_id,
            progress=normalized,
            metadata=self._metadata,
        )
        self.runner._upsert_stage(self.plan.job_id, stage)
        self.runner._record_stage_event(
            self.plan.job_id,
            self.stage_plan.stage_id,
            "stage.progress",
            payload={"progress": normalized, "message": message, "lease_id": self.lease_id},
        )

    def cancel(self, reason: str = "canceled") -> None:
        """Cooperatively cancel the current job without deleting artifacts."""

        raise JobCancellationRequested(reason)

    def cancel_if_requested(self) -> None:
        reason = self.runner.cancellation_reason(self.plan.job_id)
        if reason is not None:
            raise JobCancellationRequested(reason)


class JobRunner:
    """Local-first generic runner backed by ``SQLiteArtifactLedger``."""

    def __init__(self, ledger: SQLiteArtifactLedger) -> None:
        self.ledger = ledger
        self._cancel_requested: dict[str, str] = {}

    def request_cancel(self, job_id: str, reason: str = "canceled") -> None:
        """Request cooperative cancellation before or during a later stage check."""

        self._cancel_requested[str(job_id)] = str(reason or "canceled")
        self.ledger.record_event(
            entity_type="job",
            entity_id=str(job_id),
            event_type="job.cancel_requested",
            reason=str(reason or "canceled"),
        )

    def cancellation_reason(self, job_id: str) -> str | None:
        normalized_job_id = str(job_id)
        memory_reason = self._cancel_requested.get(normalized_job_id)
        if memory_reason is not None:
            return memory_reason

        last_cancel: LedgerEvent | None = None
        last_terminal_cancel_event_id = 0
        for event in self.ledger.list_events(entity_type="job", entity_id=normalized_job_id):
            if event.event_type == "job.cancel_requested":
                last_cancel = event
            elif event.event_type == "job.canceled":
                last_terminal_cancel_event_id = event.event_id
        if last_cancel is None or last_cancel.event_id <= last_terminal_cancel_event_id:
            return None
        return last_cancel.reason or "canceled"

    def mark_stage_stale(self, job_id: str, stage_id: str, *, reason: str = "stage marked stale") -> StageRun:
        """Mark a persisted stage stale so the next resume starts there."""

        stage = self._stage_by_id(job_id, stage_id)
        updated = replace(
            stage,
            state=LifecycleState.STALE,
            metadata={**dict(stage.metadata), "stale_reason": reason},
        )
        self._upsert_stage(job_id, updated)
        self._record_stage_event(job_id, stage_id, "stage.stale", reason=reason)
        job = self._get_job(job_id)
        self._upsert_job(
            replace(job, state=LifecycleState.STALE, stages=self._stage_runs_or_empty(job_id)),
            event_type="job.stale",
            reason=reason,
        )
        return updated

    def list_job_events(self, job_id: str) -> tuple[LedgerEvent, ...]:
        """Return job and stage events in append order for API/MCP consumers."""

        prefix = f"{job_id}:"
        return tuple(
            event
            for event in self.ledger.list_events()
            if (event.entity_type == "job" and event.entity_id == job_id)
            or (event.entity_type == "stage_run" and event.entity_id.startswith(prefix))
        )

    def run(self, plan: JobPlan | Mapping[str, Any], *, resume: bool = False) -> Job:
        """Run or resume an ordered job plan."""

        normalized = plan if isinstance(plan, JobPlan) else JobPlan(**dict(plan))
        existing_job = self._get_job_or_none(normalized.job_id)
        if existing_job is None or not resume:
            stage_runs = tuple(self._pending_stage(stage) for stage in normalized.stages)
            job = Job(
                job_id=normalized.job_id,
                tool_id=normalized.tool_id,
                state=LifecycleState.PENDING,
                created_at=_utc_now(),
                stages=stage_runs,
                input_artifact_ids=normalized.input_artifact_ids,
                config_fingerprint=config_fingerprint(normalized.config),
                metadata=normalized.metadata,
            )
            self._upsert_job(job, event_type="job.created")
            for stage_run in stage_runs:
                self._upsert_stage(normalized.job_id, stage_run)
        else:
            job = existing_job
            stage_runs = self._merged_stage_runs(normalized)
            for stage_run in stage_runs:
                self._upsert_stage(normalized.job_id, stage_run)

        job = self._upsert_job(
            replace(job, state=LifecycleState.RUNNING, stages=self._stage_runs_or_empty(normalized.job_id)),
            event_type="job.running",
        )

        for stage_plan in normalized.stages:
            cancel_reason = self.cancellation_reason(normalized.job_id)
            if cancel_reason is not None:
                return self._finish_canceled_before_stage(normalized, stage_plan, cancel_reason, job)

            current_stage = self._stage_by_id(normalized.job_id, stage_plan.stage_id)
            if current_stage.state == LifecycleState.CANCELED:
                return self._finish_job(normalized, LifecycleState.CANCELED, event_type="job.canceled")
            if current_stage.state == LifecycleState.COMPLETED and self._outputs_current(normalized, stage_plan):
                self._record_stage_event(
                    normalized.job_id,
                    stage_plan.stage_id,
                    "stage.skipped_current",
                    payload={"state_preserved": LifecycleState.COMPLETED.value},
                )
                continue
            if current_stage.state == LifecycleState.SKIPPED and self._outputs_current(normalized, stage_plan):
                self._record_stage_event(
                    normalized.job_id,
                    stage_plan.stage_id,
                    "stage.skipped_current",
                    payload={"state_preserved": LifecycleState.SKIPPED.value},
                )
                continue
            if current_stage.state == LifecycleState.PENDING and self._outputs_current(normalized, stage_plan):
                skipped = replace(current_stage, state=LifecycleState.SKIPPED, completed_at=_utc_now(), progress=1.0)
                self._upsert_stage(normalized.job_id, skipped)
                self._record_stage_event(
                    normalized.job_id,
                    stage_plan.stage_id,
                    "stage.skipped_current",
                    payload={"state": LifecycleState.SKIPPED.value},
                )
                continue

            stage_result = self._run_stage(normalized, stage_plan)
            if stage_result.state == LifecycleState.FAILED:
                return self._finish_job(
                    normalized,
                    LifecycleState.FAILED,
                    event_type="job.failed",
                    payload={"failed_stage_id": stage_plan.stage_id},
                )
            if stage_result.state == LifecycleState.CANCELED:
                return self._finish_job(
                    normalized,
                    LifecycleState.CANCELED,
                    event_type="job.canceled",
                    payload={"canceled_stage_id": stage_plan.stage_id},
                )

        return self._finish_job(normalized, LifecycleState.COMPLETED, event_type="job.completed")

    def _run_stage(self, plan: JobPlan, stage_plan: StagePlan) -> StageRun:
        last_stage: StageRun | None = None
        for attempt in range(1, stage_plan.retry_policy.max_attempts + 1):
            started_at = _utc_now()
            lease_id = f"{plan.job_id}:{stage_plan.stage_id}:attempt-{attempt}"
            running = StageRun(
                stage_id=stage_plan.stage_id,
                state=LifecycleState.RUNNING,
                started_at=started_at,
                input_artifact_ids=stage_plan.input_artifact_ids,
                retry=RetryMetadata(attempt=attempt, max_attempts=stage_plan.retry_policy.max_attempts),
                lease_id=lease_id,
                progress=0.0,
                metadata=stage_plan.metadata,
            )
            self._upsert_stage(plan.job_id, running)
            self._record_stage_event(
                plan.job_id,
                stage_plan.stage_id,
                "stage.running",
                payload={"attempt": attempt, "lease_id": lease_id},
            )
            context = StageContext(
                runner=self,
                plan=plan,
                stage_plan=stage_plan,
                attempt=attempt,
                lease_id=lease_id,
                started_at=started_at,
            )
            try:
                context.cancel_if_requested()
                raw_result = stage_plan.handler(context)
                result = raw_result if isinstance(raw_result, StageExecutionResult) else StageExecutionResult()
                registered_output_ids = context.registered_output_ids
                reported_output_ids = result.output_artifact_ids
                self._validate_declared_outputs_available(
                    plan,
                    stage_plan,
                    registered_output_ids=registered_output_ids,
                    reported_output_ids=reported_output_ids,
                )
                output_ids = _merge_artifact_ids(registered_output_ids, reported_output_ids)
                completed = StageRun(
                    stage_id=stage_plan.stage_id,
                    state=LifecycleState.COMPLETED,
                    started_at=started_at,
                    completed_at=_utc_now(),
                    input_artifact_ids=stage_plan.input_artifact_ids,
                    output_artifact_ids=output_ids,
                    retry=RetryMetadata(attempt=attempt, max_attempts=stage_plan.retry_policy.max_attempts),
                    lease_id=lease_id,
                    progress=result.progress if result.progress is not None else context.progress,
                    metadata={**context._metadata, **result.metadata},
                )
                self._upsert_stage(plan.job_id, completed)
                self._record_stage_event(
                    plan.job_id,
                    stage_plan.stage_id,
                    "stage.completed",
                    payload={
                        "attempt": attempt,
                        "lease_id": lease_id,
                        "output_artifact_ids": [artifact_id.to_dict() for artifact_id in output_ids],
                    },
                )
                return completed
            except JobCancellationRequested as exc:
                canceled = StageRun(
                    stage_id=stage_plan.stage_id,
                    state=LifecycleState.CANCELED,
                    started_at=started_at,
                    completed_at=_utc_now(),
                    input_artifact_ids=stage_plan.input_artifact_ids,
                    output_artifact_ids=context.registered_output_ids,
                    retry=RetryMetadata(attempt=attempt, max_attempts=stage_plan.retry_policy.max_attempts),
                    lease_id=lease_id,
                    progress=context.progress,
                    metadata={
                        **context._metadata,
                        "cancellation_reason": exc.reason,
                        "cleanup_policy": "artifacts_preserved_for_inspection",
                    },
                )
                self._upsert_stage(plan.job_id, canceled)
                self._record_stage_event(plan.job_id, stage_plan.stage_id, "stage.canceled", reason=exc.reason)
                return canceled
            except StageExecutionError as exc:
                envelope = exc.error
            except Exception as exc:  # noqa: BLE001 - runner must normalize concrete handler failures.
                envelope = ErrorEnvelope(
                    code=f"{type(exc).__module__}.{type(exc).__name__}",
                    message=str(exc),
                    category="stage_handler",
                    retryable=False,
                )

            retryable = stage_plan.retry_policy.is_retryable(envelope)
            failed = StageRun(
                stage_id=stage_plan.stage_id,
                state=LifecycleState.FAILED,
                started_at=started_at,
                completed_at=_utc_now(),
                input_artifact_ids=stage_plan.input_artifact_ids,
                output_artifact_ids=context.registered_output_ids,
                retry=RetryMetadata(
                    attempt=attempt,
                    max_attempts=stage_plan.retry_policy.max_attempts,
                    retryable=retryable,
                    last_error_code=envelope.code,
                ),
                lease_id=lease_id,
                progress=context.progress,
                metadata={"error": envelope.to_dict()},
            )
            self._upsert_stage(plan.job_id, failed)
            self._record_stage_event(
                plan.job_id,
                stage_plan.stage_id,
                "stage.failed",
                reason=envelope.message,
                payload={"attempt": attempt, "error": envelope.to_dict(), "retryable": retryable},
            )
            last_stage = failed
            if retryable and attempt < stage_plan.retry_policy.max_attempts:
                self._record_stage_event(
                    plan.job_id,
                    stage_plan.stage_id,
                    "stage.retry_scheduled",
                    payload={
                        "attempt": attempt,
                        "next_attempt": attempt + 1,
                        "max_attempts": stage_plan.retry_policy.max_attempts,
                        "error_code": envelope.code,
                    },
                )
                continue
            return failed
        assert last_stage is not None
        return last_stage

    def _validate_declared_outputs_available(
        self,
        plan: JobPlan,
        stage_plan: StagePlan,
        *,
        registered_output_ids: tuple[ArtifactId, ...],
        reported_output_ids: tuple[ArtifactId, ...],
    ) -> None:
        declared_by_qualified = {
            contract.artifact_id.qualified: contract for contract in stage_plan.output_artifacts
        }
        registered_by_qualified = {
            ArtifactId.from_dict(artifact_id).qualified for artifact_id in registered_output_ids
        }
        reported_by_qualified = {
            ArtifactId.from_dict(artifact_id).qualified for artifact_id in reported_output_ids
        }
        produced_by_qualified = registered_by_qualified | reported_by_qualified
        undeclared = sorted(produced_by_qualified - set(declared_by_qualified))
        if undeclared:
            raise ContractValidationError(
                f"stage {stage_plan.stage_id!r} reported undeclared output artifacts: "
                f"{', '.join(undeclared)}"
            )

        missing = sorted(set(declared_by_qualified) - registered_by_qualified)
        if missing:
            raise ContractValidationError(
                f"stage {stage_plan.stage_id!r} did not register declared output artifacts: "
                f"{', '.join(missing)}"
            )

        for qualified, contract in declared_by_qualified.items():
            artifact = self.ledger.get_artifact(contract.artifact_id, missing_ok=True)
            if artifact is None:
                raise ContractValidationError(
                    f"stage {stage_plan.stage_id!r} did not persist declared output artifact: {qualified}"
                )
            self._validate_output_artifact_matches_plan(plan, stage_plan, contract, artifact)

    def _outputs_current(self, plan: JobPlan, stage_plan: StagePlan) -> bool:
        if not stage_plan.output_artifacts:
            return False
        for contract in stage_plan.output_artifacts:
            artifact = self.ledger.get_artifact(contract.artifact_id, missing_ok=True)
            if artifact is None:
                return False
            if artifact.freshness != FreshnessState.CURRENT:
                return False
            try:
                self._validate_output_artifact_matches_plan(plan, stage_plan, contract, artifact)
            except ContractValidationError:
                return False
        return True

    def _validate_output_artifact_matches_plan(
        self,
        plan: JobPlan,
        stage_plan: StagePlan,
        contract: ArtifactContract,
        artifact: ArtifactRef,
    ) -> None:
        qualified = contract.artifact_id.qualified
        if artifact.artifact_type != contract.artifact_type:
            raise ContractValidationError(
                f"declared output {qualified!r} has type "
                f"{artifact.artifact_type!r}; expected {contract.artifact_type!r}"
            )
        if artifact.artifact_schema_version != contract.artifact_schema_version:
            raise ContractValidationError(
                f"declared output {qualified!r} has schema "
                f"{artifact.artifact_schema_version!r}; expected {contract.artifact_schema_version!r}"
            )
        if artifact.freshness != FreshnessState.CURRENT:
            raise ContractValidationError(
                f"declared output {qualified!r} is {artifact.freshness.value}; expected current"
            )
        if artifact.producer_tool_id != plan.tool_id:
            raise ContractValidationError(
                f"declared output {qualified!r} was produced by tool "
                f"{artifact.producer_tool_id!r}; expected {plan.tool_id!r}"
            )
        if artifact.producer_stage_id != stage_plan.stage_id:
            raise ContractValidationError(
                f"declared output {qualified!r} was produced by stage "
                f"{artifact.producer_stage_id!r}; expected {stage_plan.stage_id!r}"
            )
        if artifact.input_artifact_ids != stage_plan.input_artifact_ids:
            raise ContractValidationError(
                f"declared output {qualified!r} has input artifact IDs that do not match stage plan"
            )
        expected_config_fingerprint = config_fingerprint(plan.config)
        if artifact.config_fingerprint != expected_config_fingerprint:
            raise ContractValidationError(
                f"declared output {qualified!r} has config fingerprint "
                f"{artifact.config_fingerprint!r}; expected {expected_config_fingerprint!r}"
            )

    def _pending_stage(self, stage_plan: StagePlan) -> StageRun:
        return StageRun(
            stage_id=stage_plan.stage_id,
            state=LifecycleState.PENDING,
            input_artifact_ids=stage_plan.input_artifact_ids,
            retry=RetryMetadata(max_attempts=stage_plan.retry_policy.max_attempts),
            metadata=stage_plan.metadata,
        )

    def _merged_stage_runs(self, plan: JobPlan) -> tuple[StageRun, ...]:
        existing = {stage.stage_id: stage for stage in self._stage_runs_or_empty(plan.job_id)}
        return tuple(existing.get(stage.stage_id, self._pending_stage(stage)) for stage in plan.stages)

    def _finish_canceled_before_stage(
        self, plan: JobPlan, stage_plan: StagePlan, reason: str, job: Job
    ) -> Job:
        current_stage = self._stage_by_id(plan.job_id, stage_plan.stage_id)
        canceled = replace(
            current_stage,
            state=LifecycleState.CANCELED,
            completed_at=_utc_now(),
            metadata={**dict(current_stage.metadata), "cancellation_reason": reason},
        )
        self._upsert_stage(plan.job_id, canceled)
        self._record_stage_event(job_id=plan.job_id, stage_id=stage_plan.stage_id, event_type="stage.canceled", reason=reason)
        self._cancel_requested.pop(plan.job_id, None)
        return self._upsert_job(
            replace(job, state=LifecycleState.CANCELED, stages=self._stage_runs_or_empty(plan.job_id)),
            event_type="job.canceled",
            reason=reason,
        )

    def _finish_job(
        self,
        plan: JobPlan,
        state: LifecycleState,
        *,
        event_type: str,
        reason: str = "",
        payload: Mapping[str, Any] | None = None,
    ) -> Job:
        existing = self._get_job(plan.job_id)
        if state == LifecycleState.CANCELED:
            self._cancel_requested.pop(plan.job_id, None)
        return self._upsert_job(
            Job(
                job_id=plan.job_id,
                tool_id=plan.tool_id,
                state=state,
                created_at=existing.created_at,
                stages=self._stage_runs_or_empty(plan.job_id),
                input_artifact_ids=plan.input_artifact_ids,
                config_fingerprint=config_fingerprint(plan.config),
                metadata=plan.metadata,
            ),
            event_type=event_type,
            reason=reason,
            payload=payload,
        )

    def _get_job_or_none(self, job_id: str) -> Job | None:
        try:
            return self.ledger.get_job(job_id)
        except KeyError:
            return None

    def _get_job(self, job_id: str) -> Job:
        return self.ledger.get_job(job_id)

    def _stage_runs_or_empty(self, job_id: str) -> tuple[StageRun, ...]:
        try:
            return self.ledger.list_stage_runs(job_id)
        except KeyError:
            return ()

    def _stage_by_id(self, job_id: str, stage_id: str) -> StageRun:
        for stage in self.ledger.list_stage_runs(job_id):
            if stage.stage_id == stage_id:
                return stage
        raise KeyError(f"{job_id}:{stage_id}")

    def _upsert_job(
        self,
        job: Job,
        *,
        event_type: str,
        reason: str = "",
        payload: Mapping[str, Any] | None = None,
    ) -> Job:
        self.ledger.upsert_job(job)
        self.ledger.record_event(
            entity_type="job",
            entity_id=job.job_id,
            event_type=event_type,
            reason=reason,
            payload=payload or {"state": job.state.value},
        )
        return job

    def _upsert_stage(self, job_id: str, stage: StageRun) -> None:
        self.ledger.upsert_stage_run(job_id, stage)

    def _record_stage_event(
        self,
        job_id: str,
        stage_id: str,
        event_type: str,
        *,
        reason: str = "",
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        self.ledger.record_event(
            entity_type="stage_run",
            entity_id=f"{job_id}:{stage_id}",
            event_type=event_type,
            reason=reason,
            payload=payload or {},
        )


def _merge_artifact_ids(*groups: tuple[ArtifactId, ...]) -> tuple[ArtifactId, ...]:
    by_qualified: dict[str, ArtifactId] = {}
    for group in groups:
        for artifact_id in group:
            normalized = ArtifactId.from_dict(artifact_id)
            by_qualified[normalized.qualified] = normalized
    return tuple(by_qualified[key] for key in sorted(by_qualified))


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
