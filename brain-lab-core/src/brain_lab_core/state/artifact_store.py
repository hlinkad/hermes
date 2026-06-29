"""Filesystem artifact helpers for checksum, size, and stable URIs."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from brain_lab_core.contracts import Checksum, ContractValidationError


@dataclass(frozen=True)
class FileArtifactDescription:
    """Measured filesystem payload details used to build an ArtifactRef."""

    path: Path
    uri: str
    checksum: Checksum
    size_bytes: int


class FilesystemArtifactStore:
    """Small local-first filesystem read model for artifact payloads.

    SQLite remains canonical for artifact metadata. This helper only measures an
    existing payload and derives a stable URI relative to the configured artifact
    root when possible.
    """

    def __init__(self, root_path: str | Path | None = None) -> None:
        self.root_path = Path(root_path).expanduser().resolve() if root_path is not None else None

    def describe(self, file_path: str | Path, *, algorithm: str = "sha256", uri: str | None = None) -> FileArtifactDescription:
        path = Path(file_path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(path)
        if not path.is_file():
            raise ContractValidationError(f"artifact path is not a file: {path}")
        checksum = compute_file_checksum(path, algorithm=algorithm)
        size_bytes = path.stat().st_size
        return FileArtifactDescription(
            path=path,
            uri=uri if uri is not None else self.uri_for(path),
            checksum=checksum,
            size_bytes=size_bytes,
        )

    def uri_for(self, path: str | Path) -> str:
        resolved = Path(path).expanduser().resolve()
        if self.root_path is not None:
            try:
                return resolved.relative_to(self.root_path).as_posix()
            except ValueError:
                pass
        return resolved.as_uri()


def compute_file_checksum(file_path: str | Path, *, algorithm: str = "sha256", chunk_size: int = 1024 * 1024) -> Checksum:
    """Compute a cryptographic checksum for a filesystem artifact."""

    if algorithm != "sha256":
        raise ContractValidationError("only sha256 checksums are currently supported")
    path = Path(file_path).expanduser().resolve()
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return Checksum(algorithm=algorithm, value=digest.hexdigest())
