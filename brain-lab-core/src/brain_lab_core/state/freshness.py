"""Deterministic freshness and provenance fingerprint helpers."""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from enum import Enum
from typing import Any

from brain_lab_core.contracts import ArtifactId, ContractValidationError


def canonical_json(value: Any) -> str:
    """Return deterministic JSON for fingerprinting caller-visible inputs.

    The helper accepts primitive JSON values, mappings/sequences, enums, sets, and
    public contract objects that expose ``to_dict()``. It deliberately rejects
    unknown Python objects instead of stringifying them, because fingerprints are
    part of the freshness contract.
    """

    return json.dumps(_canonical_value(value), sort_keys=True, separators=(",", ":"), allow_nan=False)


def fingerprint(value: Any, *, algorithm: str = "sha256") -> str:
    """Fingerprint a canonical JSON representation as ``algorithm:hex``."""

    if algorithm != "sha256":
        raise ContractValidationError("only sha256 fingerprints are currently supported")
    digest = hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
    return f"{algorithm}:{digest}"


def config_fingerprint(config: Any) -> str:
    """Fingerprint a tool/stage configuration object for stale detection."""

    return fingerprint({"config": config})


def input_fingerprint(input_artifact_ids: tuple[ArtifactId, ...] | list[ArtifactId]) -> str:
    """Fingerprint input artifact IDs as an order-insensitive dependency set."""

    _ensure_input_id_iterable(input_artifact_ids)
    qualified = sorted(ArtifactId.from_dict(artifact_id).qualified for artifact_id in input_artifact_ids)
    return fingerprint({"input_artifact_ids": qualified})


def derivation_fingerprint(
    *,
    producer_tool_id: str,
    producer_stage_id: str,
    input_artifact_ids: tuple[ArtifactId, ...] | list[ArtifactId],
    config_fingerprint_value: str,
    artifact_type: str,
    artifact_schema_version: str,
) -> str:
    """Fingerprint the semantic derivation contract for a produced artifact."""

    _ensure_input_id_iterable(input_artifact_ids)
    return fingerprint(
        {
            "producer_tool_id": producer_tool_id,
            "producer_stage_id": producer_stage_id,
            "input_artifact_ids": sorted(
                ArtifactId.from_dict(artifact_id).qualified for artifact_id in input_artifact_ids
            ),
            "config_fingerprint": config_fingerprint_value,
            "artifact_type": artifact_type,
            "artifact_schema_version": artifact_schema_version,
        }
    )


def _ensure_input_id_iterable(input_artifact_ids: Any) -> None:
    if isinstance(input_artifact_ids, str | bytes | ArtifactId) or isinstance(
        input_artifact_ids, Mapping
    ):
        raise ContractValidationError(
            "input_artifact_ids must be an iterable of artifact IDs; wrap a single input ID in a tuple"
        )


def _canonical_value(value: Any) -> Any:
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _canonical_value(value.to_dict())
    if isinstance(value, ArtifactId):
        return value.to_dict()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        safe: dict[str, Any] = {}
        for key, item_value in sorted(
            value.items(), key=lambda item: (str(item[0]), type(item[0]).__name__)
        ):
            text_key = str(key)
            if text_key in safe:
                raise ContractValidationError(
                    f"fingerprint mapping keys collide after string normalization: {text_key!r}"
                )
            safe[text_key] = _canonical_value(item_value)
        return safe
    if isinstance(value, tuple | list):
        return [_canonical_value(item) for item in value]
    if isinstance(value, set | frozenset):
        return sorted(
            (_canonical_value(item) for item in value),
            key=lambda item: json.dumps(item, sort_keys=True),
        )
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ContractValidationError("fingerprint numeric values must be finite")
        return value
    raise ContractValidationError(f"unsupported fingerprint value type: {type(value).__name__}")
