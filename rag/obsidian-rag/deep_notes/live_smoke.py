"""Live Qdrant smoke test for the Obsidian-aware Hermes Brain RAG path.

The smoke intentionally uses a temporary fixture vault and temporary Qdrant
collection by default. It proves the real ingestion/retrieval stack works without
mutating the user's live vault or persistent Hermes Brain collection.
"""

from __future__ import annotations

import argparse
import json
import secrets
import shutil
import sys
import tempfile
from contextlib import nullcontext, redirect_stdout
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from deep_notes.config import Settings, get_settings
from deep_notes.hermes_context import build_context_for_prompt
from deep_notes.ingest import run_ingest
from deep_notes.obsidian_core_adapter import OBSIDIAN_STRUCTURAL_METADATA_KEYS
from deep_notes.query import SourceChunk, retrieve

UNIQUE_PHRASE = "cobalt-lantern-walrus-DH223"
FIXTURE_RELATIVE_PATH = "wiki/dh223-live-smoke.md"
DEFAULT_COLLECTION_PREFIX = "dh223_obsidian_live_smoke"
RESERVED_COLLECTION_NAMES = {"hermes_brain"}
DEFAULT_NEGATIVE_QUERY = "unrelated payroll terraform banana outage"
DEFAULT_MIN_POSITIVE_SCORE = 0.45
DEFAULT_NEGATIVE_MAX_SCORE = 0.45


@dataclass(frozen=True)
class LiveSmokeReport:
    collection_name: str
    qdrant_url: str
    vault_path: str
    fixture_file: str
    docs_indexed: int
    qdrant_points: int
    positive_query: str
    positive_sources: list[dict[str, Any]]
    negative_query: str
    negative_top_score: float | None
    negative_context_injected: bool
    metadata_checks: dict[str, Any]
    cleanup_collection: bool
    cleanup_collection_verified: bool
    cleanup_vault: bool
    cleanup_vault_verified: bool
    remaining_feature_gates: list[str]

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2, sort_keys=True)


def create_fixture_vault(base_dir: Path, unique_phrase: str = UNIQUE_PHRASE) -> Path:
    """Create a minimal scoped Obsidian vault fixture and return the vault root."""

    vault = base_dir / "dh223-smoke-vault"
    note = vault / FIXTURE_RELATIVE_PATH
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(
        f"""---
title: DH223 Live Smoke Note
tags: [dh223, smoke, obsidian-rag]
aliases: [DH223 Smoke Alias]
sources: [dh223-live-smoke-fixture]
---
# DH223 Live Smoke Note
The unique retrieval phrase is {unique_phrase}; it proves scoped Obsidian ingest.
This note links to [[Target Smoke Note|target smoke alias]] for metadata verification.
![[smoke-diagram.png|400]]
Important smoke detail. ^dh223-smoke-block
> [!tip] Smoke citation
> Retrieval should cite this Obsidian-backed note and keep this readable prose.
""",
        encoding="utf-8",
    )
    return vault


def run_live_smoke(
    *,
    qdrant_url: str,
    ollama_base_url: str,
    obsidian_core_path: str,
    collection_name: str | None = None,
    fixture_root: Path | None = None,
    embed_provider: str = "ollama",
    embed_model: str = "bge-m3",
    positive_query: str | None = None,
    negative_query: str = DEFAULT_NEGATIVE_QUERY,
    min_positive_score: float = DEFAULT_MIN_POSITIVE_SCORE,
    negative_max_score: float = DEFAULT_NEGATIVE_MAX_SCORE,
    cleanup_collection: bool = True,
    cleanup_vault: bool = True,
    replace_existing_collection: bool = False,
) -> LiveSmokeReport:
    """Run a controlled end-to-end ingest/retrieval smoke against live Qdrant."""

    requested_collection = collection_name
    collection_name = collection_name or _temporary_collection_name()
    positive_query = positive_query or f"Which Obsidian note mentions {UNIQUE_PHRASE}?"

    cleanup_collection_verified = False
    cleanup_vault_verified = False
    cleanup_managed_collection = False
    client: Any | None = None
    fixture_workspace: Path | None = None
    report: LiveSmokeReport | None = None
    cleanup_errors: list[str] = []
    try:
        if (
            requested_collection in RESERVED_COLLECTION_NAMES
            and not replace_existing_collection
        ):
            raise RuntimeError(
                f"Qdrant collection {collection_name!r} is reserved for persistent "
                "Hermes Brain data. Use a fresh temporary collection name, or pass "
                "--replace-existing-collection only when deleting/replacing it is intended."
            )

        from qdrant_client import QdrantClient

        fixture_workspace = _fixture_workspace(fixture_root)
        vault = create_fixture_vault(fixture_workspace)
        fixture_file = vault / FIXTURE_RELATIVE_PATH
        expected_source_root = str(vault)

        config = get_settings(
            vault_path=expected_source_root,
            source_paths="",
            book_paths="",
            obsidian_core_enabled=True,
            obsidian_core_path=obsidian_core_path,
            vector_store_provider="qdrant",
            qdrant_url=qdrant_url,
            collection_name=collection_name,
            embed_provider=embed_provider,
            embed_model=embed_model,
            ollama_base_url=ollama_base_url,
            similarity_top_k=3,
            auto_context_enabled=True,
            auto_context_top_k=3,
            auto_context_min_score=negative_max_score,
            chunk_strategy="markdown",
            chunk_size=512,
            chunk_overlap=20,
        )
        client = QdrantClient(url=config.qdrant_url, timeout=15)

        collection_preexisting = _collection_exists(client, collection_name)
        if collection_preexisting and not requested_collection:
            raise RuntimeError(
                f"Generated temporary Qdrant collection {collection_name!r} already exists. "
                "Refusing to delete a collection this process did not create. Retry the smoke."
            )
        if collection_preexisting and not replace_existing_collection:
            raise RuntimeError(
                f"Qdrant collection {collection_name!r} already exists. "
                "Use a fresh temporary collection name, --keep-collection for a new custom "
                "collection, or --replace-existing-collection only when deletion is intended."
            )
        if collection_preexisting:
            _delete_collection_if_exists(client, collection_name)
        cleanup_managed_collection = True

        docs_indexed = run_ingest(config)
        if docs_indexed != 1:
            raise RuntimeError(
                f"live smoke expected to index exactly one fixture document; got {docs_indexed}"
            )

        qdrant_points = client.count(collection_name, exact=True).count
        if qdrant_points <= 0:
            raise RuntimeError("live Qdrant collection has zero points after ingest")

        payloads = _scroll_payloads(client, collection_name)
        scoped_checks = _verify_scoped_payloads(
            payloads,
            expected_source_root=expected_source_root,
            expected_file_path=FIXTURE_RELATIVE_PATH,
        )
        fixture_payload = _find_payload(payloads, FIXTURE_RELATIVE_PATH)
        metadata_checks = {
            **verify_obsidian_payload(
                fixture_payload,
                UNIQUE_PHRASE,
                expected_source_root=expected_source_root,
            ),
            **scoped_checks,
        }

        positive_retrieval = retrieve(positive_query, config)
        positive_sources = [_source_to_dict(source) for source in positive_retrieval.sources]
        _verify_positive_retrieval(
            positive_retrieval.sources,
            min_positive_score=min_positive_score,
            unique_phrase=UNIQUE_PHRASE,
        )

        negative_retrieval = retrieve(negative_query, config)
        negative_top_score = (
            max((source.score for source in negative_retrieval.sources), default=None)
            if negative_retrieval.sources
            else None
        )
        if negative_top_score is not None and negative_top_score >= negative_max_score:
            raise RuntimeError(
                "negative query produced a high-scoring source: "
                f"score={negative_top_score:.3f}, threshold={negative_max_score:.3f}"
            )

        negative_context = build_context_for_prompt(negative_query, config)
        if negative_context.strip():
            raise RuntimeError("negative query would inject context despite score filtering")

        report = LiveSmokeReport(
            collection_name=collection_name,
            qdrant_url=config.qdrant_url,
            vault_path=str(vault),
            fixture_file=str(fixture_file),
            docs_indexed=docs_indexed,
            qdrant_points=qdrant_points,
            positive_query=positive_query,
            positive_sources=positive_sources,
            negative_query=negative_query,
            negative_top_score=negative_top_score,
            negative_context_injected=False,
            metadata_checks=metadata_checks,
            cleanup_collection=cleanup_collection,
            cleanup_collection_verified=False,
            cleanup_vault=cleanup_vault,
            cleanup_vault_verified=False,
            remaining_feature_gates=[
                "OBSIDIAN_CORE_ENABLED remains disabled by default; this smoke enables it explicitly.",
                "The smoke uses a temporary collection unless --collection-name is provided.",
            ],
        )
    finally:
        if cleanup_collection and cleanup_managed_collection and client is not None:
            try:
                _delete_collection_if_exists(client, collection_name)
                cleanup_collection_verified = not _collection_exists(client, collection_name)
                if not cleanup_collection_verified:
                    cleanup_errors.append(
                        f"collection cleanup requested but {collection_name!r} still exists"
                    )
            except Exception as exc:  # noqa: BLE001 - cleanup errors must fail the smoke
                cleanup_errors.append(f"collection cleanup failed: {exc}")
        if cleanup_vault and fixture_workspace is not None:
            try:
                shutil.rmtree(fixture_workspace)
            except FileNotFoundError:
                pass
            except Exception as exc:  # noqa: BLE001 - cleanup errors must fail the smoke
                cleanup_errors.append(f"fixture vault cleanup failed: {exc}")
            cleanup_vault_verified = not fixture_workspace.exists()
            if not cleanup_vault_verified:
                cleanup_errors.append(
                    f"fixture vault cleanup requested but {fixture_workspace} still exists"
                )

    if report is None:
        raise RuntimeError("live smoke did not produce a report")
    if cleanup_errors:
        raise RuntimeError("live smoke cleanup failed: " + "; ".join(cleanup_errors))

    return LiveSmokeReport(
        **{
            **asdict(report),
            "cleanup_collection_verified": cleanup_collection_verified,
            "cleanup_vault_verified": cleanup_vault_verified,
        }
    )


def verify_obsidian_payload(
    payload: dict[str, Any],
    unique_phrase: str,
    *,
    expected_source_root: str | None = None,
) -> dict[str, Any]:
    """Validate that the live Qdrant payload kept metadata but not text noise."""

    node_content = _node_content(payload)
    node_text = str(node_content.get("text") or "")
    excluded_embed = set(node_content.get("excluded_embed_metadata_keys") or [])
    excluded_llm = set(node_content.get("excluded_llm_metadata_keys") or [])

    expected_pairs: dict[str, Any] = {
        "file_name": "dh223-live-smoke.md",
        "file_path": FIXTURE_RELATIVE_PATH,
        "source_kind": "vault",
        "layer": "wiki",
        "title": "DH223 Live Smoke Note",
        "tags": ["dh223", "smoke", "obsidian-rag"],
        "aliases": ["DH223 Smoke Alias"],
        "sources": ["dh223-live-smoke-fixture"],
        "obsidian_metadata_schema": "hermes_brain.rag_metadata.v1",
    }
    for key, expected in expected_pairs.items():
        if payload.get(key) != expected:
            raise RuntimeError(f"payload[{key!r}]={payload.get(key)!r}; expected {expected!r}")

    if not payload.get("source_root"):
        raise RuntimeError("payload is missing source_root metadata")
    if expected_source_root is not None and payload.get("source_root") != expected_source_root:
        raise RuntimeError(
            f"payload['source_root']={payload.get('source_root')!r}; "
            f"expected {expected_source_root!r}"
        )

    if payload.get("links", [{}])[0].get("target") != "Target Smoke Note":
        raise RuntimeError("payload did not preserve Obsidian wikilink target metadata")
    if payload.get("embeds", [{}])[0].get("target") != "smoke-diagram.png":
        raise RuntimeError("payload did not preserve Obsidian embed metadata")
    if payload.get("block_ids") != ["dh223-smoke-block"]:
        raise RuntimeError("payload did not preserve block id metadata")
    if payload.get("callouts", [{}])[0].get("callout_type") != "tip":
        raise RuntimeError("payload did not preserve callout metadata")
    if payload.get("obsidian_summary", {}).get("callouts") != 1:
        raise RuntimeError("payload did not preserve Obsidian summary metadata")

    if unique_phrase not in node_text:
        raise RuntimeError("semantic node text does not contain the expected unique phrase")
    for noisy_text in ("![[smoke-diagram.png|400]]", "^dh223-smoke-block", "[!tip]"):
        if noisy_text in node_text:
            raise RuntimeError(f"semantic node text still contains structural noise: {noisy_text}")

    structural_keys = set(OBSIDIAN_STRUCTURAL_METADATA_KEYS)
    if not structural_keys.issubset(excluded_embed):
        raise RuntimeError("structural metadata keys are not excluded from embed text")
    if not structural_keys.issubset(excluded_llm):
        raise RuntimeError("structural metadata keys are not excluded from LLM text")

    legacy_fields = [
        "file_name",
        "file_path",
        "source_root",
        "source_kind",
        "layer",
        "title",
        "tags",
        "sources",
    ]
    obsidian_fields = [
        "aliases",
        "links",
        "embeds",
        "block_ids",
        "callouts",
        "obsidian_summary",
    ]
    return {
        "file_path": payload["file_path"],
        "source_root": payload["source_root"],
        "legacy_fields_present": [key for key in legacy_fields if key in payload],
        "obsidian_fields_present": [key for key in obsidian_fields if key in payload],
        "structural_metadata_excluded_from_embed_text": True,
        "structural_metadata_excluded_from_llm_text": True,
        "semantic_text_noise_removed": True,
    }


def _workspace_tmp() -> str | None:
    path = Path("/workspace/tmp")
    if path.is_dir():
        return str(path)
    return None


def _fixture_workspace(fixture_root: Path | None) -> Path:
    if fixture_root is None:
        return Path(
            tempfile.mkdtemp(prefix="dh223_obsidian_live_smoke_", dir=_workspace_tmp())
        ).resolve()

    base = fixture_root.expanduser().resolve()
    workspace = base / f"dh223_obsidian_live_smoke_{secrets.token_hex(8)}"
    workspace.mkdir(parents=True, exist_ok=False)
    return workspace


def _temporary_collection_name() -> str:
    return f"{DEFAULT_COLLECTION_PREFIX}_{secrets.token_hex(12)}"


def _delete_collection_if_exists(client: Any, collection_name: str) -> None:
    if _collection_exists(client, collection_name):
        client.delete_collection(collection_name)


def _collection_exists(client: Any, collection_name: str) -> bool:
    try:
        return bool(client.collection_exists(collection_name))
    except AttributeError:
        pass

    try:
        client.get_collection(collection_name)
        return True
    except Exception as exc:
        if _is_not_found_error(exc):
            return False
        raise


def _is_not_found_error(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    response = getattr(exc, "response", None)
    if status_code is None and response is not None:
        status_code = getattr(response, "status_code", None)
    if status_code == 404:
        return True

    message = str(exc).lower()
    return "not found" in message or "404" in message


def _scroll_payloads(client: Any, collection_name: str) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    next_offset: Any | None = None
    while True:
        points, next_offset = client.scroll(
            collection_name,
            limit=100,
            offset=next_offset,
            with_payload=True,
            with_vectors=False,
        )
        payloads.extend(dict(point.payload or {}) for point in points)
        if next_offset is None:
            return payloads


def _verify_scoped_payloads(
    payloads: list[dict[str, Any]],
    *,
    expected_source_root: str,
    expected_file_path: str,
) -> dict[str, Any]:
    if not payloads:
        raise RuntimeError("live Qdrant collection has no payloads to validate")

    unexpected_payloads = [
        {
            "file_path": payload.get("file_path"),
            "source_root": payload.get("source_root"),
            "source_kind": payload.get("source_kind"),
        }
        for payload in payloads
        if payload.get("source_root") != expected_source_root
        or payload.get("file_path") != expected_file_path
    ]
    if unexpected_payloads:
        raise RuntimeError(
            "live smoke collection contains payloads outside the scoped fixture: "
            f"{unexpected_payloads[:5]!r}"
        )

    return {
        "payloads_checked": len(payloads),
        "all_payloads_scoped_to_fixture": True,
    }


def _find_payload(payloads: list[dict[str, Any]], file_path: str) -> dict[str, Any]:
    for payload in payloads:
        if payload.get("file_path") == file_path:
            return payload
    raise RuntimeError(f"could not find Qdrant payload for fixture path {file_path!r}")


def _node_content(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("_node_content")
    if isinstance(raw, str) and raw.strip():
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    if isinstance(raw, dict):
        return raw
    return {}


def _source_to_dict(source: SourceChunk) -> dict[str, Any]:
    return {
        "file_name": source.file_name,
        "file_path": source.file_path,
        "citation": source.citation,
        "score": source.score,
        "layer": source.layer,
        "source_kind": source.source_kind,
        "text_preview": source.text[:300],
    }


def _verify_positive_retrieval(
    sources: list[SourceChunk],
    *,
    min_positive_score: float,
    unique_phrase: str,
) -> None:
    for source in sources:
        if source.file_path != FIXTURE_RELATIVE_PATH:
            continue
        if unique_phrase not in source.text:
            continue
        if source.score < min_positive_score:
            raise RuntimeError(
                "positive retrieval found the fixture below threshold: "
                f"score={source.score:.3f}, threshold={min_positive_score:.3f}"
            )
        if "DH223 Live Smoke Note" not in source.citation:
            raise RuntimeError("positive retrieval citation does not include the note title")
        return
    raise RuntimeError("positive retrieval did not return the expected fixture note/chunk")


def _print_human_report(report: LiveSmokeReport) -> None:
    print("DH-223 live Obsidian RAG smoke passed")
    print(f"collection: {report.collection_name}")
    print(f"qdrant_url: {report.qdrant_url}")
    print(f"fixture_file: {report.fixture_file}")
    print(f"docs_indexed: {report.docs_indexed}")
    print(f"qdrant_points: {report.qdrant_points}")
    print("positive_sources:")
    for source in report.positive_sources:
        print(
            "- "
            f"{source['citation']} path={source['file_path']} "
            f"score={source['score']:.3f}"
        )
    print(
        "negative_query: "
        f"top_score={report.negative_top_score}; "
        f"context_injected={report.negative_context_injected}"
    )
    print(
        "cleanup: "
        f"collection={report.cleanup_collection_verified}, "
        f"vault={report.cleanup_vault_verified}"
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a live scoped Obsidian RAG smoke against Qdrant/Ollama."
    )
    defaults = Settings()
    parser.add_argument("--qdrant-url", default=defaults.qdrant_url)
    parser.add_argument("--ollama-base-url", default=defaults.ollama_base_url)
    parser.add_argument("--obsidian-core-path", default=defaults.obsidian_core_path)
    parser.add_argument("--collection-name", default="")
    parser.add_argument("--fixture-root", default="")
    parser.add_argument("--embed-provider", default="ollama")
    parser.add_argument("--embed-model", default="bge-m3")
    parser.add_argument("--positive-query", default="")
    parser.add_argument("--negative-query", default=DEFAULT_NEGATIVE_QUERY)
    parser.add_argument("--min-positive-score", type=float, default=DEFAULT_MIN_POSITIVE_SCORE)
    parser.add_argument("--negative-max-score", type=float, default=DEFAULT_NEGATIVE_MAX_SCORE)
    parser.add_argument("--keep-collection", action="store_true")
    parser.add_argument(
        "--replace-existing-collection",
        action="store_true",
        help="Delete an existing named collection before the smoke. Never needed for defaults.",
    )
    parser.add_argument("--keep-vault", action="store_true")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON report")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    fixture_root = Path(args.fixture_root) if args.fixture_root else None
    try:
        stdout_context = redirect_stdout(sys.stderr) if args.json else nullcontext()
        with stdout_context:
            report = run_live_smoke(
                qdrant_url=args.qdrant_url,
                ollama_base_url=args.ollama_base_url,
                obsidian_core_path=args.obsidian_core_path,
                collection_name=args.collection_name or None,
                fixture_root=fixture_root,
                embed_provider=args.embed_provider,
                embed_model=args.embed_model,
                positive_query=args.positive_query or None,
                negative_query=args.negative_query,
                min_positive_score=args.min_positive_score,
                negative_max_score=args.negative_max_score,
                cleanup_collection=not args.keep_collection,
                cleanup_vault=not args.keep_vault,
                replace_existing_collection=args.replace_existing_collection,
            )
    except Exception as exc:  # noqa: BLE001 - CLI should emit concise failure context
        print(f"DH-223 live Obsidian RAG smoke failed: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(report.to_json())
    else:
        _print_human_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
