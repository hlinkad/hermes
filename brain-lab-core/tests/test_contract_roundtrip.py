from __future__ import annotations

import json
import unittest

from brain_lab_core.contracts import (
    ArtifactId,
    ArtifactRef,
    Checksum,
    Citation,
    ContractValidationError,
    ErrorEnvelope,
    EvidenceRef,
    FreshnessState,
    Job,
    LifecycleState,
    Provenance,
    ProviderCapability,
    ProviderSpec,
    ResourceProfile,
    RetryMetadata,
    SchemaExtensionPoint,
    SourceSpan,
    StageRun,
    ToolManifest,
)


class ContractRoundTripTests(unittest.TestCase):
    def test_artifact_ref_round_trips_without_losing_schema_or_provenance(self) -> None:
        provenance = Provenance(
            tool_id="video-intel",
            stage_id="transcribe",
            provider_id="faster-whisper",
            provider_version="1.0.0",
            source_refs=("source.url:https://example.test/video",),
            created_at="2026-06-29T12:00:00Z",
        )
        artifact = ArtifactRef(
            artifact_id=ArtifactId("transcript-001", namespace="video-intel"),
            artifact_type="video.transcript",
            artifact_schema_version="video.transcript.v1",
            uri="artifacts/video/transcript-001.json",
            checksum=Checksum(algorithm="sha256", value="a" * 64),
            size_bytes=512,
            producer_tool_id="video-intel",
            producer_stage_id="transcribe",
            created_at="2026-06-29T12:01:00Z",
            input_artifact_ids=(ArtifactId("source-001", namespace="video-intel"),),
            config_fingerprint="sha256:" + "b" * 64,
            freshness=FreshnessState.CURRENT,
            provenance=provenance,
            metadata={"language": "en", "duration_seconds": 42},
        )

        loaded = ArtifactRef.from_json(artifact.to_json())

        self.assertEqual(loaded, artifact)
        self.assertEqual(loaded.to_dict()["contract_type"], "brain_lab.artifact_ref")
        self.assertEqual(loaded.to_dict()["schema_version"], "brain_lab.contracts.v1")
        self.assertEqual(loaded.provenance.provider_id, "faster-whisper")
        self.assertEqual(loaded.freshness, FreshnessState.CURRENT)
        json.dumps(loaded.to_dict(), sort_keys=True)

    def test_evidence_ref_round_trips_with_citation_span_and_confidence(self) -> None:
        source_artifact = ArtifactId("transcript-001", namespace="video-intel")
        evidence = EvidenceRef(
            evidence_id="evidence-001",
            source_artifact_id=source_artifact,
            source_type="video.transcript",
            span=SourceSpan(kind="time", start=12.5, end=18.0, unit="seconds"),
            quote="The exact quoted evidence text.",
            confidence=0.87,
            provenance=Provenance(tool_id="video-intel", stage_id="chunk", created_at="2026-06-29T12:05:00Z"),
            citations=(
                Citation(
                    citation_id="cite-001",
                    label="00:12.5-00:18.0",
                    artifact_id=source_artifact,
                    span=SourceSpan(kind="time", start=12.5, end=18.0, unit="seconds"),
                    quote="The exact quoted evidence text.",
                    confidence=0.87,
                ),
            ),
        )

        loaded = EvidenceRef.from_json(evidence.to_json())

        self.assertEqual(loaded, evidence)
        self.assertEqual(loaded.to_dict()["contract_type"], "brain_lab.evidence_ref")
        self.assertEqual(loaded.citations[0].artifact_id, source_artifact)
        self.assertEqual(loaded.span.kind, "time")

    def test_job_stage_lifecycle_round_trips(self) -> None:
        job = Job(
            job_id="job-001",
            tool_id="video-intel",
            state=LifecycleState.RUNNING,
            created_at="2026-06-29T12:00:00Z",
            stages=(
                StageRun(
                    stage_id="ingest",
                    state=LifecycleState.COMPLETED,
                    started_at="2026-06-29T12:00:01Z",
                    completed_at="2026-06-29T12:00:05Z",
                    output_artifact_ids=(ArtifactId("media-001", namespace="video-intel"),),
                    retry=RetryMetadata(attempt=1, max_attempts=3, retryable=True),
                ),
                StageRun(
                    stage_id="transcribe",
                    state=LifecycleState.RUNNING,
                    started_at="2026-06-29T12:00:06Z",
                    input_artifact_ids=(ArtifactId("media-001", namespace="video-intel"),),
                    retry=RetryMetadata(attempt=2, max_attempts=3, retryable=True, last_error_code="provider_timeout"),
                ),
            ),
            metadata={"resume_from_stage": "transcribe"},
        )

        loaded = Job.from_json(job.to_json())

        self.assertEqual(loaded, job)
        self.assertEqual(loaded.stages[0].state, LifecycleState.COMPLETED)
        self.assertEqual(loaded.stages[1].retry.last_error_code, "provider_timeout")

    def test_fake_tool_manifest_and_provider_spec_are_valid(self) -> None:
        manifest = ToolManifest(
            tool_id="fixture-tool",
            tool_version="0.1.0",
            capabilities=("fixture.ingest", "fixture.summarize"),
            input_artifact_types=("source.url",),
            output_artifact_types=("retrieval.chunks", "report.markdown"),
            entrypoints={"python": "fixture_tool.integration:register", "cli": "fixture-tool"},
            resource_profile=ResourceProfile(cpu_cores=1.0, memory_mb=512, disk_mb=128, timeout_seconds=60),
            license_notes="MIT fixture only",
            required_secret_names=("FIXTURE_API_KEY",),
        )
        provider = ProviderSpec(
            provider_id="qdrant-local",
            provider_type="vector_store",
            adapter_module="brain_lab_core.retrieval.qdrant_index",
            capabilities=(
                ProviderCapability(
                    name="retrieval.index",
                    version="v1",
                    input_artifact_types=("retrieval.chunks",),
                    output_artifact_types=("retrieval.index",),
                ),
            ),
            metadata={"deployment": "local"},
        )

        self.assertEqual(ToolManifest.from_json(manifest.to_json()), manifest)
        self.assertEqual(ProviderSpec.from_json(provider.to_json()), provider)
        self.assertEqual(manifest.validate(), ())
        self.assertEqual(provider.validate(), ())

    def test_normalized_error_envelope_is_json_round_trippable(self) -> None:
        error = ErrorEnvelope(
            code="provider_timeout",
            message="Provider did not finish before timeout.",
            category="provider",
            severity="error",
            retryable=True,
            retry_after_seconds=30,
            provenance=Provenance(tool_id="fixture-tool", stage_id="summarize"),
            context={"provider_id": "fixture-provider", "attempt": 2},
        )

        loaded = ErrorEnvelope.from_json(error.to_json())

        self.assertEqual(loaded, error)
        self.assertTrue(loaded.retryable)
        self.assertEqual(loaded.to_dict()["contract_type"], "brain_lab.error_envelope")

    def test_schema_extension_point_keeps_domain_schemas_out_of_core_contracts(self) -> None:
        extension = SchemaExtensionPoint(
            namespace="video",
            owner_tool_id="video-intel",
            artifact_types=("video.timeline", "video.frame_manifest"),
            evidence_types=("video.timestamp_quote",),
            field_prefixes=("video.",),
            metadata_schema_uris=("urn:brain-lab:video-intel:metadata:v1",),
            compatibility_notes="Foundation stores and validates the declaration; video-intel owns the schema.",
        )

        loaded = SchemaExtensionPoint.from_json(extension.to_json())

        self.assertEqual(loaded, extension)
        self.assertEqual(loaded.to_dict()["contract_type"], "brain_lab.schema_extension_point")
        self.assertEqual(loaded.field_prefixes, ("video.",))

    def test_invalid_contract_examples_raise_clear_validation_errors(self) -> None:
        with self.assertRaisesRegex(ContractValidationError, "artifact_id.value"):
            ArtifactId("")
        with self.assertRaisesRegex(ContractValidationError, "checksum.value"):
            Checksum(algorithm="sha256", value="")
        with self.assertRaisesRegex(ContractValidationError, "tool_manifest.capabilities"):
            ToolManifest(
                tool_id="fixture-tool",
                tool_version="0.1.0",
                capabilities=(),
                input_artifact_types=("source.url",),
                output_artifact_types=("report.markdown",),
                entrypoints={"python": "fixture_tool.integration:register"},
            )
        with self.assertRaisesRegex(ContractValidationError, "stage_run.state"):
            StageRun(stage_id="bad", state="done")  # type: ignore[arg-type]
        with self.assertRaisesRegex(ContractValidationError, "provider_spec.capabilities"):
            ProviderSpec(provider_id="empty", provider_type="llm", capabilities=())


if __name__ == "__main__":
    unittest.main()
