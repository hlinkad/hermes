"""Shared primitives for schema-versioned AI Lab contracts."""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, ClassVar, Mapping, Protocol, TypeVar, runtime_checkable

CONTRACT_SCHEMA_VERSION = "brain_lab.contracts.v1"
JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
T = TypeVar("T")


class ContractValidationError(ValueError):
    """Raised when a contract instance cannot represent valid framework data."""


@dataclass(frozen=True, order=True)
class ContractDiagnostic:
    """Structured, serializable diagnostic emitted by contract validators."""

    code: str
    message: str
    severity: str = "warning"
    location: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _required_text(self.code, "diagnostic.code"))
        object.__setattr__(self, "message", str(self.message or ""))
        severity = str(self.severity or "warning").lower()
        if severity not in {"error", "warning", "info"}:
            severity = "warning"
        object.__setattr__(self, "severity", severity)
        object.__setattr__(self, "location", str(self.location or ""))

    def to_dict(self) -> dict[str, JsonValue]:
        return asdict(self)

    def as_dict(self) -> dict[str, JsonValue]:
        return self.to_dict()


@runtime_checkable
class JsonContract(Protocol):
    """Protocol implemented by all public contracts."""

    contract_type: ClassVar[str]

    def to_dict(self) -> dict[str, JsonValue]:
        """Return a deterministic JSON-compatible representation."""

    def to_json(self) -> str:
        """Serialize to compact, sorted JSON."""


def to_json(data: Mapping[str, Any]) -> str:
    return json.dumps(_json_mapping(data), sort_keys=True, separators=(",", ":"), allow_nan=False)


def load_json_object(text: str, contract_name: str) -> dict[str, Any]:
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ContractValidationError(f"{contract_name}: invalid JSON: {exc.msg}") from exc
    if not isinstance(loaded, dict):
        raise ContractValidationError(f"{contract_name}: JSON payload must be an object")
    _validate_contract_type(loaded, contract_name, require=True)
    _validate_schema_version(loaded, contract_name, require=True)
    return loaded


def contract_header(contract_type: str, schema_version: str = CONTRACT_SCHEMA_VERSION) -> dict[str, str]:
    return {"contract_type": contract_type, "schema_version": schema_version}


def _validate_contract_type(
    data: Mapping[str, Any], expected_contract_type: str, *, require: bool = False
) -> None:
    observed = data.get("contract_type")
    if observed is None:
        if require:
            raise ContractValidationError(f"{expected_contract_type}: contract_type is required")
        return
    if observed != expected_contract_type:
        raise ContractValidationError(
            f"contract_type must be {expected_contract_type!r}; got {observed!r}"
        )


def _validate_schema_version(
    data: Mapping[str, Any], contract_name: str, *, require: bool = False
) -> None:
    observed = data.get("schema_version")
    if observed is None:
        if require:
            raise ContractValidationError(f"{contract_name}: schema_version is required")
        return
    _schema_version(observed)


def _schema_version(value: Any, field_name: str = "schema_version") -> str:
    text = _required_text(value, field_name)
    if text != CONTRACT_SCHEMA_VERSION:
        raise ContractValidationError(
            f"{field_name} must be {CONTRACT_SCHEMA_VERSION!r}; got {text!r}"
        )
    return text


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ContractValidationError(f"{field_name} is required")
    return text


def _optional_text(value: Any) -> str:
    return str(value or "").strip()


def _required_tuple(values: Any, field_name: str) -> tuple[str, ...]:
    normalized = _string_tuple(values)
    if not normalized:
        raise ContractValidationError(f"{field_name} must contain at least one value")
    return normalized


def _string_tuple(values: Any) -> tuple[str, ...]:
    if values is None or values == "":
        return ()
    if isinstance(values, str):
        raw_values = (values,)
    else:
        try:
            raw_values = tuple(values)
        except TypeError:
            raw_values = (values,)
    normalized_values: list[str] = []
    for value in raw_values:
        if value is None or value == "":
            continue
        if not isinstance(value, str):
            raise ContractValidationError("tuple values must be strings")
        text = value.strip()
        if text:
            normalized_values.append(text)
    return tuple(dict.fromkeys(normalized_values))


def _non_negative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool):
        raise ContractValidationError(f"{field_name} must be an integer")
    if isinstance(value, int):
        number = value
    else:
        raise ContractValidationError(f"{field_name} must be an integer")
    if number < 0:
        raise ContractValidationError(f"{field_name} must be non-negative")
    return number


def _bool_value(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ContractValidationError(f"{field_name} must be a boolean")
    return value


def _positive_int(value: Any, field_name: str) -> int:
    number = _non_negative_int(value, field_name)
    if number < 1:
        raise ContractValidationError(f"{field_name} must be at least 1")
    return number


def _non_negative_float(value: Any, field_name: str) -> float:
    if isinstance(value, bool):
        raise ContractValidationError(f"{field_name} must be a number")
    if not isinstance(value, int | float):
        raise ContractValidationError(f"{field_name} must be a number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(f"{field_name} must be a number") from exc
    if not math.isfinite(number) or number < 0:
        raise ContractValidationError(f"{field_name} must be a finite non-negative number")
    return number


def _unit_interval(value: Any, field_name: str) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ContractValidationError(f"{field_name} must be a number between 0 and 1")
    if not isinstance(value, int | float):
        raise ContractValidationError(f"{field_name} must be a number between 0 and 1")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(f"{field_name} must be a number between 0 and 1") from exc
    if not math.isfinite(number) or number < 0 or number > 1:
        raise ContractValidationError(f"{field_name} must be a finite number between 0 and 1")
    return number


def _confidence(value: Any, field_name: str) -> float | None:
    return _unit_interval(value, field_name)


def _json_value(value: Any) -> JsonValue:
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, ContractDiagnostic):
        return value.to_dict()
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _json_mapping(value.to_dict())
    if isinstance(value, Mapping):
        return _json_mapping(value)
    if isinstance(value, tuple | list):
        return [_json_value(item) for item in value]
    if isinstance(value, set | frozenset):
        items = [_json_value(item) for item in value]
        return sorted(
            items,
            key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":"), allow_nan=False),
        )
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ContractValidationError("JSON numeric values must be finite")
        return value
    raise ContractValidationError(f"unsupported JSON value type: {type(value).__name__}")


def _json_mapping(value: Mapping[str, Any] | None) -> dict[str, JsonValue]:
    if not value:
        return {}
    safe: dict[str, JsonValue] = {}
    for key in sorted(value, key=str):
        safe[str(key)] = _json_value(value[key])
    return safe


def _metadata(value: Any) -> dict[str, JsonValue]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ContractValidationError("metadata must be a mapping")
    return _json_mapping(value)


def _enum_value(enum_type: type[T], value: Any, field_name: str) -> T:
    if isinstance(value, enum_type):
        return value
    text = str(value or "")
    try:
        return enum_type(text)  # type: ignore[call-arg, return-value]
    except ValueError as exc:
        valid = ", ".join(str(item.value) for item in enum_type)  # type: ignore[attr-defined]
        raise ContractValidationError(f"{field_name} must be one of: {valid}") from exc


def _diagnostic_tuple(values: Any) -> tuple[ContractDiagnostic, ...]:
    if values is None or values == "":
        return ()
    if isinstance(values, ContractDiagnostic):
        return (values,)
    try:
        raw_values = tuple(values)
    except TypeError:
        raw_values = (values,)
    diagnostics: list[ContractDiagnostic] = []
    for item in raw_values:
        if isinstance(item, ContractDiagnostic):
            diagnostics.append(item)
        elif isinstance(item, Mapping):
            diagnostics.append(
                ContractDiagnostic(
                    code=item.get("code", "contract_diagnostic"),
                    message=item.get("message", ""),
                    severity=item.get("severity", "warning"),
                    location=item.get("location", ""),
                )
            )
        else:
            diagnostics.append(ContractDiagnostic(code="contract_diagnostic", message=str(item)))
    return tuple(sorted(set(diagnostics)))
