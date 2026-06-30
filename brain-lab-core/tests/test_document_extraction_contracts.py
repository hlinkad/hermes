from __future__ import annotations

import json
import sys
import unittest

from brain_lab_core.contracts import (
    ArtifactId,
    ArtifactRef,
    Checksum,
    ContractDiagnostic,
    ContractValidationError,
    DocumentBlock,
    DocumentBlockKind,
    DocumentExtractionResult,
    DocumentExtractionStatus,
    DocumentPage,
    DocumentPageStatus,
    DocumentProvenance,
    PdfBlock,
    PdfExtractionResult,
    PdfPageResult,
    SourceSpan,
)
from brain_lab_core.registry import ToolRegistry, mineru_document_extraction_manifest


class DocumentExtractionContractTests(unittest.TestCase):
    def _checksum(self, value: str = "a") -> Checksum:
        return Checksum("sha256", value * 64)

    def _artifact_ref(self, value: str, artifact_type: str, uri: str) -> ArtifactRef:
        return ArtifactRef(
            artifact_id=ArtifactId(value, namespace="mineru"),
            artifact_type=artifact_type,
            artifact_schema_version=f"{artifact_type}.v1",
            uri=uri,
            checksum=self._checksum("b"),
            producer_tool_id="mineru-api",
            producer_stage_id="extract-pdf",
        )

    def _provenance(
        self,
        *,
        page_number: int | None = None,
        block_id: str = "",
        block_span: SourceSpan | None = None,
        diagnostics: tuple[ContractDiagnostic, ...] = (),
    ) -> DocumentProvenance:
        return DocumentProvenance(
            source_uri="file:///workspace/fixtures/sample.pdf",
            source_path="/workspace/fixtures/sample.pdf",
            content_hash=self._checksum(),
            page_number=page_number,
            page_span=SourceSpan(kind="page", start=page_number, end=page_number, unit="page")
            if page_number is not None
            else SourceSpan(kind="unknown"),
            block_id=block_id,
            block_span=block_span or SourceSpan(kind="unknown"),
            extractor_name="mineru-api",
            extractor_version="3.4.0",
            extracted_at="2026-06-30T17:45:00Z",
            diagnostics=diagnostics,
            metadata={"service_boundary": "http", "tags": {"pdf", "mineru"}},
        )

    def test_pdf_result_round_trips_representative_pages_blocks_artifacts_and_diagnostics(self) -> None:
        text_block = PdfBlock(
            block_id="p1-b001",
            kind=DocumentBlockKind.TEXT,
            order=0,
            text="Introductory paragraph from the born-digital PDF.",
            span=SourceSpan(kind="text", start=0, end=48, unit="char"),
            confidence=0.99,
            provenance=self._provenance(
                page_number=1,
                block_id="p1-b001",
                block_span=SourceSpan(kind="text", start=0, end=48, unit="char"),
            ),
        )
        table_block = PdfBlock(
            block_id="p1-b002",
            kind="table",
            order=1,
            table={"headers": ["Metric", "Value"], "rows": [["pages", "4"]]},
            text="Metric | Value\npages | 4",
            confidence=0.91,
            provenance=self._provenance(page_number=1, block_id="p1-b002"),
        )
        image_block = PdfBlock(
            block_id="p1-b003",
            kind=DocumentBlockKind.IMAGE,
            order=2,
            image={"asset_uri": "artifacts/assets/page-1-figure.png", "alt_text": "workflow figure"},
            confidence=0.84,
            provenance=self._provenance(page_number=1, block_id="p1-b003"),
        )
        formula_block = PdfBlock(
            block_id="p1-b004",
            kind=DocumentBlockKind.FORMULA,
            order=3,
            formula="E = mc^2",
            text="E = mc^2",
            confidence=0.88,
            provenance=self._provenance(page_number=1, block_id="p1-b004"),
        )
        ocr_warning = ContractDiagnostic(
            code="ocr.low_confidence",
            message="OCR produced low-confidence text on scanned page 2.",
            severity="warning",
            location="pages[1].blocks[0]",
        )
        ocr_block = PdfBlock(
            block_id="p2-b001",
            kind=DocumentBlockKind.OCR_TEXT,
            order=0,
            text="Scanned page text",
            ocr_text="Scanned page text",
            confidence=0.62,
            diagnostics=(ocr_warning,),
            provenance=self._provenance(page_number=2, block_id="p2-b001", diagnostics=(ocr_warning,)),
        )
        page_failure = ContractDiagnostic(
            code="page.parse_failed",
            message="Page 4 could not be parsed, but earlier pages are still usable.",
            severity="error",
            location="pages[3]",
        )
        page_one = PdfPageResult(
            page_number=1,
            blocks=(formula_block, text_block, image_block, table_block),
            text="Introductory paragraph from the born-digital PDF.\nMetric | Value\npages | 4\nE = mc^2",
            markdown="Introductory paragraph from the born-digital PDF.\n\n| Metric | Value |\n| --- | --- |\n| pages | 4 |\n\n![workflow figure](assets/page-1-figure.png)\n\nE = mc^2",
            confidence=0.94,
            provenance=self._provenance(page_number=1),
        )
        scanned_page = PdfPageResult(
            page_number=2,
            status=DocumentPageStatus.PARTIAL,
            blocks=(ocr_block,),
            text="Scanned page text",
            markdown="Scanned page text",
            confidence=0.62,
            diagnostics=(ocr_warning,),
            provenance=self._provenance(page_number=2, diagnostics=(ocr_warning,)),
        )
        empty_page = PdfPageResult(
            page_number=3,
            status="empty",
            blocks=(),
            text="",
            markdown="",
            provenance=self._provenance(page_number=3),
        )
        failed_page = PdfPageResult(
            page_number=4,
            status=DocumentPageStatus.FAILED,
            blocks=(),
            diagnostics=(page_failure,),
            provenance=self._provenance(page_number=4, diagnostics=(page_failure,)),
        )
        result = PdfExtractionResult(
            document_id="sample-pdf",
            source_uri="file:///workspace/fixtures/sample.pdf",
            source_path="/workspace/fixtures/sample.pdf",
            content_hash=self._checksum(),
            mime_type="application/pdf",
            status=DocumentExtractionStatus.PARTIAL,
            pages=(page_one, scanned_page, empty_page, failed_page),
            artifacts=(
                self._artifact_ref("sample-pdf-markdown", "document.markdown", "artifacts/sample.md"),
                self._artifact_ref("sample-pdf-assets", "document.assets", "artifacts/assets/"),
            ),
            provenance=self._provenance(diagnostics=(page_failure, ocr_warning)),
            diagnostics=(page_failure, ocr_warning),
            metadata={"fixture": True, "source_policy": "unknown"},
        )

        loaded = PdfExtractionResult.from_json(result.to_json())

        self.assertEqual(loaded, result)
        self.assertEqual(loaded.to_dict()["contract_type"], "brain_lab.pdf_extraction_result")
        self.assertEqual(loaded.pages[0].blocks[0].block_id, "p1-b001")
        self.assertEqual(loaded.pages[0].blocks[1].kind, DocumentBlockKind.TABLE)
        self.assertEqual(loaded.pages[1].blocks[0].ocr_text, "Scanned page text")
        self.assertEqual(loaded.pages[2].status, DocumentPageStatus.EMPTY)
        self.assertEqual(loaded.pages[3].diagnostics[0].code, "page.parse_failed")
        self.assertEqual(loaded.artifacts[0].artifact_type, "document.markdown")
        self.assertEqual(
            json.loads(loaded.provenance.to_json())["metadata"]["tags"],
            ["mineru", "pdf"],
        )
        self.assertEqual(loaded.to_json(), PdfExtractionResult.from_dict(loaded.to_dict()).to_json())
        json.dumps(loaded.to_dict(), sort_keys=True)

    def test_generic_document_contracts_support_plain_text_and_deterministic_ordering(self) -> None:
        result = DocumentExtractionResult(
            document_id="plain-text",
            source_uri="file:///workspace/fixtures/plain.txt",
            content_hash=self._checksum("c"),
            mime_type="text/plain",
            pages=(
                DocumentPage(
                    page_number=1,
                    blocks=(
                        DocumentBlock(block_id="b2", kind="text", order=2, text="second"),
                        DocumentBlock(block_id="b1", kind="text", order=1, text="first"),
                    ),
                    text="first\nsecond",
                    markdown="first\nsecond",
                ),
            ),
        )

        loaded = DocumentExtractionResult.from_json(result.to_json())

        self.assertEqual(loaded.pages[0].blocks[0].block_id, "b1")
        self.assertEqual(loaded.pages[0].blocks[1].block_id, "b2")
        self.assertEqual(loaded.status, DocumentExtractionStatus.COMPLETE)
        self.assertEqual(loaded.to_json(), DocumentExtractionResult.from_dict(loaded.to_dict()).to_json())

    def test_provenance_is_autofilled_and_consistency_checked_across_document_page_and_block(self) -> None:
        result = DocumentExtractionResult(
            document_id="plain-text",
            source_uri="file:///workspace/fixtures/plain.txt",
            source_path="/workspace/fixtures/plain.txt",
            content_hash=self._checksum("d"),
            pages=(
                DocumentPage(
                    page_number=7,
                    blocks=(DocumentBlock(block_id="p7-b1", kind="text", order=0, text="body"),),
                    text="body",
                ),
            ),
        )

        page = result.pages[0]
        block = page.blocks[0]
        self.assertEqual(result.provenance.source_uri, result.source_uri)
        self.assertEqual(result.provenance.source_path, result.source_path)
        self.assertEqual(result.provenance.content_hash, result.content_hash)
        self.assertEqual(page.provenance.page_number, 7)
        self.assertEqual(page.provenance.page_span, SourceSpan(kind="page", start=7, end=7, unit="page"))
        self.assertEqual(page.provenance.source_uri, result.source_uri)
        self.assertEqual(block.provenance.page_number, 7)
        self.assertEqual(block.provenance.block_id, "p7-b1")
        self.assertEqual(block.provenance.source_path, result.source_path)

        with self.assertRaisesRegex(ContractValidationError, "page_number"):
            DocumentPage(page_number=7, provenance=DocumentProvenance(page_number=8))
        with self.assertRaisesRegex(ContractValidationError, "block_id"):
            DocumentBlock(
                block_id="actual",
                kind="text",
                order=0,
                text="body",
                provenance=DocumentProvenance(block_id="other"),
            )
        with self.assertRaisesRegex(ContractValidationError, "source_uri"):
            DocumentExtractionResult(
                document_id="source-mismatch",
                source_uri="file:///workspace/fixtures/plain.txt",
                pages=(
                    DocumentPage(
                        page_number=1,
                        provenance=DocumentProvenance(source_uri="file:///workspace/fixtures/other.txt"),
                    ),
                ),
            )
        with self.assertRaisesRegex(ContractValidationError, "source_uri"):
            DocumentExtractionResult(
                document_id="nested-source-mismatch",
                source_path="/workspace/fixtures/plain.txt",
                pages=(
                    DocumentPage(
                        page_number=1,
                        blocks=(
                            DocumentBlock(
                                block_id="b1",
                                kind="text",
                                order=0,
                                text="body",
                                provenance=DocumentProvenance(source_uri="file:///workspace/fixtures/block.txt"),
                            ),
                        ),
                        provenance=DocumentProvenance(source_uri="file:///workspace/fixtures/page.txt"),
                    ),
                ),
            )
        with self.assertRaisesRegex(ContractValidationError, "page_span"):
            DocumentPage(
                page_number=1,
                provenance=DocumentProvenance(page_span=SourceSpan(kind="text", start=0, end=5, unit="char")),
            )
        with self.assertRaisesRegex(ContractValidationError, "numeric page boundaries"):
            DocumentPage(
                page_number=1,
                provenance=DocumentProvenance(page_span=SourceSpan(kind="page", start="1", end="1", unit="page")),
            )
        with self.assertRaisesRegex(ContractValidationError, "block_span"):
            DocumentBlock(
                block_id="span-mismatch",
                kind="text",
                order=0,
                text="body",
                span=SourceSpan(kind="text", start=0, end=4, unit="char"),
                provenance=DocumentProvenance(
                    block_id="span-mismatch",
                    block_span=SourceSpan(kind="text", start=5, end=9, unit="char"),
                ),
            )
        with self.assertRaisesRegex(ContractValidationError, "blocks\[page-span-mismatch\].span"):
            DocumentPage(
                page_number=1,
                blocks=(
                    DocumentBlock(
                        block_id="page-span-mismatch",
                        kind="text",
                        order=0,
                        text="body",
                        span=SourceSpan(kind="page", start=2, end=2, unit="page"),
                    ),
                ),
            )
        with self.assertRaisesRegex(ContractValidationError, "provenance.block_span"):
            DocumentPage(
                page_number=1,
                blocks=(
                    DocumentBlock(
                        block_id="provenance-page-span-mismatch",
                        kind="text",
                        order=0,
                        text="body",
                        provenance=DocumentProvenance(
                            block_id="provenance-page-span-mismatch",
                            block_span=SourceSpan(kind="page", start=2, end=2, unit="page"),
                        ),
                    ),
                ),
            )
        with self.assertRaisesRegex(ContractValidationError, "unit"):
            DocumentPage(
                page_number=1,
                blocks=(
                    DocumentBlock(
                        block_id="bad-page-span-unit",
                        kind="text",
                        order=0,
                        text="body",
                        span=SourceSpan(kind="page", start=1, end=1, unit="char"),
                    ),
                ),
            )

    def test_block_payload_validation_is_kind_specific_with_diagnostic_escape_hatch(self) -> None:
        with self.assertRaisesRegex(ContractValidationError, "text is required"):
            DocumentBlock(block_id="text-missing", kind=DocumentBlockKind.TEXT, order=0)
        with self.assertRaisesRegex(ContractValidationError, "table"):
            DocumentBlock(block_id="table-missing", kind=DocumentBlockKind.TABLE, order=0)
        with self.assertRaisesRegex(ContractValidationError, "table"):
            DocumentBlock(block_id="table-empty", kind=DocumentBlockKind.TABLE, order=0, table={"rows": []})
        with self.assertRaisesRegex(ContractValidationError, "image"):
            DocumentBlock(block_id="image-missing", kind=DocumentBlockKind.IMAGE, order=0)
        with self.assertRaisesRegex(ContractValidationError, "image"):
            DocumentBlock(block_id="image-empty", kind=DocumentBlockKind.IMAGE, order=0, image={"asset_uri": ""})
        with self.assertRaisesRegex(ContractValidationError, "formula"):
            DocumentBlock(block_id="formula-missing", kind=DocumentBlockKind.FORMULA, order=0)
        with self.assertRaisesRegex(ContractValidationError, "ocr_text"):
            DocumentBlock(block_id="ocr-missing", kind=DocumentBlockKind.OCR_TEXT, order=0)

        unrelated = ContractDiagnostic(code="ocr.low_confidence", message="OCR confidence is low.")
        with self.assertRaisesRegex(ContractValidationError, "text is required"):
            DocumentBlock(block_id="text-unrelated-diagnostic", kind="text", order=0, diagnostics=(unrelated,))

        diagnostic = ContractDiagnostic(
            code="extractor.empty_block",
            message="The extractor reported an empty table block with geometry only.",
        )
        self.assertEqual(
            DocumentBlock(
                block_id="table-diagnostic",
                kind=DocumentBlockKind.TABLE,
                order=0,
                diagnostics=(diagnostic,),
            ).diagnostics,
            (diagnostic,),
        )

    def test_document_status_and_pdf_mime_type_are_consistent_with_normalized_pages(self) -> None:
        extraction_error = ContractDiagnostic(
            code="extractor.page_failed",
            message="The extractor failed on page 1.",
            severity="error",
        )
        with self.assertRaisesRegex(ContractValidationError, "complete"):
            DocumentExtractionResult(
                document_id="complete-with-failure",
                source_uri="file:///tmp/a.pdf",
                pages=(DocumentPage(page_number=1, status=DocumentPageStatus.FAILED, diagnostics=(extraction_error,)),),
            )
        with self.assertRaisesRegex(ContractValidationError, "cannot include blocks"):
            DocumentPage(page_number=1, status=DocumentPageStatus.EMPTY, text="unexpected")
        with self.assertRaisesRegex(ContractValidationError, "cannot include blocks"):
            DocumentPage(
                page_number=1,
                status=DocumentPageStatus.SKIPPED,
                blocks=(DocumentBlock(block_id="skipped-body", kind="text", order=0, text="unexpected"),),
            )
        with self.assertRaisesRegex(ContractValidationError, "failed requires an error diagnostic"):
            DocumentPage(page_number=1, status=DocumentPageStatus.FAILED)
        with self.assertRaisesRegex(ContractValidationError, "use partial"):
            DocumentPage(page_number=1, status=DocumentPageStatus.FAILED, text="salvaged", diagnostics=(extraction_error,))
        with self.assertRaisesRegex(ContractValidationError, "partial"):
            DocumentExtractionResult(
                document_id="partial-without-evidence",
                source_uri="file:///tmp/a.pdf",
                status=DocumentExtractionStatus.PARTIAL,
                pages=(DocumentPage(page_number=1),),
            )
        with self.assertRaisesRegex(ContractValidationError, "failed"):
            DocumentExtractionResult(
                document_id="failed-without-error",
                source_uri="file:///tmp/a.pdf",
                status=DocumentExtractionStatus.FAILED,
                pages=(DocumentPage(page_number=1),),
            )
        with self.assertRaisesRegex(ContractValidationError, "application/pdf"):
            PdfExtractionResult(
                document_id="not-a-pdf",
                source_uri="file:///tmp/a.txt",
                mime_type="text/plain",
                pages=(PdfPageResult(page_number=1),),
            )

    def test_malformed_document_shapes_raise_actionable_validation_errors(self) -> None:
        with self.assertRaisesRegex(ContractValidationError, "document_id"):
            DocumentExtractionResult(source_uri="file:///tmp/a.pdf")
        with self.assertRaisesRegex(ContractValidationError, "document_id"):
            DocumentExtractionResult(document_id="", source_uri="file:///tmp/a.pdf")
        with self.assertRaisesRegex(ContractValidationError, "source"):
            DocumentExtractionResult(document_id="missing-source")
        with self.assertRaisesRegex(ContractValidationError, "page_number.*required"):
            DocumentPage()
        with self.assertRaisesRegex(ContractValidationError, "page_number"):
            DocumentPage(page_number=0)
        with self.assertRaisesRegex(ContractValidationError, "duplicate block_id"):
            DocumentPage(
                page_number=1,
                blocks=(
                    DocumentBlock(block_id="dup", kind="text", order=1, text="first"),
                    DocumentBlock(block_id="dup", kind="text", order=2, text="second"),
                ),
            )
        with self.assertRaisesRegex(ContractValidationError, "document_block.block_id"):
            DocumentBlock(kind="text", order=0, text="body")
        with self.assertRaisesRegex(ContractValidationError, "document_block.kind.*required"):
            DocumentBlock(block_id="missing-kind", order=0, text="body")
        with self.assertRaisesRegex(ContractValidationError, "document_block.order.*required"):
            DocumentBlock(block_id="missing-order", kind="text", text="body")
        with self.assertRaisesRegex(ContractValidationError, "document_block.kind"):
            DocumentBlock(block_id="bad", kind="unsupported", order=0)
        with self.assertRaisesRegex(ContractValidationError, "confidence"):
            DocumentBlock(block_id="bad", kind="text", order=0, confidence=1.5)
        with self.assertRaisesRegex(ContractValidationError, "duplicate page_number"):
            DocumentExtractionResult(
                document_id="dup-pages",
                source_uri="file:///tmp/a.pdf",
                pages=(DocumentPage(page_number=1), DocumentPage(page_number=1)),
            )
        with self.assertRaisesRegex(ContractValidationError, "duplicate block order"):
            DocumentPage(
                page_number=1,
                blocks=(
                    DocumentBlock(block_id="b1", kind="text", order=1, text="first"),
                    DocumentBlock(block_id="b2", kind="text", order=1, text="second"),
                ),
            )
        with self.assertRaisesRegex(ContractValidationError, "document_page.blocks"):
            DocumentPage.from_dict({"page_number": 1, "blocks": None})
        with self.assertRaisesRegex(ContractValidationError, "page_number.*required"):
            DocumentPage.from_dict({"blocks": []})
        with self.assertRaisesRegex(ContractValidationError, "document_extraction.pages"):
            DocumentExtractionResult.from_dict(
                {"document_id": "bad-pages", "source_uri": "file:///tmp/a.pdf", "pages": None}
            )
        with self.assertRaisesRegex(ContractValidationError, "document_extraction.artifacts"):
            DocumentExtractionResult.from_dict(
                {"document_id": "bad-artifacts", "source_uri": "file:///tmp/a.pdf", "artifacts": None}
            )

    def test_mineru_manifest_is_metadata_only_and_discoverable_without_importing_mineru(self) -> None:
        had_mineru = "mineru" in sys.modules
        existing_mineru = sys.modules.get("mineru")
        sys.modules.pop("mineru", None)
        try:
            manifest = mineru_document_extraction_manifest()
            registry = ToolRegistry([manifest])
            discovery = registry.discovery_document()

            self.assertEqual(manifest.validate(), ())
            self.assertEqual(registry.tools_for_capability("pdf.extract"), (manifest,))
            self.assertEqual(registry.tools_for_capability("ocr.extract"), (manifest,))
            self.assertEqual(registry.tools_producing_artifact_type("document.extraction"), (manifest,))
            self.assertEqual(registry.tools_producing_artifact_type("pdf.extraction"), (manifest,))
            self.assertEqual(discovery["tools"][0]["tool_id"], "mineru-api")
            self.assertEqual(
                discovery["tools"][0]["metadata"]["artifact_contracts"]["pdf_normalized_json"],
                "pdf.extraction",
            )
            self.assertLessEqual(
                {"GET /health", "POST /file_parse", "GET /tasks/{task_id}/result"},
                set(discovery["tools"][0]["metadata"]["service_endpoints"]),
            )
            manifest_text = json.dumps(discovery, sort_keys=True).lower()
            self.assertIn("qdrant and obsidian remain downstream consumers", manifest_text)
            allowed_capabilities = {"document.extract", "pdf.extract", "ocr.extract"}
            allowed_inputs = {"source.document", "source.pdf", "source.file"}
            allowed_outputs = {"document.extraction", "pdf.extraction", "document.markdown", "document.assets"}
            self.assertEqual(set(manifest.capabilities), allowed_capabilities)
            self.assertEqual(set(manifest.input_artifact_types), allowed_inputs)
            self.assertEqual(set(manifest.output_artifact_types), allowed_outputs)
            for public_type in (*manifest.capabilities, *manifest.input_artifact_types, *manifest.output_artifact_types):
                self.assertNotRegex(public_type, r"(?:qdrant|obsidian|retrieval\.|vault\.)")
            self.assertNotIn("mineru", sys.modules)
            json.dumps(discovery, sort_keys=True)
        finally:
            if had_mineru and existing_mineru is not None:
                sys.modules["mineru"] = existing_mineru
            else:
                sys.modules.pop("mineru", None)


if __name__ == "__main__":
    unittest.main()
