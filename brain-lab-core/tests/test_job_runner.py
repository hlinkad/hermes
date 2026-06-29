from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from brain_lab_core.contracts import (
    ArtifactId,
    ContractValidationError,
    ErrorEnvelope,
    FreshnessState,
    LifecycleState,
)
from brain_lab_core.orchestration import (
    ArtifactContract,
    JobPlan,
    JobRunner,
    RetryPolicy,
    StageExecutionError,
    StageExecutionResult,
    StagePlan,
)
from brain_lab_core.state import SQLiteArtifactLedger


class JobRunnerLifecycleTests(unittest.TestCase):
    def test_multistage_job_fails_then_resumes_from_failed_stage_and_completes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = SQLiteArtifactLedger(root / "ledger.sqlite", artifact_root=root)
            source_id = ArtifactId("source", namespace="fixture")
            source_path = root / "source.txt"
            source_path.write_text("source\n", encoding="utf-8")
            ledger.register_artifact_from_file(
                artifact_id=source_id,
                artifact_type="source.text",
                artifact_schema_version="source.v1",
                file_path=source_path,
            )
            attempts = {"extract": 0, "summarize": 0}
            records_id = ArtifactId("records", namespace="fixture")
            report_id = ArtifactId("report", namespace="fixture")

            def extract(context):
                attempts["extract"] += 1
                records_path = root / "records.json"
                records_path.write_text('{"records": ["source"]}\n', encoding="utf-8")
                artifact = context.register_output(records_id, records_path)
                return StageExecutionResult(output_artifact_ids=(artifact.artifact_id,))

            def summarize(context):
                attempts["summarize"] += 1
                if attempts["summarize"] == 1:
                    raise StageExecutionError(
                        ErrorEnvelope(
                            code="fixture.summarize.missing_model",
                            message="model unavailable until resume",
                            retryable=False,
                        )
                    )
                report_path = root / "report.md"
                report_path.write_text("summary\n", encoding="utf-8")
                artifact = context.register_output(report_id, report_path)
                return StageExecutionResult(output_artifact_ids=(artifact.artifact_id,))

            plan = JobPlan(
                job_id="job-resume",
                tool_id="fixture-tool",
                input_artifact_ids=(source_id,),
                config={"revision": 1},
                stages=(
                    StagePlan(
                        stage_id="extract",
                        handler=extract,
                        input_artifact_ids=(source_id,),
                        output_artifacts=(ArtifactContract(records_id, "fixture.records", "records.v1"),),
                    ),
                    StagePlan(
                        stage_id="summarize",
                        handler=summarize,
                        input_artifact_ids=(records_id,),
                        output_artifacts=(ArtifactContract(report_id, "report.markdown", "report.v1"),),
                    ),
                ),
            )
            runner = JobRunner(ledger)

            failed_job = runner.run(plan)

            self.assertEqual(failed_job.state, LifecycleState.FAILED)
            self.assertEqual(
                [(stage.stage_id, stage.state) for stage in ledger.list_stage_runs(plan.job_id)],
                [("extract", LifecycleState.COMPLETED), ("summarize", LifecycleState.FAILED)],
            )
            self.assertEqual(attempts, {"extract": 1, "summarize": 1})
            self.assertEqual(ledger.artifact_count(), 2)

            completed_job = runner.run(plan, resume=True)

            self.assertEqual(completed_job.state, LifecycleState.COMPLETED)
            self.assertEqual(
                [(stage.stage_id, stage.state) for stage in ledger.list_stage_runs(plan.job_id)],
                [("extract", LifecycleState.COMPLETED), ("summarize", LifecycleState.COMPLETED)],
            )
            self.assertEqual(attempts, {"extract": 1, "summarize": 2})
            self.assertEqual(ledger.artifact_count(), 3)
            self.assertEqual(ledger.get_artifact(report_id).artifact_type, "report.markdown")
            events = runner.list_job_events(plan.job_id)
            event_types = [event.event_type for event in events]
            self.assertIn("job.running", event_types)
            self.assertIn("stage.failed", event_types)
            self.assertIn("job.completed", event_types)
            self.assertEqual([event.event_id for event in events], sorted(event.event_id for event in events))
            json.dumps(
                [
                    {
                        "event_id": event.event_id,
                        "created_at": event.created_at,
                        "entity_type": event.entity_type,
                        "entity_id": event.entity_id,
                        "event_type": event.event_type,
                        "reason": event.reason,
                        "payload": event.payload,
                    }
                    for event in events
                ],
                sort_keys=True,
            )

    def test_retry_policy_classifies_retryable_and_non_retryable_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = SQLiteArtifactLedger(root / "ledger.sqlite", artifact_root=root)
            transient_attempts = {"count": 0}
            transient_id = ArtifactId("transient-output", namespace="fixture")
            terminal_id = ArtifactId("terminal-output", namespace="fixture")

            def transient(context):
                transient_attempts["count"] += 1
                if transient_attempts["count"] == 1:
                    raise StageExecutionError(
                        ErrorEnvelope(
                            code="TEMPORARY.network",
                            message="classified by retry policy code",
                            retryable=False,
                        )
                    )
                payload = root / "transient.txt"
                payload.write_text("ok\n", encoding="utf-8")
                artifact = context.register_output(transient_id, payload)
                return StageExecutionResult(output_artifact_ids=(artifact.artifact_id,))

            def terminal(_context):
                raise StageExecutionError(
                    ErrorEnvelope(
                        code="BUG",
                        message="non retryable bug",
                        retryable=True,
                    )
                )

            plan = JobPlan(
                job_id="job-retry",
                tool_id="fixture-tool",
                stages=(
                    StagePlan(
                        stage_id="transient",
                        handler=transient,
                        output_artifacts=(ArtifactContract(transient_id, "fixture.text", "fixture.v1"),),
                        retry_policy=RetryPolicy(max_attempts=3, retryable_error_codes=("TEMPORARY*",)),
                    ),
                    StagePlan(
                        stage_id="terminal",
                        handler=terminal,
                        output_artifacts=(ArtifactContract(terminal_id, "fixture.text", "fixture.v1"),),
                        retry_policy=RetryPolicy(
                            max_attempts=3,
                            retryable_error_codes=("TEMPORARY",),
                            non_retryable_error_codes=("BUG",),
                        ),
                    ),
                ),
            )
            runner = JobRunner(ledger)

            job = runner.run(plan)

            self.assertEqual(job.state, LifecycleState.FAILED)
            self.assertEqual(transient_attempts["count"], 2)
            stages = {stage.stage_id: stage for stage in ledger.list_stage_runs(plan.job_id)}
            self.assertEqual(stages["transient"].state, LifecycleState.COMPLETED)
            self.assertEqual(stages["transient"].retry.attempt, 2)
            self.assertEqual(stages["terminal"].state, LifecycleState.FAILED)
            self.assertEqual(stages["terminal"].retry.attempt, 1)
            event_types = [event.event_type for event in runner.list_job_events(plan.job_id)]
            self.assertEqual(event_types.count("stage.retry_scheduled"), 1)

    def test_stale_stage_rerun_is_idempotent_and_current_outputs_are_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = SQLiteArtifactLedger(root / "ledger.sqlite", artifact_root=root)
            output_id = ArtifactId("stable-report", namespace="fixture")
            calls = {"write": 0}

            def write_report(context):
                calls["write"] += 1
                path = root / "stable-report.md"
                path.write_text("stable report\n", encoding="utf-8")
                artifact = context.register_output(output_id, path)
                return StageExecutionResult(output_artifact_ids=(artifact.artifact_id,))

            plan = JobPlan(
                job_id="job-stale",
                tool_id="fixture-tool",
                stages=(
                    StagePlan(
                        stage_id="write-report",
                        handler=write_report,
                        output_artifacts=(ArtifactContract(output_id, "report.markdown", "report.v1"),),
                    ),
                ),
            )
            runner = JobRunner(ledger)

            self.assertEqual(runner.run(plan).state, LifecycleState.COMPLETED)
            self.assertEqual(ledger.artifact_count(), 1)
            runner.mark_stage_stale(plan.job_id, "write-report", reason="fixture invalidated")
            self.assertEqual(runner.run(plan, resume=True).state, LifecycleState.COMPLETED)
            self.assertEqual(ledger.artifact_count(), 1)
            self.assertEqual(calls["write"], 2)

            # A later resume sees the completed stage's declared output is current and does not call it again.
            self.assertEqual(runner.run(plan, resume=True).state, LifecycleState.COMPLETED)
            self.assertEqual(ledger.artifact_count(), 1)
            self.assertEqual(calls["write"], 2)
            event_types = [event.event_type for event in runner.list_job_events(plan.job_id)]
            self.assertIn("stage.stale", event_types)
            self.assertIn("stage.skipped_current", event_types)

    def test_stale_artifact_is_revalidated_without_duplicate_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = SQLiteArtifactLedger(root / "ledger.sqlite", artifact_root=root)
            source_id = ArtifactId("source", namespace="fixture")
            output_id = ArtifactId("derived", namespace="fixture")
            source_path = root / "source.txt"
            source_path.write_text("source\n", encoding="utf-8")
            ledger.register_artifact_from_file(
                artifact_id=source_id,
                artifact_type="source.text",
                artifact_schema_version="source.v1",
                file_path=source_path,
            )
            calls = {"derive": 0}

            def derive(context):
                calls["derive"] += 1
                payload = root / "derived.txt"
                payload.write_text("same derived payload\n", encoding="utf-8")
                artifact = context.register_output(output_id, payload)
                return StageExecutionResult(output_artifact_ids=(artifact.artifact_id,))

            plan = JobPlan(
                job_id="job-artifact-stale",
                tool_id="fixture-tool",
                input_artifact_ids=(source_id,),
                stages=(
                    StagePlan(
                        stage_id="derive",
                        handler=derive,
                        input_artifact_ids=(source_id,),
                        output_artifacts=(ArtifactContract(output_id, "fixture.derived", "fixture.v1"),),
                    ),
                ),
            )
            runner = JobRunner(ledger)

            self.assertEqual(runner.run(plan).state, LifecycleState.COMPLETED)
            self.assertEqual(ledger.mark_dependents_stale((source_id,), reason="fixture upstream invalidation"), 1)
            self.assertEqual(ledger.get_artifact(output_id).freshness, FreshnessState.STALE)

            self.assertEqual(runner.run(plan, resume=True).state, LifecycleState.COMPLETED)

            self.assertEqual(calls["derive"], 2)
            self.assertEqual(ledger.artifact_count(), 2)
            self.assertEqual(ledger.get_artifact(output_id).freshness, FreshnessState.CURRENT)
            event_types = [event.event_type for event in runner.list_job_events(plan.job_id)]
            self.assertIn("stage.completed", event_types)
            ledger_event_types = [event.event_type for event in ledger.list_events(entity_id=output_id.qualified)]
            self.assertIn("artifact.revalidated", ledger_event_types)

    def test_cancellation_leaves_state_artifacts_and_events_inspectable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = SQLiteArtifactLedger(root / "ledger.sqlite", artifact_root=root)
            partial_id = ArtifactId("partial", namespace="fixture")

            def cancellable(context):
                payload = root / "partial.txt"
                payload.write_text("partial but inspectable\n", encoding="utf-8")
                artifact = context.register_output(partial_id, payload)
                context.record_progress(0.5, message="halfway")
                context.cancel("operator requested stop")
                return StageExecutionResult(output_artifact_ids=(artifact.artifact_id,))

            plan = JobPlan(
                job_id="job-cancel",
                tool_id="fixture-tool",
                stages=(
                    StagePlan(
                        stage_id="long-running",
                        handler=cancellable,
                        output_artifacts=(ArtifactContract(partial_id, "fixture.partial", "fixture.v1"),),
                    ),
                ),
            )
            runner = JobRunner(ledger)

            job = runner.run(plan)

            self.assertEqual(job.state, LifecycleState.CANCELED)
            self.assertEqual(ledger.get_artifact(partial_id).artifact_type, "fixture.partial")
            self.assertEqual(ledger.get_artifact_path(partial_id).read_text(encoding="utf-8"), "partial but inspectable\n")
            stage = ledger.list_stage_runs(plan.job_id)[0]
            self.assertEqual(stage.state, LifecycleState.CANCELED)
            self.assertEqual(stage.output_artifact_ids, (partial_id,))
            self.assertEqual(stage.progress, 0.5)
            self.assertIn("operator requested stop", stage.metadata["cancellation_reason"])
            event_types = [event.event_type for event in runner.list_job_events(plan.job_id)]
            self.assertIn("stage.progress", event_types)
            self.assertIn("stage.canceled", event_types)
            self.assertIn("job.canceled", event_types)

    def test_completed_stage_preserves_progress_and_result_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = SQLiteArtifactLedger(root / "ledger.sqlite", artifact_root=root)
            output_id = ArtifactId("metadata-output", namespace="fixture")

            def complete_with_progress(context):
                context.record_progress(0.25, message="quarter done")
                payload = root / "metadata-output.txt"
                payload.write_text("ok\n", encoding="utf-8")
                context.register_output(output_id, payload)
                return StageExecutionResult(metadata={"result": "ready"})

            plan = JobPlan(
                job_id="job-progress-metadata",
                tool_id="fixture-tool",
                stages=(
                    StagePlan(
                        stage_id="metadata-stage",
                        handler=complete_with_progress,
                        output_artifacts=(ArtifactContract(output_id, "fixture.text", "fixture.v1"),),
                        metadata={"planned": True},
                    ),
                ),
            )
            runner = JobRunner(ledger)

            self.assertEqual(runner.run(plan).state, LifecycleState.COMPLETED)

            stage = ledger.list_stage_runs(plan.job_id)[0]
            self.assertEqual(stage.progress, 1.0)
            self.assertEqual(stage.metadata["planned"], True)
            self.assertEqual(stage.metadata["progress_message"], "quarter done")
            self.assertEqual(stage.metadata["result"], "ready")

    def test_ledger_backed_cancel_request_cancels_new_runner_and_is_consumed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = SQLiteArtifactLedger(root / "ledger.sqlite", artifact_root=root)
            output_id = ArtifactId("should-not-run", namespace="fixture")
            calls = {"count": 0}

            def handler(context):
                calls["count"] += 1
                payload = root / "should-not-run.txt"
                payload.write_text("unexpected\n", encoding="utf-8")
                context.register_output(output_id, payload)
                return StageExecutionResult()

            plan = JobPlan(
                job_id="job-durable-cancel",
                tool_id="fixture-tool",
                stages=(
                    StagePlan(
                        stage_id="first-stage",
                        handler=handler,
                        output_artifacts=(ArtifactContract(output_id, "fixture.text", "fixture.v1"),),
                    ),
                ),
            )
            JobRunner(ledger).request_cancel(plan.job_id, reason="operator canceled before dispatch")
            runner = JobRunner(ledger)

            job = runner.run(plan)

            self.assertEqual(job.state, LifecycleState.CANCELED)
            self.assertEqual(calls["count"], 0)
            self.assertIsNone(runner.cancellation_reason(plan.job_id))
            self.assertIsNone(JobRunner(ledger).cancellation_reason(plan.job_id))
            stage = ledger.list_stage_runs(plan.job_id)[0]
            self.assertEqual(stage.state, LifecycleState.CANCELED)
            self.assertIn("operator canceled", stage.metadata["cancellation_reason"])
            event_types = [event.event_type for event in runner.list_job_events(plan.job_id)]
            self.assertIn("job.cancel_requested", event_types)
            self.assertIn("job.canceled", event_types)

    def test_plan_validation_requires_explicit_contracts_and_known_dependencies(self) -> None:
        out_id = ArtifactId("out", namespace="fixture")
        with self.assertRaisesRegex(ContractValidationError, "job_plan.job_id"):
            JobPlan(
                job_id="ambiguous:job",
                tool_id="fixture-tool",
                stages=(StagePlan("stage", lambda _context: StageExecutionResult()),),
            )
        with self.assertRaisesRegex(ContractValidationError, "stage_plan.stage_id"):
            StagePlan("ambiguous:stage", lambda _context: StageExecutionResult())
        with self.assertRaisesRegex(ContractValidationError, "duplicate stage_id"):
            JobPlan(
                job_id="duplicate-stages",
                tool_id="fixture-tool",
                stages=(
                    StagePlan("stage", lambda _context: StageExecutionResult(), output_artifacts=(ArtifactContract(out_id, "x", "v1"),)),
                    StagePlan("stage", lambda _context: StageExecutionResult(), output_artifacts=(ArtifactContract(ArtifactId("other", namespace="fixture"), "x", "v1"),)),
                ),
            )
        with self.assertRaisesRegex(ContractValidationError, "unknown input artifact"):
            JobPlan(
                job_id="unknown-input",
                tool_id="fixture-tool",
                stages=(
                    StagePlan(
                        "needs-missing",
                        lambda _context: StageExecutionResult(),
                        input_artifact_ids=(ArtifactId("missing", namespace="fixture"),),
                        output_artifacts=(ArtifactContract(out_id, "x", "v1"),),
                    ),
                ),
            )
        with self.assertRaisesRegex(ContractValidationError, "duplicate output artifact"):
            JobPlan(
                job_id="duplicate-output",
                tool_id="fixture-tool",
                stages=(
                    StagePlan("one", lambda _context: StageExecutionResult(), output_artifacts=(ArtifactContract(out_id, "x", "v1"),)),
                    StagePlan("two", lambda _context: StageExecutionResult(), output_artifacts=(ArtifactContract(out_id, "x", "v1"),)),
                ),
            )

    def test_stage_cannot_register_undeclared_output_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = SQLiteArtifactLedger(root / "ledger.sqlite", artifact_root=root)
            declared_id = ArtifactId("declared", namespace="fixture")
            undeclared_id = ArtifactId("undeclared", namespace="fixture")

            def bad_stage(context):
                payload = root / "undeclared.txt"
                payload.write_text("not declared\n", encoding="utf-8")
                context.register_output(undeclared_id, payload)
                return StageExecutionResult()

            plan = JobPlan(
                job_id="job-undeclared-output",
                tool_id="fixture-tool",
                stages=(
                    StagePlan(
                        stage_id="bad-stage",
                        handler=bad_stage,
                        output_artifacts=(ArtifactContract(declared_id, "fixture.text", "fixture.v1"),),
                    ),
                ),
            )
            runner = JobRunner(ledger)

            job = runner.run(plan)

            self.assertEqual(job.state, LifecycleState.FAILED)
            failed_stage = ledger.list_stage_runs(plan.job_id)[0]
            self.assertEqual(failed_stage.state, LifecycleState.FAILED)
            self.assertIn("undeclared output", failed_stage.metadata["error"]["message"])
            self.assertEqual(ledger.artifact_count(), 0)

    def test_stage_cannot_claim_unregistered_or_undeclared_result_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            declared_id = ArtifactId("declared-result", namespace="fixture")
            undeclared_id = ArtifactId("undeclared-result", namespace="fixture")

            def claim_without_registering(_context):
                return StageExecutionResult(output_artifact_ids=(declared_id,))

            ledger = SQLiteArtifactLedger(root / "unregistered.sqlite", artifact_root=root)
            preexisting_payload = root / "preexisting-declared-result.txt"
            preexisting_payload.write_text("external current artifact\n", encoding="utf-8")
            ledger.register_artifact_from_file(
                artifact_id=declared_id,
                artifact_type="fixture.text",
                artifact_schema_version="fixture.v1",
                file_path=preexisting_payload,
            )
            plan = JobPlan(
                job_id="job-unregistered-result-output",
                tool_id="fixture-tool",
                stages=(
                    StagePlan(
                        stage_id="claim-only",
                        handler=claim_without_registering,
                        output_artifacts=(ArtifactContract(declared_id, "fixture.text", "fixture.v1"),),
                    ),
                ),
            )
            runner = JobRunner(ledger)

            job = runner.run(plan)

            self.assertEqual(job.state, LifecycleState.FAILED)
            failed_stage = ledger.list_stage_runs(plan.job_id)[0]
            self.assertIn("did not register", failed_stage.metadata["error"]["message"])
            self.assertEqual(ledger.artifact_count(), 1)

            def register_declared_but_report_extra(context):
                payload = root / "declared-result.txt"
                payload.write_text("registered\n", encoding="utf-8")
                context.register_output(declared_id, payload)
                return StageExecutionResult(output_artifact_ids=(undeclared_id,))

            extra_ledger = SQLiteArtifactLedger(root / "undeclared-result.sqlite", artifact_root=root)
            extra_plan = JobPlan(
                job_id="job-undeclared-result-output",
                tool_id="fixture-tool",
                stages=(
                    StagePlan(
                        stage_id="extra-result",
                        handler=register_declared_but_report_extra,
                        output_artifacts=(ArtifactContract(declared_id, "fixture.text", "fixture.v1"),),
                    ),
                ),
            )
            extra_runner = JobRunner(extra_ledger)

            extra_job = extra_runner.run(extra_plan)

            self.assertEqual(extra_job.state, LifecycleState.FAILED)
            extra_failed_stage = extra_ledger.list_stage_runs(extra_plan.job_id)[0]
            self.assertIn("reported undeclared output", extra_failed_stage.metadata["error"]["message"])


if __name__ == "__main__":
    unittest.main()
