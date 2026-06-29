from __future__ import annotations

import json
import sys
import unittest

from brain_lab_core.contracts import (
    ContractValidationError,
    ProviderCapability,
    ProviderSpec,
    ToolManifest,
)
from brain_lab_core.registry import (
    AdapterRegistry,
    RegistryConflictError,
    RegistryLookupError,
    ToolRegistry,
    fixture_provider_spec,
    fixture_tool_manifest,
    register_fixture_tool,
)


class ToolRegistryTests(unittest.TestCase):
    def test_registers_fake_tool_manifest_and_exposes_api_safe_discovery(self) -> None:
        manifest = fixture_tool_manifest(
            entrypoints={
                "python": "missing_fixture_package.integration:register",
                "cli": "fixture-tool",
                "container_image": "localhost/fixture-tool:0.1.0",
            }
        )
        registry = ToolRegistry()

        registered = registry.register(manifest)
        discovery = registry.discovery_document()

        self.assertEqual(registered, manifest)
        self.assertEqual(registry.get("fixture-tool"), manifest)
        self.assertEqual(registry.tools_for_capability("fixture.summarize"), (manifest,))
        self.assertEqual(registry.tools_producing_artifact_type("report.markdown"), (manifest,))
        self.assertEqual(registry.tools_accepting_artifact_type("source.url"), (manifest,))
        self.assertNotIn("missing_fixture_package", sys.modules)
        json.dumps(discovery, sort_keys=True)
        self.assertEqual(discovery["contract_type"], "brain_lab.tool_registry.discovery")
        self.assertEqual(discovery["tools"][0]["tool_id"], "fixture-tool")
        self.assertEqual(
            discovery["capabilities"],
            [
                {
                    "capability": "fixture.ingest",
                    "entrypoints": {
                        "cli": "fixture-tool",
                        "container_image": "localhost/fixture-tool:0.1.0",
                        "python": "missing_fixture_package.integration:register",
                    },
                    "input_artifact_types": ["source.url"],
                    "output_artifact_types": ["fixture.records", "report.markdown"],
                    "required_secret_names": [],
                    "tool_id": "fixture-tool",
                    "tool_version": "0.1.0",
                },
                {
                    "capability": "fixture.summarize",
                    "entrypoints": {
                        "cli": "fixture-tool",
                        "container_image": "localhost/fixture-tool:0.1.0",
                        "python": "missing_fixture_package.integration:register",
                    },
                    "input_artifact_types": ["source.url"],
                    "output_artifact_types": ["fixture.records", "report.markdown"],
                    "required_secret_names": [],
                    "tool_id": "fixture-tool",
                    "tool_version": "0.1.0",
                },
            ],
        )

    def test_registry_registration_is_idempotent_but_conflicting_ids_fail(self) -> None:
        registry = ToolRegistry()
        manifest = fixture_tool_manifest()

        self.assertEqual(registry.register(manifest), manifest)
        self.assertEqual(registry.register(manifest), manifest)
        with self.assertRaisesRegex(RegistryConflictError, "fixture-tool"):
            registry.register(
                fixture_tool_manifest(
                    tool_version="0.2.0",
                    capabilities=("fixture.ingest", "fixture.enrich"),
                )
            )

    def test_registry_snapshots_manifests_and_returns_fresh_copies(self) -> None:
        manifest = fixture_tool_manifest(metadata={"nested": {"values": [1]}})
        registry = ToolRegistry([manifest])

        manifest.entrypoints["pythno"] = "fixture_tool.integration:register"
        manifest.metadata["nested"]["values"].append(object())
        returned = registry.get("fixture-tool")
        returned.entrypoints["pythno"] = "fixture_tool.integration:register"
        returned.metadata["nested"]["values"].append(object())
        discovery = registry.discovery_document()

        self.assertNotIn("pythno", discovery["tools"][0]["entrypoints"])
        self.assertEqual(discovery["tools"][0]["metadata"], {"nested": {"values": [1]}})
        json.dumps(discovery, sort_keys=True)

    def test_package_only_entrypoint_is_supported_for_package_registrations(self) -> None:
        registry = ToolRegistry()
        manifest = fixture_tool_manifest(
            tool_id="package-tool",
            entrypoints={"package": "fixture_tool.integration:register"},
        )

        self.assertEqual(manifest.validate(), ())
        self.assertEqual(registry.register(manifest), manifest)
        self.assertEqual(registry.tools_for_capability("fixture.ingest"), (manifest,))

    def test_mixed_supported_and_unsupported_entrypoints_fail(self) -> None:
        registry = ToolRegistry()
        manifest = fixture_tool_manifest(
            entrypoints={
                "python": "fixture_tool.integration:register",
                "pythno": "fixture_tool.integration:register",
            }
        )

        diagnostics = manifest.validate()
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(diagnostics[0].code, "tool_manifest.entrypoints.unsupported")
        self.assertIn("pythno", diagnostics[0].message)
        with self.assertRaisesRegex(ContractValidationError, "pythno"):
            registry.register(manifest)

    def test_invalid_manifests_fail_with_actionable_entrypoint_errors(self) -> None:
        registry = ToolRegistry()
        manifest = ToolManifest(
            tool_id="bad-tool",
            tool_version="0.1.0",
            capabilities=("fixture.ingest",),
            input_artifact_types=("source.url",),
            output_artifact_types=("report.markdown",),
            entrypoints={"not_supported": "bad_tool:register"},
        )

        diagnostics = manifest.validate()
        self.assertEqual(diagnostics[0].severity, "error")
        self.assertIn("python", diagnostics[0].message)
        with self.assertRaisesRegex(ContractValidationError, "entrypoints.*python.*cli.*container_image"):
            registry.register(manifest)

    def test_missing_tool_lookup_is_explicit(self) -> None:
        registry = ToolRegistry()

        with self.assertRaisesRegex(RegistryLookupError, "missing-tool"):
            registry.get("missing-tool")
        self.assertEqual(registry.tools_for_capability("missing.capability"), ())


class AdapterRegistryTests(unittest.TestCase):
    def test_registers_provider_specs_and_supports_capability_lookup(self) -> None:
        spec = fixture_provider_spec()
        registry = AdapterRegistry()

        registered = registry.register(spec)
        discovery = registry.discovery_document()

        self.assertEqual(registered, spec)
        self.assertEqual(registry.get("fixture-provider"), spec)
        self.assertEqual(registry.providers_for_capability("fixture.embed"), (spec,))
        self.assertEqual(registry.providers_for_capability("fixture.embed", version="v1"), (spec,))
        self.assertEqual(registry.providers_for_capability("fixture.embed", version="v2"), ())
        self.assertEqual(registry.providers_producing_artifact_type("retrieval.embedding"), (spec,))
        self.assertEqual(registry.providers_accepting_artifact_type("retrieval.chunks"), (spec,))
        json.dumps(discovery, sort_keys=True)
        self.assertEqual(discovery["contract_type"], "brain_lab.adapter_registry.discovery")
        self.assertEqual(discovery["providers"][0]["provider_id"], "fixture-provider")
        self.assertEqual(
            discovery["capabilities"],
            [
                {
                    "adapter_module": "fixture_provider.adapters:FixtureAdapter",
                    "capability": "fixture.embed",
                    "capability_version": "v1",
                    "input_artifact_types": ["retrieval.chunks"],
                    "output_artifact_types": ["retrieval.embedding"],
                    "provider_id": "fixture-provider",
                    "provider_type": "embedding",
                    "provider_version": "0.1.0",
                    "required_secret_names": [],
                },
                {
                    "adapter_module": "fixture_provider.adapters:FixtureAdapter",
                    "capability": "fixture.rank",
                    "capability_version": "v1",
                    "input_artifact_types": ["retrieval.embedding"],
                    "output_artifact_types": ["retrieval.ranking"],
                    "provider_id": "fixture-provider",
                    "provider_type": "embedding",
                    "provider_version": "0.1.0",
                    "required_secret_names": [],
                },
            ],
        )

    def test_duplicate_provider_id_with_different_spec_fails(self) -> None:
        registry = AdapterRegistry()
        spec = fixture_provider_spec()

        self.assertEqual(registry.register(spec), spec)
        self.assertEqual(registry.register(spec), spec)
        with self.assertRaisesRegex(RegistryConflictError, "fixture-provider"):
            registry.register(
                ProviderSpec(
                    provider_id="fixture-provider",
                    provider_type="embedding",
                    provider_version="0.2.0",
                    capabilities=(ProviderCapability(name="fixture.embed", version="v2"),),
                )
            )

    def test_adapter_registry_snapshots_provider_specs_and_returns_fresh_copies(self) -> None:
        spec = fixture_provider_spec(metadata={"nested": {"values": [1]}})
        registry = AdapterRegistry([spec])

        spec.metadata["bad"] = object()
        returned = registry.get("fixture-provider")
        returned.metadata["bad"] = object()
        discovery = registry.discovery_document()

        self.assertEqual(discovery["providers"][0]["metadata"], {"nested": {"values": [1]}})
        json.dumps(discovery, sort_keys=True)

    def test_provider_specs_with_duplicate_capabilities_fail_usefully(self) -> None:
        registry = AdapterRegistry()
        spec = ProviderSpec(
            provider_id="bad-provider",
            provider_type="embedding",
            capabilities=(
                ProviderCapability(name="fixture.embed", version="v1"),
                ProviderCapability(name="fixture.embed", version="v1"),
            ),
        )

        diagnostics = spec.validate()
        self.assertEqual(diagnostics[0].severity, "error")
        self.assertIn("duplicate", diagnostics[0].message)
        with self.assertRaisesRegex(ContractValidationError, "duplicate provider capability"):
            registry.register(spec)

    def test_fixture_registration_registers_tool_and_adapter_together(self) -> None:
        tool_registry = ToolRegistry()
        adapter_registry = AdapterRegistry()

        tool, provider = register_fixture_tool(tool_registry, adapter_registry)

        self.assertEqual(tool.tool_id, "fixture-tool")
        self.assertEqual(provider.provider_id, "fixture-provider")
        self.assertEqual(tool_registry.tools_for_capability("fixture.ingest"), (tool,))
        self.assertEqual(adapter_registry.providers_for_capability("fixture.rank"), (provider,))


if __name__ == "__main__":
    unittest.main()
