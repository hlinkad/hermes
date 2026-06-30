"""Document and PDF extraction result contracts.

These contracts intentionally describe extraction outputs and provenance only. They
must not import concrete extractor packages such as MinerU, call services, or pull
retrieval/indexing concerns into the document layer.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, ClassVar, Mapping

from .artifacts import ArtifactRef, Checksum
from .base import (
    CONTRACT_SCHEMA_VERSION,
    ContractDiagnostic,
    ContractValidationError,
    JsonValue,
    _confidence,
    _diagnostic_tuple,
    _enum_value,
    _metadata,
    _non_negative_int,
    _optional_text,
    _schema_version,
    _validate_contract_type,
    contract_header,
    load_json_object,
    to_json,
)
from .evidence import SourceSpan


class DocumentBlockKind(str, Enum):
    """Normalized block families produced by document extractors."""

    TEXT = "text"
    TITLE = "title"
    HEADING = "heading"
    LIST_ITEM = "list_item"
    TABLE = "table"
    IMAGE = "image"
    FORMULA = "formula"
    OCR_TEXT = "ocr_text"
    HEADER = "header"
    FOOTER = "footer"
    UNKNOWN = "unknown"


class DocumentPageStatus(str, Enum):
    """Extraction status for a single source page."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    EMPTY = "empty"
    FAILED = "failed"
    SKIPPED = "skipped"


class DocumentExtractionStatus(str, Enum):
    """Overall extraction status for a document artifact."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"


def _optional_checksum(value: Any) -> Checksum | None:
    if value is None or value == {} or value == "":
        return None
    return Checksum.from_dict(value)


def _optional_positive_int(value: Any, field_name: str) -> int | None:
    if value is None or value == "":
        return None
    number = _non_negative_int(value, field_name)
    if number < 1:
        raise ContractValidationError(f"{field_name} must be at least 1")
    return number


def _required_positive_int(value: Any, field_name: str) -> int:
    number = _optional_positive_int(value, field_name)
    if number is None:
        raise ContractValidationError(f"{field_name} is required")
    return number


def _required_non_negative_int(value: Any, field_name: str) -> int:
    if value is None or value == "":
        raise ContractValidationError(f"{field_name} is required")
    return _non_negative_int(value, field_name)


def _sequence_tuple(value: Any, field_name: str) -> tuple[Any, ...]:
    if value is None:
        raise ContractValidationError(f"{field_name} must be a list or tuple")
    if isinstance(value, str | bytes) or isinstance(value, Mapping):
        raise ContractValidationError(f"{field_name} must be a list or tuple")
    if isinstance(value, Iterable):
        return tuple(value)
    raise ContractValidationError(f"{field_name} must be a list or tuple")


def _mapping_sequence(data: Mapping[str, Any], key: str, field_name: str) -> tuple[Any, ...]:
    if key not in data:
        return ()
    return _sequence_tuple(data[key], field_name)


def _has_text(value: str) -> bool:
    return bool(value.strip())


def _has_non_empty_payload(mapping: Mapping[str, Any], keys: tuple[str, ...]) -> bool:
    for key in keys:
        if key not in mapping:
            continue
        value = mapping[key]
        if isinstance(value, str):
            if value.strip():
                return True
        elif isinstance(value, Mapping):
            if value:
                return True
        elif isinstance(value, list | tuple | set | frozenset):
            if value:
                return True
        elif value is not None and value != "":
            return True
    return False


def _diagnostics_explain_missing_payload(
    kind: DocumentBlockKind,
    diagnostics: tuple[ContractDiagnostic, ...],
) -> bool:
    if kind == DocumentBlockKind.UNKNOWN:
        return True
    missing_terms = (
        "missing",
        "empty",
        "unavailable",
        "unsupported",
        "failed",
        "failure",
        "omitted",
        "no payload",
        "not extracted",
    )
    for diagnostic in diagnostics:
        text = f"{diagnostic.code} {diagnostic.message}".lower()
        if any(term in text for term in missing_terms):
            return True
    return False


def _unique_source_value(values: Iterable[Any], field_name: str) -> Any:
    unique: list[Any] = []
    for value in values:
        if value is None or value == "":
            continue
        if value not in unique:
            unique.append(value)
    if len(unique) > 1:
        raise ContractValidationError(f"document_extraction.{field_name} must be consistent across result, page, and block provenance")
    return unique[0] if unique else None


def _page_span(page_number: int) -> SourceSpan:
    return SourceSpan(kind="page", start=page_number, end=page_number, unit="page")


def _span_page_matches(span: SourceSpan, page_number: int, field_name: str) -> None:
    if span.kind == "unknown":
        return
    if span.kind != "page":
        raise ContractValidationError(f"{field_name}.kind must be 'page' or 'unknown'")
    if not isinstance(span.start, int | float) or not isinstance(span.end, int | float):
        raise ContractValidationError(f"{field_name} must have numeric page boundaries")
    if span.unit and span.unit != "page":
        raise ContractValidationError(f"{field_name}.unit must be 'page' when provided")
    if span.start != page_number:
        raise ContractValidationError(f"{field_name}.start must match page_number")
    if span.end != page_number:
        raise ContractValidationError(f"{field_name}.end must match page_number")


def _sync_page_provenance(
    provenance: "DocumentProvenance",
    *,
    page_number: int,
    field_name: str,
) -> "DocumentProvenance":
    provenance = DocumentProvenance.from_dict(provenance)
    if provenance.page_number is not None and provenance.page_number != page_number:
        raise ContractValidationError(f"{field_name}.page_number must match page_number")
    _span_page_matches(provenance.page_span, page_number, f"{field_name}.page_span")
    updates: dict[str, Any] = {}
    if provenance.page_number is None:
        updates["page_number"] = page_number
    if provenance.page_span.kind == "unknown":
        updates["page_span"] = _page_span(page_number)
    return replace(provenance, **updates) if updates else provenance


def _sync_source_provenance(
    provenance: "DocumentProvenance",
    *,
    source_uri: str,
    source_path: str,
    content_hash: Checksum | None,
    field_name: str,
) -> "DocumentProvenance":
    provenance = DocumentProvenance.from_dict(provenance)
    if provenance.source_uri and source_uri and provenance.source_uri != source_uri:
        raise ContractValidationError(f"{field_name}.source_uri must match document source_uri")
    if provenance.source_path and source_path and provenance.source_path != source_path:
        raise ContractValidationError(f"{field_name}.source_path must match document source_path")
    if provenance.content_hash is not None and content_hash is not None and provenance.content_hash != content_hash:
        raise ContractValidationError(f"{field_name}.content_hash must match document content_hash")
    updates: dict[str, Any] = {}
    if not provenance.source_uri and source_uri:
        updates["source_uri"] = source_uri
    if not provenance.source_path and source_path:
        updates["source_path"] = source_path
    if provenance.content_hash is None and content_hash is not None:
        updates["content_hash"] = content_hash
    return replace(provenance, **updates) if updates else provenance


@dataclass(frozen=True)
class DocumentProvenance:
    """Page-aware provenance for document, page, and block extraction records."""

    source_uri: str = ""
    source_path: str = ""
    content_hash: Checksum | None = None
    page_number: int | None = None
    page_span: SourceSpan = field(default_factory=SourceSpan)
    block_id: str = ""
    block_span: SourceSpan = field(default_factory=SourceSpan)
    extractor_name: str = ""
    extractor_version: str = ""
    extracted_at: str = ""
    diagnostics: tuple[ContractDiagnostic, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = CONTRACT_SCHEMA_VERSION

    contract_type: ClassVar[str] = "brain_lab.document_provenance"

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_uri", _optional_text(self.source_uri))
        object.__setattr__(self, "source_path", _optional_text(self.source_path))
        object.__setattr__(self, "content_hash", _optional_checksum(self.content_hash))
        object.__setattr__(self, "page_number", _optional_positive_int(self.page_number, "document_provenance.page_number"))
        object.__setattr__(self, "page_span", SourceSpan.from_dict(self.page_span))
        object.__setattr__(self, "block_id", _optional_text(self.block_id))
        object.__setattr__(self, "block_span", SourceSpan.from_dict(self.block_span))
        object.__setattr__(self, "extractor_name", _optional_text(self.extractor_name))
        object.__setattr__(self, "extractor_version", _optional_text(self.extractor_version))
        object.__setattr__(self, "extracted_at", _optional_text(self.extracted_at))
        object.__setattr__(self, "diagnostics", _diagnostic_tuple(self.diagnostics))
        object.__setattr__(self, "metadata", _metadata(self.metadata))
        object.__setattr__(self, "schema_version", _schema_version(self.schema_version))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            **contract_header(self.contract_type, self.schema_version),
            "source_uri": self.source_uri,
            "source_path": self.source_path,
            "content_hash": self.content_hash.to_dict() if self.content_hash else None,
            "page_number": self.page_number,
            "page_span": self.page_span.to_dict(),
            "block_id": self.block_id,
            "block_span": self.block_span.to_dict(),
            "extractor_name": self.extractor_name,
            "extractor_version": self.extractor_version,
            "extracted_at": self.extracted_at,
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "metadata": dict(self.metadata),
        }

    def to_json(self) -> str:
        return to_json(self.to_dict())

    @classmethod
    def from_json(cls, text: str) -> "DocumentProvenance":
        return cls.from_dict(load_json_object(text, cls.contract_type))

    @classmethod
    def from_dict(cls, data: Any) -> "DocumentProvenance":
        if isinstance(data, DocumentProvenance):
            return data
        if data is None:
            return cls()
        if not isinstance(data, Mapping):
            raise ContractValidationError("document_provenance must be a mapping")
        _validate_contract_type(data, cls.contract_type)
        return cls(
            source_uri=data.get("source_uri", ""),
            source_path=data.get("source_path", ""),
            content_hash=_optional_checksum(data.get("content_hash")),
            page_number=data.get("page_number"),
            page_span=SourceSpan.from_dict(data.get("page_span", {})),
            block_id=data.get("block_id", ""),
            block_span=SourceSpan.from_dict(data.get("block_span", {})),
            extractor_name=data.get("extractor_name", ""),
            extractor_version=data.get("extractor_version", ""),
            extracted_at=data.get("extracted_at", ""),
            diagnostics=data.get("diagnostics", ()),
            metadata=data.get("metadata", {}),
            schema_version=data.get("schema_version", CONTRACT_SCHEMA_VERSION),
        )


def _validate_block_payload(
    *,
    kind: DocumentBlockKind,
    text: str,
    table: Mapping[str, Any],
    image: Mapping[str, Any],
    formula: str,
    ocr_text: str,
    diagnostics: tuple[ContractDiagnostic, ...],
) -> None:
    if _diagnostics_explain_missing_payload(kind, diagnostics):
        return
    textual_kinds = {
        DocumentBlockKind.TEXT,
        DocumentBlockKind.TITLE,
        DocumentBlockKind.HEADING,
        DocumentBlockKind.LIST_ITEM,
        DocumentBlockKind.HEADER,
        DocumentBlockKind.FOOTER,
    }
    if kind in textual_kinds and not (_has_text(text) or _has_text(ocr_text)):
        raise ContractValidationError(f"document_block.text is required for {kind.value} blocks unless diagnostics explain the missing payload")
    if kind == DocumentBlockKind.TABLE and not _has_non_empty_payload(table, ("rows", "cells", "html", "markdown")):
        raise ContractValidationError("document_block.table must include non-empty rows, cells, html, or markdown for table blocks unless diagnostics explain the missing payload")
    if kind == DocumentBlockKind.IMAGE and not _has_non_empty_payload(image, ("asset_uri", "artifact_id", "uri")):
        raise ContractValidationError("document_block.image must include a non-empty asset_uri, artifact_id, or uri for image blocks unless diagnostics explain the missing payload")
    if kind == DocumentBlockKind.FORMULA and not (_has_text(formula) or _has_text(text)):
        raise ContractValidationError("document_block.formula is required for formula blocks unless diagnostics explain the missing payload")
    if kind == DocumentBlockKind.OCR_TEXT and not (_has_text(ocr_text) or _has_text(text)):
        raise ContractValidationError("document_block.ocr_text is required for ocr_text blocks unless diagnostics explain the missing payload")


@dataclass(frozen=True)
class DocumentBlock:
    """A normalized block extracted from a document page."""

    block_id: str = ""
    kind: DocumentBlockKind | str | None = None
    order: int | None = None
    text: str = ""
    table: Mapping[str, Any] = field(default_factory=dict)
    image: Mapping[str, Any] = field(default_factory=dict)
    formula: str = ""
    ocr_text: str = ""
    confidence: float | None = None
    span: SourceSpan = field(default_factory=SourceSpan)
    provenance: DocumentProvenance = field(default_factory=DocumentProvenance)
    diagnostics: tuple[ContractDiagnostic, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = CONTRACT_SCHEMA_VERSION

    contract_type: ClassVar[str] = "brain_lab.document_block"

    def __post_init__(self) -> None:
        block_id = _optional_text(self.block_id)
        if not block_id:
            raise ContractValidationError("document_block.block_id is required")
        if self.kind is None or self.kind == "":
            raise ContractValidationError("document_block.kind is required")
        kind = _enum_value(DocumentBlockKind, self.kind, "document_block.kind")
        order = _required_non_negative_int(self.order, "document_block.order")
        text = str(self.text or "")
        table = _metadata(self.table)
        image = _metadata(self.image)
        formula = str(self.formula or "")
        ocr_text = str(self.ocr_text or "")
        confidence = _confidence(self.confidence, "document_block.confidence")
        span = SourceSpan.from_dict(self.span)
        diagnostics = _diagnostic_tuple(self.diagnostics)
        _validate_block_payload(
            kind=kind,
            text=text,
            table=table,
            image=image,
            formula=formula,
            ocr_text=ocr_text,
            diagnostics=diagnostics,
        )
        provenance = DocumentProvenance.from_dict(self.provenance)
        if provenance.block_id and provenance.block_id != block_id:
            raise ContractValidationError("document_block.provenance.block_id must match block_id")
        if provenance.block_span.kind != "unknown" and span.kind != "unknown" and provenance.block_span != span:
            raise ContractValidationError("document_block.provenance.block_span must match span when both are present")
        provenance_updates: dict[str, Any] = {}
        if not provenance.block_id:
            provenance_updates["block_id"] = block_id
        if provenance.block_span.kind == "unknown" and span.kind != "unknown":
            provenance_updates["block_span"] = span
        if provenance_updates:
            provenance = replace(provenance, **provenance_updates)
        object.__setattr__(self, "block_id", block_id)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "order", order)
        object.__setattr__(self, "text", text)
        object.__setattr__(self, "table", table)
        object.__setattr__(self, "image", image)
        object.__setattr__(self, "formula", formula)
        object.__setattr__(self, "ocr_text", ocr_text)
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "span", span)
        object.__setattr__(self, "provenance", provenance)
        object.__setattr__(self, "diagnostics", diagnostics)
        object.__setattr__(self, "metadata", _metadata(self.metadata))
        object.__setattr__(self, "schema_version", _schema_version(self.schema_version))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            **contract_header(self.contract_type, self.schema_version),
            "block_id": self.block_id,
            "kind": self.kind.value,
            "order": self.order,
            "text": self.text,
            "table": dict(self.table),
            "image": dict(self.image),
            "formula": self.formula,
            "ocr_text": self.ocr_text,
            "confidence": self.confidence,
            "span": self.span.to_dict(),
            "provenance": self.provenance.to_dict(),
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "metadata": dict(self.metadata),
        }

    def to_json(self) -> str:
        return to_json(self.to_dict())

    @classmethod
    def from_json(cls, text: str) -> "DocumentBlock":
        return cls.from_dict(load_json_object(text, cls.contract_type))

    @classmethod
    def from_dict(cls, data: Any) -> "DocumentBlock":
        if isinstance(data, cls):
            return data
        if not isinstance(data, Mapping):
            raise ContractValidationError("document_block must be a mapping")
        _validate_contract_type(data, cls.contract_type)
        return cls(
            block_id=data.get("block_id", ""),
            kind=data.get("kind"),
            order=data.get("order"),
            text=data.get("text", ""),
            table=data.get("table", {}),
            image=data.get("image", {}),
            formula=data.get("formula", ""),
            ocr_text=data.get("ocr_text", ""),
            confidence=data.get("confidence"),
            span=SourceSpan.from_dict(data.get("span", {})),
            provenance=DocumentProvenance.from_dict(data.get("provenance", {})),
            diagnostics=data.get("diagnostics", ()),
            metadata=data.get("metadata", {}),
            schema_version=data.get("schema_version", CONTRACT_SCHEMA_VERSION),
        )


def _validate_page_status_payload(
    *,
    status: DocumentPageStatus,
    blocks: tuple[DocumentBlock, ...],
    text: str,
    markdown: str,
    diagnostics: tuple[ContractDiagnostic, ...],
) -> None:
    has_payload = bool(blocks) or _has_text(text) or _has_text(markdown)
    if status in {DocumentPageStatus.EMPTY, DocumentPageStatus.SKIPPED} and has_payload:
        raise ContractValidationError(f"document_page.status {status.value} cannot include blocks, text, or markdown")
    if status == DocumentPageStatus.FAILED:
        has_error_diagnostic = any(diagnostic.severity == "error" for diagnostic in diagnostics)
        if not has_error_diagnostic:
            raise ContractValidationError("document_page.status failed requires an error diagnostic")
        if has_payload:
            raise ContractValidationError("document_page.status failed cannot include payload; use partial for salvaged content")


@dataclass(frozen=True)
class DocumentPage:
    """A source page with normalized text, Markdown, blocks, and diagnostics."""

    page_number: int | None = None
    status: DocumentPageStatus | str = DocumentPageStatus.COMPLETE
    blocks: tuple[DocumentBlock, ...] = field(default_factory=tuple)
    text: str = ""
    markdown: str = ""
    confidence: float | None = None
    provenance: DocumentProvenance = field(default_factory=DocumentProvenance)
    diagnostics: tuple[ContractDiagnostic, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = CONTRACT_SCHEMA_VERSION

    contract_type: ClassVar[str] = "brain_lab.document_page"
    block_type: ClassVar[type[DocumentBlock]] = DocumentBlock

    def __post_init__(self) -> None:
        page_number = _required_positive_int(self.page_number, "document_page.page_number")
        status = _enum_value(DocumentPageStatus, self.status, "document_page.status")
        blocks = tuple(self.block_type.from_dict(block) for block in _sequence_tuple(self.blocks, "document_page.blocks"))
        block_ids = [block.block_id for block in blocks]
        duplicate_block_ids = sorted({block_id for block_id in block_ids if block_ids.count(block_id) > 1})
        if duplicate_block_ids:
            raise ContractValidationError(f"duplicate block_id(s) on page {page_number}: {', '.join(duplicate_block_ids)}")
        block_orders = [block.order for block in blocks]
        duplicate_orders = sorted({order for order in block_orders if block_orders.count(order) > 1})
        if duplicate_orders:
            duplicates = ", ".join(str(order) for order in duplicate_orders)
            raise ContractValidationError(f"duplicate block order(s) on page {page_number}: {duplicates}")
        diagnostics = _diagnostic_tuple(self.diagnostics)
        provenance = _sync_page_provenance(
            self.provenance,
            page_number=page_number,
            field_name="document_page.provenance",
        )
        normalized_blocks: list[DocumentBlock] = []
        for block in blocks:
            block_provenance = _sync_page_provenance(
                block.provenance,
                page_number=page_number,
                field_name=f"document_page.blocks[{block.block_id}].provenance",
            )
            if block.span.kind == "page":
                _span_page_matches(block.span, page_number, f"document_page.blocks[{block.block_id}].span")
            if block_provenance.block_span.kind == "page":
                _span_page_matches(
                    block_provenance.block_span,
                    page_number,
                    f"document_page.blocks[{block.block_id}].provenance.block_span",
                )
            if block_provenance != block.provenance:
                block = replace(block, provenance=block_provenance)
            normalized_blocks.append(block)
        text = str(self.text or "")
        markdown = str(self.markdown or "")
        normalized_blocks_tuple = tuple(sorted(normalized_blocks, key=lambda block: (block.order, block.block_id)))
        _validate_page_status_payload(
            status=status,
            blocks=normalized_blocks_tuple,
            text=text,
            markdown=markdown,
            diagnostics=diagnostics,
        )
        object.__setattr__(self, "page_number", page_number)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "blocks", normalized_blocks_tuple)
        object.__setattr__(self, "text", text)
        object.__setattr__(self, "markdown", markdown)
        object.__setattr__(self, "confidence", _confidence(self.confidence, "document_page.confidence"))
        object.__setattr__(self, "provenance", provenance)
        object.__setattr__(self, "diagnostics", diagnostics)
        object.__setattr__(self, "metadata", _metadata(self.metadata))
        object.__setattr__(self, "schema_version", _schema_version(self.schema_version))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            **contract_header(self.contract_type, self.schema_version),
            "page_number": self.page_number,
            "status": self.status.value,
            "blocks": [block.to_dict() for block in self.blocks],
            "text": self.text,
            "markdown": self.markdown,
            "confidence": self.confidence,
            "provenance": self.provenance.to_dict(),
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "metadata": dict(self.metadata),
        }

    def to_json(self) -> str:
        return to_json(self.to_dict())

    @classmethod
    def from_json(cls, text: str) -> "DocumentPage":
        return cls.from_dict(load_json_object(text, cls.contract_type))

    @classmethod
    def from_dict(cls, data: Any) -> "DocumentPage":
        if isinstance(data, cls):
            return data
        if not isinstance(data, Mapping):
            raise ContractValidationError("document_page must be a mapping")
        _validate_contract_type(data, cls.contract_type)
        return cls(
            page_number=data.get("page_number"),
            status=data.get("status", DocumentPageStatus.COMPLETE.value),
            blocks=_mapping_sequence(data, "blocks", "document_page.blocks"),
            text=data.get("text", ""),
            markdown=data.get("markdown", ""),
            confidence=data.get("confidence"),
            provenance=DocumentProvenance.from_dict(data.get("provenance", {})),
            diagnostics=data.get("diagnostics", ()),
            metadata=data.get("metadata", {}),
            schema_version=data.get("schema_version", CONTRACT_SCHEMA_VERSION),
        )


def _all_result_diagnostics(
    pages: tuple[DocumentPage, ...],
    diagnostics: tuple[ContractDiagnostic, ...],
) -> tuple[ContractDiagnostic, ...]:
    collected: list[ContractDiagnostic] = list(diagnostics)
    for page in pages:
        collected.extend(page.diagnostics)
        for block in page.blocks:
            collected.extend(block.diagnostics)
    return tuple(collected)


def _validate_result_status(
    status: DocumentExtractionStatus,
    pages: tuple[DocumentPage, ...],
    diagnostics: tuple[ContractDiagnostic, ...],
) -> None:
    all_diagnostics = _all_result_diagnostics(pages, diagnostics)
    has_error_diagnostic = any(diagnostic.severity == "error" for diagnostic in all_diagnostics)
    degraded_statuses = {DocumentPageStatus.PARTIAL, DocumentPageStatus.FAILED, DocumentPageStatus.SKIPPED}
    degraded_pages = [page.page_number for page in pages if page.status in degraded_statuses]
    failed_pages = [page.page_number for page in pages if page.status == DocumentPageStatus.FAILED]
    if status == DocumentExtractionStatus.COMPLETE:
        if degraded_pages:
            pages_text = ", ".join(str(page_number) for page_number in degraded_pages)
            raise ContractValidationError(f"document_extraction.status complete cannot include degraded page(s): {pages_text}")
        if has_error_diagnostic:
            raise ContractValidationError("document_extraction.status complete cannot include error diagnostics")
    elif status == DocumentExtractionStatus.PARTIAL:
        if not degraded_pages and not all_diagnostics:
            raise ContractValidationError("document_extraction.status partial requires degraded pages or diagnostics")
    elif status == DocumentExtractionStatus.FAILED and not failed_pages and not has_error_diagnostic:
        raise ContractValidationError("document_extraction.status failed requires failed pages or error diagnostics")


@dataclass(frozen=True)
class DocumentExtractionResult:
    """A deterministic, tool-neutral document extraction result."""

    document_id: str = ""
    source_uri: str = ""
    source_path: str = ""
    content_hash: Checksum | None = None
    mime_type: str = ""
    status: DocumentExtractionStatus | str = DocumentExtractionStatus.COMPLETE
    pages: tuple[DocumentPage, ...] = field(default_factory=tuple)
    artifacts: tuple[ArtifactRef, ...] = field(default_factory=tuple)
    provenance: DocumentProvenance = field(default_factory=DocumentProvenance)
    diagnostics: tuple[ContractDiagnostic, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = CONTRACT_SCHEMA_VERSION

    contract_type: ClassVar[str] = "brain_lab.document_extraction_result"
    page_type: ClassVar[type[DocumentPage]] = DocumentPage

    def __post_init__(self) -> None:
        document_id = _optional_text(self.document_id)
        if not document_id:
            raise ContractValidationError("document_extraction.document_id is required")
        source_uri = _optional_text(self.source_uri)
        source_path = _optional_text(self.source_path)
        content_hash = _optional_checksum(self.content_hash)
        mime_type = _optional_text(self.mime_type)
        status = _enum_value(DocumentExtractionStatus, self.status, "document_extraction.status")
        diagnostics = _diagnostic_tuple(self.diagnostics)
        pages = tuple(self.page_type.from_dict(page) for page in _sequence_tuple(self.pages, "document_extraction.pages"))
        page_numbers = [page.page_number for page in pages]
        duplicate_page_numbers = sorted({page_number for page_number in page_numbers if page_numbers.count(page_number) > 1})
        if duplicate_page_numbers:
            duplicates = ", ".join(str(page_number) for page_number in duplicate_page_numbers)
            raise ContractValidationError(f"duplicate page_number(s): {duplicates}")
        raw_provenance = DocumentProvenance.from_dict(self.provenance)
        nested_provenance = [raw_provenance]
        for page in pages:
            nested_provenance.append(page.provenance)
            nested_provenance.extend(block.provenance for block in page.blocks)
        source_uri = _unique_source_value(
            [source_uri, *(provenance.source_uri for provenance in nested_provenance)],
            "source_uri",
        ) or ""
        source_path = _unique_source_value(
            [source_path, *(provenance.source_path for provenance in nested_provenance)],
            "source_path",
        ) or ""
        content_hash = _unique_source_value(
            [content_hash, *(provenance.content_hash for provenance in nested_provenance)],
            "content_hash",
        )
        if not source_uri and not source_path and content_hash is None:
            raise ContractValidationError("document_extraction source_uri, source_path, or content_hash is required")
        provenance = _sync_source_provenance(
            raw_provenance,
            source_uri=source_uri,
            source_path=source_path,
            content_hash=content_hash,
            field_name="document_extraction.provenance",
        )
        normalized_pages: list[DocumentPage] = []
        for page in pages:
            page_provenance = _sync_source_provenance(
                page.provenance,
                source_uri=source_uri,
                source_path=source_path,
                content_hash=content_hash,
                field_name=f"document_extraction.pages[{page.page_number}].provenance",
            )
            normalized_blocks: list[DocumentBlock] = []
            for block in page.blocks:
                block_provenance = _sync_source_provenance(
                    block.provenance,
                    source_uri=source_uri,
                    source_path=source_path,
                    content_hash=content_hash,
                    field_name=f"document_extraction.pages[{page.page_number}].blocks[{block.block_id}].provenance",
                )
                if block_provenance != block.provenance:
                    block = replace(block, provenance=block_provenance)
                normalized_blocks.append(block)
            if page_provenance != page.provenance or tuple(normalized_blocks) != page.blocks:
                page = replace(page, provenance=page_provenance, blocks=tuple(normalized_blocks))
            normalized_pages.append(page)
        normalized_pages_tuple = tuple(sorted(normalized_pages, key=lambda page: page.page_number))
        _validate_result_status(status, normalized_pages_tuple, diagnostics)
        artifacts = tuple(
            ArtifactRef.from_dict(artifact)
            for artifact in _sequence_tuple(self.artifacts, "document_extraction.artifacts")
        )
        object.__setattr__(self, "document_id", document_id)
        object.__setattr__(self, "source_uri", source_uri)
        object.__setattr__(self, "source_path", source_path)
        object.__setattr__(self, "content_hash", content_hash)
        object.__setattr__(self, "mime_type", mime_type)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "pages", normalized_pages_tuple)
        object.__setattr__(self, "artifacts", artifacts)
        object.__setattr__(self, "provenance", provenance)
        object.__setattr__(self, "diagnostics", diagnostics)
        object.__setattr__(self, "metadata", _metadata(self.metadata))
        object.__setattr__(self, "schema_version", _schema_version(self.schema_version))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            **contract_header(self.contract_type, self.schema_version),
            "document_id": self.document_id,
            "source_uri": self.source_uri,
            "source_path": self.source_path,
            "content_hash": self.content_hash.to_dict() if self.content_hash else None,
            "mime_type": self.mime_type,
            "status": self.status.value,
            "pages": [page.to_dict() for page in self.pages],
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "provenance": self.provenance.to_dict(),
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "metadata": dict(self.metadata),
        }

    def to_json(self) -> str:
        return to_json(self.to_dict())

    @classmethod
    def from_json(cls, text: str) -> "DocumentExtractionResult":
        return cls.from_dict(load_json_object(text, cls.contract_type))

    @classmethod
    def from_dict(cls, data: Any) -> "DocumentExtractionResult":
        if isinstance(data, cls):
            return data
        if not isinstance(data, Mapping):
            raise ContractValidationError("document_extraction must be a mapping")
        _validate_contract_type(data, cls.contract_type)
        return cls(
            document_id=data.get("document_id", ""),
            source_uri=data.get("source_uri", ""),
            source_path=data.get("source_path", ""),
            content_hash=_optional_checksum(data.get("content_hash")),
            mime_type=data.get("mime_type", ""),
            status=data.get("status", DocumentExtractionStatus.COMPLETE.value),
            pages=_mapping_sequence(data, "pages", "document_extraction.pages"),
            artifacts=_mapping_sequence(data, "artifacts", "document_extraction.artifacts"),
            provenance=DocumentProvenance.from_dict(data.get("provenance", {})),
            diagnostics=data.get("diagnostics", ()),
            metadata=data.get("metadata", {}),
            schema_version=data.get("schema_version", CONTRACT_SCHEMA_VERSION),
        )


@dataclass(frozen=True)
class PdfBlock(DocumentBlock):
    """PDF-specific block contract using the same normalized block fields."""

    contract_type: ClassVar[str] = "brain_lab.pdf_block"


@dataclass(frozen=True)
class PdfPageResult(DocumentPage):
    """PDF page result with PDF block normalization."""

    contract_type: ClassVar[str] = "brain_lab.pdf_page_result"
    block_type: ClassVar[type[DocumentBlock]] = PdfBlock


@dataclass(frozen=True)
class PdfExtractionResult(DocumentExtractionResult):
    """PDF extraction result over page-aware PDF page records."""

    contract_type: ClassVar[str] = "brain_lab.pdf_extraction_result"
    page_type: ClassVar[type[DocumentPage]] = PdfPageResult

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.mime_type and self.mime_type.lower() not in {"application/pdf", "application/x-pdf"}:
            raise ContractValidationError("pdf_extraction.mime_type must be application/pdf when provided")
