"""Tool and adapter registry extension point.

Registries store manifest/spec metadata and expose deterministic JSON-safe
capability discovery for API/MCP consumers without importing concrete tool or
provider internals.
"""
from __future__ import annotations

from ._common import RegistryConflictError, RegistryLookupError
from .adapter_registry import AdapterRegistry
from .fixtures import (
    fixture_provider_spec,
    fixture_registries,
    fixture_tool_manifest,
    register_fixture_tool,
)
from .tool_registry import ToolRegistry

__all__ = [
    "AdapterRegistry",
    "RegistryConflictError",
    "RegistryLookupError",
    "ToolRegistry",
    "fixture_provider_spec",
    "fixture_registries",
    "fixture_tool_manifest",
    "register_fixture_tool",
]
