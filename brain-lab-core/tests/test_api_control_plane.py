from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from brain_lab_core.api import (
    FoundationControlPlane,
    FoundationMCPTools,
    JobSubmission,
    create_fastapi_app,
    create_fixture_control_plane,
    foundation_openapi_schema,
    redact_secrets,
)
from brain_lab_core.contracts import ContractValidationError, FreshnessState, LifecycleState
from brain_lab_core.orchestration import JobPlan, StageExecutionResult, StagePlan
from brain_lab_core.registry import fixture_registries
from brain_lab_core.state import SQLiteArtifactLedger


class ApiControlPlaneTests(unittest.TestCase):
    def test_openapi_schema_exposes_tool_neutral_routes_and_secret_safe_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plane = create_fixture_control_plane(
                state_root=Path(tmp),
                config={
                    "public_base_url": "http://127.0.0.1:8765",
                    "OPENAI_API_KEY": "sk-real-value",
                    "nested": {"password": "super-secret", "safe": "visible"},
                },
            )

            schema = foundation_openapi_schema(plane)
            config = plane.config_status()

        self.assertEqual(schema["openapi"], "3.1.0")
        self.assertEqual(
            set(schema["paths"]),
            {
                "/tools",
                "/jobs",
                "/jobs/{job_id}",
                "/jobs/{job_id}/resume",
                "/jobs/{job_id}/cancel",
                "/jobs/{job_id}/artifacts",
                "/artifacts/{artifact_id}",
                "/search",
                "/answers",
                "/healthz",
                "/config",
            },
        )
        self.assertEqual(config["config"]["public_base_url"], "http://127.0.0.1:8765")
        self.assertEqual(schema["paths"]["/jobs"]["post"]["requestBody"]["content"]["application/json"]["schema"]["$ref"], "#/components/schemas/JobCreateRequest")
        self.assertEqual(schema["paths"]["/jobs/{job_id}"]["get"]["parameters"][0]["name"], "job_id")
        self.assertEqual(config["config"]["OPENAI_API_KEY"], "[REDACTED]")
        self.assertEqual(config["config"]["nested"]["password"], "[REDACTED]")
        self.assertEqual(config["config"]["nested"]["safe"], "visible")
        self.assertEqual(config["secret_policy"]["redacted"], True)
        self.assertIn("OPENAI_API_KEY", config["secret_policy"]["secret_names"])
        json.dumps(schema, sort_keys=True)
        json.dumps(config, sort_keys=True)

    def test_mcp_tools_create_poll_resume_cancel_and_read_fixture_job_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plane = create_fixture_control_plane(state_root=Path(tmp), config={"fixture_token": "secret-token"})
            mcp = FoundationMCPTools(plane)

            tools = mcp.list_tools()
            created = mcp.create_job(
                {
                    "tool_id": "fixture-tool",
                    "job_id": "fixture-job",
                    "config": {"revision": 1, "api_key": "sk-should-not-leak"},
                    "inputs": {"prompt": "foundation control plane smoke"},
                }
            )
            polled = mcp.get_job("fixture-job")
            artifacts = mcp.list_job_artifacts("fixture-job")
            artifact_id = artifacts["artifacts"][0]["artifact_id"]["value"]
            artifact = mcp.get_artifact(f"fixture:{artifact_id}")
            resume = mcp.resume_job("fixture-job")
            cancel = mcp.cancel_job("fixture-job", reason="operator test")
            health = mcp.healthz()
            config = mcp.config()

        self.assertEqual(tools["tools"][0]["tool_id"], "fixture-tool")
        self.assertIn("fixture_token", tools["tools"][0]["required_secret_names"])
        self.assertEqual(created["job"]["state"], LifecycleState.COMPLETED.value)
        self.assertEqual(polled["job"]["state"], LifecycleState.COMPLETED.value)
        self.assertEqual(resume["job"]["state"], LifecycleState.COMPLETED.value)
        self.assertEqual(cancel["cancel_requested"], False)
        self.assertEqual(health["status"], "ok")
        self.assertEqual(config["config"]["fixture_token"], "[REDACTED]")
        self.assertEqual(len(artifacts["artifacts"]), 1)
        self.assertEqual(artifact["artifact"]["producer_tool_id"], "fixture-tool")
        self.assertEqual(artifact["artifact"]["producer_stage_id"], "write-fixture-report")
        self.assertEqual(artifact["artifact"]["freshness"], FreshnessState.CURRENT.value)
        event_types = [event["event_type"] for event in polled["events"]]
        self.assertIn("job.completed", event_types)
        self.assertIn("stage.output_registered", event_types)
        serialized = json.dumps(
            {
                "created": created,
                "polled": polled,
                "artifacts": artifacts,
                "artifact": artifact,
                "resume": resume,
                "cancel": cancel,
                "health": health,
                "config": config,
            },
            sort_keys=True,
        )
        self.assertNotIn("sk-should-not-leak", serialized)
        self.assertNotIn("secret-token", serialized)

    def test_search_and_answers_are_tool_neutral_and_do_not_expose_unconfigured_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plane = create_fixture_control_plane(state_root=Path(tmp), config={"ANTHROPIC_API_KEY": "secret"})
            mcp = FoundationMCPTools(plane)

            mcp.create_job({"tool_id": "fixture-tool", "job_id": "fixture-search-job"})
            search = mcp.search({"query": "fixture", "collection_name": "fixture.reports", "limit": 5})
            answer = mcp.answer({"question": "What did the fixture job produce?", "collection_name": "fixture.reports"})

        self.assertEqual(search["query"], "fixture")
        self.assertEqual(search["collection_name"], "fixture.reports")
        self.assertEqual(search["hits"][0]["artifact_ref"]["producer_tool_id"], "fixture-tool")
        self.assertEqual(answer["answer_state"], "unconfigured")
        self.assertEqual(answer["citations"][0]["artifact_id"], "fixture:fixture-search-job-report")
        self.assertNotIn("secret", json.dumps({"search": search, "answer": answer}, sort_keys=True))

    def test_search_is_collection_scoped_and_restart_ledger_backed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_plane = create_fixture_control_plane(state_root=root)
            first_plane.create_job({"tool_id": "fixture-tool", "job_id": "durable-search-job"})

            reopened_plane = create_fixture_control_plane(state_root=root)
            search = reopened_plane.search(
                {"query": "fixture job", "collection_name": "fixture.reports", "limit": 5}
            )
            wrong_collection = reopened_plane.search(
                {"query": "fixture job", "collection_name": "other.collection", "limit": 5}
            )

        self.assertEqual(search["hits"][0]["payload"]["artifact_id"], "fixture:durable-search-job-report")
        self.assertEqual(wrong_collection["hits"], [])

    def test_control_plane_rejects_unsafe_or_duplicate_job_requests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plane = create_fixture_control_plane(state_root=Path(tmp))
            plane.create_job({"tool_id": "fixture-tool", "job_id": "unique-job"})

            with self.assertRaisesRegex(ContractValidationError, "already exists"):
                plane.create_job({"tool_id": "fixture-tool", "job_id": "unique-job"})
            with self.assertRaisesRegex(ContractValidationError, "job_id"):
                plane.create_job({"tool_id": "fixture-tool", "job_id": "../escape"})
            with self.assertRaisesRegex(ContractValidationError, "inputs.artifact_id"):
                plane.create_job(
                    {
                        "tool_id": "fixture-tool",
                        "job_id": "unsafe-artifact-job",
                        "inputs": {"artifact_id": "../escape"},
                    }
                )
            with self.assertRaisesRegex(ContractValidationError, "search query"):
                plane.search({"query": "", "collection_name": "fixture.reports"})
            with self.assertRaisesRegex(ContractValidationError, "job inputs"):
                plane.create_job({"tool_id": "fixture-tool", "job_id": "bad-inputs", "inputs": []})
            with self.assertRaises(KeyError):
                plane.cancel_job("missing-job")

    def test_control_plane_rejects_plan_factories_that_change_request_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool_registry, adapter_registry = fixture_registries()
            ledger = SQLiteArtifactLedger(Path(tmp) / "ledger.sqlite", artifact_root=Path(tmp))

            def bad_factory(submission: JobSubmission) -> JobPlan:
                return JobPlan(
                    job_id=f"{submission.job_id}-other",
                    tool_id=submission.tool_id,
                    stages=(StagePlan(stage_id="noop", handler=lambda _context: StageExecutionResult()),),
                )

            plane = FoundationControlPlane(
                tool_registry=tool_registry,
                adapter_registry=adapter_registry,
                ledger=ledger,
                job_plan_factories={"fixture-tool": bad_factory},
            )

            with self.assertRaisesRegex(ContractValidationError, "job_id"):
                plane.create_job({"tool_id": "fixture-tool", "job_id": "requested-job"})

    def test_redaction_recurses_through_mappings_sequences_and_named_secrets(self) -> None:
        payload = {
            "token": "abc",
            "safe_key": "visible",
            "nested": [{"CUSTOM_SECRET": "value", "note": "ok"}],
        }

        redacted = redact_secrets(
            payload,
            secret_names=("CUSTOM_SECRET",),
            secret_values=("value", "secret-token"),
        )

        self.assertEqual(redacted["token"], "[REDACTED]")
        self.assertEqual(redacted["safe_key"], "visible")
        self.assertEqual(redacted["nested"][0]["CUSTOM_SECRET"], "[REDACTED]")
        self.assertEqual(redacted["nested"][0]["note"], "ok")
        self.assertEqual(
            redact_secrets({"reason": "prefix secret-token suffix"}, secret_values=("secret-token",))[
                "reason"
            ],
            "prefix [REDACTED] suffix",
        )

    def test_fastapi_adapter_is_lazy_and_uses_control_plane_schema_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plane = create_fixture_control_plane(state_root=Path(tmp))

            if importlib.util.find_spec("fastapi") is None:
                with self.assertRaisesRegex(RuntimeError, r"brain-lab-core\[api\]"):
                    create_fastapi_app(plane)
                return

            app = create_fastapi_app(plane)
            schema = app.openapi()

        self.assertEqual(schema["openapi"], "3.1.0")
        self.assertEqual(schema["paths"]["/jobs"]["post"]["operationId"], "createJob")


if __name__ == "__main__":
    unittest.main()
