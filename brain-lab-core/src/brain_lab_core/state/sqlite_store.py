"""SQLite-backed canonical artifact and state ledger."""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from brain_lab_core.contracts import (
    ArtifactId,
    ArtifactRef,
    ContractValidationError,
    EvidenceRef,
    FreshnessState,
    Job,
    Provenance,
    StageRun,
)

from .artifact_store import FilesystemArtifactStore
from .freshness import config_fingerprint as make_config_fingerprint
from .freshness import derivation_fingerprint, input_fingerprint

SCHEMA_VERSION = 1


class ArtifactConflictError(ContractValidationError):
    """Raised when an artifact ID is reused for different canonical payload."""


@dataclass(frozen=True)
class ArtifactRegistrationResult:
    """Result of registering a filesystem artifact."""

    artifact: ArtifactRef
    inserted: bool
    duplicate: bool = False
    stale_count: int = 0


@dataclass(frozen=True)
class LedgerEvent:
    """Append-only audit event from the state ledger."""

    event_id: int
    created_at: str
    entity_type: str
    entity_id: str
    event_type: str
    reason: str = ""
    payload: Mapping[str, Any] | None = None


class SQLiteArtifactLedger:
    """Canonical local SQLite source of truth for jobs, stages, artifacts, and evidence.

    The ledger keeps SQLite canonical and treats the filesystem as a measured
    payload read model. Registering the same artifact twice is a no-op; reusing
    an artifact ID for a different canonical payload raises ``ArtifactConflictError``.
    """

    def __init__(self, db_path: str | Path, *, artifact_root: str | Path | None = None) -> None:
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.artifact_store = FilesystemArtifactStore(artifact_root)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        try:
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._initialize_schema()
            self._conn.execute("PRAGMA journal_mode = WAL")
        except Exception:
            self._conn.close()
            raise

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "SQLiteArtifactLedger":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def register_artifact_from_file(
        self,
        *,
        artifact_id: ArtifactId | str | Mapping[str, Any],
        artifact_type: str,
        artifact_schema_version: str,
        file_path: str | Path,
        artifact_uri: str | None = None,
        producer_tool_id: str = "",
        producer_stage_id: str = "",
        input_artifact_ids: Iterable[ArtifactId | str | Mapping[str, Any]] = (),
        config: Any | None = None,
        config_fingerprint: str | None = None,
        provenance: Provenance | Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
        created_at: str | None = None,
        stale_existing_derivations: bool = True,
    ) -> ArtifactRegistrationResult:
        """Measure and register a filesystem payload as a canonical ArtifactRef."""

        normalized_id = ArtifactId.from_dict(artifact_id)
        normalized_inputs = _normalize_input_ids(input_artifact_ids)
        measured = self.artifact_store.describe(file_path, uri=artifact_uri)
        normalized_config_fingerprint = config_fingerprint or make_config_fingerprint(
            config if config is not None else {}
        )
        normalized_provenance = Provenance.from_dict(provenance if provenance is not None else {})
        created = created_at or _utc_now()
        derivation = derivation_fingerprint(
            producer_tool_id=producer_tool_id,
            producer_stage_id=producer_stage_id,
            input_artifact_ids=normalized_inputs,
            config_fingerprint_value=normalized_config_fingerprint,
            artifact_type=artifact_type,
            artifact_schema_version=artifact_schema_version,
        )
        artifact = ArtifactRef(
            artifact_id=normalized_id,
            artifact_type=artifact_type,
            artifact_schema_version=artifact_schema_version,
            uri=measured.uri,
            checksum=measured.checksum,
            size_bytes=measured.size_bytes,
            producer_tool_id=producer_tool_id,
            producer_stage_id=producer_stage_id,
            created_at=created,
            input_artifact_ids=normalized_inputs,
            config_fingerprint=normalized_config_fingerprint,
            freshness=FreshnessState.CURRENT,
            provenance=normalized_provenance,
            metadata=metadata if metadata is not None else {},
        )

        existing = self.get_artifact(normalized_id, missing_ok=True)
        stable = _stable_artifact_payload(
            artifact=artifact,
            file_path=measured.path,
            input_fingerprint_value=input_fingerprint(normalized_inputs),
            derivation_fingerprint_value=derivation,
        )
        if existing is not None:
            existing_row = self._artifact_row(normalized_id)
            assert existing_row is not None
            if _stable_payload_from_row(existing_row) != stable:
                raise ArtifactConflictError(
                    f"artifact {normalized_id.value!r} in namespace {normalized_id.namespace!r} already exists with different canonical payload"
                )
            return ArtifactRegistrationResult(artifact=existing, inserted=False, duplicate=True)

        stale_count = 0
        with self._conn:
            if stale_existing_derivations:
                stale_count = self._mark_previous_derivations_stale(
                    artifact=artifact,
                    input_fingerprint_value=input_fingerprint(normalized_inputs),
                    reason="producer/stage input or config fingerprint changed",
                )
            self._insert_artifact(
                artifact=artifact,
                file_path=measured.path,
                input_fingerprint_value=input_fingerprint(normalized_inputs),
                derivation_fingerprint_value=derivation,
            )
            self._record_event(
                entity_type="artifact",
                entity_id=normalized_id.qualified,
                event_type="artifact.registered",
                payload={
                    "artifact_type": artifact.artifact_type,
                    "uri": artifact.uri,
                    "checksum": artifact.checksum.to_dict(),
                    "size_bytes": artifact.size_bytes,
                },
            )
        return ArtifactRegistrationResult(artifact=artifact, inserted=True, duplicate=False, stale_count=stale_count)

    def get_artifact(
        self, artifact_id: ArtifactId | str | Mapping[str, Any], *, missing_ok: bool = False
    ) -> ArtifactRef | None:
        row = self._artifact_row(ArtifactId.from_dict(artifact_id))
        if row is None:
            if missing_ok:
                return None
            raise KeyError(ArtifactId.from_dict(artifact_id).qualified)
        return ArtifactRef.from_dict(_loads(row["contract_json"]))

    def get_artifact_path(self, artifact_id: ArtifactId | str | Mapping[str, Any]) -> Path:
        """Return the measured filesystem path stored with an artifact record."""

        normalized_id = ArtifactId.from_dict(artifact_id)
        row = self._artifact_row(normalized_id)
        if row is None:
            raise KeyError(normalized_id.qualified)
        return Path(row["file_path"])

    def artifact_count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS count FROM artifacts").fetchone()
        return int(row["count"])

    def mark_dependents_stale(
        self,
        changed_artifact_ids: Iterable[ArtifactId | str | Mapping[str, Any]],
        *,
        reason: str = "input artifact changed",
    ) -> int:
        """Mark current artifacts stale when they depend on any changed input."""

        queue = [artifact_id.qualified for artifact_id in _normalize_input_ids(changed_artifact_ids)]
        if not queue:
            return 0
        with self._conn:
            return self._mark_descendants_stale(queue, reason=reason)

    def supersede_artifact(
        self,
        artifact_id: ArtifactId | str | Mapping[str, Any],
        *,
        replacement_artifact_id: ArtifactId | str | Mapping[str, Any],
        reason: str = "artifact superseded",
    ) -> None:
        """Mark an artifact superseded while preserving its ledger row and events."""

        current = ArtifactId.from_dict(artifact_id)
        replacement = ArtifactId.from_dict(replacement_artifact_id)
        if current == replacement:
            raise ContractValidationError("replacement_artifact_id must differ from artifact_id")
        if self.get_artifact(replacement, missing_ok=True) is None:
            raise KeyError(replacement.qualified)
        with self._conn:
            changed = self._set_artifact_freshness(
                current.qualified,
                FreshnessState.SUPERSEDED,
                reason=reason,
                event_type="artifact.superseded",
                payload={"replacement_artifact_id": replacement.to_dict()},
            )
            if changed == 0:
                raise KeyError(current.qualified)
            self._mark_descendants_stale((current.qualified,), reason=reason)

    def upsert_job(self, job: Job | Mapping[str, Any]) -> None:
        normalized = Job.from_dict(job)
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO jobs (job_id, tool_id, state, created_at, config_fingerprint, contract_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                  tool_id=excluded.tool_id,
                  state=excluded.state,
                  created_at=excluded.created_at,
                  config_fingerprint=excluded.config_fingerprint,
                  contract_json=excluded.contract_json,
                  updated_at=excluded.updated_at
                """,
                (
                    normalized.job_id,
                    normalized.tool_id,
                    normalized.state.value,
                    normalized.created_at,
                    normalized.config_fingerprint,
                    normalized.to_json(),
                    _utc_now(),
                ),
            )
            self._record_event(
                entity_type="job",
                entity_id=normalized.job_id,
                event_type="job.upserted",
                payload={"state": normalized.state.value},
            )

    def get_job(self, job_id: str) -> Job:
        row = self._conn.execute("SELECT contract_json FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        return Job.from_dict(_loads(row["contract_json"]))

    def upsert_stage_run(self, job_id: str, stage_run: StageRun | Mapping[str, Any]) -> None:
        # Ensure the owning job exists; stages are append/update state under that job.
        self.get_job(job_id)
        normalized = StageRun.from_dict(stage_run)
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO stage_runs (job_id, stage_id, state, contract_json, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(job_id, stage_id) DO UPDATE SET
                  state=excluded.state,
                  contract_json=excluded.contract_json,
                  updated_at=excluded.updated_at
                """,
                (job_id, normalized.stage_id, normalized.state.value, normalized.to_json(), _utc_now()),
            )
            self._record_event(
                entity_type="stage_run",
                entity_id=f"{job_id}:{normalized.stage_id}",
                event_type="stage_run.upserted",
                payload={"state": normalized.state.value},
            )

    def list_stage_runs(self, job_id: str) -> tuple[StageRun, ...]:
        rows = self._conn.execute(
            "SELECT contract_json FROM stage_runs WHERE job_id = ? ORDER BY rowid", (job_id,)
        ).fetchall()
        return tuple(StageRun.from_dict(_loads(row["contract_json"])) for row in rows)

    def upsert_evidence_ref(self, evidence_ref: EvidenceRef | Mapping[str, Any]) -> None:
        normalized = EvidenceRef.from_dict(evidence_ref)
        if self.get_artifact(normalized.source_artifact_id, missing_ok=True) is None:
            raise KeyError(normalized.source_artifact_id.qualified)
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO evidence_refs (evidence_id, source_artifact_qualified_id, contract_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(evidence_id) DO UPDATE SET
                  source_artifact_qualified_id=excluded.source_artifact_qualified_id,
                  contract_json=excluded.contract_json,
                  updated_at=excluded.updated_at
                """,
                (
                    normalized.evidence_id,
                    normalized.source_artifact_id.qualified,
                    normalized.to_json(),
                    _utc_now(),
                ),
            )
            self._record_event(
                entity_type="evidence_ref",
                entity_id=normalized.evidence_id,
                event_type="evidence_ref.upserted",
                payload={"source_artifact_id": normalized.source_artifact_id.to_dict()},
            )

    def get_evidence_ref(self, evidence_id: str) -> EvidenceRef:
        row = self._conn.execute(
            "SELECT contract_json FROM evidence_refs WHERE evidence_id = ?", (evidence_id,)
        ).fetchone()
        if row is None:
            raise KeyError(evidence_id)
        return EvidenceRef.from_dict(_loads(row["contract_json"]))

    def list_events(self, *, entity_type: str | None = None, entity_id: str | None = None) -> tuple[LedgerEvent, ...]:
        clauses: list[str] = []
        args: list[Any] = []
        if entity_type is not None:
            clauses.append("entity_type = ?")
            args.append(entity_type)
        if entity_id is not None:
            clauses.append("entity_id = ?")
            args.append(entity_id)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = self._conn.execute(
            f"SELECT * FROM ledger_events{where} ORDER BY event_id", args
        ).fetchall()
        return tuple(
            LedgerEvent(
                event_id=int(row["event_id"]),
                created_at=row["created_at"],
                entity_type=row["entity_type"],
                entity_id=row["entity_id"],
                event_type=row["event_type"],
                reason=row["reason"] or "",
                payload=_loads(row["payload_json"]) if row["payload_json"] else {},
            )
            for row in rows
        )

    def export_schema_version_json(self) -> str:
        return json.dumps({"schema_version": self.schema_version()}, sort_keys=True, separators=(",", ":"))

    def schema_version(self) -> int:
        """Return the on-disk ledger schema version managed by migrations."""

        row = self._conn.execute("PRAGMA user_version").fetchone()
        version = int(row[0])
        if version:
            return version
        row = self._conn.execute("SELECT MAX(version) AS version FROM schema_migrations").fetchone()
        return int(row["version"] or 0)

    def _initialize_schema(self) -> None:
        user_version = int(self._conn.execute("PRAGMA user_version").fetchone()[0])
        if user_version > SCHEMA_VERSION:
            raise ContractValidationError(
                f"ledger schema version {user_version} is newer than supported version {SCHEMA_VERSION}"
            )
        if self._table_exists("schema_migrations"):
            row = self._conn.execute("SELECT MAX(version) AS version FROM schema_migrations").fetchone()
            migration_version = int(row["version"] or 0)
            if migration_version > SCHEMA_VERSION:
                raise ContractValidationError(
                    f"ledger migration version {migration_version} is newer than supported version {SCHEMA_VERSION}"
                )
        with self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                  version INTEGER PRIMARY KEY,
                  applied_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS artifacts (
                  artifact_qualified_id TEXT PRIMARY KEY,
                  namespace TEXT NOT NULL,
                  artifact_value TEXT NOT NULL,
                  artifact_type TEXT NOT NULL,
                  artifact_schema_version TEXT NOT NULL,
                  uri TEXT NOT NULL,
                  file_path TEXT NOT NULL,
                  checksum_algorithm TEXT NOT NULL,
                  checksum_value TEXT NOT NULL,
                  size_bytes INTEGER NOT NULL,
                  producer_tool_id TEXT NOT NULL,
                  producer_stage_id TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  input_artifact_ids_json TEXT NOT NULL,
                  input_fingerprint TEXT NOT NULL,
                  config_fingerprint TEXT NOT NULL,
                  derivation_fingerprint TEXT NOT NULL,
                  freshness TEXT NOT NULL,
                  stale_at TEXT NOT NULL DEFAULT '',
                  stale_reason TEXT NOT NULL DEFAULT '',
                  provenance_json TEXT NOT NULL,
                  metadata_json TEXT NOT NULL,
                  contract_json TEXT NOT NULL,
                  schema_version TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_artifacts_derivation
                  ON artifacts (producer_tool_id, producer_stage_id, artifact_type, artifact_schema_version, input_fingerprint, config_fingerprint, freshness);

                CREATE TABLE IF NOT EXISTS artifact_inputs (
                  artifact_qualified_id TEXT NOT NULL,
                  input_qualified_id TEXT NOT NULL,
                  PRIMARY KEY (artifact_qualified_id, input_qualified_id),
                  FOREIGN KEY (artifact_qualified_id) REFERENCES artifacts(artifact_qualified_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_artifact_inputs_input
                  ON artifact_inputs (input_qualified_id);

                CREATE TABLE IF NOT EXISTS jobs (
                  job_id TEXT PRIMARY KEY,
                  tool_id TEXT NOT NULL,
                  state TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  config_fingerprint TEXT NOT NULL,
                  contract_json TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS stage_runs (
                  job_id TEXT NOT NULL,
                  stage_id TEXT NOT NULL,
                  state TEXT NOT NULL,
                  contract_json TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  PRIMARY KEY (job_id, stage_id),
                  FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS evidence_refs (
                  evidence_id TEXT PRIMARY KEY,
                  source_artifact_qualified_id TEXT NOT NULL,
                  contract_json TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  FOREIGN KEY (source_artifact_qualified_id) REFERENCES artifacts(artifact_qualified_id) ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS ledger_events (
                  event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                  created_at TEXT NOT NULL,
                  entity_type TEXT NOT NULL,
                  entity_id TEXT NOT NULL,
                  event_type TEXT NOT NULL,
                  reason TEXT NOT NULL DEFAULT '',
                  payload_json TEXT NOT NULL DEFAULT '{}'
                );
                """
            )
            self._conn.execute(
                "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (SCHEMA_VERSION, _utc_now()),
            )
            self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def _table_exists(self, table_name: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table_name,)
        ).fetchone()
        return row is not None

    def _insert_artifact(
        self,
        *,
        artifact: ArtifactRef,
        file_path: Path,
        input_fingerprint_value: str,
        derivation_fingerprint_value: str,
    ) -> None:
        input_json = _dumps([artifact_id.to_dict() for artifact_id in artifact.input_artifact_ids])
        provenance_json = _dumps(artifact.provenance.to_dict())
        metadata_json = _dumps(dict(artifact.metadata))
        self._conn.execute(
            """
            INSERT INTO artifacts (
              artifact_qualified_id, namespace, artifact_value, artifact_type, artifact_schema_version,
              uri, file_path, checksum_algorithm, checksum_value, size_bytes,
              producer_tool_id, producer_stage_id, created_at, input_artifact_ids_json,
              input_fingerprint, config_fingerprint, derivation_fingerprint, freshness,
              provenance_json, metadata_json, contract_json, schema_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact.artifact_id.qualified,
                artifact.artifact_id.namespace,
                artifact.artifact_id.value,
                artifact.artifact_type,
                artifact.artifact_schema_version,
                artifact.uri,
                file_path.as_posix(),
                artifact.checksum.algorithm,
                artifact.checksum.value,
                artifact.size_bytes,
                artifact.producer_tool_id,
                artifact.producer_stage_id,
                artifact.created_at,
                input_json,
                input_fingerprint_value,
                artifact.config_fingerprint,
                derivation_fingerprint_value,
                artifact.freshness.value,
                provenance_json,
                metadata_json,
                artifact.to_json(),
                artifact.schema_version,
            ),
        )
        self._conn.executemany(
            "INSERT INTO artifact_inputs (artifact_qualified_id, input_qualified_id) VALUES (?, ?)",
            [(artifact.artifact_id.qualified, input_id.qualified) for input_id in artifact.input_artifact_ids],
        )

    def _mark_previous_derivations_stale(
        self,
        *,
        artifact: ArtifactRef,
        input_fingerprint_value: str,
        reason: str,
    ) -> int:
        if not artifact.producer_tool_id and not artifact.producer_stage_id:
            return 0
        rows = self._conn.execute(
            """
            SELECT artifact_qualified_id
            FROM artifacts
            WHERE producer_tool_id = ?
              AND producer_stage_id = ?
              AND (input_fingerprint != ? OR config_fingerprint != ?)
              AND freshness = ?
              AND artifact_qualified_id != ?
            """,
            (
                artifact.producer_tool_id,
                artifact.producer_stage_id,
                input_fingerprint_value,
                artifact.config_fingerprint,
                FreshnessState.CURRENT.value,
                artifact.artifact_id.qualified,
            ),
        ).fetchall()
        changed = 0
        changed_artifact_ids: list[str] = []
        for row in rows:
            artifact_qualified_id = row["artifact_qualified_id"]
            row_changed = self._set_artifact_freshness(
                artifact_qualified_id,
                FreshnessState.STALE,
                reason=reason,
                event_type="artifact.stale",
            )
            changed += row_changed
            if row_changed:
                changed_artifact_ids.append(artifact_qualified_id)
        changed += self._mark_descendants_stale(changed_artifact_ids, reason=reason)
        return changed

    def _mark_descendants_stale(self, changed_qualified_ids: Iterable[str], *, reason: str) -> int:
        queue = list(dict.fromkeys(changed_qualified_ids))
        changed = 0
        visited: set[str] = set()
        while queue:
            input_id = queue.pop(0)
            if input_id in visited:
                continue
            visited.add(input_id)
            rows = self._conn.execute(
                """
                SELECT DISTINCT a.artifact_qualified_id, a.freshness
                FROM artifacts a
                JOIN artifact_inputs i ON i.artifact_qualified_id = a.artifact_qualified_id
                WHERE i.input_qualified_id = ?
                """,
                (input_id,),
            ).fetchall()
            for row in rows:
                artifact_qualified_id = row["artifact_qualified_id"]
                if row["freshness"] == FreshnessState.CURRENT.value:
                    changed += self._set_artifact_freshness(
                        artifact_qualified_id,
                        FreshnessState.STALE,
                        reason=reason,
                        event_type="artifact.stale",
                    )
                queue.append(artifact_qualified_id)
        return changed

    def _set_artifact_freshness(
        self,
        artifact_qualified_id: str,
        freshness: FreshnessState,
        *,
        reason: str,
        event_type: str,
        payload: Mapping[str, Any] | None = None,
    ) -> int:
        row = self._conn.execute(
            "SELECT contract_json, freshness FROM artifacts WHERE artifact_qualified_id = ?",
            (artifact_qualified_id,),
        ).fetchone()
        if row is None:
            return 0
        if row["freshness"] == freshness.value:
            return 0
        artifact = ArtifactRef.from_dict(_loads(row["contract_json"]))
        now = _utc_now()
        updated = replace(artifact, freshness=freshness)
        self._conn.execute(
            """
            UPDATE artifacts
            SET freshness = ?, stale_at = ?, stale_reason = ?, contract_json = ?
            WHERE artifact_qualified_id = ?
            """,
            (freshness.value, now, reason, updated.to_json(), artifact_qualified_id),
        )
        self._record_event(
            entity_type="artifact",
            entity_id=artifact_qualified_id,
            event_type=event_type,
            reason=reason,
            payload=payload or {},
        )
        return 1

    def _artifact_row(self, artifact_id: ArtifactId) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM artifacts WHERE artifact_qualified_id = ?", (artifact_id.qualified,)
        ).fetchone()

    def _record_event(
        self,
        *,
        entity_type: str,
        entity_id: str,
        event_type: str,
        reason: str = "",
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO ledger_events (created_at, entity_type, entity_id, event_type, reason, payload_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (_utc_now(), entity_type, entity_id, event_type, reason, _dumps(payload or {})),
        )


def _normalize_input_ids(values: Iterable[ArtifactId | str | Mapping[str, Any]]) -> tuple[ArtifactId, ...]:
    """Normalize dependency IDs as a deterministic set for replay/idempotency."""

    if isinstance(values, str | bytes | ArtifactId) or isinstance(values, Mapping):
        raise ContractValidationError(
            "input_artifact_ids must be an iterable of artifact IDs; wrap a single input ID in a tuple"
        )
    normalized = tuple(ArtifactId.from_dict(value) for value in values)
    by_qualified = {artifact_id.qualified: artifact_id for artifact_id in normalized}
    return tuple(by_qualified[key] for key in sorted(by_qualified))


def _stable_artifact_payload(
    *,
    artifact: ArtifactRef,
    file_path: Path,
    input_fingerprint_value: str,
    derivation_fingerprint_value: str,
) -> dict[str, Any]:
    return {
        "namespace": artifact.artifact_id.namespace,
        "artifact_value": artifact.artifact_id.value,
        "artifact_type": artifact.artifact_type,
        "artifact_schema_version": artifact.artifact_schema_version,
        "uri": artifact.uri,
        "file_path": file_path.as_posix(),
        "checksum_algorithm": artifact.checksum.algorithm,
        "checksum_value": artifact.checksum.value,
        "size_bytes": artifact.size_bytes,
        "producer_tool_id": artifact.producer_tool_id,
        "producer_stage_id": artifact.producer_stage_id,
        "input_artifact_ids_json": _dumps([artifact_id.to_dict() for artifact_id in artifact.input_artifact_ids]),
        "input_fingerprint": input_fingerprint_value,
        "config_fingerprint": artifact.config_fingerprint,
        "derivation_fingerprint": derivation_fingerprint_value,
        "provenance_json": _dumps(artifact.provenance.to_dict()),
        "metadata_json": _dumps(dict(artifact.metadata)),
        "schema_version": artifact.schema_version,
    }


def _stable_payload_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "namespace": row["namespace"],
        "artifact_value": row["artifact_value"],
        "artifact_type": row["artifact_type"],
        "artifact_schema_version": row["artifact_schema_version"],
        "uri": row["uri"],
        "file_path": row["file_path"],
        "checksum_algorithm": row["checksum_algorithm"],
        "checksum_value": row["checksum_value"],
        "size_bytes": row["size_bytes"],
        "producer_tool_id": row["producer_tool_id"],
        "producer_stage_id": row["producer_stage_id"],
        "input_artifact_ids_json": row["input_artifact_ids_json"],
        "input_fingerprint": row["input_fingerprint"],
        "config_fingerprint": row["config_fingerprint"],
        "derivation_fingerprint": row["derivation_fingerprint"],
        "provenance_json": row["provenance_json"],
        "metadata_json": row["metadata_json"],
        "schema_version": row["schema_version"],
    }


def _dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _loads(value: str) -> Any:
    return json.loads(value)


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
