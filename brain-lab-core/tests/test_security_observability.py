from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from brain_lab_core.api import FoundationControlPlane
from brain_lab_core.contracts import (
    CONTRACT_SCHEMA_VERSION,
    ErrorEnvelope,
    Job,
    LifecycleState,
    Provenance,
    ResourceProfile,
    ToolManifest,
)
from brain_lab_core.observability import EvaluationHook, ObservabilityEvent, TraceContext
from brain_lab_core.orchestration import ArtifactContract, JobPlan, StageExecutionError, StageExecutionResult, StagePlan
from brain_lab_core.registry import ToolRegistry, fixture_tool_manifest
from brain_lab_core.security import (
    DependencyMetadata,
    FileAccessMode,
    FileAccessPolicy,
    NetworkAccessMode,
    NetworkPolicy,
    REDACTED,
    SandboxClass,
    SandboxPolicy,
    SecretDeclaration,
    SourceLicensePolicy,
    SourcePolicyStatus,
    collect_secret_values,
    redact_secrets,
)
from brain_lab_core.state import SQLiteArtifactLedger


class SecurityPolicyTests(unittest.TestCase):
    def test_tool_manifest_declares_sandbox_dependencies_and_secret_policy(self) -> None:
        sandbox = SandboxPolicy(
            sandbox_class=SandboxClass.NETWORKED,
            filesystem=FileAccessPolicy(mode=FileAccessMode.READ, allowed_paths=("/workspace/input",)),
            network=NetworkPolicy(mode=NetworkAccessMode.OUTBOUND, allowed_hosts=("qdrant.local",)),
            allow_subprocess=False,
            metadata={"fixture": True},
        )
        dependency = DependencyMetadata(
            name="qdrant-client",
            version="1.9.0",
            package_url="pkg:pypi/qdrant-client@1.9.0",
            license_name="Apache-2.0",
        )
        secret = SecretDeclaration(
            name="QDRANT_API_KEY",
            required=True,
            provider_id="qdrant-local",
            redaction_hint="api key",
        )
        manifest = ToolManifest(
            tool_id="retrieval-fixture",
            tool_version="0.1.0",
            capabilities=("retrieval.index",),
            input_artifact_types=("retrieval.chunks",),
            output_artifact_types=("retrieval.embedding",),
            entrypoints={"python": "retrieval_fixture:register"},
            resource_profile=ResourceProfile(network_required=True, memory_mb=128),
            required_secret_names=("QDRANT_API_KEY",),
            secret_declarations=(secret,),
            sandbox_policy=sandbox,
            dependency_metadata=(dependency,),
        )

        payload = manifest.to_dict()
        round_tripped = ToolManifest.from_json(manifest.to_json())
        diagnostics = manifest.validate()

        self.assertEqual(round_tripped, manifest)
        self.assertEqual(payload["sandbox_policy"]["sandbox_class"], SandboxClass.NETWORKED.value)
        self.assertEqual(payload["sandbox_policy"]["network"]["allowed_hosts"], ["qdrant.local"])
        self.assertEqual(payload["dependency_metadata"][0]["package_url"], "pkg:pypi/qdrant-client@1.9.0")
        self.assertEqual(payload["secret_declarations"][0]["provider_id"], "qdrant-local")
        self.assertEqual(payload["required_secret_names"], ["QDRANT_API_KEY"])
        self.assertEqual(diagnostics, ())

    def test_manifest_validation_flags_resource_and_sandbox_conflicts(self) -> None:
        manifest = ToolManifest(
            tool_id="networked-but-locked",
            tool_version="0.1.0",
            capabilities=("fixture.run",),
            input_artifact_types=("source.url",),
            output_artifact_types=("report.markdown",),
            entrypoints={"python": "fixture:register"},
            resource_profile=ResourceProfile(network_required=True, gpu_required=True),
            sandbox_policy=SandboxPolicy(),
        )

        diagnostics = manifest.validate()

        self.assertTrue(any(diagnostic.severity == "error" for diagnostic in diagnostics))
        diagnostic_messages = "\n".join(diagnostic.message for diagnostic in diagnostics)
        self.assertIn("network", diagnostic_messages)
        self.assertIn("GPU", diagnostic_messages)

    def test_redaction_preserves_public_secret_metadata_and_collects_values(self) -> None:
        payload = {
            "secret_policy": {"secret_names": ["CUSTOM_TOKEN"], "redaction_marker": REDACTED},
            "required_secret_names": ["CUSTOM_TOKEN"],
            "CUSTOM_TOKEN": "super-secret-value",
            "message": "prefix super-secret-value suffix",
            "safe": "visible",
        }

        secret_values = collect_secret_values(payload, ("CUSTOM_TOKEN",))
        redacted = redact_secrets(payload, secret_names=("CUSTOM_TOKEN",), secret_values=secret_values)

        self.assertEqual(secret_values, {"super-secret-value"})
        self.assertEqual(redacted["secret_policy"]["secret_names"], ["CUSTOM_TOKEN"])
        self.assertEqual(redacted["required_secret_names"], ["CUSTOM_TOKEN"])
        self.assertEqual(redacted["CUSTOM_TOKEN"], REDACTED)
        self.assertEqual(redacted["message"], f"prefix {REDACTED} suffix")
        self.assertEqual(redacted["safe"], "visible")

    def test_control_plane_redacts_optional_declared_secret_names(self) -> None:
        manifest = ToolManifest(
            tool_id="optional-secret-fixture",
            tool_version="0.1.0",
            capabilities=("fixture.run",),
            input_artifact_types=("source.url",),
            output_artifact_types=("report.markdown",),
            entrypoints={"python": "fixture:register"},
            secret_declarations=(SecretDeclaration(name="OPTIONAL_TOKEN", required=False),),
        )
        with tempfile.TemporaryDirectory() as tmp:
            plane = FoundationControlPlane(
                tool_registry=ToolRegistry([manifest]),
                ledger=SQLiteArtifactLedger(Path(tmp) / "ledger.sqlite", artifact_root=Path(tmp) / "artifacts"),
                config={"OPTIONAL_TOKEN": "optional-secret-value"},
            )
            config = plane.config_status()
            tools = plane.list_tools()

        serialized = json.dumps({"config": config, "tools": tools}, sort_keys=True)
        self.assertEqual(config["config"]["OPTIONAL_TOKEN"], REDACTED)
        self.assertIn("OPTIONAL_TOKEN", config["secret_policy"]["secret_names"])
        self.assertEqual(tools["tools"][0]["secret_declarations"][0]["name"], "OPTIONAL_TOKEN")
        self.assertNotIn("optional-secret-value", serialized)
        self.assertEqual(manifest.required_secret_names, ())

    def test_provenance_carries_license_source_policy_without_collapsing_unknowns(self) -> None:
        provenance = Provenance(
            tool_id="fixture-tool",
            source_refs=("source:url:https://example.test/report",),
            source_name="Example Source",
            source_url="https://example.test/report",
            license_name="CC-BY-4.0",
            license_url="https://creativecommons.org/licenses/by/4.0/",
            source_policy_status=SourcePolicyStatus.ALLOWED.value,
            source_policy_notes="Attribution required in downstream reports.",
        )
        policy = SourceLicensePolicy.from_provenance(
            provenance,
            robots_allowed=None,
            api_allowed=True,
            attribution_required=True,
        )
        disallowed = SourceLicensePolicy(
            source_name="Blocked Source",
            source_url="https://blocked.example/",
            policy_status=SourcePolicyStatus.DISALLOWED,
            robots_allowed=False,
            api_allowed=True,
        )

        round_tripped = Provenance.from_json(provenance.to_json())
        allowed_diagnostics = policy.validate()
        disallowed_diagnostics = disallowed.validate()

        self.assertEqual(round_tripped, provenance)
        self.assertEqual(provenance.to_dict()["source_policy_status"], "allowed")
        self.assertEqual(allowed_diagnostics, ())
        self.assertTrue(any(diagnostic.severity == "error" for diagnostic in disallowed_diagnostics))
        self.assertIsNone(policy.robots_allowed)

    def test_control_plane_redacts_secrets_from_failed_status_and_events(self) -> None:
        secret_value = "stage-secret-token"
        with tempfile.TemporaryDirectory() as tmp:
            manifest = fixture_tool_manifest(required_secret_names=("FAIL_TOKEN",))
            tool_registry = ToolRegistry([manifest])
            ledger = SQLiteArtifactLedger(Path(tmp) / "ledger.sqlite", artifact_root=Path(tmp) / "artifacts")

            def factory(_submission: object) -> JobPlan:
                def fail(_context: object) -> object:
                    raise StageExecutionError(
                        ErrorEnvelope(
                            code="fixture.secret_failure",
                            message=f"provider returned {secret_value}",
                            context={"credential": secret_value, "public": "safe"},
                        )
                    )

                return JobPlan(
                    job_id="failing-job",
                    tool_id="fixture-tool",
                    stages=(StagePlan(stage_id="fail", handler=fail),),
                )

            plane = FoundationControlPlane(
                tool_registry=tool_registry,
                ledger=ledger,
                config={"FAIL_TOKEN": secret_value},
                job_plan_factories={"fixture-tool": factory},
            )
            response = plane.create_job({"tool_id": "fixture-tool", "job_id": "failing-job"})
            polled = plane.get_job("failing-job")
            stored_job = ledger.get_job("failing-job").to_dict()
            stored_stages = [stage.to_dict() for stage in ledger.list_stage_runs("failing-job")]
            stored_events = [event.__dict__ for event in ledger.list_events()]
            config = plane.config_status()

        serialized = json.dumps(
            {
                "response": response,
                "polled": polled,
                "stored_job": stored_job,
                "stored_stages": stored_stages,
                "stored_events": stored_events,
                "config": config,
            },
            sort_keys=True,
        )
        self.assertNotIn(secret_value, serialized)
        self.assertIn(REDACTED, serialized)
        self.assertEqual(config["config"]["FAIL_TOKEN"], REDACTED)
        self.assertEqual(response["stages"][0]["metadata"]["error"]["context"]["public"], "safe")

    def test_job_redaction_context_does_not_expose_secret_values_to_stage_plans(self) -> None:
        allowed_secret = "allowed-stage-secret"
        unrelated_secret = "unrelated-control-plane-secret"
        observed_plan_metadata: list[str] = []
        manifest = ToolManifest(
            tool_id="scoped-secret-fixture",
            tool_version="0.1.0",
            capabilities=("fixture.run",),
            input_artifact_types=("source.url",),
            output_artifact_types=("report.markdown",),
            entrypoints={"python": "fixture:register"},
            secret_declarations=(SecretDeclaration(name="RUN_TOKEN", required=True),),
        )

        def factory(_submission: object) -> JobPlan:
            def inspect_metadata(context: object) -> StageExecutionResult:
                observed_plan_metadata.append(json.dumps(context.plan.metadata, sort_keys=True))
                return StageExecutionResult(metadata={"message": f"used {allowed_secret}"})

            return JobPlan(
                job_id="scoped-secret-job",
                tool_id="scoped-secret-fixture",
                stages=(StagePlan(stage_id="inspect", handler=inspect_metadata),),
            )

        with tempfile.TemporaryDirectory() as tmp:
            plane = FoundationControlPlane(
                tool_registry=ToolRegistry([manifest]),
                ledger=SQLiteArtifactLedger(Path(tmp) / "ledger.sqlite", artifact_root=Path(tmp) / "artifacts"),
                config={"RUN_TOKEN": allowed_secret, "OTHER_TOKEN": unrelated_secret},
                job_plan_factories={"scoped-secret-fixture": factory},
            )
            response = plane.create_job({"tool_id": "scoped-secret-fixture", "job_id": "scoped-secret-job"})

        self.assertEqual(len(observed_plan_metadata), 1)
        self.assertNotIn(allowed_secret, observed_plan_metadata[0])
        self.assertNotIn(unrelated_secret, observed_plan_metadata[0])
        serialized = json.dumps(response, sort_keys=True)
        self.assertNotIn(allowed_secret, serialized)
        self.assertNotIn(unrelated_secret, serialized)
        self.assertIn(REDACTED, serialized)

    def test_artifact_and_search_outputs_redact_job_scoped_secret_values(self) -> None:
        secret_value = "artifact-secret-token"
        artifact_id = "fixture:secret-artifact"
        manifest = ToolManifest(
            tool_id="artifact-secret-fixture",
            tool_version="0.1.0",
            capabilities=("fixture.run",),
            input_artifact_types=("source.url",),
            output_artifact_types=("report.markdown",),
            entrypoints={"python": "fixture:register"},
            secret_declarations=(SecretDeclaration(name="ARTIFACT_TOKEN", required=True),),
        )

        with tempfile.TemporaryDirectory() as tmp:
            artifact_path = Path(tmp) / "artifact.txt"

            def factory(_submission: object) -> JobPlan:
                def produce(context: object) -> StageExecutionResult:
                    artifact_path.write_text(f"artifact body has {secret_value}", encoding="utf-8")
                    artifact = context.register_output(
                        artifact_id,
                        artifact_path,
                        metadata={"collection_name": "default", "note": f"metadata {secret_value}"},
                        provenance=Provenance(
                            tool_id="artifact-secret-fixture",
                            stage_id="produce",
                            source_url=f"https://source.example/data?token={secret_value}",
                            license_url=f"https://license.example/terms?token={secret_value}",
                            source_policy_notes=f"provenance {secret_value}",
                        ),
                        artifact_uri=f"https://objects.example/artifact?token={secret_value}",
                    )
                    return StageExecutionResult(output_artifact_ids=(artifact.artifact_id,))

                return JobPlan(
                    job_id="artifact-secret-job",
                    tool_id="artifact-secret-fixture",
                    stages=(
                        StagePlan(
                            stage_id="produce",
                            handler=produce,
                            output_artifacts=(ArtifactContract(artifact_id, "report.markdown", "v1"),),
                        ),
                    ),
                )

            ledger = SQLiteArtifactLedger(Path(tmp) / "ledger.sqlite", artifact_root=Path(tmp) / "artifacts")
            plane = FoundationControlPlane(
                tool_registry=ToolRegistry([manifest]),
                ledger=ledger,
                config={"ARTIFACT_TOKEN": secret_value},
                job_plan_factories={"artifact-secret-fixture": factory},
            )
            plane.create_job({"tool_id": "artifact-secret-fixture", "job_id": "artifact-secret-job"})
            list_response = plane.list_job_artifacts("artifact-secret-job")
            artifact_response = plane.get_artifact(artifact_id, include_content=True)
            search_response = plane.search({"query": "artifact", "collection_name": "default", "limit": 5})
            stored_artifact = ledger.get_artifact(artifact_id).to_dict()
            restarted = FoundationControlPlane(
                tool_registry=ToolRegistry([manifest]),
                ledger=SQLiteArtifactLedger(Path(tmp) / "ledger.sqlite", artifact_root=Path(tmp) / "artifacts"),
                config={},
            )
            restarted_artifact_response = restarted.get_artifact(artifact_id, include_content=True)
            restarted_search_response = restarted.search(
                {"query": "secret-artifact", "collection_name": "default", "limit": 5}
            )

        serialized = json.dumps(
            {
                "list_response": list_response,
                "artifact_response": artifact_response,
                "search_response": search_response,
                "stored_artifact": stored_artifact,
                "restarted_artifact_response": restarted_artifact_response,
                "restarted_search_response": restarted_search_response,
            },
            sort_keys=True,
        )
        self.assertNotIn(secret_value, serialized)
        self.assertIn(REDACTED, serialized)

    def test_custom_search_handlers_apply_known_job_scoped_redaction(self) -> None:
        secret_value = "custom-search-plan-secret"
        manifest = ToolManifest(
            tool_id="custom-search-fixture",
            tool_version="0.1.0",
            capabilities=("fixture.run",),
            input_artifact_types=("source.url",),
            output_artifact_types=("report.markdown",),
            entrypoints={"python": "fixture:register"},
            secret_declarations=(SecretDeclaration(name="PLAN_TOKEN", required=True),),
        )

        def factory(submission: object) -> JobPlan:
            return JobPlan(
                job_id="custom-search-job",
                tool_id="custom-search-fixture",
                config=submission.config,
                stages=(StagePlan(stage_id="noop", handler=lambda _context: StageExecutionResult()),),
            )

        def search_handler(_payload: object) -> dict[str, object]:
            return {"hits": [{"chunk_id": "custom", "text": f"leak {secret_value}"}]}

        with tempfile.TemporaryDirectory() as tmp:
            plane = FoundationControlPlane(
                tool_registry=ToolRegistry([manifest]),
                ledger=SQLiteArtifactLedger(Path(tmp) / "ledger.sqlite", artifact_root=Path(tmp) / "artifacts"),
                job_plan_factories={"custom-search-fixture": factory},
                search_handlers={"custom": search_handler},
            )
            plane.create_job(
                {
                    "tool_id": "custom-search-fixture",
                    "job_id": "custom-search-job",
                    "config": {"PLAN_TOKEN": secret_value},
                }
            )
            response = plane.search({"query": "leak", "collection_name": "custom", "limit": 1})

        serialized = json.dumps(response, sort_keys=True)
        self.assertNotIn(secret_value, serialized)
        self.assertIn(REDACTED, serialized)

    def test_cancel_reason_is_redacted_before_response_and_event_persistence(self) -> None:
        secret_value = "cancel-secret-token"
        with tempfile.TemporaryDirectory() as tmp:
            ledger = SQLiteArtifactLedger(Path(tmp) / "ledger.sqlite", artifact_root=Path(tmp) / "artifacts")
            plane = FoundationControlPlane(
                tool_registry=ToolRegistry([]),
                ledger=ledger,
                config={"CANCEL_TOKEN": secret_value},
            )
            ledger.upsert_job(
                Job(
                    job_id="cancel-job",
                    tool_id="cancel-tool",
                    state=LifecycleState.RUNNING,
                    created_at="2026-06-30T00:00:00Z",
                    metadata={"secret_policy": {"secret_names": ["CANCEL_TOKEN"]}},
                )
            )
            plane._job_ids_by_creation.append("cancel-job")
            plane._job_secret_names_by_job_id["cancel-job"] = ("CANCEL_TOKEN",)
            plane._job_secret_values_by_job_id["cancel-job"] = (secret_value,)
            plane.runner.set_redaction_policy(
                "cancel-job",
                secret_names=("CANCEL_TOKEN",),
                secret_values=(secret_value,),
            )
            response = plane.cancel_job("cancel-job", reason=f"stop {secret_value}")
            events = [event.__dict__ for event in ledger.list_events()]

        serialized = json.dumps({"response": response, "events": events}, sort_keys=True)
        self.assertNotIn(secret_value, serialized)
        self.assertIn(REDACTED, serialized)


class ObservabilityContractTests(unittest.TestCase):
    def test_observability_event_round_trips_trace_and_eval_hooks(self) -> None:
        event = ObservabilityEvent(
            event_type="stage.completed",
            entity_type="stage_run",
            entity_id="job-1:stage-1",
            created_at="2026-06-30T00:00:00Z",
            severity="info",
            reason="completed",
            trace=TraceContext(trace_id="trace-1", span_id="span-1", parent_span_id="root"),
            evaluation_hooks=(
                EvaluationHook(
                    evaluator_id="fixture-evaluator",
                    metric_names=("latency_ms", "quality_score"),
                    artifact_ids=("fixture:report",),
                ),
            ),
            payload={"latency_ms": 12, "quality_score": 0.9},
        )

        loaded = ObservabilityEvent.from_json(event.to_json())

        self.assertEqual(loaded, event)
        self.assertEqual(loaded.to_dict()["contract_type"], ObservabilityEvent.contract_type)
        self.assertEqual(loaded.to_dict()["schema_version"], CONTRACT_SCHEMA_VERSION)
        self.assertEqual(loaded.to_dict()["trace"]["trace_id"], "trace-1")
        self.assertEqual(loaded.to_dict()["evaluation_hooks"][0]["metric_names"], ["latency_ms", "quality_score"])

    def test_observability_event_can_normalize_ledger_events(self) -> None:
        ledger_event = SimpleNamespace(
            event_id=7,
            created_at="2026-06-30T00:00:00Z",
            entity_type="job",
            entity_id="job-1",
            event_type="job.failed",
            reason="failed safely",
            payload={"trace_id": "trace-1", "span_id": "job-span", "attempt": 1},
        )

        event = ObservabilityEvent.from_ledger_event(ledger_event)

        self.assertEqual(event.event_id, 7)
        self.assertEqual(event.trace.trace_id, "trace-1")
        self.assertEqual(event.trace.span_id, "job-span")
        self.assertEqual(event.payload["attempt"], 1)


if __name__ == "__main__":
    unittest.main()
