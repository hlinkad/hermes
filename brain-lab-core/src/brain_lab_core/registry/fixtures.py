"""Fixture registrations for registry and integration-contract tests."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from brain_lab_core.contracts import ProviderCapability, ProviderSpec, ResourceProfile, ToolManifest
from brain_lab_core.registry.adapter_registry import AdapterRegistry
from brain_lab_core.registry.tool_registry import ToolRegistry


def fixture_tool_manifest(
    *,
    tool_id: str = "fixture-tool",
    tool_version: str = "0.1.0",
    capabilities: tuple[str, ...] = ("fixture.ingest", "fixture.summarize"),
    input_artifact_types: tuple[str, ...] = ("source.url",),
    output_artifact_types: tuple[str, ...] = ("fixture.records", "report.markdown"),
    entrypoints: Mapping[str, str] | None = None,
    required_secret_names: tuple[str, ...] = (),
    metadata: Mapping[str, Any] | None = None,
) -> ToolManifest:
    """Return a generic fake tool manifest used to prove the registry seam."""

    default_entrypoints = {"python": "fixture_tool.integration:register", "cli": "fixture-tool"}
    return ToolManifest(
        tool_id=tool_id,
        tool_version=tool_version,
        capabilities=capabilities,
        input_artifact_types=input_artifact_types,
        output_artifact_types=output_artifact_types,
        entrypoints=default_entrypoints if entrypoints is None else dict(entrypoints),
        resource_profile=ResourceProfile(cpu_cores=1.0, memory_mb=256, disk_mb=64, timeout_seconds=30),
        license_notes="MIT fixture only",
        required_secret_names=required_secret_names,
        metadata={"fixture": True} if metadata is None else metadata,
    )


def fixture_provider_spec(
    *,
    provider_id: str = "fixture-provider",
    provider_type: str = "embedding",
    provider_version: str = "0.1.0",
    adapter_module: str = "fixture_provider.adapters:FixtureAdapter",
    required_secret_names: tuple[str, ...] = (),
    metadata: Mapping[str, Any] | None = None,
) -> ProviderSpec:
    """Return a fake provider adapter spec with two discoverable capabilities."""

    return ProviderSpec(
        provider_id=provider_id,
        provider_type=provider_type,
        provider_version=provider_version,
        adapter_module=adapter_module,
        capabilities=(
            ProviderCapability(
                name="fixture.embed",
                version="v1",
                input_artifact_types=("retrieval.chunks",),
                output_artifact_types=("retrieval.embedding",),
            ),
            ProviderCapability(
                name="fixture.rank",
                version="v1",
                input_artifact_types=("retrieval.embedding",),
                output_artifact_types=("retrieval.ranking",),
            ),
        ),
        required_secret_names=required_secret_names,
        metadata={"fixture": True} if metadata is None else metadata,
    )


def register_fixture_tool(
    tool_registry: ToolRegistry,
    adapter_registry: AdapterRegistry,
) -> tuple[ToolManifest, ProviderSpec]:
    """Register the fake tool and fake provider into caller-owned registries."""

    tool = tool_registry.register(fixture_tool_manifest())
    provider = adapter_registry.register(fixture_provider_spec())
    return tool, provider


def fixture_registries() -> tuple[ToolRegistry, AdapterRegistry]:
    """Return populated registries containing the fake tool and fake provider."""

    tool_registry = ToolRegistry()
    adapter_registry = AdapterRegistry()
    register_fixture_tool(tool_registry, adapter_registry)
    return tool_registry, adapter_registry
