"""API/control-plane extension point.

The API package exposes a dependency-free control-plane core plus thin transport
adapters for MCP and optional FastAPI/OpenAPI. All transports should route
through ``FoundationControlPlane`` so job/artifact state remains canonical in the
SQLite ledger and config/status responses share the same secret-redaction path.
"""
from __future__ import annotations

from .control_plane import (
    FoundationControlPlane,
    JobSubmission,
    create_fixture_control_plane,
    create_video_intel_fixture_control_plane,
    foundation_openapi_schema,
    redact_secrets,
)
from .fastapi_app import create_fastapi_app
from .mcp_tools import FoundationMCPTools

__all__ = [
    "FoundationControlPlane",
    "FoundationMCPTools",
    "JobSubmission",
    "create_fastapi_app",
    "create_fixture_control_plane",
    "create_video_intel_fixture_control_plane",
    "foundation_openapi_schema",
    "redact_secrets",
]
