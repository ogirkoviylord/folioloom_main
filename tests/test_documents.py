import unittest

from translator_service.document_scanner import (
    FakeDocumentScanner,
    ScannerVerdict,
    ScanResult,
)
from translator_service.documents import (
    DocumentFormat,
    EmptyDocumentError,
    FileTooLargeError,
    UnsupportedDocumentError,
    validate_document_upload,
)


class DocumentUploadValidationTest(unittest.TestCase):
    def test_accepts_supported_document_extensions_case_insensitively(self):
        cases = {
            "novel.epub": DocumentFormat.EPUB,
            "contract.DOCX": DocumentFormat.DOCX,
            "scan.Pdf": DocumentFormat.PDF,
            "notes.TXT": DocumentFormat.TXT,
        }

        for file_name, expected_format in cases.items():
            with self.subTest(file_name=file_name):
                upload = validate_document_upload(
                    file_name=file_name,
                    size_bytes=1024,
                    max_upload_mb=50,
                )

                self.assertEqual(upload.file_name, file_name)
                self.assertEqual(upload.document_format, expected_format)
                self.assertEqual(upload.size_bytes, 1024)

    def test_rejects_unsupported_extension(self):
        with self.assertRaises(UnsupportedDocumentError) as error:
            validate_document_upload(
                file_name="archive.zip",
                size_bytes=1024,
                max_upload_mb=50,
            )

        self.assertIn("archive.zip", str(error.exception))

    def test_rejects_file_without_extension(self):
        with self.assertRaises(UnsupportedDocumentError):
            validate_document_upload(
                file_name="document",
                size_bytes=1024,
                max_upload_mb=50,
            )

    def test_rejects_file_that_exceeds_upload_limit(self):
        with self.assertRaises(FileTooLargeError) as error:
            validate_document_upload(
                file_name="large.pdf",
                size_bytes=51 * 1024 * 1024,
                max_upload_mb=50,
            )

        self.assertIn("50 MB", str(error.exception))

    def test_rejects_empty_file(self):
        with self.assertRaises(EmptyDocumentError):
            validate_document_upload(
                file_name="empty.txt",
                size_bytes=0,
                max_upload_mb=50,
            )


class DocumentScannerContractTest(unittest.TestCase):
    def test_scanner_verdict_contract_includes_fail_closed_states(self):
        self.assertEqual(ScannerVerdict.CLEAN.value, "clean")
        self.assertEqual(ScannerVerdict.INFECTED.value, "infected")
        self.assertEqual(ScannerVerdict.SCANNER_TIMEOUT.value, "scanner_timeout")
        self.assertEqual(
            ScannerVerdict.SCANNER_UNAVAILABLE.value,
            "scanner_unavailable",
        )
        self.assertEqual(ScannerVerdict.SCANNER_ERROR.value, "scanner_error")
        self.assertEqual(ScannerVerdict.UNSUPPORTED.value, "unsupported")
        self.assertEqual(
            ScannerVerdict.SUSPICIOUS_CONTAINER.value,
            "suspicious_container",
        )

    def test_scan_result_metadata_is_safe_and_does_not_include_raw_text(self):
        result = ScanResult(
            verdict=ScannerVerdict.SCANNER_ERROR,
            scanner_name="fake-scanner",
            scanner_version="test-1",
            signature_database_version="fixtures-2026-05-23",
            content_sha256="abc123",
            size_bytes=23,
            document_format=DocumentFormat.TXT,
            safe_error_class="scanner_error",
        )

        metadata = result.safe_metadata()

        self.assertEqual(
            metadata,
            {
                "verdict": "scanner_error",
                "scanner_name": "fake-scanner",
                "scanner_version": "test-1",
                "signature_database_version": "fixtures-2026-05-23",
                "content_sha256": "abc123",
                "size_bytes": 23,
                "document_format": "txt",
                "safe_error_class": "scanner_error",
            },
        )
        self.assertNotIn("raw", metadata)
        self.assertNotIn("text", metadata)

    def test_fake_scanner_returns_configured_verdict_with_content_hash(self):
        scanner = FakeDocumentScanner(
            default_verdict=ScannerVerdict.INFECTED,
            scanner_version="test-1",
            signature_database_version="fixtures",
        )

        result = scanner.scan(
            file_name="notes.txt",
            content=b"private source text",
            document_format=DocumentFormat.TXT,
        )

        self.assertEqual(result.verdict, ScannerVerdict.INFECTED)
        self.assertEqual(result.size_bytes, len(b"private source text"))
        self.assertEqual(result.document_format, DocumentFormat.TXT)
        self.assertNotIn("private source text", str(result.safe_metadata()))


if __name__ == "__main__":
    unittest.main()
