"""MCP-facing wrapper methods for the foundation control plane.

The native MCP server can expose methods on this class as tool handlers without
knowing about SQLite, job runners, or registries. Keeping the wrapper thin gives
HTTP and MCP identical validation, provenance, and redaction behavior.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .control_plane import FoundationControlPlane, JsonObject


class FoundationMCPTools:
    """Transport-neutral MCP operation facade over ``FoundationControlPlane``."""

    def __init__(self, control_plane: FoundationControlPlane) -> None:
        self.control_plane = control_plane

    def list_tools(self) -> JsonObject:
        return self.control_plane.list_tools()

    def create_job(self, payload: Mapping[str, Any]) -> JsonObject:
        return self.control_plane.create_job(payload)

    def get_job(self, job_id: str) -> JsonObject:
        return self.control_plane.get_job(job_id)

    def resume_job(self, job_id: str) -> JsonObject:
        return self.control_plane.resume_job(job_id)

    def cancel_job(self, job_id: str, *, reason: str = "operator requested cancellation") -> JsonObject:
        return self.control_plane.cancel_job(job_id, reason=reason)

    def list_job_artifacts(self, job_id: str) -> JsonObject:
        return self.control_plane.list_job_artifacts(job_id)

    def get_artifact(self, artifact_id: str, *, include_content: bool = False) -> JsonObject:
        return self.control_plane.get_artifact(artifact_id, include_content=include_content)

    def search(self, payload: Mapping[str, Any]) -> JsonObject:
        return self.control_plane.search(payload)

    def answer(self, payload: Mapping[str, Any]) -> JsonObject:
        return self.control_plane.answer(payload)

    def healthz(self) -> JsonObject:
        return self.control_plane.healthz()

    def config(self) -> JsonObject:
        return self.control_plane.config_status()

    def openapi_schema(self) -> JsonObject:
        return self.control_plane.openapi_schema()
