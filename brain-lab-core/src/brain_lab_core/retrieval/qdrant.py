"""Qdrant-style evidence-aware retrieval facade.

The facade is intentionally dependency-free: concrete deployments can provide a
Qdrant client adapter behind :class:`VectorStoreBackend`, while tests and local
integration code can use :class:`InMemoryQdrantBackend`. SQLite/filesystem
artifacts remain canonical; vector payloads are derived read models that carry
artifact/evidence references back to the ledger.
"""
from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, ClassVar, Protocol

from brain_lab_core.contracts import (
    ArtifactRef,
    ContractValidationError,
    EvidenceRef,
    FreshnessState,
    ProviderCapability,
    ProviderSpec,
)
from brain_lab_core.contracts.base import (
    CONTRACT_SCHEMA_VERSION,
    JsonValue,
    _metadata,
    _positive_int,
    _required_text,
    _schema_version,
    _validate_contract_type,
    contract_header,
    load_json_object,
    to_json,
)

RETRIEVAL_CHUNK_CONTRACT_TYPE = "brain_lab.retrieval.chunk"
RETRIEVAL_INDEX_RESULT_CONTRACT_TYPE = "brain_lab.retrieval.index_result"
RETRIEVAL_HIT_CONTRACT_TYPE = "brain_lab.retrieval.hit"
RETRIEVAL_SEARCH_RESULT_CONTRACT_TYPE = "brain_lab.retrieval.search_result"
_RESERVED_PAYLOAD_KEYS = {
    "artifact_freshness",
    "artifact_id",
    "artifact_ref",
    "chunk_id",
    "contract_type",
    "evidence_refs",
    "metadata",
    "schema_version",
    "score",
    "text",
    "tool_fields",
}
_SUPPORTED_DISTANCE_METRICS = {"cosine"}
FreshnessResolver = Callable[[ArtifactRef], ArtifactRef | FreshnessState | str | Mapping[str, Any] | None]


class SearchFreshnessPolicy(str, Enum):
    """How retrieval search handles non-current artifacts."""

    CURRENT_ONLY = "current_only"
    INCLUDE_WITH_FLAGS = "include_with_flags"


class EmbeddingProvider(Protocol):
    """Minimal embedding provider protocol consumed by retrieval indexing/search."""

    provider_id: str
    dimension: int

    def embed_texts(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        """Return one embedding vector per input text."""


class VectorStoreBackend(Protocol):
    """Minimal Qdrant-like vector store boundary used by the facade."""

    def ensure_collection(
        self,
        collection_name: str,
        *,
        vector_size: int,
        distance: str = "cosine",
        metadata: Mapping[str, Any] | None = None,
        recreate: bool = False,
    ) -> None:
        """Create or validate a vector collection."""

    def count_points(
        self,
        collection_name: str,
        *,
        payload_filter: Mapping[str, Any] | None = None,
    ) -> int:
        """Count points matching a payload filter."""

    def upsert_points(self, collection_name: str, points: Sequence["QdrantPoint"]) -> None:
        """Insert or replace vector points."""

    def search_points(
        self,
        collection_name: str,
        query_vector: Sequence[float],
        *,
        limit: int,
        payload_filter: Mapping[str, Any] | None = None,
    ) -> tuple["QdrantScoredPoint", ...]:
        """Search vector points and return scored payloads."""


@dataclass(frozen=True)
class QdrantPoint:
    """Dependency-free representation of a Qdrant point."""

    point_id: str
    vector: Sequence[float]
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "point_id", _required_text(self.point_id, "qdrant_point.point_id"))
        object.__setattr__(self, "vector", _vector_tuple(self.vector, "qdrant_point.vector"))
        object.__setattr__(self, "payload", _metadata(self.payload))


@dataclass(frozen=True)
class QdrantScoredPoint:
    """Vector-store search result with a score and original payload."""

    point_id: str
    score: float
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "point_id", _required_text(self.point_id, "qdrant_point.point_id"))
        if isinstance(self.score, bool) or not isinstance(self.score, int | float) or not math.isfinite(float(self.score)):
            raise ContractValidationError("qdrant_scored_point.score must be a finite number")
        object.__setattr__(self, "score", float(self.score))
        object.__setattr__(self, "payload", _metadata(self.payload))


@dataclass(frozen=True)
class RetrievalChunk:
    """Text chunk payload indexed into Qdrant with canonical citations."""

    chunk_id: str
    text: str
    artifact_ref: ArtifactRef | Mapping[str, Any]
    evidence_refs: Iterable[EvidenceRef | Mapping[str, Any]] = field(default_factory=tuple)
    tool_fields: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = CONTRACT_SCHEMA_VERSION

    contract_type: ClassVar[str] = RETRIEVAL_CHUNK_CONTRACT_TYPE

    def __post_init__(self) -> None:
        object.__setattr__(self, "chunk_id", _required_text(self.chunk_id, "retrieval_chunk.chunk_id"))
        object.__setattr__(self, "text", _required_text(self.text, "retrieval_chunk.text"))
        object.__setattr__(self, "artifact_ref", ArtifactRef.from_dict(self.artifact_ref))
        object.__setattr__(
            self,
            "evidence_refs",
            _evidence_ref_tuple(self.evidence_refs, "retrieval_chunk.evidence_refs"),
        )
        object.__setattr__(self, "tool_fields", _tool_fields(self.tool_fields))
        object.__setattr__(self, "metadata", _metadata(self.metadata))
        object.__setattr__(self, "schema_version", _schema_version(self.schema_version))

    @property
    def freshness(self) -> FreshnessState:
        return self.artifact_ref.freshness

    def to_payload(self) -> dict[str, JsonValue]:
        """Return the Qdrant payload, including flat namespaced tool fields."""

        payload: dict[str, JsonValue] = {
            **contract_header(self.contract_type, self.schema_version),
            "chunk_id": self.chunk_id,
            "text": self.text,
            "artifact_id": self.artifact_ref.artifact_id.qualified,
            "artifact_freshness": self.artifact_ref.freshness.value,
            "artifact_ref": self.artifact_ref.to_dict(),
            "evidence_refs": [evidence_ref.to_dict() for evidence_ref in self.evidence_refs],
            "tool_fields": dict(self.tool_fields),
            "metadata": dict(self.metadata),
        }
        payload.update(self.tool_fields)
        return payload

    def to_dict(self) -> dict[str, JsonValue]:
        return self.to_payload()

    def to_json(self) -> str:
        return to_json(self.to_dict())

    @classmethod
    def from_json(cls, text: str) -> "RetrievalChunk":
        return cls.from_dict(load_json_object(text, cls.contract_type))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RetrievalChunk":
        return cls.from_payload(data)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "RetrievalChunk":
        if not isinstance(payload, Mapping):
            raise ContractValidationError("retrieval_chunk payload must be a mapping")
        _validate_contract_type(payload, RETRIEVAL_CHUNK_CONTRACT_TYPE)
        return cls(
            chunk_id=payload.get("chunk_id", ""),
            text=payload.get("text", ""),
            artifact_ref=ArtifactRef.from_dict(payload.get("artifact_ref")),
            evidence_refs=_evidence_ref_tuple(payload.get("evidence_refs", ()), "retrieval_chunk.evidence_refs"),
            tool_fields=_tool_fields_from_payload(payload),
            metadata=payload.get("metadata", {}),
            schema_version=payload.get("schema_version", CONTRACT_SCHEMA_VERSION),
        )


@dataclass(frozen=True)
class RetrievalIndexResult:
    """Summary returned after indexing chunks into a collection."""

    collection_name: str
    indexed_count: int
    collection_config: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = CONTRACT_SCHEMA_VERSION

    contract_type: ClassVar[str] = RETRIEVAL_INDEX_RESULT_CONTRACT_TYPE

    def __post_init__(self) -> None:
        object.__setattr__(self, "collection_name", _required_text(self.collection_name, "collection_name"))
        if isinstance(self.indexed_count, bool) or not isinstance(self.indexed_count, int) or self.indexed_count < 0:
            raise ContractValidationError("indexed_count must be a non-negative integer")
        object.__setattr__(self, "collection_config", _metadata(self.collection_config))
        object.__setattr__(self, "schema_version", _schema_version(self.schema_version))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            **contract_header(self.contract_type, self.schema_version),
            "collection_name": self.collection_name,
            "collection_config": dict(self.collection_config),
            "indexed_count": self.indexed_count,
        }

    def to_json(self) -> str:
        return to_json(self.to_dict())

    @classmethod
    def from_json(cls, text: str) -> "RetrievalIndexResult":
        return cls.from_dict(load_json_object(text, cls.contract_type))

    @classmethod
    def from_dict(cls, data: Any) -> "RetrievalIndexResult":
        if isinstance(data, RetrievalIndexResult):
            return data
        if not isinstance(data, Mapping):
            raise ContractValidationError("retrieval_index_result must be a mapping")
        _validate_contract_type(data, cls.contract_type)
        return cls(
            collection_name=data.get("collection_name", ""),
            indexed_count=data.get("indexed_count", -1),
            collection_config=data.get("collection_config", {}),
            schema_version=data.get("schema_version", CONTRACT_SCHEMA_VERSION),
        )


@dataclass(frozen=True)
class RetrievalHit:
    """Cited retrieval hit returned by the facade."""

    chunk_id: str
    score: float
    text: str
    artifact_ref: ArtifactRef | Mapping[str, Any]
    evidence_refs: Iterable[EvidenceRef | Mapping[str, Any]]
    tool_fields: Mapping[str, JsonValue]
    metadata: Mapping[str, JsonValue]
    payload: Mapping[str, JsonValue]
    schema_version: str = CONTRACT_SCHEMA_VERSION

    contract_type: ClassVar[str] = RETRIEVAL_HIT_CONTRACT_TYPE

    def __post_init__(self) -> None:
        object.__setattr__(self, "chunk_id", _required_text(self.chunk_id, "retrieval_hit.chunk_id"))
        if isinstance(self.score, bool) or not isinstance(self.score, int | float) or not math.isfinite(float(self.score)):
            raise ContractValidationError("retrieval_hit.score must be a finite number")
        object.__setattr__(self, "score", float(self.score))
        object.__setattr__(self, "text", _required_text(self.text, "retrieval_hit.text"))
        object.__setattr__(self, "artifact_ref", ArtifactRef.from_dict(self.artifact_ref))
        object.__setattr__(
            self,
            "evidence_refs",
            _evidence_ref_tuple(self.evidence_refs, "retrieval_hit.evidence_refs"),
        )
        object.__setattr__(self, "tool_fields", _tool_fields(self.tool_fields))
        object.__setattr__(self, "metadata", _metadata(self.metadata))
        object.__setattr__(self, "payload", _metadata(self.payload))
        object.__setattr__(self, "schema_version", _schema_version(self.schema_version))

    @property
    def freshness(self) -> FreshnessState:
        return self.artifact_ref.freshness

    @property
    def is_stale(self) -> bool:
        return self.freshness != FreshnessState.CURRENT

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            **contract_header(self.contract_type, self.schema_version),
            "chunk_id": self.chunk_id,
            "score": self.score,
            "text": self.text,
            "artifact_ref": self.artifact_ref.to_dict(),
            "evidence_refs": [evidence_ref.to_dict() for evidence_ref in self.evidence_refs],
            "tool_fields": dict(self.tool_fields),
            "metadata": dict(self.metadata),
            "payload": dict(self.payload),
        }

    def to_json(self) -> str:
        return to_json(self.to_dict())

    @classmethod
    def from_json(cls, text: str) -> "RetrievalHit":
        return cls.from_dict(load_json_object(text, cls.contract_type))

    @classmethod
    def from_dict(cls, data: Any) -> "RetrievalHit":
        if isinstance(data, RetrievalHit):
            return data
        if not isinstance(data, Mapping):
            raise ContractValidationError("retrieval_hit must be a mapping")
        _validate_contract_type(data, cls.contract_type)
        return cls(
            chunk_id=data.get("chunk_id", ""),
            score=data.get("score", float("nan")),
            text=data.get("text", ""),
            artifact_ref=ArtifactRef.from_dict(data.get("artifact_ref")),
            evidence_refs=_evidence_ref_tuple(data.get("evidence_refs", ()), "retrieval_hit.evidence_refs"),
            tool_fields=data.get("tool_fields", {}),
            metadata=data.get("metadata", {}),
            payload=data.get("payload", {}),
            schema_version=data.get("schema_version", CONTRACT_SCHEMA_VERSION),
        )

    @classmethod
    def from_scored_point(cls, point: QdrantScoredPoint) -> "RetrievalHit":
        chunk = RetrievalChunk.from_payload(point.payload)
        return cls(
            chunk_id=chunk.chunk_id,
            score=point.score,
            text=chunk.text,
            artifact_ref=chunk.artifact_ref,
            evidence_refs=chunk.evidence_refs,
            tool_fields=chunk.tool_fields,
            metadata=chunk.metadata,
            payload=point.payload,
        )


@dataclass(frozen=True)
class RetrievalSearchResult:
    """Search response containing cited, artifact-backed hits."""

    collection_name: str
    query_text: str
    hits: Iterable[RetrievalHit | Mapping[str, Any]]
    freshness_policy: SearchFreshnessPolicy | str = SearchFreshnessPolicy.CURRENT_ONLY
    schema_version: str = CONTRACT_SCHEMA_VERSION

    contract_type: ClassVar[str] = RETRIEVAL_SEARCH_RESULT_CONTRACT_TYPE

    def __post_init__(self) -> None:
        object.__setattr__(self, "collection_name", _required_text(self.collection_name, "collection_name"))
        object.__setattr__(self, "query_text", _required_text(self.query_text, "query_text"))
        object.__setattr__(self, "hits", tuple(_coerce_hit(hit) for hit in self.hits))
        object.__setattr__(
            self,
            "freshness_policy",
            _search_freshness_policy(self.freshness_policy),
        )
        object.__setattr__(self, "schema_version", _schema_version(self.schema_version))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            **contract_header(self.contract_type, self.schema_version),
            "collection_name": self.collection_name,
            "query_text": self.query_text,
            "hits": [hit.to_dict() for hit in self.hits],
            "freshness_policy": self.freshness_policy.value,
        }

    def to_json(self) -> str:
        return to_json(self.to_dict())

    @classmethod
    def from_json(cls, text: str) -> "RetrievalSearchResult":
        return cls.from_dict(load_json_object(text, cls.contract_type))

    @classmethod
    def from_dict(cls, data: Any) -> "RetrievalSearchResult":
        if isinstance(data, RetrievalSearchResult):
            return data
        if not isinstance(data, Mapping):
            raise ContractValidationError("retrieval_search_result must be a mapping")
        _validate_contract_type(data, cls.contract_type)
        return cls(
            collection_name=data.get("collection_name", ""),
            query_text=data.get("query_text", ""),
            hits=tuple(_coerce_hit(hit) for hit in data.get("hits", ())),
            freshness_policy=data.get("freshness_policy", SearchFreshnessPolicy.CURRENT_ONLY.value),
            schema_version=data.get("schema_version", CONTRACT_SCHEMA_VERSION),
        )


class DeterministicEmbeddingProvider:
    """Tiny deterministic embedding provider for fixtures and contract tests.

    This is not a semantic model. It is a stable token-hashing embedder that lets
    downstream tools verify the generic retrieval boundary without installing a
    third-party model dependency.
    """

    def __init__(self, *, provider_id: str = "deterministic-embedder", dimension: int = 32) -> None:
        self.provider_id = _required_text(provider_id, "embedding_provider.provider_id")
        self.dimension = _positive_int(dimension, "embedding_provider.dimension")

    def embed_texts(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        return tuple(self._embed(text) for text in texts)

    def _embed(self, text: str) -> tuple[float, ...]:
        tokens = re.findall(r"[a-z0-9]+", str(text).lower())
        vector = [0.0] * self.dimension
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            sign = -1.0 if digest[4] % 2 else 1.0
            vector[index] += sign
        return _normalize_vector(vector)


class InMemoryQdrantBackend:
    """In-memory Qdrant-like backend for tests and local fixture integrations."""

    def __init__(self) -> None:
        self._collections: dict[str, dict[str, Any]] = {}

    def ensure_collection(
        self,
        collection_name: str,
        *,
        vector_size: int,
        distance: str = "cosine",
        metadata: Mapping[str, Any] | None = None,
        recreate: bool = False,
    ) -> None:
        name = _required_text(collection_name, "collection_name")
        size = _positive_int(vector_size, "vector_size")
        metric = _required_text(distance, "distance")
        collection_metadata = _metadata(metadata or {})
        if metric not in _SUPPORTED_DISTANCE_METRICS:
            raise ContractValidationError(f"unsupported distance metric: {metric}")
        expected_config = {"vector_size": size, "distance": metric, "metadata": collection_metadata}
        if recreate or name not in self._collections:
            self._collections[name] = {
                "config": expected_config,
                "points": {},
            }
            return
        config = self._collections[name]["config"]
        if config != expected_config:
            raise ContractValidationError(
                f"collection {name!r} already exists with incompatible vector config"
            )

    def count_points(
        self,
        collection_name: str,
        *,
        payload_filter: Mapping[str, Any] | None = None,
    ) -> int:
        collection = self._collection(collection_name)
        normalized_filter = _metadata(payload_filter or {})
        return sum(
            1
            for point in collection["points"].values()
            if _matches_payload_filter(point.payload, normalized_filter)
        )

    def upsert_points(self, collection_name: str, points: Sequence[QdrantPoint]) -> None:
        collection = self._collection(collection_name)
        size = int(collection["config"]["vector_size"])
        stored = collection["points"]
        for point in points:
            normalized = QdrantPoint(point.point_id, point.vector, point.payload)
            if len(normalized.vector) != size:
                raise ContractValidationError(
                    f"point {normalized.point_id!r} vector dimension {len(normalized.vector)} does not match collection size {size}"
                )
            stored[normalized.point_id] = normalized

    def search_points(
        self,
        collection_name: str,
        query_vector: Sequence[float],
        *,
        limit: int,
        payload_filter: Mapping[str, Any] | None = None,
    ) -> tuple[QdrantScoredPoint, ...]:
        collection = self._collection(collection_name)
        max_hits = _positive_int(limit, "limit")
        vector = _vector_tuple(query_vector, "query_vector")
        size = int(collection["config"]["vector_size"])
        if len(vector) != size:
            raise ContractValidationError(
                f"query vector dimension {len(vector)} does not match collection size {size}"
            )
        scored: list[QdrantScoredPoint] = []
        normalized_filter = _metadata(payload_filter or {})
        for point in collection["points"].values():
            if not _matches_payload_filter(point.payload, normalized_filter):
                continue
            scored.append(
                QdrantScoredPoint(
                    point_id=point.point_id,
                    score=_cosine_similarity(vector, point.vector),
                    payload=point.payload,
                )
            )
        return tuple(sorted(scored, key=lambda hit: (-hit.score, hit.point_id))[:max_hits])

    def collection_exists(self, collection_name: str) -> bool:
        return collection_name in self._collections

    def collection_config(self, collection_name: str) -> dict[str, JsonValue]:
        return dict(self._collection(collection_name)["config"])

    def points(self, collection_name: str) -> tuple[QdrantPoint, ...]:
        return tuple(self._collection(collection_name)["points"].values())

    def _collection(self, collection_name: str) -> dict[str, Any]:
        name = _required_text(collection_name, "collection_name")
        try:
            return self._collections[name]
        except KeyError as exc:
            raise KeyError(name) from exc


class QdrantRetrievalFacade:
    """Evidence-aware retrieval facade over an injected Qdrant-like backend."""

    def __init__(
        self,
        *,
        vector_store: VectorStoreBackend,
        embedding_provider: EmbeddingProvider,
        distance: str = "cosine",
        freshness_resolver: FreshnessResolver | None = None,
    ) -> None:
        self.vector_store = vector_store
        self.embedding_provider = embedding_provider
        self.freshness_resolver = freshness_resolver
        self.distance = _required_text(distance, "distance")
        if self.distance not in _SUPPORTED_DISTANCE_METRICS:
            raise ContractValidationError(f"unsupported distance metric: {self.distance}")
        self.dimension = _positive_int(
            getattr(embedding_provider, "dimension", 0), "embedding_provider.dimension"
        )
        self.provider_id = _required_text(
            getattr(embedding_provider, "provider_id", ""), "embedding_provider.provider_id"
        )
        self.provider_version = str(getattr(embedding_provider, "provider_version", "") or "")

    def ensure_collection(self, collection_name: str, *, recreate: bool = False) -> None:
        self.vector_store.ensure_collection(
            _required_text(collection_name, "collection_name"),
            vector_size=self.dimension,
            distance=self.distance,
            metadata=self.collection_metadata(),
            recreate=recreate,
        )

    def collection_metadata(self) -> dict[str, JsonValue]:
        """Return metadata that must match before reusing an existing vector collection."""

        return {
            "distance": self.distance,
            "embedding_dimension": self.dimension,
            "embedding_provider_id": self.provider_id,
            "embedding_provider_version": self.provider_version,
            "payload_contract_schema_version": CONTRACT_SCHEMA_VERSION,
            "payload_contract_type": RETRIEVAL_CHUNK_CONTRACT_TYPE,
        }

    def index_chunks(
        self,
        collection_name: str,
        chunks: Iterable[RetrievalChunk | Mapping[str, Any]],
        *,
        recreate: bool = False,
    ) -> RetrievalIndexResult:
        name = _required_text(collection_name, "collection_name")
        normalized_chunks = tuple(_coerce_chunk(chunk) for chunk in chunks)
        self.ensure_collection(name, recreate=recreate)
        if not normalized_chunks:
            return RetrievalIndexResult(
                collection_name=name,
                indexed_count=0,
                collection_config=self.collection_metadata(),
            )
        vectors = self.embedding_provider.embed_texts(tuple(chunk.text for chunk in normalized_chunks))
        if len(vectors) != len(normalized_chunks):
            raise ContractValidationError("embedding provider must return one vector per chunk")
        points = tuple(
            QdrantPoint(chunk.chunk_id, _checked_dimension(vector, self.dimension), chunk.to_payload())
            for chunk, vector in zip(normalized_chunks, vectors, strict=True)
        )
        self.vector_store.upsert_points(name, points)
        return RetrievalIndexResult(
            collection_name=name,
            indexed_count=len(points),
            collection_config=self.collection_metadata(),
        )

    def search(
        self,
        collection_name: str,
        query_text: str,
        *,
        limit: int = 10,
        freshness_policy: SearchFreshnessPolicy | str = SearchFreshnessPolicy.CURRENT_ONLY,
        tool_filter: Mapping[str, Any] | None = None,
        freshness_resolver: FreshnessResolver | None = None,
        candidate_limit: int | None = None,
    ) -> RetrievalSearchResult:
        name = _required_text(collection_name, "collection_name")
        query = _required_text(query_text, "query_text")
        max_hits = _positive_int(limit, "limit")
        policy = _search_freshness_policy(freshness_policy)
        active_resolver = freshness_resolver or self.freshness_resolver
        payload_filter = _tool_fields(tool_filter or {})
        if policy == SearchFreshnessPolicy.CURRENT_ONLY and active_resolver is None:
            payload_filter = {**payload_filter, "artifact_freshness": FreshnessState.CURRENT.value}
        search_limit = max_hits
        if active_resolver is not None:
            if candidate_limit is None:
                search_limit = max(
                    max_hits,
                    self.vector_store.count_points(name, payload_filter=payload_filter or None),
                )
            else:
                search_limit = _positive_int(candidate_limit, "candidate_limit")
                if search_limit < max_hits:
                    raise ContractValidationError("candidate_limit must be greater than or equal to limit")
        query_vector = self.embedding_provider.embed_texts((query,))
        if len(query_vector) != 1:
            raise ContractValidationError("embedding provider must return exactly one query vector")
        scored = self.vector_store.search_points(
            name,
            _checked_dimension(query_vector[0], self.dimension),
            limit=search_limit,
            payload_filter=payload_filter or None,
        )
        hits = tuple(RetrievalHit.from_scored_point(point) for point in scored)
        if active_resolver is not None:
            hits = tuple(_resolve_hit_freshness(hit, active_resolver) for hit in hits)
        if policy == SearchFreshnessPolicy.CURRENT_ONLY:
            hits = tuple(hit for hit in hits if hit.freshness == FreshnessState.CURRENT)
        hits = hits[:max_hits]
        return RetrievalSearchResult(
            collection_name=name,
            query_text=query,
            hits=hits,
            freshness_policy=policy,
        )


def retrieval_embedding_provider_spec(
    *,
    provider_id: str,
    dimension: int,
    adapter_module: str = "",
    provider_version: str = "",
    capability_version: str = "v1",
    required_secret_names: Iterable[str] = (),
    metadata: Mapping[str, Any] | None = None,
) -> ProviderSpec:
    """Build an AdapterRegistry-compatible spec for a retrieval embedder."""

    dim = _positive_int(dimension, "dimension")
    capability = ProviderCapability(
        name="retrieval.embed",
        version=_required_text(capability_version, "capability_version"),
        input_artifact_types=("retrieval.chunk.text",),
        output_artifact_types=("retrieval.embedding",),
        metadata={"dimension": dim},
    )
    spec_metadata = dict(_metadata(metadata or {}))
    spec_metadata["embedding_dimension"] = dim
    return ProviderSpec(
        provider_id=provider_id,
        provider_type="embedding",
        provider_version=provider_version,
        adapter_module=adapter_module,
        required_secret_names=tuple(required_secret_names),
        capabilities=(capability,),
        metadata=spec_metadata,
    )


def sqlite_artifact_freshness_resolver(ledger: Any) -> FreshnessResolver:
    """Build a resolver that refreshes search hits from a SQLiteArtifactLedger-like object.

    The helper is duck-typed to keep retrieval service-free: the object only
    needs a ``get_artifact(artifact_id, *, missing_ok=True)``-compatible method.
    Missing canonical artifacts resolve to ``unknown`` so ``CURRENT_ONLY`` does
    not accidentally treat orphaned vector payloads as decision-grade evidence.
    """

    get_artifact = getattr(ledger, "get_artifact", None)
    if get_artifact is None or not callable(get_artifact):
        raise ContractValidationError("ledger must expose a callable get_artifact method")

    def resolve(artifact_ref: ArtifactRef) -> ArtifactRef | FreshnessState:
        try:
            current = get_artifact(artifact_ref.artifact_id, missing_ok=True)
        except TypeError:
            try:
                current = get_artifact(artifact_ref.artifact_id)
            except KeyError:
                current = None
        if current is None:
            return FreshnessState.UNKNOWN
        return ArtifactRef.from_dict(current)

    return resolve


def _coerce_chunk(chunk: RetrievalChunk | Mapping[str, Any]) -> RetrievalChunk:
    if isinstance(chunk, RetrievalChunk):
        return chunk
    return RetrievalChunk.from_payload(chunk)


def _coerce_hit(hit: RetrievalHit | Mapping[str, Any]) -> RetrievalHit:
    if isinstance(hit, RetrievalHit):
        return hit
    return RetrievalHit.from_dict(hit)


def _evidence_ref_tuple(values: Iterable[EvidenceRef | Mapping[str, Any]], field_name: str) -> tuple[EvidenceRef, ...]:
    if isinstance(values, str | bytes):
        raise ContractValidationError(f"{field_name} must be a sequence of evidence refs")
    try:
        raw_values = tuple(values)
    except TypeError as exc:
        raise ContractValidationError(f"{field_name} must be a sequence of evidence refs") from exc
    return tuple(EvidenceRef.from_dict(value) for value in raw_values)


def _resolve_hit_freshness(hit: RetrievalHit, resolver: FreshnessResolver) -> RetrievalHit:
    try:
        resolved = resolver(hit.artifact_ref)
    except ContractValidationError:
        raise
    except Exception as exc:  # pragma: no cover - exact backend exceptions are adapter-defined.
        raise ContractValidationError(
            f"freshness_resolver failed for artifact {hit.artifact_ref.artifact_id.qualified!r}"
        ) from exc
    if resolved is None:
        return hit
    artifact_ref = _resolved_artifact_ref(hit.artifact_ref, resolved)
    payload = dict(hit.payload)
    payload["artifact_id"] = artifact_ref.artifact_id.qualified
    payload["artifact_freshness"] = artifact_ref.freshness.value
    payload["artifact_ref"] = artifact_ref.to_dict()
    return RetrievalHit(
        chunk_id=hit.chunk_id,
        score=hit.score,
        text=hit.text,
        artifact_ref=artifact_ref,
        evidence_refs=hit.evidence_refs,
        tool_fields=hit.tool_fields,
        metadata=hit.metadata,
        payload=payload,
        schema_version=hit.schema_version,
    )


def _resolved_artifact_ref(
    existing: ArtifactRef,
    resolved: ArtifactRef | FreshnessState | str | Mapping[str, Any],
) -> ArtifactRef:
    if isinstance(resolved, ArtifactRef):
        return resolved
    if isinstance(resolved, Mapping):
        if "freshness" in resolved and "artifact_id" not in resolved:
            return replace(existing, freshness=_freshness_state(resolved["freshness"]))
        return ArtifactRef.from_dict(resolved)
    return replace(existing, freshness=_freshness_state(resolved))


def _freshness_state(value: FreshnessState | str) -> FreshnessState:
    try:
        return FreshnessState(value)
    except ValueError as exc:
        valid = ", ".join(state.value for state in FreshnessState)
        raise ContractValidationError(f"freshness must be one of: {valid}") from exc


def _search_freshness_policy(value: SearchFreshnessPolicy | str) -> SearchFreshnessPolicy:
    try:
        return SearchFreshnessPolicy(value)
    except ValueError as exc:
        valid = ", ".join(policy.value for policy in SearchFreshnessPolicy)
        raise ContractValidationError(f"freshness_policy must be one of: {valid}") from exc


def _tool_fields_from_payload(payload: Mapping[str, Any]) -> dict[str, JsonValue]:
    nested = _tool_fields(payload.get("tool_fields", {}))
    flat = _flat_tool_fields(payload)
    merged = dict(nested)
    for key, value in flat.items():
        if key in merged and merged[key] != value:
            raise ContractValidationError(
                f"tool field {key!r} differs between nested tool_fields and flat payload value"
            )
        merged[key] = value
    return merged


def _flat_tool_fields(payload: Mapping[str, Any]) -> dict[str, JsonValue]:
    flat: dict[str, Any] = {}
    for key, value in payload.items():
        if key in _RESERVED_PAYLOAD_KEYS:
            continue
        if "." in str(key) and not str(key).startswith(".") and not str(key).endswith("."):
            flat[str(key)] = value
    return _tool_fields(flat)


def _tool_fields(value: Mapping[str, Any]) -> dict[str, JsonValue]:
    fields = _metadata(value)
    for key in fields:
        if key in _RESERVED_PAYLOAD_KEYS:
            raise ContractValidationError(f"tool field {key!r} collides with reserved retrieval payload field")
        if "." not in key or key.startswith(".") or key.endswith("."):
            raise ContractValidationError(
                "tool-specific payload keys must be namespaced, for example 'video.t_start'"
            )
    return fields


def _vector_tuple(vector: Sequence[float], field_name: str) -> tuple[float, ...]:
    if isinstance(vector, str | bytes):
        raise ContractValidationError(f"{field_name} must be a sequence of finite numbers")
    try:
        values = tuple(vector)
    except TypeError as exc:
        raise ContractValidationError(f"{field_name} must be a sequence of finite numbers") from exc
    if not values:
        raise ContractValidationError(f"{field_name} must not be empty")
    normalized: list[float] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(float(value)):
            raise ContractValidationError(f"{field_name} must contain only finite numbers")
        normalized.append(float(value))
    return tuple(normalized)


def _checked_dimension(vector: Sequence[float], dimension: int) -> tuple[float, ...]:
    normalized = _vector_tuple(vector, "embedding")
    if len(normalized) != dimension:
        raise ContractValidationError(
            f"embedding dimension {len(normalized)} does not match provider dimension {dimension}"
        )
    return normalized


def _normalize_vector(vector: Sequence[float]) -> tuple[float, ...]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return tuple(float(value) for value in vector)
    return tuple(float(value) / norm for value in vector)


def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    left_vector = _vector_tuple(left, "left_vector")
    right_vector = _vector_tuple(right, "right_vector")
    if len(left_vector) != len(right_vector):
        raise ContractValidationError("cosine vectors must have equal dimensions")
    left_norm = math.sqrt(sum(value * value for value in left_vector))
    right_norm = math.sqrt(sum(value * value for value in right_vector))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return sum(a * b for a, b in zip(left_vector, right_vector, strict=True)) / (left_norm * right_norm)


def _matches_payload_filter(payload: Mapping[str, Any], payload_filter: Mapping[str, Any]) -> bool:
    missing = object()
    for key, expected in payload_filter.items():
        observed = payload.get(key, missing)
        if not _matches_filter_value(observed, expected, missing):
            return False
    return True


def _matches_filter_value(observed: Any, expected: Any, missing: object) -> bool:
    if isinstance(expected, Mapping):
        if not expected:
            return observed == expected
        unsupported = set(expected) - {"eq", "exists", "gt", "gte", "in", "lt", "lte"}
        if unsupported:
            raise ContractValidationError(
                f"unsupported payload filter operator(s): {', '.join(sorted(str(op) for op in unsupported))}"
            )
        if "exists" in expected:
            should_exist = expected["exists"]
            if not isinstance(should_exist, bool):
                raise ContractValidationError("payload filter operator 'exists' must be boolean")
            exists = observed is not missing
            if exists != should_exist:
                return False
            if not should_exist and len(expected) == 1:
                return True
        if observed is missing:
            return False
        if "eq" in expected and observed != expected["eq"]:
            return False
        if "in" in expected and not _matches_in_operator(observed, expected["in"]):
            return False
        for op, predicate in (
            ("gt", lambda left, right: left > right),
            ("gte", lambda left, right: left >= right),
            ("lt", lambda left, right: left < right),
            ("lte", lambda left, right: left <= right),
        ):
            if op in expected and not _matches_numeric_operator(observed, expected[op], op, predicate):
                return False
        return True
    if isinstance(expected, tuple | list | set | frozenset):
        return observed is not missing and observed in expected
    return observed is not missing and observed == expected


def _matches_in_operator(observed: Any, expected_values: Any) -> bool:
    if isinstance(expected_values, str | bytes) or not isinstance(expected_values, Iterable):
        raise ContractValidationError("payload filter operator 'in' must be a non-string iterable")
    return observed in tuple(expected_values)


def _matches_numeric_operator(
    observed: Any,
    expected: Any,
    operator: str,
    predicate: Callable[[float, float], bool],
) -> bool:
    if isinstance(observed, bool) or not isinstance(observed, int | float):
        return False
    if isinstance(expected, bool) or not isinstance(expected, int | float):
        raise ContractValidationError(f"payload filter operator {operator!r} must compare against a number")
    return predicate(float(observed), float(expected))


__all__ = [
    "DeterministicEmbeddingProvider",
    "EmbeddingProvider",
    "FreshnessResolver",
    "InMemoryQdrantBackend",
    "QdrantPoint",
    "QdrantRetrievalFacade",
    "QdrantScoredPoint",
    "RETRIEVAL_CHUNK_CONTRACT_TYPE",
    "RETRIEVAL_HIT_CONTRACT_TYPE",
    "RETRIEVAL_INDEX_RESULT_CONTRACT_TYPE",
    "RETRIEVAL_SEARCH_RESULT_CONTRACT_TYPE",
    "RetrievalChunk",
    "RetrievalHit",
    "RetrievalIndexResult",
    "RetrievalSearchResult",
    "SearchFreshnessPolicy",
    "VectorStoreBackend",
    "retrieval_embedding_provider_spec",
    "sqlite_artifact_freshness_resolver",
]
