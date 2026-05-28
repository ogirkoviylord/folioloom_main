import unittest
from pathlib import Path

from translator_service.document_sandbox import DocumentSandbox
from translator_service.documents import (
    DocumentFormat,
    UnsupportedDocumentError,
    validate_document_upload,
)
from translator_service.order_estimates import (
    estimate_epub_order,
    estimate_order,
    estimate_txt_order,
)
from translator_service.pricing import PricingRules

TEST_SAMPLES_DIR = Path(__file__).resolve().parents[1] / "test_samples"


class TxtOrderEstimateTest(unittest.TestCase):
    def test_estimates_valid_txt_order_before_payment(self):
        upload = validate_document_upload(
            file_name="notes.txt",
            size_bytes=36,
            max_upload_mb=50,
        )

        estimate = estimate_txt_order(
            upload=upload,
            content="Первый абзац.\n\nВторой абзац длиннее.".encode(),
            pricing_rules=PricingRules(
                deepseek_input_usd_per_million_tokens=0.28,
                expected_output_multiplier=1.2,
                service_markup_multiplier=3.0,
                minimum_price_usd=0.10,
            ),
            max_fragment_chars=20,
        )

        self.assertEqual(estimate.file_name, "notes.txt")
        self.assertEqual(estimate.document_format, DocumentFormat.TXT)
        self.assertEqual(estimate.character_count, 36)
        self.assertEqual(estimate.estimated_input_tokens, 70)
        self.assertEqual(estimate.fragment_count, 2)
        self.assertEqual(estimate.price_usd, 0.10)

    def test_rejects_non_txt_upload_for_txt_estimator(self):
        upload = validate_document_upload(
            file_name="book.epub",
            size_bytes=100,
            max_upload_mb=50,
        )

        with self.assertRaises(ValueError) as error:
            estimate_txt_order(
                upload=upload,
                content=b"plain text",
                pricing_rules=PricingRules(
                    deepseek_input_usd_per_million_tokens=0.28,
                    expected_output_multiplier=1.2,
                    service_markup_multiplier=3.0,
                    minimum_price_usd=0.10,
                ),
                max_fragment_chars=20,
            )

        self.assertIn("TXT", str(error.exception))

    def test_estimate_order_dispatches_txt_uploads(self):
        upload = validate_document_upload(
            file_name="notes.txt",
            size_bytes=9,
            max_upload_mb=50,
        )

        estimate = estimate_order(
            upload=upload,
            content=b"Some text",
            pricing_rules=PricingRules(
                deepseek_input_usd_per_million_tokens=0.28,
                expected_output_multiplier=1.2,
                service_markup_multiplier=3.0,
                minimum_price_usd=0.10,
            ),
            max_fragment_chars=100,
        )

        self.assertEqual(estimate.file_name, "notes.txt")
        self.assertEqual(estimate.document_format, DocumentFormat.TXT)

    def test_estimate_order_can_use_sandboxed_adapter_plan(self):
        upload = validate_document_upload(
            file_name="notes.txt",
            size_bytes=9,
            max_upload_mb=50,
        )
        sandbox = RecordingPlanSandbox()

        estimate = estimate_order(
            upload=upload,
            content=b"Some text",
            pricing_rules=PricingRules(
                deepseek_input_usd_per_million_tokens=0.28,
                expected_output_multiplier=1.2,
                service_markup_multiplier=3.0,
                minimum_price_usd=0.10,
            ),
            max_fragment_chars=100,
            document_sandbox=sandbox,
        )

        self.assertEqual(
            sandbox.calls,
            [(DocumentFormat.TXT, b"Some text", 100)],
        )
        self.assertEqual(estimate.file_name, "notes.txt")
        self.assertEqual(estimate.document_format, DocumentFormat.TXT)
        self.assertEqual(estimate.character_count, 9)
        self.assertEqual(estimate.fragment_count, 1)

    def test_pdf_is_rejected_before_order_estimation(self):
        with self.assertRaises(UnsupportedDocumentError) as error:
            validate_document_upload(
                file_name="scan.pdf",
                size_bytes=100,
                max_upload_mb=50,
            )

        self.assertIn("TXT, DOCX, and EPUB", str(error.exception))
        self.assertNotIn("scan.pdf", str(error.exception))

    def test_estimate_order_dispatches_docx_uploads(self):
        upload = validate_document_upload(
            file_name="contract.docx",
            size_bytes=500,
            max_upload_mb=50,
        )

        estimate = estimate_order(
            upload=upload,
            content=_make_docx(
                """
                <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                  <w:body>
                    <w:p><w:r><w:t>First paragraph</w:t></w:r></w:p>
                    <w:p><w:r><w:t>Second paragraph</w:t></w:r></w:p>
                  </w:body>
                </w:document>
                """
            ),
            pricing_rules=PricingRules(
                deepseek_input_usd_per_million_tokens=0.28,
                expected_output_multiplier=1.2,
                service_markup_multiplier=3.0,
                minimum_price_usd=0.10,
            ),
            max_fragment_chars=100,
        )

        self.assertEqual(estimate.file_name, "contract.docx")
        self.assertEqual(estimate.document_format, DocumentFormat.DOCX)
        self.assertEqual(estimate.character_count, 33)
        self.assertEqual(estimate.fragment_count, 1)

    def test_docx_estimate_counts_headers_footers_notes_and_comments(self):
        upload = validate_document_upload(
            file_name="stress.docx",
            size_bytes=500,
            max_upload_mb=50,
        )

        estimate = estimate_order(
            upload=upload,
            content=_make_docx(
                """
                <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                  <w:body><w:p><w:r><w:t>Main</w:t></w:r></w:p></w:body>
                </w:document>
                """,
                extra_parts={
                    "word/header1.xml": _docx_part_xml("Header"),
                    "word/footer1.xml": _docx_part_xml("Footer"),
                    "word/footnotes.xml": _docx_part_xml("Footnote"),
                    "word/endnotes.xml": _docx_part_xml("Endnote"),
                    "word/comments.xml": _docx_part_xml("Comment"),
                },
            ),
            pricing_rules=PricingRules(
                deepseek_input_usd_per_million_tokens=0.28,
                expected_output_multiplier=1.2,
                service_markup_multiplier=3.0,
                minimum_price_usd=0.10,
            ),
            max_fragment_chars=100,
        )

        self.assertEqual(estimate.character_count, 48)
        self.assertEqual(estimate.fragment_count, 1)

    def test_docx_estimate_counts_structural_table_unit_separately(self):
        upload = validate_document_upload(
            file_name="table.docx",
            size_bytes=500,
            max_upload_mb=50,
        )

        estimate = estimate_order(
            upload=upload,
            content=_make_docx(
                """
                <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                  <w:body>
                    <w:p><w:r><w:t>Intro paragraph.</w:t></w:r></w:p>
                    <w:tbl>
                      <w:tr>
                        <w:tc><w:p><w:r><w:t>Source</w:t></w:r></w:p></w:tc>
                        <w:tc><w:p><w:r><w:t>Target</w:t></w:r></w:p></w:tc>
                      </w:tr>
                    </w:tbl>
                    <w:p><w:r><w:t>Outro paragraph.</w:t></w:r></w:p>
                  </w:body>
                </w:document>
                """
            ),
            pricing_rules=PricingRules(
                deepseek_input_usd_per_million_tokens=0.28,
                expected_output_multiplier=1.2,
                service_markup_multiplier=3.0,
                minimum_price_usd=0.10,
            ),
            max_fragment_chars=1_000,
        )

        self.assertEqual(estimate.fragment_count, 3)

    def test_docx_estimate_accepts_russian_profile_regression_sample(self):
        path = TEST_SAMPLES_DIR / "russian_profile_regression.en-ru.docx"
        upload = validate_document_upload(
            file_name=path.name,
            size_bytes=path.stat().st_size,
            max_upload_mb=50,
        )

        estimate = estimate_order(
            upload=upload,
            content=path.read_bytes(),
            pricing_rules=PricingRules(
                deepseek_input_usd_per_million_tokens=0.28,
                expected_output_multiplier=1.2,
                service_markup_multiplier=3.0,
                minimum_price_usd=0.10,
            ),
            max_fragment_chars=300,
        )

        self.assertEqual(estimate.document_format, DocumentFormat.DOCX)
        self.assertGreater(estimate.character_count, 1_000)
        self.assertEqual(estimate.fragment_count, 10)
        self.assertGreater(estimate.estimated_input_tokens, 700)

    def test_estimate_order_dispatches_epub_uploads(self):
        upload = validate_document_upload(
            file_name="book.epub",
            size_bytes=500,
            max_upload_mb=50,
        )

        estimate = estimate_order(
            upload=upload,
            content=_make_epub(
                {
                    "OPS/chapter.xhtml": """
                    <html xmlns="http://www.w3.org/1999/xhtml">
                      <body>
                        <h1>Title</h1>
                        <p>First paragraph.</p>
                      </body>
                    </html>
                    """
                }
            ),
            pricing_rules=PricingRules(
                deepseek_input_usd_per_million_tokens=0.28,
                expected_output_multiplier=1.2,
                service_markup_multiplier=3.0,
                minimum_price_usd=0.10,
            ),
            max_fragment_chars=100,
        )

        self.assertEqual(estimate.file_name, "book.epub")
        self.assertEqual(estimate.document_format, DocumentFormat.EPUB)
        self.assertEqual(estimate.character_count, 23)
        self.assertEqual(estimate.fragment_count, 1)

    def test_epub_estimate_counts_grouped_api_fragments_not_xhtml_blocks(self):
        upload = validate_document_upload(
            file_name="book.epub",
            size_bytes=500,
            max_upload_mb=50,
        )

        estimate = estimate_order(
            upload=upload,
            content=_make_epub(
                {
                    "OPS/chapter.xhtml": """
                    <html xmlns="http://www.w3.org/1999/xhtml">
                      <body>
                        <p>One short paragraph.</p>
                        <p>Two short paragraph.</p>
                        <p>Three short paragraph.</p>
                      </body>
                    </html>
                    """
                }
            ),
            pricing_rules=PricingRules(
                deepseek_input_usd_per_million_tokens=0.28,
                expected_output_multiplier=1.2,
                service_markup_multiplier=3.0,
                minimum_price_usd=0.10,
            ),
            max_fragment_chars=50,
        )

        self.assertEqual(estimate.fragment_count, 2)

    def test_epub_estimate_counts_auxiliary_navigation_but_not_noise_blocks(self):
        upload = validate_document_upload(
            file_name="book.epub",
            size_bytes=500,
            max_upload_mb=50,
        )

        estimate = estimate_order(
            upload=upload,
            content=_make_epub(
                {
                    "OPS/front.xhtml": """
                    <html xmlns="http://www.w3.org/1999/xhtml">
                      <body>
                        <h1>Contents</h1>
                        <p>Chapter 1</p>
                        <p>Chapter 2</p>
                      </body>
                    </html>
                    """,
                    "OPS/chapter.xhtml": """
                    <html xmlns="http://www.w3.org/1999/xhtml">
                      <body>
                        <h1>Chapter 1</h1>
                        <p>* * *</p>
                        <p>First real paragraph of the book.</p>
                      </body>
                    </html>
                    """,
                }
            ),
            pricing_rules=PricingRules(
                deepseek_input_usd_per_million_tokens=0.28,
                expected_output_multiplier=1.2,
                service_markup_multiplier=3.0,
                minimum_price_usd=0.10,
            ),
            max_fragment_chars=60,
        )

        self.assertEqual(estimate.character_count, 76)
        self.assertEqual(estimate.fragment_count, 4)

    def test_epub_estimate_counts_structural_table_unit_separately(self):
        upload = validate_document_upload(
            file_name="book.epub",
            size_bytes=500,
            max_upload_mb=50,
        )

        estimate = estimate_order(
            upload=upload,
            content=_make_epub(
                {
                    "OPS/chapter.xhtml": """
                    <html xmlns="http://www.w3.org/1999/xhtml">
                      <body>
                        <p>Intro paragraph.</p>
                        <table>
                          <tr><td>Source</td><td>Target</td></tr>
                        </table>
                        <p>Outro paragraph.</p>
                      </body>
                    </html>
                    """
                }
            ),
            pricing_rules=PricingRules(
                deepseek_input_usd_per_million_tokens=0.28,
                expected_output_multiplier=1.2,
                service_markup_multiplier=3.0,
                minimum_price_usd=0.10,
            ),
            max_fragment_chars=1_000,
        )

        self.assertEqual(estimate.fragment_count, 3)

    def test_epub_estimate_accepts_russian_profile_regression_sample(self):
        path = TEST_SAMPLES_DIR / "russian_profile_regression.en-ru.epub"
        upload = validate_document_upload(
            file_name=path.name,
            size_bytes=path.stat().st_size,
            max_upload_mb=50,
        )

        content = path.read_bytes()
        estimate = estimate_order(
            upload=upload,
            content=content,
            pricing_rules=PricingRules(
                deepseek_input_usd_per_million_tokens=0.28,
                expected_output_multiplier=1.2,
                service_markup_multiplier=3.0,
                minimum_price_usd=0.10,
            ),
            max_fragment_chars=300,
        )
        from translator_service.format_adapters import plan_epub_translation

        expected_plan = plan_epub_translation(
            content=content,
            max_fragment_chars=300,
        )

        self.assertEqual(estimate.document_format, DocumentFormat.EPUB)
        self.assertGreater(estimate.character_count, 1_000)
        self.assertEqual(estimate.fragment_count, expected_plan.fragment_count)
        self.assertGreater(estimate.estimated_input_tokens, 400)

    def test_rejects_non_epub_upload_for_epub_estimator(self):
        upload = validate_document_upload(
            file_name="notes.txt",
            size_bytes=100,
            max_upload_mb=50,
        )

        with self.assertRaises(ValueError) as error:
            estimate_epub_order(
                upload=upload,
                content=b"plain text",
                pricing_rules=PricingRules(
                    deepseek_input_usd_per_million_tokens=0.28,
                    expected_output_multiplier=1.2,
                    service_markup_multiplier=3.0,
                    minimum_price_usd=0.10,
                ),
                max_fragment_chars=20,
            )

        self.assertIn("EPUB", str(error.exception))


if __name__ == "__main__":
    unittest.main()


def _make_docx(document_xml: str, extra_parts: dict[str, str] | None = None) -> bytes:
    from io import BytesIO
    from zipfile import ZipFile

    archive = BytesIO()
    with ZipFile(archive, "w") as docx:
        docx.writestr("word/document.xml", document_xml)
        for file_name, content in (extra_parts or {}).items():
            docx.writestr(file_name, content)
    return archive.getvalue()


def _docx_part_xml(text: str) -> str:
    return f"""
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body>
    </w:document>
    """


def _make_epub(xhtml_items: dict[str, str]) -> bytes:
    from io import BytesIO
    from zipfile import ZipFile

    archive = BytesIO()
    with ZipFile(archive, "w") as epub:
        epub.writestr("mimetype", "application/epub+zip")
        epub.writestr("META-INF/container.xml", "<container />")
        for file_name, content in xhtml_items.items():
            epub.writestr(file_name, content)
    return archive.getvalue()


class RecordingPlanSandbox(DocumentSandbox):
    def __init__(self) -> None:
        self.calls: list[tuple[DocumentFormat, bytes, int]] = []

    def plan_translation(
        self,
        *,
        document_format: DocumentFormat,
        content: bytes,
        max_fragment_chars: int,
        translation_mode: str | None = None,
    ):
        self.calls.append((document_format, content, max_fragment_chars))
        from translator_service.format_adapters import plan_txt_translation

        return plan_txt_translation(
            content=content,
            max_fragment_chars=max_fragment_chars,
        )
