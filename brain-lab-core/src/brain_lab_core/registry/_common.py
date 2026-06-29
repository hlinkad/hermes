"""Shared registry validation and error helpers."""
from __future__ import annotations

from typing import Any

from brain_lab_core.contracts import ContractDiagnostic, ContractValidationError


class RegistryConflictError(ValueError):
    """Raised when a registry key is reused for a different declaration."""


class RegistryLookupError(KeyError):
    """Raised when a requested registry declaration is missing."""


def required_registry_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ContractValidationError(f"{field_name} is required")
    return text


def raise_for_error_diagnostics(diagnostics: tuple[ContractDiagnostic, ...]) -> None:
    errors = [diagnostic for diagnostic in diagnostics if diagnostic.severity == "error"]
    if not errors:
        return
    details = []
    for diagnostic in errors:
        if diagnostic.location:
            details.append(f"{diagnostic.location}: {diagnostic.message}")
        else:
            details.append(diagnostic.message)
    raise ContractValidationError("; ".join(details))
