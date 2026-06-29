"""Retrieval/indexing facade surface.

`brain_lab_core.retrieval` owns dependency-free contracts and protocols for
Qdrant-style vector retrieval. Concrete tools emit chunks/evidence refs; this
package owns collection management, embedding-provider boundaries, Qdrant point
payload shape, and cited search responses.
"""
from __future__ import annotations

from .qdrant import (
    RETRIEVAL_CHUNK_CONTRACT_TYPE,
    RETRIEVAL_HIT_CONTRACT_TYPE,
    RETRIEVAL_INDEX_RESULT_CONTRACT_TYPE,
    RETRIEVAL_SEARCH_RESULT_CONTRACT_TYPE,
    DeterministicEmbeddingProvider,
    EmbeddingProvider,
    FreshnessResolver,
    InMemoryQdrantBackend,
    QdrantPoint,
    QdrantRetrievalFacade,
    QdrantScoredPoint,
    RetrievalChunk,
    RetrievalHit,
    RetrievalIndexResult,
    RetrievalSearchResult,
    SearchFreshnessPolicy,
    VectorStoreBackend,
    retrieval_embedding_provider_spec,
    sqlite_artifact_freshness_resolver,
)

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
