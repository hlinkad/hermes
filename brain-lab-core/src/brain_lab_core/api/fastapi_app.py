"""Optional FastAPI adapter for the generic foundation control plane.

FastAPI is intentionally imported lazily: ``brain_lab_core`` remains usable in
stdlib-only environments, while deployments that install ``brain-lab-core[api]``
can expose the same control-plane operations over HTTP/OpenAPI.
"""
from __future__ import annotations

from typing import Any

from .control_plane import FoundationControlPlane, foundation_openapi_schema


def create_fastapi_app(control_plane: FoundationControlPlane):  # pragma: no cover - exercised when FastAPI is installed.
    """Create a FastAPI app backed by ``FoundationControlPlane``.

    Raises a clear runtime error instead of making the core package import-time
    depend on FastAPI/Pydantic.
    """

    try:
        from fastapi import FastAPI, HTTPException
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency absent in core tests.
        raise RuntimeError("Install brain-lab-core[api] to use create_fastapi_app().") from exc

    app = FastAPI(
        title="AI Lab Foundation Control Plane",
        version="brain_lab.contracts.v1",
        description="Generic tool/job/artifact/search API over brain_lab_core.",
    )

    def guarded(call, *args, **kwargs):
        try:
            return call(*args, **kwargs)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/tools")
    def list_tools():
        return guarded(control_plane.list_tools)

    @app.post("/jobs")
    def create_job(payload: dict[str, Any]):
        return guarded(control_plane.create_job, payload)

    @app.get("/jobs/{job_id}")
    def get_job(job_id: str):
        return guarded(control_plane.get_job, job_id)

    @app.post("/jobs/{job_id}/resume")
    def resume_job(job_id: str):
        return guarded(control_plane.resume_job, job_id)

    @app.post("/jobs/{job_id}/cancel")
    def cancel_job(job_id: str, payload: dict[str, Any] | None = None):
        reason = "operator requested cancellation"
        if payload:
            reason = str(payload.get("reason", reason))
        return guarded(control_plane.cancel_job, job_id, reason=reason)

    @app.get("/jobs/{job_id}/artifacts")
    def list_job_artifacts(job_id: str):
        return guarded(control_plane.list_job_artifacts, job_id)

    @app.get("/artifacts/{artifact_id}")
    def get_artifact(artifact_id: str, include_content: bool = False):
        return guarded(control_plane.get_artifact, artifact_id, include_content=include_content)

    @app.post("/search")
    def search(payload: dict[str, Any]):
        return guarded(control_plane.search, payload)

    @app.post("/answers")
    def answer(payload: dict[str, Any]):
        return guarded(control_plane.answer, payload)

    @app.get("/healthz")
    def healthz():
        return guarded(control_plane.healthz)

    @app.get("/config")
    def config():
        return guarded(control_plane.config_status)

    def custom_openapi():
        return foundation_openapi_schema(control_plane)

    app.openapi = custom_openapi
    return app
