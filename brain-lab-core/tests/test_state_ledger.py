from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from brain_lab_core.contracts import (
    ArtifactId,
    ContractValidationError,
    EvidenceRef,
    FreshnessState,
    Job,
    LifecycleState,
    Provenance,
    SourceSpan,
    StageRun,
)
from brain_lab_core.state import (
    ArtifactConflictError,
    SQLiteArtifactLedger,
    config_fingerprint,
    input_fingerprint,
)


class SQLiteArtifactLedgerTests(unittest.TestCase):
    def test_register_file_artifact_calculates_checksum_size_and_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = root / "artifacts" / "report.md"
            payload.parent.mkdir()
            payload.write_text("hello foundation\n", encoding="utf-8")
            db_path = root / "state" / "ledger.sqlite"

            ledger = SQLiteArtifactLedger(db_path, artifact_root=root)
            result = ledger.register_artifact_from_file(
                artifact_id=ArtifactId("report-001", namespace="fixture"),
                artifact_type="report.markdown",
                artifact_schema_version="report.v1",
                file_path=payload,
                producer_tool_id="fixture-tool",
                producer_stage_id="summarize",
                input_artifact_ids=(ArtifactId("source-001", namespace="fixture"),),
                config={"temperature": 0, "model": "deterministic"},
                provenance=Provenance(tool_id="fixture-tool", stage_id="summarize"),
                metadata={"purpose": "unit-test"},
            )

            artifact = result.artifact
            self.assertTrue(result.inserted)
            self.assertFalse(result.duplicate)
            self.assertEqual(artifact.size_bytes, len(b"hello foundation\n"))
            self.assertEqual(
                artifact.checksum.value,
                hashlib.sha256(b"hello foundation\n").hexdigest(),
            )
            self.assertEqual(artifact.checksum.algorithm, "sha256")
            self.assertEqual(artifact.uri, "artifacts/report.md")
            self.assertEqual(ledger.get_artifact_path(artifact.artifact_id), payload.resolve())
            self.assertEqual(artifact.freshness, FreshnessState.CURRENT)
            self.assertEqual(artifact.producer_tool_id, "fixture-tool")
            self.assertEqual(artifact.producer_stage_id, "summarize")
            self.assertTrue(artifact.config_fingerprint.startswith("sha256:"))

            loaded = ledger.get_artifact(ArtifactId("report-001", namespace="fixture"))
            self.assertEqual(loaded, artifact)
            self.assertEqual(ledger.artifact_count(), 1)
            self.assertEqual([event.event_type for event in ledger.list_events()], ["artifact.registered"])

    def test_registering_same_artifact_twice_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = root / "artifact.json"
            payload.write_text('{"ok": true}\n', encoding="utf-8")
            ledger = SQLiteArtifactLedger(root / "ledger.sqlite", artifact_root=root)
            artifact_id = ArtifactId("artifact-001", namespace="fixture")

            first = ledger.register_artifact_from_file(
                artifact_id=artifact_id,
                artifact_type="fixture.json",
                artifact_schema_version="fixture.v1",
                file_path=payload,
                producer_tool_id="fixture-tool",
                producer_stage_id="extract",
                input_artifact_ids=(ArtifactId("b", namespace="fixture"), ArtifactId("a", namespace="fixture")),
                config={"revision": 1},
            )
            second = ledger.register_artifact_from_file(
                artifact_id=artifact_id,
                artifact_type="fixture.json",
                artifact_schema_version="fixture.v1",
                file_path=payload,
                producer_tool_id="fixture-tool",
                producer_stage_id="extract",
                input_artifact_ids=(ArtifactId("a", namespace="fixture"), ArtifactId("b", namespace="fixture")),
                config={"revision": 1},
            )

            self.assertTrue(first.inserted)
            self.assertTrue(second.duplicate)
            self.assertFalse(second.inserted)
            self.assertEqual(second.artifact, first.artifact)
            self.assertEqual([artifact_id.value for artifact_id in first.artifact.input_artifact_ids], ["a", "b"])
            self.assertEqual(ledger.artifact_count(), 1)
            self.assertEqual(len(ledger.list_events()), 1)

    def test_falsy_config_values_keep_distinct_fingerprints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = root / "artifact.json"
            payload.write_text('{"ok": true}\n', encoding="utf-8")
            ledger = SQLiteArtifactLedger(root / "ledger.sqlite", artifact_root=root)

            false_config = ledger.register_artifact_from_file(
                artifact_id=ArtifactId("false-config", namespace="fixture"),
                artifact_type="fixture.json",
                artifact_schema_version="fixture.v1",
                file_path=payload,
                config=False,
            ).artifact
            empty_dict_config = ledger.register_artifact_from_file(
                artifact_id=ArtifactId("empty-dict-config", namespace="fixture"),
                artifact_type="fixture.json",
                artifact_schema_version="fixture.v1",
                file_path=payload,
                config={},
            ).artifact

            self.assertEqual(false_config.config_fingerprint, config_fingerprint(False))
            self.assertEqual(empty_dict_config.config_fingerprint, config_fingerprint({}))
            self.assertNotEqual(false_config.config_fingerprint, empty_dict_config.config_fingerprint)

    def test_ambiguous_artifact_id_components_are_rejected(self) -> None:
        with self.assertRaisesRegex(ContractValidationError, "artifact_id.value"):
            ArtifactId("report:001", namespace="fixture")
        with self.assertRaisesRegex(ContractValidationError, "artifact_id.namespace"):
            ArtifactId("report-001", namespace="fixture:reports")
        with self.assertRaisesRegex(ContractValidationError, "artifact_id.value"):
            ArtifactId.from_dict("fixture:reports:001")

    def test_bare_input_artifact_id_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = root / "artifact.json"
            payload.write_text('{"ok": true}\n', encoding="utf-8")
            ledger = SQLiteArtifactLedger(root / "ledger.sqlite", artifact_root=root)

            with self.assertRaisesRegex(ContractValidationError, "input_artifact_ids"):
                ledger.register_artifact_from_file(
                    artifact_id=ArtifactId("artifact-001", namespace="fixture"),
                    artifact_type="fixture.json",
                    artifact_schema_version="fixture.v1",
                    file_path=payload,
                    input_artifact_ids="source-001",
                )
            with self.assertRaisesRegex(ContractValidationError, "input_artifact_ids"):
                ledger.mark_dependents_stale("source-001")
            with self.assertRaisesRegex(ContractValidationError, "input_artifact_ids"):
                input_fingerprint("source-001")

    def test_config_fingerprint_rejects_ambiguous_or_non_finite_values(self) -> None:
        with self.assertRaisesRegex(ContractValidationError, "collide"):
            config_fingerprint({1: "numeric", "1": "string"})
        with self.assertRaisesRegex(ContractValidationError, "finite"):
            config_fingerprint({"threshold": float("nan")})
        with self.assertRaisesRegex(ContractValidationError, "finite"):
            config_fingerprint({"threshold": float("inf")})

    def test_falsy_invalid_metadata_and_provenance_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = root / "artifact.json"
            payload.write_text('{"ok": true}\n', encoding="utf-8")
            ledger = SQLiteArtifactLedger(root / "ledger.sqlite", artifact_root=root)

            with self.assertRaisesRegex(ContractValidationError, "metadata"):
                ledger.register_artifact_from_file(
                    artifact_id=ArtifactId("bad-metadata", namespace="fixture"),
                    artifact_type="fixture.json",
                    artifact_schema_version="fixture.v1",
                    file_path=payload,
                    metadata=False,
                )
            with self.assertRaisesRegex(ContractValidationError, "provenance"):
                ledger.register_artifact_from_file(
                    artifact_id=ArtifactId("bad-provenance", namespace="fixture"),
                    artifact_type="fixture.json",
                    artifact_schema_version="fixture.v1",
                    file_path=payload,
                    provenance=False,
                )

    def test_same_artifact_id_with_different_payload_raises_domain_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = root / "artifact.txt"
            payload.write_text("version one\n", encoding="utf-8")
            ledger = SQLiteArtifactLedger(root / "ledger.sqlite", artifact_root=root)
            artifact_id = ArtifactId("artifact-001", namespace="fixture")
            original = ledger.register_artifact_from_file(
                artifact_id=artifact_id,
                artifact_type="fixture.text",
                artifact_schema_version="fixture.v1",
                file_path=payload,
            ).artifact

            payload.write_text("version two\n", encoding="utf-8")
            with self.assertRaisesRegex(ArtifactConflictError, "artifact-001"):
                ledger.register_artifact_from_file(
                    artifact_id=artifact_id,
                    artifact_type="fixture.text",
                    artifact_schema_version="fixture.v1",
                    file_path=payload,
                )

            self.assertEqual(ledger.get_artifact(artifact_id), original)
            self.assertEqual(ledger.artifact_count(), 1)

    def test_new_config_marks_previous_matching_outputs_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "source.txt"
            source_path.write_text("source\n", encoding="utf-8")
            report_v1 = root / "report-v1.md"
            report_v1.write_text("report one\n", encoding="utf-8")
            report_v2 = root / "report-v2.md"
            report_v2.write_text("report two\n", encoding="utf-8")
            summary_path = root / "summary.md"
            summary_path.write_text("summary from report one\n", encoding="utf-8")
            ledger = SQLiteArtifactLedger(root / "ledger.sqlite", artifact_root=root)
            source_id = ArtifactId("source-001", namespace="fixture")
            ledger.register_artifact_from_file(
                artifact_id=source_id,
                artifact_type="source.text",
                artifact_schema_version="source.v1",
                file_path=source_path,
            )

            first = ledger.register_artifact_from_file(
                artifact_id=ArtifactId("report-v1", namespace="fixture"),
                artifact_type="report.markdown",
                artifact_schema_version="report.v1",
                file_path=report_v1,
                producer_tool_id="fixture-tool",
                producer_stage_id="summarize",
                input_artifact_ids=(source_id,),
                config={"prompt": "v1"},
            ).artifact
            summary = ledger.register_artifact_from_file(
                artifact_id=ArtifactId("summary-v1", namespace="fixture"),
                artifact_type="summary.markdown",
                artifact_schema_version="summary.v1",
                file_path=summary_path,
                input_artifact_ids=(first.artifact_id,),
                config={"style": "brief"},
            ).artifact
            second = ledger.register_artifact_from_file(
                artifact_id=ArtifactId("report-v2", namespace="fixture"),
                artifact_type="report.markdown",
                artifact_schema_version="report.v1",
                file_path=report_v2,
                producer_tool_id="fixture-tool",
                producer_stage_id="summarize",
                input_artifact_ids=(source_id,),
                config={"prompt": "v2"},
            ).artifact

            self.assertEqual(
                ledger.get_artifact(first.artifact_id).freshness,
                FreshnessState.STALE,
            )
            self.assertEqual(
                ledger.get_artifact(second.artifact_id).freshness,
                FreshnessState.CURRENT,
            )
            self.assertEqual(
                ledger.get_artifact(summary.artifact_id).freshness,
                FreshnessState.STALE,
            )
            stale_events = [event for event in ledger.list_events() if event.event_type == "artifact.stale"]
            self.assertEqual(len(stale_events), 2)
            self.assertIn("input or config fingerprint changed", stale_events[0].reason)

    def test_new_input_set_marks_previous_stage_outputs_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = SQLiteArtifactLedger(root / "ledger.sqlite", artifact_root=root)
            source_one = ArtifactId("source-1", namespace="fixture")
            source_two = ArtifactId("source-2", namespace="fixture")
            for source_id in (source_one, source_two):
                path = root / f"{source_id.value}.txt"
                path.write_text(source_id.value, encoding="utf-8")
                ledger.register_artifact_from_file(
                    artifact_id=source_id,
                    artifact_type="source.text",
                    artifact_schema_version="source.v1",
                    file_path=path,
                )

            first_path = root / "report-source-1.md"
            first_path.write_text("from source one\n", encoding="utf-8")
            second_path = root / "report-source-2.md"
            second_path.write_text("from source two\n", encoding="utf-8")
            summary_path = root / "summary-source-1.md"
            summary_path.write_text("summary from source one\n", encoding="utf-8")
            first = ledger.register_artifact_from_file(
                artifact_id=ArtifactId("report-source-1", namespace="fixture"),
                artifact_type="report.markdown",
                artifact_schema_version="report.v1",
                file_path=first_path,
                producer_tool_id="fixture-tool",
                producer_stage_id="summarize",
                input_artifact_ids=(source_one,),
                config={"prompt": "same"},
            ).artifact
            summary = ledger.register_artifact_from_file(
                artifact_id=ArtifactId("summary-source-1", namespace="fixture"),
                artifact_type="summary.markdown",
                artifact_schema_version="summary.v1",
                file_path=summary_path,
                input_artifact_ids=(first.artifact_id,),
            ).artifact
            second = ledger.register_artifact_from_file(
                artifact_id=ArtifactId("report-source-2", namespace="fixture"),
                artifact_type="report.markdown",
                artifact_schema_version="report.v1",
                file_path=second_path,
                producer_tool_id="fixture-tool",
                producer_stage_id="summarize",
                input_artifact_ids=(source_two,),
                config={"prompt": "same"},
            ).artifact

            self.assertEqual(ledger.get_artifact(first.artifact_id).freshness, FreshnessState.STALE)
            self.assertEqual(ledger.get_artifact(summary.artifact_id).freshness, FreshnessState.STALE)
            self.assertEqual(ledger.get_artifact(second.artifact_id).freshness, FreshnessState.CURRENT)

    def test_config_change_stales_all_current_outputs_from_same_stage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = SQLiteArtifactLedger(root / "ledger.sqlite", artifact_root=root)
            source_id = ArtifactId("source-001", namespace="fixture")
            source_path = root / "source.txt"
            source_path.write_text("source\n", encoding="utf-8")
            ledger.register_artifact_from_file(
                artifact_id=source_id,
                artifact_type="source.text",
                artifact_schema_version="source.v1",
                file_path=source_path,
            )
            old_outputs = []
            for name, artifact_type in (("old-report", "report.markdown"), ("old-metrics", "metrics.json")):
                path = root / f"{name}.txt"
                path.write_text(name, encoding="utf-8")
                old_outputs.append(
                    ledger.register_artifact_from_file(
                        artifact_id=ArtifactId(name, namespace="fixture"),
                        artifact_type=artifact_type,
                        artifact_schema_version="artifact.v1",
                        file_path=path,
                        producer_tool_id="fixture-tool",
                        producer_stage_id="summarize",
                        input_artifact_ids=(source_id,),
                        config={"prompt": "v1"},
                    ).artifact
                )
            new_path = root / "new-report.txt"
            new_path.write_text("new", encoding="utf-8")
            new_output = ledger.register_artifact_from_file(
                artifact_id=ArtifactId("new-report", namespace="fixture"),
                artifact_type="report.markdown",
                artifact_schema_version="artifact.v1",
                file_path=new_path,
                producer_tool_id="fixture-tool",
                producer_stage_id="summarize",
                input_artifact_ids=(source_id,),
                config={"prompt": "v2"},
            ).artifact

            self.assertEqual(
                [ledger.get_artifact(output.artifact_id).freshness for output in old_outputs],
                [FreshnessState.STALE, FreshnessState.STALE],
            )
            self.assertEqual(ledger.get_artifact(new_output.artifact_id).freshness, FreshnessState.CURRENT)

    def test_changed_input_marks_dependent_artifacts_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "source.txt"
            source_path.write_text("source\n", encoding="utf-8")
            report_path = root / "report.md"
            report_path.write_text("report\n", encoding="utf-8")
            summary_path = root / "summary.md"
            summary_path.write_text("summary\n", encoding="utf-8")
            ledger = SQLiteArtifactLedger(root / "ledger.sqlite", artifact_root=root)
            source_id = ArtifactId("source-001", namespace="fixture")
            ledger.register_artifact_from_file(
                artifact_id=source_id,
                artifact_type="source.text",
                artifact_schema_version="source.v1",
                file_path=source_path,
            )
            report = ledger.register_artifact_from_file(
                artifact_id=ArtifactId("report-001", namespace="fixture"),
                artifact_type="report.markdown",
                artifact_schema_version="report.v1",
                file_path=report_path,
                input_artifact_ids=(source_id,),
                config={"prompt": "stable"},
            ).artifact
            summary = ledger.register_artifact_from_file(
                artifact_id=ArtifactId("summary-001", namespace="fixture"),
                artifact_type="summary.markdown",
                artifact_schema_version="summary.v1",
                file_path=summary_path,
                input_artifact_ids=(report.artifact_id,),
                config={"prompt": "stable"},
            ).artifact

            changed = ledger.mark_dependents_stale((source_id,), reason="source payload changed")

            self.assertEqual(changed, 2)
            self.assertEqual(ledger.get_artifact(report.artifact_id).freshness, FreshnessState.STALE)
            self.assertEqual(ledger.get_artifact(summary.artifact_id).freshness, FreshnessState.STALE)
            self.assertEqual(ledger.get_artifact(source_id).freshness, FreshnessState.CURRENT)

    def test_changed_input_propagates_through_already_stale_intermediates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = SQLiteArtifactLedger(root / "ledger.sqlite", artifact_root=root)
            source_path = root / "source.txt"
            source_path.write_text("source", encoding="utf-8")
            middle_path = root / "middle.txt"
            middle_path.write_text("middle", encoding="utf-8")
            final_path = root / "final.txt"
            final_path.write_text("final", encoding="utf-8")
            source = ArtifactId("source", namespace="fixture")
            source_artifact = ledger.register_artifact_from_file(
                artifact_id=source,
                artifact_type="source.text",
                artifact_schema_version="source.v1",
                file_path=source_path,
            ).artifact
            middle = ledger.register_artifact_from_file(
                artifact_id=ArtifactId("middle", namespace="fixture"),
                artifact_type="middle.text",
                artifact_schema_version="middle.v1",
                file_path=middle_path,
                input_artifact_ids=(source_artifact.artifact_id,),
            ).artifact
            self.assertEqual(ledger.mark_dependents_stale((source,), reason="first stale"), 1)
            final = ledger.register_artifact_from_file(
                artifact_id=ArtifactId("final", namespace="fixture"),
                artifact_type="final.text",
                artifact_schema_version="final.v1",
                file_path=final_path,
                input_artifact_ids=(middle.artifact_id,),
            ).artifact

            self.assertEqual(ledger.mark_dependents_stale((source,), reason="second stale"), 1)
            self.assertEqual(ledger.get_artifact(middle.artifact_id).freshness, FreshnessState.STALE)
            self.assertEqual(ledger.get_artifact(final.artifact_id).freshness, FreshnessState.STALE)

    def test_superseded_state_is_recorded_without_deleting_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_path = root / "old.md"
            old_path.write_text("old\n", encoding="utf-8")
            new_path = root / "new.md"
            new_path.write_text("new\n", encoding="utf-8")
            child_path = root / "child.md"
            child_path.write_text("child from old\n", encoding="utf-8")
            ledger = SQLiteArtifactLedger(root / "ledger.sqlite", artifact_root=root)
            old = ledger.register_artifact_from_file(
                artifact_id=ArtifactId("old", namespace="fixture"),
                artifact_type="report.markdown",
                artifact_schema_version="report.v1",
                file_path=old_path,
            ).artifact
            new = ledger.register_artifact_from_file(
                artifact_id=ArtifactId("new", namespace="fixture"),
                artifact_type="report.markdown",
                artifact_schema_version="report.v1",
                file_path=new_path,
            ).artifact
            child = ledger.register_artifact_from_file(
                artifact_id=ArtifactId("child", namespace="fixture"),
                artifact_type="summary.markdown",
                artifact_schema_version="summary.v1",
                file_path=child_path,
                input_artifact_ids=(old.artifact_id,),
            ).artifact

            ledger.supersede_artifact(old.artifact_id, replacement_artifact_id=new.artifact_id, reason="manual replacement")

            self.assertEqual(ledger.get_artifact(old.artifact_id).freshness, FreshnessState.SUPERSEDED)
            duplicate_old = ledger.register_artifact_from_file(
                artifact_id=old.artifact_id,
                artifact_type="report.markdown",
                artifact_schema_version="report.v1",
                file_path=old_path,
            )
            self.assertTrue(duplicate_old.duplicate)
            self.assertEqual(duplicate_old.artifact.freshness, FreshnessState.SUPERSEDED)
            self.assertEqual(ledger.get_artifact(old.artifact_id).freshness, FreshnessState.SUPERSEDED)
            self.assertEqual(ledger.get_artifact(new.artifact_id).freshness, FreshnessState.CURRENT)
            self.assertEqual(ledger.get_artifact(child.artifact_id).freshness, FreshnessState.STALE)
            self.assertEqual(ledger.artifact_count(), 3)
            self.assertIn("artifact.superseded", [event.event_type for event in ledger.list_events()])
            with self.assertRaisesRegex(ContractValidationError, "replacement_artifact_id"):
                ledger.supersede_artifact(new.artifact_id, replacement_artifact_id=new.artifact_id)

    def test_jobs_stage_runs_and_evidence_refs_round_trip_through_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = SQLiteArtifactLedger(root / "ledger.sqlite", artifact_root=root)
            source_id = ArtifactId("source-001", namespace="fixture")
            source_path = root / "source.txt"
            source_path.write_text("source", encoding="utf-8")
            ledger.register_artifact_from_file(
                artifact_id=source_id,
                artifact_type="source.text",
                artifact_schema_version="source.v1",
                file_path=source_path,
            )
            job = Job(
                job_id="job-001",
                tool_id="fixture-tool",
                state=LifecycleState.RUNNING,
                created_at="2026-06-29T12:00:00Z",
                input_artifact_ids=(source_id,),
                config_fingerprint=config_fingerprint({"mode": "test"}),
            )
            stage = StageRun(
                stage_id="extract",
                state=LifecycleState.COMPLETED,
                started_at="2026-06-29T12:00:01Z",
                completed_at="2026-06-29T12:00:02Z",
                output_artifact_ids=(ArtifactId("output-001", namespace="fixture"),),
                progress=1.0,
            )
            evidence = EvidenceRef(
                evidence_id="evidence-001",
                source_artifact_id=source_id,
                source_type="source.text",
                span=SourceSpan(kind="text", start=0, end=6),
                quote="source",
                confidence=1.0,
            )

            ledger.upsert_job(job)
            ledger.upsert_stage_run(job.job_id, stage)
            ledger.upsert_evidence_ref(evidence)

            loaded_job = ledger.get_job(job.job_id)
            self.assertEqual(loaded_job, job)
            self.assertEqual(ledger.list_stage_runs(job.job_id), (stage,))
            self.assertEqual(ledger.get_evidence_ref(evidence.evidence_id), evidence)
            self.assertEqual(json.loads(ledger.export_schema_version_json())["schema_version"], 1)
            self.assertEqual(ledger.schema_version(), 1)

    def test_evidence_refs_require_existing_source_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = SQLiteArtifactLedger(root / "ledger.sqlite", artifact_root=root)
            missing_source = ArtifactId("missing-source", namespace="fixture")
            evidence = EvidenceRef(
                evidence_id="evidence-missing",
                source_artifact_id=missing_source,
                source_type="source.text",
                quote="missing",
            )

            with self.assertRaisesRegex(KeyError, missing_source.qualified):
                ledger.upsert_evidence_ref(evidence)
            self.assertEqual(ledger._conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            with self.assertRaises(sqlite3.IntegrityError):
                ledger._conn.execute(
                    """
                    INSERT INTO evidence_refs (
                      evidence_id, source_artifact_qualified_id, contract_json, updated_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    ("direct-missing", missing_source.qualified, "{}", "2026-06-29T12:00:00Z"),
                )

    def test_future_schema_version_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "ledger.sqlite"
            with sqlite3.connect(db_path) as conn:
                conn.execute("PRAGMA user_version = 999")

            with self.assertRaisesRegex(ContractValidationError, "newer than supported"):
                SQLiteArtifactLedger(db_path)
            self.assertFalse(Path(f"{db_path}-wal").exists())
            self.assertFalse(Path(f"{db_path}-shm").exists())
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0], "delete")


if __name__ == "__main__":
    unittest.main()
