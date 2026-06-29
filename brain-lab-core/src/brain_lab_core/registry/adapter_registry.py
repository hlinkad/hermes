"""Provider adapter registration and capability discovery."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from brain_lab_core.contracts import CONTRACT_SCHEMA_VERSION, ProviderSpec
from brain_lab_core.contracts.base import JsonValue
from brain_lab_core.registry._common import (
    RegistryConflictError,
    RegistryLookupError,
    raise_for_error_diagnostics,
    required_registry_text,
)


class AdapterRegistry:
    """In-memory registry for provider adapter declarations.

    The registry indexes `ProviderSpec` metadata by provider and capability. It
    does not instantiate adapters or import adapter modules, which keeps
    discovery safe for API/MCP listing and local control-plane startup.
    """

    discovery_contract_type = "brain_lab.adapter_registry.discovery"

    def __init__(self, providers: Iterable[ProviderSpec | Mapping[str, Any]] = ()) -> None:
        # Store immutable JSON snapshots instead of caller-owned objects so
        # post-registration mutations cannot corrupt discovery state.
        self._provider_snapshots: dict[str, str] = {}
        for provider in providers:
            self.register(provider)

    def __len__(self) -> int:
        return len(self._provider_snapshots)

    def __contains__(self, provider_id: object) -> bool:
        return isinstance(provider_id, str) and provider_id in self._provider_snapshots

    def register(self, provider: ProviderSpec | Mapping[str, Any]) -> ProviderSpec:
        """Register a provider spec after contract and registry validation."""

        normalized = ProviderSpec.from_dict(provider)
        raise_for_error_diagnostics(normalized.validate())
        snapshot = normalized.to_json()
        existing = self._provider_snapshots.get(normalized.provider_id)
        if existing is not None:
            if existing == snapshot:
                return ProviderSpec.from_json(existing)
            raise RegistryConflictError(
                f"provider_id {normalized.provider_id!r} is already registered with a different spec"
            )
        self._provider_snapshots[normalized.provider_id] = snapshot
        return ProviderSpec.from_json(snapshot)

    def get(self, provider_id: str) -> ProviderSpec:
        normalized_id = required_registry_text(provider_id, "provider_id")
        try:
            snapshot = self._provider_snapshots[normalized_id]
        except KeyError as exc:
            raise RegistryLookupError(f"provider_id {normalized_id!r} is not registered") from exc
        return ProviderSpec.from_json(snapshot)

    def list_providers(self) -> tuple[ProviderSpec, ...]:
        return tuple(self.get(provider_id) for provider_id in sorted(self._provider_snapshots))

    def providers_for_capability(
        self, capability: str, *, version: str | None = None
    ) -> tuple[ProviderSpec, ...]:
        normalized_capability = required_registry_text(capability, "capability")
        normalized_version = None if version is None else required_registry_text(version, "version")
        providers: list[ProviderSpec] = []
        for provider in self.list_providers():
            for provider_capability in provider.capabilities:
                if provider_capability.name != normalized_capability:
                    continue
                if normalized_version is not None and provider_capability.version != normalized_version:
                    continue
                providers.append(provider)
                break
        return tuple(providers)

    def providers_accepting_artifact_type(self, artifact_type: str) -> tuple[ProviderSpec, ...]:
        normalized_type = required_registry_text(artifact_type, "artifact_type")
        providers: list[ProviderSpec] = []
        for provider in self.list_providers():
            if any(
                normalized_type in capability.input_artifact_types
                for capability in provider.capabilities
            ):
                providers.append(provider)
        return tuple(providers)

    def providers_producing_artifact_type(self, artifact_type: str) -> tuple[ProviderSpec, ...]:
        normalized_type = required_registry_text(artifact_type, "artifact_type")
        providers: list[ProviderSpec] = []
        for provider in self.list_providers():
            if any(
                normalized_type in capability.output_artifact_types
                for capability in provider.capabilities
            ):
                providers.append(provider)
        return tuple(providers)

    def capability_catalog(self) -> tuple[dict[str, JsonValue], ...]:
        """Return deterministic, JSON-safe provider capability records."""

        records: list[dict[str, JsonValue]] = []
        for provider in self.list_providers():
            for capability in provider.capabilities:
                records.append(
                    {
                        "capability": capability.name,
                        "capability_version": capability.version,
                        "provider_id": provider.provider_id,
                        "provider_type": provider.provider_type,
                        "provider_version": provider.provider_version,
                        "adapter_module": provider.adapter_module,
                        "input_artifact_types": list(capability.input_artifact_types),
                        "output_artifact_types": list(capability.output_artifact_types),
                        "required_secret_names": list(provider.required_secret_names),
                    }
                )
        return tuple(records)

    def artifact_type_catalog(self) -> tuple[dict[str, JsonValue], ...]:
        indexed: dict[tuple[str, str], set[str]] = {}
        for provider in self.list_providers():
            for capability in provider.capabilities:
                for artifact_type in capability.input_artifact_types:
                    indexed.setdefault((artifact_type, "input"), set()).add(provider.provider_id)
                for artifact_type in capability.output_artifact_types:
                    indexed.setdefault((artifact_type, "output"), set()).add(provider.provider_id)
        return tuple(
            {
                "artifact_type": artifact_type,
                "direction": direction,
                "provider_ids": sorted(provider_ids),
            }
            for (artifact_type, direction), provider_ids in sorted(indexed.items())
        )

    def discovery_document(self) -> dict[str, JsonValue]:
        return {
            "contract_type": self.discovery_contract_type,
            "schema_version": CONTRACT_SCHEMA_VERSION,
            "providers": [provider.to_dict() for provider in self.list_providers()],
            "capabilities": list(self.capability_catalog()),
            "artifact_types": list(self.artifact_type_catalog()),
        }
