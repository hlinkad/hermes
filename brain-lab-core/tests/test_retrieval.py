from __future__ import annotations

import json
import unittest

from brain_lab_core.contracts import (
    ArtifactId,
    ArtifactRef,
    Checksum,
    ContractValidationError,
    EvidenceRef,
    FreshnessState,
    Provenance,
    SourceSpan,
)
from brain_lab_core.registry import AdapterRegistry
from brain_lab_core.retrieval import (
    DeterministicEmbeddingProvider,
    InMemoryQdrantBackend,
    QdrantRetrievalFacade,
    RetrievalChunk,
    RetrievalHit,
    RetrievalIndexResult,
    RetrievalSearchResult,
    SearchFreshnessPolicy,
    retrieval_embedding_provider_spec,
    sqlite_artifact_freshness_resolver,
)


def _artifact(value: str, freshness: FreshnessState = FreshnessState.CURRENT) -> ArtifactRef:
    return ArtifactRef(
        artifact_id=ArtifactId(value, namespace="fixture"),
        artifact_type="retrieval.chunkset",
        artifact_schema_version="retrieval.chunkset.v1",
        uri=f"artifacts/{value}.jsonl",
        checksum=Checksum("sha256", "0" * 64),
        size_bytes=128,
        producer_tool_id="fixture-tool",
        producer_stage_id="chunk",
        freshness=freshness,
        provenance=Provenance(tool_id="fixture-tool", stage_id="chunk"),
    )


def _evidence(artifact: ArtifactRef, evidence_id: str = "ev-1") -> EvidenceRef:
    return EvidenceRef(
        evidence_id=evidence_id,
        source_artifact_id=artifact.artifact_id,
        source_type="transcript",
        span=SourceSpan(kind="time", start=12.0, end=18.5, unit="seconds"),
        quote="Qdrant retrieval should preserve evidence citations.",
        confidence=0.91,
        provenance=Provenance(tool_id="fixture-tool", stage_id="chunk"),
    )


class ConstantEmbeddingProvider:
    provider_id = "constant-test-embed"
    provider_version = "test"
    dimension = 2

    def embed_texts(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        return tuple((1.0, 0.0) for _ in texts)


class RetrievalFacadeTests(unittest.TestCase):
    def test_indexes_fixture_chunks_as_qdrant_points_with_citations_and_namespaced_payload(self) -> None:
        artifact = _artifact("chunkset-001")
        chunk = RetrievalChunk(
            chunk_id="chunk-001",
            text="Qdrant retrieval should preserve evidence citations for AI lab tools.",
            artifact_ref=artifact,
            evidence_refs=(_evidence(artifact),),
            tool_fields={"video.t_start": 12.0, "video.t_end": 18.5},
            metadata={"chunk_kind": "semantic"},
        )
        backend = InMemoryQdrantBackend()
        facade = QdrantRetrievalFacade(
            vector_store=backend,
            embedding_provider=DeterministicEmbeddingProvider(provider_id="fixture-embed", dimension=16),
        )

        result = facade.index_chunks("foundation.chunks", (chunk,), recreate=True)
        stored_points = backend.points("foundation.chunks")
        search = facade.search("foundation.chunks", "evidence citations retrieval", limit=3)

        self.assertEqual(result.collection_name, "foundation.chunks")
        self.assertEqual(result.indexed_count, 1)
        self.assertTrue(backend.collection_exists("foundation.chunks"))
        self.assertEqual(backend.collection_config("foundation.chunks")["vector_size"], 16)
        self.assertEqual(len(stored_points), 1)
        payload = stored_points[0].payload
        json.dumps(payload, sort_keys=True)
        self.assertEqual(payload["contract_type"], "brain_lab.retrieval.chunk")
        self.assertEqual(payload["artifact_id"], "fixture:chunkset-001")
        self.assertEqual(payload["artifact_freshness"], "current")
        self.assertEqual(payload["evidence_refs"][0]["evidence_id"], "ev-1")
        self.assertEqual(payload["tool_fields"], {"video.t_end": 18.5, "video.t_start": 12.0})
        self.assertEqual(payload["video.t_start"], 12.0)
        self.assertEqual(search.hits[0].chunk_id, "chunk-001")
        self.assertEqual(search.hits[0].artifact_ref.artifact_id.qualified, "fixture:chunkset-001")
        self.assertEqual(search.hits[0].evidence_refs[0].evidence_id, "ev-1")
        self.assertFalse(search.hits[0].is_stale)

    def test_default_search_excludes_stale_and_superseded_but_can_include_with_flags(self) -> None:
        current = _artifact("current", FreshnessState.CURRENT)
        stale = _artifact("stale", FreshnessState.STALE)
        superseded = _artifact("superseded", FreshnessState.SUPERSEDED)
        chunks = (
            RetrievalChunk("current-chunk", "shared retrieval citations", current, (_evidence(current, "ev-current"),)),
            RetrievalChunk("stale-chunk", "shared retrieval citations", stale, (_evidence(stale, "ev-stale"),)),
            RetrievalChunk(
                "superseded-chunk",
                "shared retrieval citations",
                superseded,
                (_evidence(superseded, "ev-superseded"),),
            ),
        )
        facade = QdrantRetrievalFacade(
            vector_store=InMemoryQdrantBackend(),
            embedding_provider=DeterministicEmbeddingProvider(provider_id="fixture-embed", dimension=8),
        )
        facade.index_chunks("foundation.chunks", chunks, recreate=True)

        default_result = facade.search("foundation.chunks", "shared retrieval", limit=10)
        flagged_result = facade.search(
            "foundation.chunks",
            "shared retrieval",
            limit=10,
            freshness_policy=SearchFreshnessPolicy.INCLUDE_WITH_FLAGS,
        )

        self.assertEqual([hit.chunk_id for hit in default_result.hits], ["current-chunk"])
        by_id = {hit.chunk_id: hit for hit in flagged_result.hits}
        self.assertEqual(set(by_id), {"current-chunk", "stale-chunk", "superseded-chunk"})
        self.assertFalse(by_id["current-chunk"].is_stale)
        self.assertTrue(by_id["stale-chunk"].is_stale)
        self.assertTrue(by_id["superseded-chunk"].is_stale)
        self.assertEqual(by_id["stale-chunk"].freshness, FreshnessState.STALE)
        self.assertEqual(by_id["superseded-chunk"].freshness, FreshnessState.SUPERSEDED)

    def test_search_can_resolve_freshness_from_canonical_ledger_and_filter_tool_fields(self) -> None:
        drifted = _artifact("drifted-now-stale", FreshnessState.CURRENT)
        current = _artifact("still-current", FreshnessState.CURRENT)
        unrelated = _artifact("other-tool-field", FreshnessState.CURRENT)
        facade = QdrantRetrievalFacade(
            vector_store=InMemoryQdrantBackend(),
            embedding_provider=DeterministicEmbeddingProvider(provider_id="fixture-embed", dimension=8),
        )
        facade.index_chunks(
            "foundation.chunks",
            (
                RetrievalChunk(
                    "drifted-chunk",
                    "shared canonical freshness retrieval",
                    drifted,
                    (_evidence(drifted, "ev-drifted"),),
                    tool_fields={"video.group": "wanted"},
                ),
                RetrievalChunk(
                    "fresh-chunk",
                    "shared canonical freshness retrieval",
                    current,
                    (_evidence(current, "ev-current"),),
                    tool_fields={"video.group": "wanted"},
                ),
                RetrievalChunk(
                    "unrelated-chunk",
                    "shared canonical freshness retrieval",
                    unrelated,
                    (_evidence(unrelated, "ev-unrelated"),),
                    tool_fields={"video.group": "other"},
                ),
            ),
            recreate=True,
        )

        def freshness_resolver(artifact_ref: ArtifactRef) -> FreshnessState | None:
            if artifact_ref.artifact_id.value == "drifted-now-stale":
                return FreshnessState.STALE
            return None

        current_only = facade.search(
            "foundation.chunks",
            "canonical freshness retrieval",
            limit=2,
            tool_filter={"video.group": "wanted"},
            freshness_resolver=freshness_resolver,
        )
        flagged = facade.search(
            "foundation.chunks",
            "canonical freshness retrieval",
            limit=10,
            freshness_policy=SearchFreshnessPolicy.INCLUDE_WITH_FLAGS,
            tool_filter={"video.group": "wanted"},
            freshness_resolver=freshness_resolver,
        )

        self.assertEqual([hit.chunk_id for hit in current_only.hits], ["fresh-chunk"])
        flagged_by_id = {hit.chunk_id: hit for hit in flagged.hits}
        self.assertEqual(set(flagged_by_id), {"drifted-chunk", "fresh-chunk"})
        self.assertTrue(flagged_by_id["drifted-chunk"].is_stale)
        self.assertEqual(flagged_by_id["drifted-chunk"].payload["artifact_freshness"], "stale")
        self.assertEqual(flagged_by_id["fresh-chunk"].tool_fields["video.group"], "wanted")

    def test_canonical_freshness_resolution_scans_past_stale_high_ranked_candidates(self) -> None:
        stale_chunks = []
        for index in range(6):
            artifact = _artifact(f"stale-{index}", FreshnessState.CURRENT)
            stale_chunks.append(
                RetrievalChunk(
                    f"a-stale-{index}",
                    "identical query text",
                    artifact,
                    (_evidence(artifact, f"ev-stale-{index}"),),
                )
            )
        current = _artifact("current-after-stale", FreshnessState.CURRENT)
        chunks = tuple(stale_chunks) + (
            RetrievalChunk(
                "z-current",
                "identical query text",
                current,
                (_evidence(current, "ev-current-after-stale"),),
            ),
        )
        facade = QdrantRetrievalFacade(
            vector_store=InMemoryQdrantBackend(),
            embedding_provider=ConstantEmbeddingProvider(),
        )
        facade.index_chunks("foundation.chunks", chunks, recreate=True)

        def freshness_resolver(artifact_ref: ArtifactRef) -> FreshnessState:
            if artifact_ref.artifact_id.value.startswith("stale-"):
                return FreshnessState.STALE
            return FreshnessState.CURRENT

        current_only = facade.search(
            "foundation.chunks",
            "identical query text",
            limit=1,
            freshness_resolver=freshness_resolver,
        )

        self.assertEqual([hit.chunk_id for hit in current_only.hits], ["z-current"])

    def test_sqlite_artifact_freshness_resolver_uses_canonical_ledger_rows(self) -> None:
        indexed_ref = _artifact("canonical-drift", FreshnessState.CURRENT)
        canonical_ref = _artifact("canonical-drift", FreshnessState.STALE)

        class FakeLedger:
            def get_artifact(self, artifact_id: ArtifactId, *, missing_ok: bool = False) -> ArtifactRef | None:
                if artifact_id == indexed_ref.artifact_id:
                    return canonical_ref
                if missing_ok:
                    return None
                raise KeyError(artifact_id.qualified)

        resolver = sqlite_artifact_freshness_resolver(FakeLedger())

        self.assertEqual(resolver(indexed_ref), canonical_ref)
        self.assertEqual(resolver(_artifact("missing")), FreshnessState.UNKNOWN)
        with self.assertRaisesRegex(ContractValidationError, "get_artifact"):
            sqlite_artifact_freshness_resolver(object())

    def test_tool_specific_payload_filters_support_ranges_and_existence(self) -> None:
        early = _artifact("early-video")
        later = _artifact("later-video")
        facade = QdrantRetrievalFacade(
            vector_store=InMemoryQdrantBackend(),
            embedding_provider=DeterministicEmbeddingProvider(provider_id="video-fixture-embed", dimension=8),
        )
        facade.index_chunks(
            "video-intel.chunks",
            (
                RetrievalChunk(
                    "early",
                    "shared timestamp retrieval",
                    early,
                    (_evidence(early, "ev-early"),),
                    tool_fields={"video.t_start": 0.0, "video.t_end": 4.2, "video.kind": "scene"},
                ),
                RetrievalChunk(
                    "later",
                    "shared timestamp retrieval",
                    later,
                    (_evidence(later, "ev-later"),),
                    tool_fields={"video.t_start": 8.0, "video.t_end": 12.0, "video.kind": "scene"},
                ),
            ),
            recreate=True,
        )

        ranged = facade.search(
            "video-intel.chunks",
            "timestamp retrieval",
            limit=5,
            tool_filter={
                "video.kind": {"in": ["scene"]},
                "video.t_start": {"gte": 5.0},
                "video.t_end": {"lte": 12.0},
            },
        )
        missing_field = facade.search(
            "video-intel.chunks",
            "timestamp retrieval",
            limit=5,
            tool_filter={"video.frame_id": {"exists": False}},
        )

        self.assertEqual([hit.chunk_id for hit in ranged.hits], ["later"])
        self.assertEqual({hit.chunk_id for hit in missing_field.hits}, {"early", "later"})
        with self.assertRaisesRegex(ContractValidationError, "unsupported payload filter"):
            facade.search(
                "video-intel.chunks",
                "timestamp retrieval",
                limit=5,
                tool_filter={"video.t_start": {"between": [0.0, 1.0]}},
            )

    def test_payload_tool_fields_fall_back_to_flat_values_and_reject_mismatch(self) -> None:
        artifact = _artifact("payload-shape")
        chunk = RetrievalChunk(
            "payload-shape-chunk",
            "payload shape",
            artifact,
            (_evidence(artifact),),
            tool_fields={"video.group": "flat"},
        )
        flat_only_payload = chunk.to_payload()
        flat_only_payload.pop("tool_fields")
        mismatched_payload = chunk.to_payload()
        mismatched_payload["tool_fields"] = {"video.group": "nested"}

        self.assertEqual(RetrievalChunk.from_payload(flat_only_payload).tool_fields["video.group"], "flat")
        with self.assertRaisesRegex(ContractValidationError, "differs"):
            RetrievalChunk.from_payload(mismatched_payload)

    def test_collection_config_binds_embedding_provider_and_payload_contract(self) -> None:
        artifact = _artifact("collection-config")
        backend = InMemoryQdrantBackend()
        first = QdrantRetrievalFacade(
            vector_store=backend,
            embedding_provider=DeterministicEmbeddingProvider(provider_id="embed-a", dimension=8),
        )
        second = QdrantRetrievalFacade(
            vector_store=backend,
            embedding_provider=DeterministicEmbeddingProvider(provider_id="embed-b", dimension=8),
        )
        index_result = first.index_chunks(
            "foundation.chunks",
            (RetrievalChunk("config-chunk", "collection config", artifact, (_evidence(artifact),)),),
            recreate=True,
        )

        self.assertEqual(index_result.collection_config["embedding_provider_id"], "embed-a")
        self.assertEqual(
            backend.collection_config("foundation.chunks")["metadata"]["payload_contract_type"],
            "brain_lab.retrieval.chunk",
        )
        with self.assertRaisesRegex(ContractValidationError, "incompatible vector config"):
            second.ensure_collection("foundation.chunks")

    def test_tool_specific_payload_keys_must_be_namespaced(self) -> None:
        artifact = _artifact("chunkset-001")

        with self.assertRaisesRegex(ContractValidationError, "namespaced"):
            RetrievalChunk(
                chunk_id="chunk-001",
                text="bad payload",
                artifact_ref=artifact,
                evidence_refs=(_evidence(artifact),),
                tool_fields={"t_start": 12.0},
            )
        with self.assertRaisesRegex(ContractValidationError, "reserved"):
            RetrievalChunk(
                chunk_id="chunk-001",
                text="bad payload",
                artifact_ref=artifact,
                evidence_refs=(_evidence(artifact),),
                tool_fields={"artifact_id": "collision"},
            )

    def test_embedding_provider_spec_registers_with_generic_adapter_registry(self) -> None:
        spec = retrieval_embedding_provider_spec(
            provider_id="fixture-embedder",
            dimension=32,
            adapter_module="fixture_retrieval.adapters:FixtureEmbedder",
            provider_version="0.1.0",
        )
        registry = AdapterRegistry([spec])
        discovery = registry.discovery_document()

        self.assertEqual(registry.providers_for_capability("retrieval.embed"), (spec,))
        self.assertEqual(spec.provider_type, "embedding")
        self.assertEqual(spec.capabilities[0].input_artifact_types, ("retrieval.chunk.text",))
        self.assertEqual(spec.capabilities[0].output_artifact_types, ("retrieval.embedding",))
        self.assertEqual(spec.capabilities[0].metadata["dimension"], 32)
        json.dumps(discovery, sort_keys=True)

    def test_retrieval_contracts_round_trip_through_deterministic_json(self) -> None:
        artifact = _artifact("round-trip")
        chunk = RetrievalChunk(
            chunk_id="round-trip-chunk",
            text="deterministic retrieval contract JSON",
            artifact_ref=artifact,
            evidence_refs=(_evidence(artifact, "ev-json"),),
            tool_fields={"video.t_start": 1.25},
            metadata={"purpose": "round-trip"},
        )
        facade = QdrantRetrievalFacade(
            vector_store=InMemoryQdrantBackend(),
            embedding_provider=DeterministicEmbeddingProvider(provider_id="fixture-embed", dimension=8),
        )
        index_result = facade.index_chunks("foundation.chunks", (chunk,), recreate=True)
        search_result = facade.search("foundation.chunks", "contract JSON", limit=1)
        hit = search_result.hits[0]

        self.assertEqual(RetrievalChunk.from_json(chunk.to_json()).to_dict(), chunk.to_dict())
        self.assertEqual(
            RetrievalIndexResult.from_json(index_result.to_json()).to_dict(),
            index_result.to_dict(),
        )
        self.assertEqual(RetrievalHit.from_json(hit.to_json()).to_dict(), hit.to_dict())
        self.assertEqual(
            RetrievalSearchResult.from_json(search_result.to_json()).to_dict(),
            search_result.to_dict(),
        )
        self.assertEqual(chunk.to_json(), RetrievalChunk.from_json(chunk.to_json()).to_json())

    def test_search_result_validates_nested_hits_and_policy(self) -> None:
        artifact = _artifact("invalid-hit")
        invalid_hit = {
            "contract_type": "brain_lab.retrieval.hit",
            "schema_version": "brain_lab.contracts.v1",
            "chunk_id": "bad-hit",
            "score": "not-a-number",
            "text": "invalid score",
            "artifact_ref": artifact.to_dict(),
            "evidence_refs": [_evidence(artifact).to_dict()],
            "tool_fields": {"video.t_start": 0.0},
            "metadata": {},
            "payload": {},
        }

        with self.assertRaisesRegex(ContractValidationError, "retrieval_hit.score"):
            RetrievalSearchResult("foundation.chunks", "query", (invalid_hit,))
        with self.assertRaisesRegex(ContractValidationError, "freshness_policy"):
            RetrievalSearchResult("foundation.chunks", "query", (), freshness_policy="maybe")

    def test_video_intel_can_call_generic_facade_without_owning_vector_store_code(self) -> None:
        artifact = _artifact("video-semantic-chunks")
        facade = QdrantRetrievalFacade(
            vector_store=InMemoryQdrantBackend(),
            embedding_provider=DeterministicEmbeddingProvider(provider_id="video-fixture-embed", dimension=12),
        )

        facade.index_chunks(
            "video-intel.chunks",
            (
                RetrievalChunk(
                    chunk_id="video-001:0001",
                    text="The architecture keeps vector storage in brain-lab-core.",
                    artifact_ref=artifact,
                    evidence_refs=(_evidence(artifact, "video-ev-1"),),
                    tool_fields={"video.t_start": 0.0, "video.t_end": 4.2},
                ),
            ),
            recreate=True,
        )
        result = facade.search("video-intel.chunks", "vector storage architecture", limit=1)

        self.assertEqual(result.collection_name, "video-intel.chunks")
        self.assertEqual(result.hits[0].chunk_id, "video-001:0001")
        self.assertEqual(result.hits[0].tool_fields["video.t_start"], 0.0)
        self.assertEqual(result.hits[0].evidence_refs[0].source_type, "transcript")


if __name__ == "__main__":
    unittest.main()
