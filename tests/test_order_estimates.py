import unittest

from translator_service.documents import DocumentFormat, validate_document_upload
from translator_service.order_estimates import (
    DocumentEstimationNotReadyError,
    estimate_order,
    estimate_txt_order,
)
from translator_service.pricing import PricingRules


class TxtOrderEstimateTest(unittest.TestCase):
    def test_estimates_valid_txt_order_before_payment(self):
        upload = validate_document_upload(
            file_name="notes.txt",
            size_bytes=36,
            max_upload_mb=50,
        )

        estimate = estimate_txt_order(
            upload=upload,
            content="Первый абзац.\n\nВторой абзац длиннее.".encode("utf-8"),
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
        self.assertEqual(estimate.estimated_input_tokens, 9)
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

    def test_estimate_order_reports_formats_that_are_not_ready_yet(self):
        upload = validate_document_upload(
            file_name="book.epub",
            size_bytes=100,
            max_upload_mb=50,
        )

        with self.assertRaises(DocumentEstimationNotReadyError) as error:
            estimate_order(
                upload=upload,
                content=b"not used yet",
                pricing_rules=PricingRules(
                    deepseek_input_usd_per_million_tokens=0.28,
                    expected_output_multiplier=1.2,
                    service_markup_multiplier=3.0,
                    minimum_price_usd=0.10,
                ),
                max_fragment_chars=100,
            )

        self.assertIn("epub", str(error.exception))

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


if __name__ == "__main__":
    unittest.main()


def _make_docx(document_xml: str) -> bytes:
    from io import BytesIO
    from zipfile import ZipFile

    archive = BytesIO()
    with ZipFile(archive, "w") as docx:
        docx.writestr("word/document.xml", document_xml)
    return archive.getvalue()
