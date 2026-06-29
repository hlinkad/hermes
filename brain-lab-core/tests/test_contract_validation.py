from __future__ import annotations

import importlib
import json
import unittest

from brain_lab_core.contracts import (
    CONTRACT_SCHEMA_VERSION,
    ArtifactId,
    ArtifactRef,
    Checksum,
    Citation,
    ContractValidationError,
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


class ContractValidationTests(unittest.TestCase):
    def test_json_loader_requires_matching_contract_header(self) -> None:
        with self.assertRaisesRegex(ContractValidationError, "contract_type"):
            ArtifactId.from_json(json.dumps({"schema_version": CONTRACT_SCHEMA_VERSION, "value": "artifact-001"}))
        with self.assertRaisesRegex(ContractValidationError, "contract_type"):
            ArtifactId.from_json(
                json.dumps(
                    {
                        "contract_type": "brain_lab.tool_manifest",
                        "schema_version": CONTRACT_SCHEMA_VERSION,
                        "value": "artifact-001",
                    }
                )
            )
        with self.assertRaisesRegex(ContractValidationError, "schema_version"):
            ArtifactId.from_json(json.dumps({"contract_type": ArtifactId.contract_type, "value": "artifact-001"}))
        with self.assertRaisesRegex(ContractValidationError, "schema_version"):
            ArtifactId.from_json(
                json.dumps(
                    {
                        "contract_type": ArtifactId.contract_type,
                        "schema_version": "brain_lab.contracts.v999",
                        "value": "artifact-001",
                    }
                )
            )

    def test_public_leaf_contracts_directly_round_trip_through_json(self) -> None:
        source_artifact = ArtifactId("source-001", namespace="fixture")
        instances = (
            source_artifact,
            Checksum("sha256", "a" * 64),
            Provenance(tool_id="fixture-tool", source_refs=("source:url",)),
            SourceSpan(kind="time", start=1.0, end=2.5, unit="seconds"),
            Citation("cite-001", "1.0-2.5s", source_artifact, SourceSpan(kind="time", start=1.0, end=2.5)),
            RetryMetadata(attempt=1, max_attempts=2, retryable=True),
            StageRun(stage_id="extract", state="completed", progress=1.0),
            ResourceProfile(cpu_cores=1.0, memory_mb=128, gpu_required=False),
            ProviderCapability(name="fixture.run", input_artifact_types=("source.url",)),
        )

        for instance in instances:
            with self.subTest(contract=type(instance).__name__):
                loaded = type(instance).from_json(instance.to_json())
                self.assertEqual(loaded, instance)
                payload = loaded.to_dict()
                self.assertEqual(payload["contract_type"], instance.contract_type)
                self.assertEqual(payload["schema_version"], CONTRACT_SCHEMA_VERSION)

    def test_artifact_ref_serialized_field_names_are_stable(self) -> None:
        artifact = ArtifactRef(
            artifact_id=ArtifactId("report-001", namespace="fixture"),
            artifact_type="report.markdown",
            artifact_schema_version="report.v1",
            uri="artifacts/report.md",
            checksum=Checksum("sha256", "a" * 64),
            provenance=Provenance(tool_id="fixture-tool"),
        )

        self.assertEqual(
            set(artifact.to_dict()),
            {
                "artifact_id",
                "artifact_schema_version",
                "artifact_type",
                "checksum",
                "config_fingerprint",
                "contract_type",
                "created_at",
                "freshness",
                "input_artifact_ids",
                "metadata",
                "producer_stage_id",
                "producer_tool_id",
                "provenance",
                "schema_version",
                "size_bytes",
                "uri",
            },
        )

    def test_metadata_sets_are_canonicalized_for_deterministic_json(self) -> None:
        provenance = Provenance(tool_id="fixture-tool", metadata={"tags": {"beta", "alpha"}})

        payload = json.loads(provenance.to_json())

        self.assertEqual(payload["metadata"]["tags"], ["alpha", "beta"])

    def test_metadata_rejects_non_json_values_instead_of_stringifying_them(self) -> None:
        with self.assertRaisesRegex(ContractValidationError, "finite"):
            Provenance(tool_id="fixture-tool", metadata={"score": float("nan")})
        with self.assertRaisesRegex(ContractValidationError, "unsupported JSON value type"):
            Provenance(tool_id="fixture-tool", metadata={"object": object()})

    def test_missing_nested_identifiers_do_not_silently_become_none_strings(self) -> None:
        with self.assertRaisesRegex(ContractValidationError, "artifact_id.value"):
            ArtifactRef.from_dict(
                {
                    "artifact_type": "report.markdown",
                    "artifact_schema_version": "report.v1",
                    "uri": "artifacts/report.md",
                    "checksum": Checksum("sha256", "a" * 64).to_dict(),
                }
            )

    def test_invalid_enums_and_unit_intervals_raise_validation_errors(self) -> None:
        with self.assertRaisesRegex(ContractValidationError, "artifact_ref.freshness"):
            ArtifactRef(
                artifact_id=ArtifactId("report-001"),
                artifact_type="report.markdown",
                artifact_schema_version="report.v1",
                uri="artifacts/report.md",
                checksum=Checksum("sha256", "a" * 64),
                freshness="fresh",  # type: ignore[arg-type]
            )
        with self.assertRaisesRegex(ContractValidationError, "artifact_ref.freshness"):
            ArtifactRef.from_dict(
                {
                    "artifact_id": ArtifactId("report-001").to_dict(),
                    "artifact_type": "report.markdown",
                    "artifact_schema_version": "report.v1",
                    "uri": "artifacts/report.md",
                    "checksum": Checksum("sha256", "a" * 64).to_dict(),
                    "freshness": "fresh",
                }
            )
        with self.assertRaisesRegex(ContractValidationError, "stage_run.progress"):
            StageRun(stage_id="summarize", state="running", progress=1.5)  # type: ignore[arg-type]
        with self.assertRaisesRegex(ContractValidationError, "retry.attempt"):
            RetryMetadata(attempt=3, max_attempts=2)

    def test_source_span_kind_and_boundaries_are_validated(self) -> None:
        with self.assertRaisesRegex(ContractValidationError, "source_span.kind"):
            SourceSpan(kind="line")
        with self.assertRaisesRegex(ContractValidationError, "source_span.start"):
            SourceSpan(kind="time", start=float("nan"))
        with self.assertRaisesRegex(ContractValidationError, "source_span.end"):
            SourceSpan(kind="time", start=10.0, end=1.0)

    def test_resource_numbers_and_booleans_are_strictly_validated(self) -> None:
        with self.assertRaisesRegex(ContractValidationError, "resource_profile.cpu_cores"):
            ResourceProfile(cpu_cores=float("nan"))
        with self.assertRaisesRegex(ContractValidationError, "resource_profile.cpu_cores"):
            ResourceProfile(cpu_cores="1.0")  # type: ignore[arg-type]
        with self.assertRaisesRegex(ContractValidationError, "resource_profile.memory_mb"):
            ResourceProfile(memory_mb=1.5)  # type: ignore[arg-type]
        with self.assertRaisesRegex(ContractValidationError, "resource_profile.memory_mb"):
            ResourceProfile(memory_mb="128")  # type: ignore[arg-type]
        with self.assertRaisesRegex(ContractValidationError, "resource_profile.gpu_required"):
            ResourceProfile(gpu_required="false")  # type: ignore[arg-type]
        with self.assertRaisesRegex(ContractValidationError, "retry.retryable"):
            RetryMetadata(retryable="false")  # type: ignore[arg-type]

    def test_tuple_contract_fields_require_strings(self) -> None:
        with self.assertRaisesRegex(ContractValidationError, "tuple values"):
            ToolManifest(
                tool_id="fixture-tool",
                tool_version="0.1.0",
                capabilities=(1,),  # type: ignore[arg-type]
                input_artifact_types=("source.url",),
                output_artifact_types=("report.markdown",),
                entrypoints={"run": "fixture:run"},
            )

    def test_manifest_provider_and_extension_declarations_require_minimum_shape(self) -> None:
        with self.assertRaisesRegex(ContractValidationError, "tool_manifest.entrypoints"):
            ToolManifest(
                tool_id="fixture-tool",
                tool_version="0.1.0",
                capabilities=("fixture.run",),
                input_artifact_types=("source.url",),
                output_artifact_types=("report.markdown",),
                entrypoints={},
            )
        with self.assertRaisesRegex(ContractValidationError, "provider_spec.capabilities"):
            ProviderSpec(provider_id="provider", provider_type="llm", capabilities=())
        with self.assertRaisesRegex(ContractValidationError, "schema_extension.extension_declarations"):
            SchemaExtensionPoint(namespace="fixture", owner_tool_id="fixture-tool")

    def test_extension_point_namespaces_are_importable(self) -> None:
        for module_name in (
            "brain_lab_core",
            "brain_lab_core.state",
            "brain_lab_core.registry",
            "brain_lab_core.orchestration",
            "brain_lab_core.retrieval",
            "brain_lab_core.api",
            "brain_lab_core.security",
            "brain_lab_core.observability",
        ):
            with self.subTest(module=module_name):
                importlib.import_module(module_name)


if __name__ == "__main__":
    unittest.main()
