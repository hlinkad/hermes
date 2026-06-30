"""Generic API/MCP control plane over foundation state, jobs, tools, and retrieval.

This module is dependency-free so the core package can expose a stable control
surface in tests, local CLIs, MCP wrappers, and optional FastAPI apps without
requiring a web stack at import time. HTTP adapters should call these methods
rather than reading SQLite/filesystem state directly, preserving the same
provenance and redaction behavior across transports.
"""
from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from brain_lab_core.contracts import (
    ArtifactId,
    CONTRACT_SCHEMA_VERSION,
    ContractValidationError,
    FreshnessState,
    LifecycleState,
)
from brain_lab_core.contracts.base import JsonValue
from brain_lab_core.orchestration import ArtifactContract, JobPlan, JobRunner, StageExecutionResult, StagePlan
from brain_lab_core.observability import ObservabilityEvent
from brain_lab_core.registry import AdapterRegistry, ToolRegistry, fixture_registries
from brain_lab_core.security import REDACTED, collect_secret_values, is_secret_key, redact_secrets as _redact_secrets
from brain_lab_core.state import SQLiteArtifactLedger

JsonObject = dict[str, JsonValue]
JobPlanFactory = Callable[["JobSubmission"], JobPlan]
SearchHandler = Callable[[Mapping[str, Any]], Mapping[str, Any]]
AnswerHandler = Callable[[Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]]

_REDACTED = REDACTED
_SAFE_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
_SEARCH_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "be",
        "can",
        "did",
        "do",
        "does",
        "for",
        "from",
        "how",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "the",
        "through",
        "to",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "with",
    }
)


@dataclass(frozen=True)
class JobSubmission:
    """Transport-neutral job creation request consumed by plan factories."""

    tool_id: str
    job_id: str = ""
    config: Mapping[str, Any] = field(default_factory=dict)
    inputs: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        tool_id = str(self.tool_id or "").strip()
        if not tool_id:
            raise ContractValidationError("job submission requires tool_id")
        job_id = str(self.job_id or f"{tool_id}-{uuid.uuid4().hex[:12]}").strip()
        if not job_id:
            raise ContractValidationError("job submission requires job_id")
        if ":" in job_id:
            raise ContractValidationError("job_id must not contain ':'")
        _validate_safe_identifier(job_id, "job_id")
        if not isinstance(self.config, Mapping):
            raise ContractValidationError("job config must be a mapping")
        if not isinstance(self.inputs, Mapping):
            raise ContractValidationError("job inputs must be a mapping")
        if not isinstance(self.metadata, Mapping):
            raise ContractValidationError("job metadata must be a mapping")
        object.__setattr__(self, "tool_id", tool_id)
        object.__setattr__(self, "job_id", job_id)
        object.__setattr__(self, "config", dict(self.config))
        object.__setattr__(self, "inputs", dict(self.inputs))
        object.__setattr__(self, "metadata", dict(self.metadata))

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "JobSubmission":
        if not isinstance(payload, Mapping):
            raise ContractValidationError("job create payload must be a mapping")
        return cls(
            tool_id=payload.get("tool_id", ""),
            job_id=payload.get("job_id", ""),
            config=_optional_mapping(payload.get("config"), "job config"),
            inputs=_optional_mapping(payload.get("inputs"), "job inputs"),
            metadata=_optional_mapping(payload.get("metadata"), "job metadata"),
        )


class FoundationControlPlane:
    """Tool-neutral API/MCP operations backed by foundation registries and ledger."""

    def __init__(
        self,
        *,
        tool_registry: ToolRegistry,
        adapter_registry: AdapterRegistry | None = None,
        ledger: SQLiteArtifactLedger,
        runner: JobRunner | None = None,
        config: Mapping[str, Any] | None = None,
        job_plan_factories: Mapping[str, JobPlanFactory] | None = None,
        search_handlers: Mapping[str, SearchHandler] | None = None,
        answer_handler: AnswerHandler | None = None,
    ) -> None:
        self.tool_registry = tool_registry
        self.adapter_registry = adapter_registry or AdapterRegistry()
        self.ledger = ledger
        self.runner = runner or JobRunner(ledger)
        self._config = dict(config or {})
        self._job_plan_factories = dict(job_plan_factories or {})
        self._plans_by_job_id: dict[str, JobPlan] = {}
        self._job_secret_names_by_job_id: dict[str, tuple[str, ...]] = {}
        self._job_secret_values_by_job_id: dict[str, tuple[str, ...]] = {}
        self._job_ids_by_creation: list[str] = []
        self._search_handlers = dict(search_handlers or {})
        self._answer_handler = answer_handler

    @property
    def secret_names(self) -> tuple[str, ...]:
        names: set[str] = set()
        for key in self._config:
            if is_secret_key(key, ()):  # Config keys such as OPENAI_API_KEY should be named in policy.
                names.add(str(key))
        for manifest in self.tool_registry.list_tools():
            names.update(manifest.required_secret_names)
            names.update(declaration.name for declaration in manifest.secret_declarations)
        for provider in self.adapter_registry.list_providers():
            names.update(provider.required_secret_names)
        return tuple(sorted(names))

    @property
    def secret_values(self) -> tuple[str, ...]:
        return tuple(sorted(collect_secret_values(self._config, self.secret_names), key=len, reverse=True))

    def healthz(self) -> JsonObject:
        return self._safe(
            {
                "status": "ok",
                "schema_version": CONTRACT_SCHEMA_VERSION,
                "ledger_schema_version": self.ledger.schema_version(),
                "registered_tool_count": len(self.tool_registry),
                "registered_provider_count": len(self.adapter_registry),
                "known_job_count": len(self._known_job_ids()),
            }
        )

    def config_status(self) -> JsonObject:
        return self._safe(
            {
                "schema_version": CONTRACT_SCHEMA_VERSION,
                "secret_policy": {
                    "redacted": True,
                    "redaction_marker": _REDACTED,
                    "secret_names": list(self.secret_names),
                },
                "config": self._config,
            }
        )

    def list_tools(self) -> JsonObject:
        document = self.tool_registry.discovery_document()
        document["provider_registry"] = self.adapter_registry.discovery_document()
        return self._safe(document)

    def create_job(self, payload: Mapping[str, Any]) -> JsonObject:
        submission = JobSubmission.from_payload(payload)
        manifest = self.tool_registry.get(submission.tool_id)
        job_exists = True
        try:
            self.ledger.get_job(submission.job_id)
        except KeyError:
            job_exists = False
        if job_exists:
            raise ContractValidationError(f"job_id {submission.job_id!r} already exists")
        try:
            factory = self._job_plan_factories[submission.tool_id]
        except KeyError as exc:
            raise ContractValidationError(
                f"tool_id {submission.tool_id!r} has no registered job plan factory"
            ) from exc
        plan = factory(submission)
        if plan.job_id != submission.job_id:
            raise ContractValidationError("job plan factory changed the submitted job_id")
        if plan.tool_id != submission.tool_id:
            raise ContractValidationError("job plan factory changed the submitted tool_id")
        job_secret_names = self._secret_names_for_manifest(manifest)
        job_secret_values = tuple(
            sorted(
                collect_secret_values(self._config, job_secret_names)
                | collect_secret_values(plan.config, job_secret_names),
                key=len,
                reverse=True,
            )
        )
        plan = self._attach_job_secret_policy(plan, job_secret_names)
        self._job_secret_names_by_job_id[plan.job_id] = job_secret_names
        self._job_secret_values_by_job_id[plan.job_id] = job_secret_values
        self.runner.set_redaction_policy(
            plan.job_id,
            secret_names=job_secret_names,
            secret_values=job_secret_values,
        )
        self._plans_by_job_id[plan.job_id] = plan
        if plan.job_id not in self._job_ids_by_creation:
            self._job_ids_by_creation.append(plan.job_id)
        job = self.runner.run(plan, resume=False)
        return self._job_response(job.job_id)

    def get_job(self, job_id: str) -> JsonObject:
        return self._job_response(_required_text(job_id, "job_id"))

    def resume_job(self, job_id: str) -> JsonObject:
        normalized = _required_text(job_id, "job_id")
        try:
            plan = self._plans_by_job_id[normalized]
        except KeyError as exc:
            raise ContractValidationError(
                f"job_id {normalized!r} has no in-memory plan for resume; recreate the control plane with a plan registry"
            ) from exc
        job = self.runner.run(plan, resume=True)
        return self._job_response(job.job_id)

    def cancel_job(self, job_id: str, *, reason: str = "operator requested cancellation") -> JsonObject:
        normalized = _required_text(job_id, "job_id")
        job = self.ledger.get_job(normalized)
        if job.state in {LifecycleState.COMPLETED, LifecycleState.CANCELED, LifecycleState.FAILED}:
            response: dict[str, Any] = {
                "job_id": normalized,
                "cancel_requested": False,
                "reason": f"job is already {job.state.value}",
            }
            response.update(self._job_response(normalized))
            return self._safe(
                response,
                secret_names=self._job_secret_names(normalized),
                secret_values=self._job_secret_values(normalized),
            )
        self.runner.request_cancel(normalized, reason=reason)
        response = {"job_id": normalized, "cancel_requested": True, "reason": reason}
        response.update(self._job_response(normalized))
        return self._safe(
            response,
            secret_names=self._job_secret_names(normalized),
            secret_values=self._job_secret_values(normalized),
        )

    def list_job_artifacts(self, job_id: str) -> JsonObject:
        normalized = _required_text(job_id, "job_id")
        self.ledger.get_job(normalized)
        artifacts = [
            self._artifact_to_safe_dict(self.ledger.get_artifact(artifact_id), normalized)
            for artifact_id in self._job_artifact_ids(normalized)
        ]
        return self._safe(
            {"job_id": normalized, "artifacts": artifacts},
            secret_names=self._job_secret_names(normalized),
            secret_values=self._job_secret_values(normalized),
        )

    def get_artifact(self, artifact_id: ArtifactId | str | Mapping[str, Any], *, include_content: bool = False) -> JsonObject:
        normalized = ArtifactId.from_dict(artifact_id)
        artifact = self.ledger.get_artifact(normalized)
        job_id = self._artifact_job_id(normalized)
        response: dict[str, Any] = {"artifact": self._artifact_to_safe_dict(artifact, job_id)}
        if include_content:
            path = self.ledger.get_artifact_path(normalized)
            response["content"] = _REDACTED if self._redaction_values_unavailable(job_id) else _read_text_if_small(path)
        return self._safe(
            response,
            secret_names=self._job_secret_names(job_id) if job_id else (),
            secret_values=self._job_secret_values(job_id) if job_id else (),
        )

    def search(self, payload: Mapping[str, Any]) -> JsonObject:
        if not isinstance(payload, Mapping):
            raise ContractValidationError("search payload must be a mapping")
        query = str(payload.get("query", "")).strip()
        if not query:
            raise ContractValidationError("search query is required")
        collection_name = str(payload.get("collection_name", "default")).strip() or "default"
        limit = _positive_int(payload.get("limit", 10), "search.limit")
        handler = self._search_handlers.get(collection_name)
        if handler is not None:
            handled = dict(handler({**dict(payload), "query": query, "collection_name": collection_name, "limit": limit}))
            return self._safe(
                handled,
                secret_names=self._known_job_secret_names(),
                secret_values=self._known_job_secret_values(),
            )
        return self._safe(self._ledger_text_search(query=query, collection_name=collection_name, limit=limit))

    def answer(self, payload: Mapping[str, Any]) -> JsonObject:
        if not isinstance(payload, Mapping):
            raise ContractValidationError("answer payload must be a mapping")
        question = str(payload.get("question", payload.get("query", ""))).strip()
        if not question:
            raise ContractValidationError("answer question is required")
        search_payload = {
            "query": question,
            "collection_name": payload.get("collection_name", "default"),
            "limit": payload.get("limit", 5),
        }
        search_result = self.search(search_payload)
        if self._answer_handler is not None:
            handled = dict(self._answer_handler(payload, search_result))
            return self._safe(handled)
        citations = [_citation_from_hit(hit) for hit in search_result.get("hits", [])]
        return self._safe(
            {
                "question": question,
                "answer_state": "unconfigured",
                "answer": "No answer provider configured; returning cited search context only.",
                "citations": citations,
                "search": search_result,
            }
        )

    def openapi_schema(self) -> JsonObject:
        return foundation_openapi_schema(self)

    def _job_response(self, job_id: str) -> JsonObject:
        job = self.ledger.get_job(job_id)
        stages = [stage.to_dict() for stage in self.ledger.list_stage_runs(job_id)]
        events = [_event_to_dict(event) for event in self.runner.list_job_events(job_id)]
        return self._safe(
            {"job": job.to_dict(), "stages": stages, "events": events},
            secret_names=self._job_secret_names(job_id),
            secret_values=self._job_secret_values(job_id),
        )

    def _job_artifact_ids(self, job_id: str) -> tuple[ArtifactId, ...]:
        by_qualified: dict[str, ArtifactId] = {}
        for stage in self.ledger.list_stage_runs(job_id):
            for artifact_id in stage.output_artifact_ids:
                normalized = ArtifactId.from_dict(artifact_id)
                by_qualified[normalized.qualified] = normalized
        return tuple(by_qualified[key] for key in sorted(by_qualified))

    def _known_job_ids(self) -> tuple[str, ...]:
        by_id: dict[str, str] = {job_id: job_id for job_id in self._job_ids_by_creation}
        list_jobs = getattr(self.ledger, "list_jobs", None)
        if callable(list_jobs):
            for job in list_jobs():
                by_id[job.job_id] = job.job_id
        return tuple(by_id[key] for key in sorted(by_id))

    def _artifact_job_id(self, artifact_id: ArtifactId) -> str:
        qualified = artifact_id.qualified
        for job_id in self._known_job_ids():
            try:
                if any(candidate.qualified == qualified for candidate in self._job_artifact_ids(job_id)):
                    return job_id
            except KeyError:
                continue
        return ""

    def _all_known_artifact_ids(self) -> tuple[ArtifactId, ...]:
        list_artifacts = getattr(self.ledger, "list_artifacts", None)
        if callable(list_artifacts):
            return tuple(artifact.artifact_id for artifact in list_artifacts())

        by_qualified: dict[str, ArtifactId] = {}
        for job_id in self._job_ids_by_creation:
            try:
                for artifact_id in self._job_artifact_ids(job_id):
                    by_qualified[artifact_id.qualified] = artifact_id
            except KeyError:
                continue
        return tuple(by_qualified[key] for key in sorted(by_qualified))

    def _ledger_text_search(self, *, query: str, collection_name: str, limit: int) -> dict[str, Any]:
        terms = _search_terms(query)
        hits: list[dict[str, Any]] = []
        for artifact_id in self._all_known_artifact_ids():
            artifact = self.ledger.get_artifact(artifact_id)
            if artifact.freshness != FreshnessState.CURRENT:
                continue
            artifact_collection = str(artifact.metadata.get("collection_name", "default") or "default")
            if artifact_collection != collection_name:
                continue
            path = self.ledger.get_artifact_path(artifact_id)
            job_id = self._artifact_job_id(artifact_id)
            text = "" if self._redaction_values_unavailable(job_id) else (_read_text_if_small(path) or "")
            artifact_ref = self._artifact_to_safe_dict(artifact, job_id)
            artifact_document = json.dumps(artifact_ref, sort_keys=True)
            searchable = f"{artifact_id.qualified}\n{text}\n{artifact_document}".lower()
            matched_terms = tuple(term for term in terms if term in searchable)
            if terms and not matched_terms:
                continue
            score = float(sum(searchable.count(term) for term in matched_terms) or 1)
            hit = {
                "chunk_id": artifact.artifact_id.qualified,
                "score": score,
                "text": _REDACTED if self._redaction_values_unavailable(job_id) else text[:500],
                "artifact_ref": artifact_ref,
                "evidence_refs": [],
                "payload": {
                    "collection_name": collection_name,
                    "artifact_id": artifact.artifact_id.qualified,
                    "artifact_freshness": artifact.freshness.value,
                    "matched_terms": list(matched_terms),
                },
            }
            if job_id:
                hit = self._safe(
                    hit,
                    secret_names=self._job_secret_names(job_id),
                    secret_values=self._job_secret_values(job_id),
                )
            hits.append(hit)
        hits.sort(key=lambda hit: (-float(hit["score"]), str(hit["chunk_id"])))
        return {
            "query": query,
            "collection_name": collection_name,
            "hits": hits[:limit],
            "search_state": "ledger_text_fallback",
        }

    def _secret_names_for_manifest(self, manifest: Any) -> tuple[str, ...]:
        names: set[str] = set()
        names.update(getattr(manifest, "required_secret_names", ()))
        names.update(declaration.name for declaration in getattr(manifest, "secret_declarations", ()))
        return tuple(sorted(str(name) for name in names if str(name).strip()))

    def _attach_job_secret_policy(self, plan: JobPlan, secret_names: Iterable[str]) -> JobPlan:
        names = set(_secret_names_from_metadata(plan.metadata))
        names.update(str(name) for name in secret_names if str(name).strip())
        if not names:
            return plan
        metadata = dict(plan.metadata)
        current_policy = metadata.get("secret_policy") if isinstance(metadata.get("secret_policy"), Mapping) else {}
        policy = dict(current_policy or {})
        policy["redacted"] = True
        policy["redaction_marker"] = _REDACTED
        policy["secret_names"] = sorted(set(_string_values(policy.get("secret_names", ()))) | names)
        metadata["secret_policy"] = policy
        return replace(plan, metadata=metadata)

    def _job_secret_names(self, job_id: str) -> tuple[str, ...]:
        names = set(self._job_secret_names_by_job_id.get(job_id, ()))
        plan = self._plans_by_job_id.get(job_id)
        if plan is not None:
            names.update(_secret_names_from_metadata(plan.metadata))
        existing_job = None
        try:
            existing_job = self.ledger.get_job(job_id)
        except KeyError:
            existing_job = None
        if existing_job is not None:
            names.update(_secret_names_from_metadata(existing_job.metadata))
        return tuple(sorted(str(name) for name in names if str(name).strip()))

    def _job_secret_values(self, job_id: str) -> tuple[str, ...]:
        names = self._job_secret_names(job_id)
        values = set(self._job_secret_values_by_job_id.get(job_id, ()))
        values.update(collect_secret_values(self._config, names))
        plan = self._plans_by_job_id.get(job_id)
        if plan is not None:
            values.update(collect_secret_values(plan.config, names))
        return tuple(sorted(values, key=len, reverse=True))

    def _known_job_secret_names(self) -> tuple[str, ...]:
        names: set[str] = set()
        for job_id in self._known_job_ids():
            names.update(self._job_secret_names(job_id))
        return tuple(sorted(names))

    def _known_job_secret_values(self) -> tuple[str, ...]:
        values: set[str] = set()
        for job_id in self._known_job_ids():
            values.update(self._job_secret_values(job_id))
        return tuple(sorted(values, key=len, reverse=True))

    def _redaction_values_unavailable(self, job_id: str) -> bool:
        return bool(job_id and self._job_secret_names(job_id) and not self._job_secret_values(job_id))

    def _artifact_to_safe_dict(self, artifact: Any, job_id: str) -> JsonObject:
        data = artifact.to_dict()
        if self._redaction_values_unavailable(job_id):
            data["uri"] = _REDACTED
            data["metadata"] = {"redaction_state": "secret_values_unavailable"}
            provenance = data.get("provenance")
            if isinstance(provenance, dict):
                redacted_provenance = dict(provenance)
                redacted_provenance["source_url"] = _REDACTED
                redacted_provenance["license_url"] = _REDACTED
                redacted_provenance["source_policy_notes"] = _REDACTED
                redacted_provenance["metadata"] = {"redaction_state": "secret_values_unavailable"}
                data["provenance"] = redacted_provenance
        return self._safe(
            data,
            secret_names=self._job_secret_names(job_id) if job_id else (),
            secret_values=self._job_secret_values(job_id) if job_id else (),
        )

    def _safe(
        self,
        payload: Any,
        *,
        secret_names: Iterable[str] = (),
        secret_values: Iterable[str] = (),
    ) -> JsonObject:
        all_secret_names = set(self.secret_names)
        all_secret_names.update(str(name) for name in secret_names if str(name).strip())
        all_secret_values = set(self.secret_values)
        all_secret_values.update(str(value) for value in secret_values if isinstance(value, str))
        safe = redact_secrets(
            payload,
            secret_names=tuple(sorted(all_secret_names)),
            secret_values=tuple(sorted(all_secret_values, key=len, reverse=True)),
        )
        if not isinstance(safe, dict):
            raise ContractValidationError("control-plane response must be a JSON object")
        return safe


def create_fixture_control_plane(
    *,
    state_root: str | Path,
    config: Mapping[str, Any] | None = None,
) -> FoundationControlPlane:
    """Return a self-contained control plane with a deterministic fixture tool.

    The fixture proves the Hermes/API/MCP seam by creating a real foundation job
    through ``JobRunner`` and registering its output artifact through the SQLite
    ledger. It deliberately avoids domain-specific video behavior.
    """

    root = Path(state_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    tool_registry, adapter_registry = fixture_registries()
    # Re-register fixture manifest with a required secret name so config/status
    # surfaces exercise the same redaction path real tools use.
    fixture_manifest = tool_registry.get("fixture-tool")
    tool_registry = ToolRegistry(
        (
            {
                **fixture_manifest.to_dict(),
                "required_secret_names": ["FIXTURE_TOKEN", "fixture_token"],
            },
        )
    )
    ledger = SQLiteArtifactLedger(root / "ledger.sqlite", artifact_root=root / "artifacts")
    runner = JobRunner(ledger)

    def fixture_job_factory(submission: JobSubmission) -> JobPlan:
        artifact_value = str(submission.inputs.get("artifact_id") or f"{submission.job_id}-report")
        _validate_safe_identifier(artifact_value, "inputs.artifact_id")
        artifact_id = ArtifactId(artifact_value, namespace="fixture")
        artifacts_dir = (root / "artifacts").resolve()

        def write_fixture_report(context: Any) -> StageExecutionResult:
            context.record_progress(0.25, message="writing fixture report")
            report_path = (artifacts_dir / f"{artifact_value}.md").resolve()
            if not report_path.is_relative_to(artifacts_dir):
                raise ContractValidationError("fixture artifact path escaped artifact root")
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                "# Fixture foundation report\n\n"
                "This fixture job proves the generic foundation control plane can create, "
                "poll, resume, search, and expose artifacts through API and MCP surfaces.\n",
                encoding="utf-8",
            )
            artifact = context.register_output(
                artifact_id,
                report_path,
                metadata={"collection_name": "fixture.reports", "fixture": True},
            )
            return StageExecutionResult(output_artifact_ids=(artifact.artifact_id,))

        return JobPlan(
            job_id=submission.job_id,
            tool_id=submission.tool_id,
            config=submission.config,
            metadata={"source": "fixture_control_plane"},
            stages=(
                StagePlan(
                    stage_id="write-fixture-report",
                    handler=write_fixture_report,
                    output_artifacts=(
                        ArtifactContract(artifact_id, "report.markdown", "report.v1"),
                    ),
                ),
            ),
        )

    return FoundationControlPlane(
        tool_registry=tool_registry,
        adapter_registry=adapter_registry,
        ledger=ledger,
        runner=runner,
        config=config or {},
        job_plan_factories={"fixture-tool": fixture_job_factory},
    )


def foundation_openapi_schema(control_plane: FoundationControlPlane | None = None) -> JsonObject:
    """Return a deterministic OpenAPI schema for the generic control surface."""

    job_id_parameter = _path_parameter("job_id", "Foundation job identifier")
    artifact_id_parameter = _path_parameter(
        "artifact_id", "Qualified artifact id, for example fixture:fixture-job-report"
    )
    paths = {
        "/tools": {"get": _operation("listTools", "List registered tools and capabilities")},
        "/jobs": {
            "post": _operation(
                "createJob",
                "Create a tool-neutral foundation job",
                request_body_ref="#/components/schemas/JobCreateRequest",
            )
        },
        "/jobs/{job_id}": {
            "get": _operation("getJob", "Poll a foundation job", parameters=(job_id_parameter,))
        },
        "/jobs/{job_id}/resume": {
            "post": _operation(
                "resumeJob", "Resume a failed or stale job", parameters=(job_id_parameter,)
            )
        },
        "/jobs/{job_id}/cancel": {
            "post": _operation(
                "cancelJob",
                "Request cooperative job cancellation",
                parameters=(job_id_parameter,),
                request_body_ref="#/components/schemas/CancelJobRequest",
            )
        },
        "/jobs/{job_id}/artifacts": {
            "get": _operation(
                "listJobArtifacts", "List artifacts emitted by a job", parameters=(job_id_parameter,)
            )
        },
        "/artifacts/{artifact_id}": {
            "get": _operation(
                "getArtifact",
                "Read canonical artifact metadata",
                parameters=(
                    artifact_id_parameter,
                    _query_parameter("include_content", "Include small text artifact content", "boolean"),
                ),
            )
        },
        "/search": {
            "post": _operation(
                "search",
                "Run cited retrieval/search",
                request_body_ref="#/components/schemas/SearchRequest",
            )
        },
        "/answers": {
            "post": _operation(
                "answer",
                "Produce an answer with citations",
                request_body_ref="#/components/schemas/AnswerRequest",
            )
        },
        "/healthz": {"get": _operation("healthz", "Read service health")},
        "/config": {"get": _operation("config", "Read redacted service configuration/status")},
    }
    schema: dict[str, Any] = {
        "openapi": "3.1.0",
        "info": {
            "title": "AI Lab Foundation Control Plane",
            "version": CONTRACT_SCHEMA_VERSION,
            "description": "Generic tool/job/artifact/search API over brain_lab_core.",
        },
        "paths": paths,
        "components": {
            "schemas": {
                "JsonObject": {"type": "object", "additionalProperties": True},
                "JobCreateRequest": {
                    "type": "object",
                    "required": ["tool_id"],
                    "additionalProperties": False,
                    "properties": {
                        "tool_id": {"type": "string"},
                        "job_id": {"type": "string"},
                        "config": {"type": "object", "additionalProperties": True},
                        "inputs": {"type": "object", "additionalProperties": True},
                        "metadata": {"type": "object", "additionalProperties": True},
                    },
                },
                "CancelJobRequest": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"reason": {"type": "string"}},
                },
                "SearchRequest": {
                    "type": "object",
                    "required": ["query"],
                    "additionalProperties": True,
                    "properties": {
                        "query": {"type": "string"},
                        "collection_name": {"type": "string", "default": "default"},
                        "limit": {"type": "integer", "minimum": 1, "default": 10},
                    },
                },
                "AnswerRequest": {
                    "type": "object",
                    "required": ["question"],
                    "additionalProperties": True,
                    "properties": {
                        "question": {"type": "string"},
                        "collection_name": {"type": "string", "default": "default"},
                        "limit": {"type": "integer", "minimum": 1, "default": 5},
                    },
                },
            }
        },
    }
    if control_plane is not None:
        schema["x-brain-lab-healthz"] = control_plane.healthz()
    return redact_secrets(
        schema,
        secret_names=control_plane.secret_names if control_plane is not None else (),
        secret_values=control_plane.secret_values if control_plane is not None else (),
    )


def redact_secrets(
    value: Any,
    *,
    secret_names: Iterable[str] = (),
    secret_values: Iterable[str] = (),
) -> JsonValue:
    """Return a JSON-safe copy with secret-looking fields and known secret values redacted."""

    return _redact_secrets(value, secret_names=secret_names, secret_values=secret_values)


def _validate_safe_identifier(value: str, field_name: str) -> None:
    if value in {".", ".."} or not _SAFE_IDENTIFIER_PATTERN.fullmatch(value):
        raise ContractValidationError(
            f"{field_name} may contain only letters, numbers, dots, underscores, and hyphens"
        )


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ContractValidationError(f"{field_name} is required")
    return text


def _optional_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ContractValidationError(f"{field_name} must be a mapping")
    return value


def _secret_names_from_metadata(metadata: Mapping[str, Any]) -> tuple[str, ...]:
    names = set(_string_values(metadata.get("required_secret_names", ())))
    names.update(_string_values(metadata.get("secret_names", ())))
    policy = metadata.get("secret_policy")
    if isinstance(policy, Mapping):
        names.update(_string_values(policy.get("secret_names", ())))
    return tuple(sorted(names))


def _string_values(value: Any) -> tuple[str, ...]:
    if value is None or value == "":
        return ()
    if isinstance(value, str):
        raw_values = (value,)
    else:
        try:
            raw_values = tuple(value)
        except TypeError:
            raw_values = (value,)
    return tuple(dict.fromkeys(str(item).strip() for item in raw_values if str(item).strip()))


def _positive_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractValidationError(f"{field_name} must be an integer")
    if value < 1:
        raise ContractValidationError(f"{field_name} must be at least 1")
    return value


def _event_to_dict(event: Any) -> dict[str, Any]:
    return ObservabilityEvent.from_ledger_event(event).to_dict()


def _search_terms(query: str) -> tuple[str, ...]:
    """Return stable, low-noise terms for the dependency-free ledger fallback search."""

    terms: list[str] = []
    seen: set[str] = set()
    for term in re.findall(r"[\w.-]+", query.lower()):
        if len(term) < 2 or term in _SEARCH_STOPWORDS or term in seen:
            continue
        seen.add(term)
        terms.append(term)
    return tuple(terms)


def _citation_from_hit(hit: Mapping[str, Any]) -> dict[str, Any]:
    payload = hit.get("payload", {})
    artifact_ref = hit.get("artifact_ref", {})
    artifact_id: Any = None
    if isinstance(payload, Mapping):
        artifact_id = payload.get("artifact_id")
    if artifact_id is None and isinstance(artifact_ref, Mapping):
        artifact_id = artifact_ref.get("artifact_id")
    return {
        "artifact_id": ArtifactId.from_dict(artifact_id).qualified if artifact_id is not None else "",
        "quote": str(hit.get("text", "")),
        "score": hit.get("score", 0.0),
    }


def _read_text_if_small(path: Path, *, max_bytes: int = 64_000) -> str | None:
    try:
        if path.stat().st_size > max_bytes:
            return None
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _operation(
    operation_id: str,
    summary: str,
    *,
    parameters: Sequence[Mapping[str, Any]] = (),
    request_body_ref: str = "",
) -> dict[str, Any]:
    operation: dict[str, Any] = {
        "operationId": operation_id,
        "summary": summary,
        "responses": {
            "200": {
                "description": "JSON response",
                "content": {"application/json": {"schema": {"$ref": "#/components/schemas/JsonObject"}}},
            }
        },
    }
    if parameters:
        operation["parameters"] = [dict(parameter) for parameter in parameters]
    if request_body_ref:
        operation["requestBody"] = {
            "required": True,
            "content": {"application/json": {"schema": {"$ref": request_body_ref}}},
        }
    return operation


def _path_parameter(name: str, description: str) -> dict[str, Any]:
    return {
        "name": name,
        "in": "path",
        "required": True,
        "description": description,
        "schema": {"type": "string"},
    }


def _query_parameter(name: str, description: str, schema_type: str) -> dict[str, Any]:
    return {
        "name": name,
        "in": "query",
        "required": False,
        "description": description,
        "schema": {"type": schema_type},
    }
