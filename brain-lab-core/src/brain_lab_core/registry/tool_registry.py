"""Tool manifest registration and discovery."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from brain_lab_core.contracts import CONTRACT_SCHEMA_VERSION, ToolManifest
from brain_lab_core.contracts.base import JsonValue
from brain_lab_core.contracts.tools import SUPPORTED_TOOL_ENTRYPOINT_KINDS
from brain_lab_core.registry._common import (
    RegistryConflictError,
    RegistryLookupError,
    raise_for_error_diagnostics,
    required_registry_text,
)


class ToolRegistry:
    """In-memory registry for concrete tool manifests.

    The registry stores only `ToolManifest` declarations. It deliberately does
    not import package entrypoints, execute CLIs, or inspect container images, so
    API/MCP callers can list tools and capabilities without loading tool
    internals or triggering side effects.
    """

    discovery_contract_type = "brain_lab.tool_registry.discovery"

    def __init__(self, manifests: Iterable[ToolManifest | Mapping[str, Any]] = ()) -> None:
        # Store immutable JSON snapshots instead of caller-owned objects so
        # post-registration mutations cannot corrupt discovery state.
        self._manifest_snapshots: dict[str, str] = {}
        for manifest in manifests:
            self.register(manifest)

    def __len__(self) -> int:
        return len(self._manifest_snapshots)

    def __contains__(self, tool_id: object) -> bool:
        return isinstance(tool_id, str) and tool_id in self._manifest_snapshots

    def register(self, manifest: ToolManifest | Mapping[str, Any]) -> ToolManifest:
        """Register a tool manifest after contract and registry validation.

        Re-registering the exact same manifest is idempotent. Reusing a tool ID
        for a different manifest fails loudly to keep API discovery stable.
        """

        normalized = ToolManifest.from_dict(manifest)
        raise_for_error_diagnostics(normalized.validate())
        snapshot = normalized.to_json()
        existing = self._manifest_snapshots.get(normalized.tool_id)
        if existing is not None:
            if existing == snapshot:
                return ToolManifest.from_json(existing)
            raise RegistryConflictError(
                f"tool_id {normalized.tool_id!r} is already registered with a different manifest"
            )
        self._manifest_snapshots[normalized.tool_id] = snapshot
        return ToolManifest.from_json(snapshot)

    def get(self, tool_id: str) -> ToolManifest:
        normalized_id = required_registry_text(tool_id, "tool_id")
        try:
            snapshot = self._manifest_snapshots[normalized_id]
        except KeyError as exc:
            raise RegistryLookupError(f"tool_id {normalized_id!r} is not registered") from exc
        return ToolManifest.from_json(snapshot)

    def list_tools(self) -> tuple[ToolManifest, ...]:
        return tuple(self.get(tool_id) for tool_id in sorted(self._manifest_snapshots))

    def tools_for_capability(self, capability: str) -> tuple[ToolManifest, ...]:
        normalized_capability = required_registry_text(capability, "capability")
        return tuple(
            manifest
            for manifest in self.list_tools()
            if normalized_capability in manifest.capabilities
        )

    def tools_accepting_artifact_type(self, artifact_type: str) -> tuple[ToolManifest, ...]:
        normalized_type = required_registry_text(artifact_type, "artifact_type")
        return tuple(
            manifest
            for manifest in self.list_tools()
            if normalized_type in manifest.input_artifact_types
        )

    def tools_producing_artifact_type(self, artifact_type: str) -> tuple[ToolManifest, ...]:
        normalized_type = required_registry_text(artifact_type, "artifact_type")
        return tuple(
            manifest
            for manifest in self.list_tools()
            if normalized_type in manifest.output_artifact_types
        )

    def capability_catalog(self) -> tuple[dict[str, JsonValue], ...]:
        """Return deterministic, JSON-safe capability records for API/MCP surfaces."""

        records: list[dict[str, JsonValue]] = []
        for manifest in self.list_tools():
            for capability in manifest.capabilities:
                records.append(
                    {
                        "capability": capability,
                        "tool_id": manifest.tool_id,
                        "tool_version": manifest.tool_version,
                        "input_artifact_types": list(manifest.input_artifact_types),
                        "output_artifact_types": list(manifest.output_artifact_types),
                        "entrypoints": dict(manifest.entrypoints),
                        "required_secret_names": list(manifest.required_secret_names),
                    }
                )
        return tuple(records)

    def artifact_type_catalog(self) -> tuple[dict[str, JsonValue], ...]:
        """Return deterministic input/output artifact-type indexes."""

        indexed: dict[tuple[str, str], set[str]] = {}
        for manifest in self.list_tools():
            for artifact_type in manifest.input_artifact_types:
                indexed.setdefault((artifact_type, "input"), set()).add(manifest.tool_id)
            for artifact_type in manifest.output_artifact_types:
                indexed.setdefault((artifact_type, "output"), set()).add(manifest.tool_id)
        return tuple(
            {
                "artifact_type": artifact_type,
                "direction": direction,
                "tool_ids": sorted(tool_ids),
            }
            for (artifact_type, direction), tool_ids in sorted(indexed.items())
        )

    def discovery_document(self) -> dict[str, JsonValue]:
        """Return the full JSON-safe registry view intended for API/MCP consumers."""

        return {
            "contract_type": self.discovery_contract_type,
            "schema_version": CONTRACT_SCHEMA_VERSION,
            "supported_entrypoint_kinds": list(SUPPORTED_TOOL_ENTRYPOINT_KINDS),
            "tools": [manifest.to_dict() for manifest in self.list_tools()],
            "capabilities": list(self.capability_catalog()),
            "artifact_types": list(self.artifact_type_catalog()),
        }
