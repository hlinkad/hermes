"""Fixture registrations for registry and integration-contract tests."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from brain_lab_core.contracts import ProviderCapability, ProviderSpec, ResourceProfile, ToolManifest
from brain_lab_core.registry.adapter_registry import AdapterRegistry
from brain_lab_core.registry.tool_registry import ToolRegistry
from brain_lab_core.security import DependencyMetadata, SandboxPolicy, SecretDeclaration


def fixture_tool_manifest(
    *,
    tool_id: str = "fixture-tool",
    tool_version: str = "0.1.0",
    capabilities: tuple[str, ...] = ("fixture.ingest", "fixture.summarize"),
    input_artifact_types: tuple[str, ...] = ("source.url",),
    output_artifact_types: tuple[str, ...] = ("fixture.records", "report.markdown"),
    entrypoints: Mapping[str, str] | None = None,
    required_secret_names: tuple[str, ...] = (),
    secret_declarations: tuple[SecretDeclaration, ...] = (),
    sandbox_policy: SandboxPolicy | Mapping[str, Any] | None = None,
    dependency_metadata: tuple[DependencyMetadata, ...] = (),
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
        secret_declarations=secret_declarations,
        sandbox_policy=SandboxPolicy.from_dict(sandbox_policy),
        dependency_metadata=dependency_metadata,
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


def mineru_document_extraction_manifest(
    *,
    tool_id: str = "mineru-api",
    tool_version: str = "3.4.0",
    entrypoints: Mapping[str, str] | None = None,
) -> ToolManifest:
    """Return metadata-only MinerU document/PDF extraction manifest.

    The foundation advertises the approved DH-227 MinerU service boundary here,
    but this fixture deliberately does not import MinerU, start a service, call a
    CLI, or require MinerU to be installed.
    """

    default_entrypoints = {"cli": "mineru-api"}
    service_endpoints = [
        "GET /health",
        "POST /tasks",
        "POST /file_parse",
        "GET /tasks/{task_id}",
        "GET /tasks/{task_id}/result",
    ]
    return ToolManifest(
        tool_id=tool_id,
        tool_version=tool_version,
        capabilities=("document.extract", "pdf.extract", "ocr.extract"),
        input_artifact_types=("source.document", "source.pdf", "source.file"),
        output_artifact_types=(
            "document.extraction",
            "pdf.extraction",
            "document.markdown",
            "document.assets",
        ),
        entrypoints=default_entrypoints if entrypoints is None else dict(entrypoints),
        resource_profile=ResourceProfile(
            cpu_cores=4.0,
            memory_mb=8192,
            disk_mb=20480,
            gpu_required=False,
            network_required=True,
            timeout_seconds=3600,
        ),
        license_notes=(
            "MinerU Open Source License: Apache 2.0 terms plus additional "
            "commercial/online-service attribution requirements; preserve raw "
            "source policy in document provenance."
        ),
        sandbox_policy=SandboxPolicy.from_dict(
            {
                "sandbox_class": "networked",
                "filesystem": {
                    "mode": "read_write",
                    "allowed_paths": ["${BRAIN_LAB_ARTIFACT_ROOT}", "${BRAIN_LAB_SOURCE_ROOT}"],
                },
                "network": {
                    "mode": "loopback",
                    "allowed_hosts": ["127.0.0.1", "localhost"],
                },
                "allow_subprocess": False,
                "allow_gpu": False,
                "metadata": {
                    "integration_surface": "optional_http_service",
                    "service_name": "mineru-api",
                },
            }
        ),
        dependency_metadata=(
            DependencyMetadata(
                name="mineru",
                version=tool_version,
                package_url="pkg:github/opendatalab/mineru@3e60291846cb7c3bf8fe7f4f16238f4fc6cce491",
                license_name="MinerU Open Source License (Apache 2.0 plus additional terms)",
                supplier="OpenDataLab",
            ),
        ),
        metadata={
            "integration_fixture": True,
            "issue_id": "DH-228",
            "depends_on": ["DH-227"],
            "service_boundary": "mineru-api HTTP service",
            "service_endpoints": service_endpoints,
            "document_contracts": {
                "result_contracts": ["DocumentExtractionResult", "PdfExtractionResult"],
                "page_contracts": ["DocumentPage", "PdfPageResult"],
                "block_contracts": ["DocumentBlock", "PdfBlock"],
                "provenance_contract": "DocumentProvenance",
            },
            "artifact_contracts": {
                "normalized_json": "document.extraction",
                "pdf_normalized_json": "pdf.extraction",
                "markdown": "document.markdown",
                "assets": "document.assets",
            },
            "guardrails": [
                "brain_lab_core remains importable without MinerU installed",
                "registry discovery is metadata-only and does not import or execute MinerU",
                "Qdrant and Obsidian remain downstream consumers, not extraction contract dependencies",
            ],
        },
    )



def video_intel_tool_manifest(
    *,
    tool_id: str = "video-intel",
    tool_version: str = "0.1.0",
    entrypoints: Mapping[str, str] | None = None,
) -> ToolManifest:
    """Return the video-intel manifest fixture for foundation contract tests.

    The fixture mirrors the DH-94..DH-103 boundary: video-intel owns concrete
    video stages, while this package owns the generic manifest, job, artifact,
    evidence, retrieval, and API/MCP contracts those stages must use.
    """

    default_entrypoints = {
        "python": "video_intel.integration:register",
        "cli": "video-intel",
        "container_image": "local/video-intel:0.1.0",
    }
    stage_contracts = (
        {
            "issue_id": "DH-94",
            "stage_id": "ingest",
            "input_artifact_types": ["source.url", "source.media_file"],
            "output_schema_versions": [
                "video.media_manifest.v1",
                "video.audio.v1",
                "source.media_file.v1",
            ],
        },
        {
            "issue_id": "DH-95",
            "stage_id": "transcribe",
            "input_artifact_types": ["video.audio", "source.media_file"],
            "output_schema_versions": ["video.transcript.v1"],
        },
        {
            "issue_id": "DH-96",
            "stage_id": "capture-frames",
            "input_artifact_types": ["source.media_file", "video.transcript"],
            "output_schema_versions": ["video.candidate_frames.v1"],
        },
        {
            "issue_id": "DH-97",
            "stage_id": "dedupe-frames",
            "input_artifact_types": ["video.candidate_frames"],
            "output_schema_versions": ["video.selected_frames.v1"],
        },
        {
            "issue_id": "DH-98",
            "stage_id": "analyze-frames",
            "input_artifact_types": ["video.selected_frames"],
            "output_schema_versions": ["video.frame_analysis.v1"],
        },
        {
            "issue_id": "DH-99",
            "stage_id": "align-timeline",
            "input_artifact_types": ["video.transcript", "video.frame_analysis"],
            "output_schema_versions": ["video.timeline.v1"],
        },
        {
            "issue_id": "DH-100",
            "stage_id": "build-chunks",
            "input_artifact_types": ["video.timeline", "video.transcript", "video.frame_analysis"],
            "output_schema_versions": ["retrieval.chunks.v1"],
        },
        {
            "issue_id": "DH-101",
            "stage_id": "index-chunks",
            "input_artifact_types": ["retrieval.chunks"],
            "output_schema_versions": ["retrieval.index_result.v1"],
        },
        {
            "issue_id": "DH-102",
            "stage_id": "synthesize",
            "input_artifact_types": ["retrieval.chunks", "video.timeline"],
            "output_schema_versions": ["report.markdown.v1", "report.json.v1"],
        },
        {
            "issue_id": "DH-103",
            "stage_id": "foundation-control-plane-integration",
            "input_artifact_types": ["source.url", "source.media_file"],
            "output_schema_versions": ["foundation.job_status.v1"],
        },
    )
    return ToolManifest(
        tool_id=tool_id,
        tool_version=tool_version,
        capabilities=(
            "video.ingest",
            "video.transcribe",
            "video.frame_capture",
            "video.frame_extract",
            "video.timeline",
            "video.chunk",
            "video.index",
            "video.summarize",
            "video.api_integration",
        ),
        input_artifact_types=("source.url", "source.media_file"),
        output_artifact_types=(
            "video.media_manifest",
            "video.audio",
            "video.transcript",
            "video.candidate_frames",
            "video.selected_frames",
            "video.frame_analysis",
            "video.timeline",
            "retrieval.chunks",
            "retrieval.index_result",
            "report.markdown",
            "report.json",
            "foundation.job_status",
        ),
        entrypoints=default_entrypoints if entrypoints is None else dict(entrypoints),
        resource_profile=ResourceProfile(
            cpu_cores=4.0,
            memory_mb=8192,
            disk_mb=20480,
            network_required=True,
            timeout_seconds=7200,
        ),
        license_notes="video-intel must record source/media license policy per artifact provenance",
        secret_declarations=(
            SecretDeclaration(
                name="VIDEO_INTEL_SOURCE_TOKEN",
                required=False,
                description="Optional source/API credential; public YouTube ingest does not require it.",
                redaction_hint="token",
            ),
        ),
        sandbox_policy=SandboxPolicy.from_dict(
            {
                "sandbox_class": "networked",
                "filesystem": {
                    "mode": "read_write",
                    "allowed_paths": ["${BRAIN_LAB_ARTIFACT_ROOT}"],
                },
                "network": {
                    "mode": "outbound",
                    "allowed_hosts": ["youtube.com", "youtu.be", "googlevideo.com"],
                },
                "allow_subprocess": True,
                "allow_gpu": True,
            }
        ),
        dependency_metadata=(
            DependencyMetadata(
                name="yt-dlp",
                package_url="pkg:pypi/yt-dlp",
                license_name="Unlicense",
                supplier="yt-dlp maintainers",
            ),
            DependencyMetadata(
                name="ffmpeg",
                package_url="pkg:generic/ffmpeg",
                license_name="LGPL/GPL depending on build flags",
                supplier="FFmpeg project",
            ),
            DependencyMetadata(
                name="faster-whisper",
                package_url="pkg:pypi/faster-whisper",
                license_name="MIT",
                supplier="SYSTRAN",
            ),
        ),
        metadata={
            "integration_fixture": True,
            "issue_range": "DH-94..DH-103",
            "foundation_boundary": {
                "generic_state_owner": "brain_lab_core.state.SQLiteArtifactLedger",
                "generic_retrieval_owner": "brain_lab_core.retrieval.QdrantRetrievalFacade",
                "generic_api_owner": "brain_lab_core.api.FoundationControlPlane",
            },
            "stage_contracts": list(stage_contracts),
        },
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
