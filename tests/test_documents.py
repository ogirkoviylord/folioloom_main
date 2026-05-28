import unittest
import zipfile
from io import BytesIO
from unittest.mock import patch

import translator_service.documents as documents
from translator_service.document_scanner import (
    FakeDocumentScanner,
    ScannerVerdict,
    ScanResult,
)
from translator_service.documents import (
    DocumentContentRejectedError,
    DocumentFormat,
    EmptyDocumentError,
    FileTooLargeError,
    UnsupportedDocumentError,
    validate_document_content,
    validate_document_upload,
)


class DocumentUploadValidationTest(unittest.TestCase):
    def test_accepts_supported_document_extensions_case_insensitively(self):
        cases = {
            "novel.epub": DocumentFormat.EPUB,
            "contract.DOCX": DocumentFormat.DOCX,
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

    def test_rejects_unsupported_extensions_without_echoing_file_name(self):
        for file_name in (
            "legacy.doc",
            "macro.docm",
            "archive.zip",
            "archive.rar",
            "installer.exe",
        ):
            with self.subTest(file_name=file_name):
                with self.assertRaises(UnsupportedDocumentError) as error:
                    validate_document_upload(
                        file_name=file_name,
                        size_bytes=1024,
                        max_upload_mb=50,
                    )

                self.assertIn("TXT, DOCX, and EPUB", str(error.exception))
                self.assertNotIn(file_name, str(error.exception))

    def test_rejects_pdf_extension(self):
        with self.assertRaises(UnsupportedDocumentError) as error:
            validate_document_upload(
                file_name="scan.Pdf",
                size_bytes=1024,
                max_upload_mb=50,
            )

        self.assertIn("TXT, DOCX, and EPUB", str(error.exception))
        self.assertNotIn("scan.Pdf", str(error.exception))

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
                file_name="large.txt",
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


class DocumentContentValidationTest(unittest.TestCase):
    def test_accepts_matching_txt_docx_and_epub_content(self):
        validate_document_content(
            file_name="notes.txt",
            content=b"\xef\xbb\xbfThis is UTF-8 text.",
            document_format=DocumentFormat.TXT,
        )
        validate_document_content(
            file_name="book.docx",
            content=_make_zip({"word/document.xml": b"<w:document />"}),
            document_format=DocumentFormat.DOCX,
        )
        validate_document_content(
            file_name="book.epub",
            content=_make_zip(
                {
                    "mimetype": b"application/epub+zip",
                    "META-INF/container.xml": b"<container />",
                    "OPS/chapter.xhtml": b"<html><body><p>Text.</p></body></html>",
                }
            ),
            document_format=DocumentFormat.EPUB,
        )

    def test_rejects_binary_looking_txt_without_leaking_content(self):
        private_text = "PRIVATE SOURCE TEXT"

        with self.assertRaises(DocumentContentRejectedError) as error:
            validate_document_content(
                file_name="notes.txt",
                content=b"\x00\x01PRIVATE SOURCE TEXT",
                document_format=DocumentFormat.TXT,
            )

        self.assertEqual(error.exception.safe_error_class, "binary_txt")
        self.assertNotIn(private_text, str(error.exception))

    def test_rejects_invalid_utf8_txt_without_leaking_content(self):
        with self.assertRaises(DocumentContentRejectedError) as error:
            validate_document_content(
                file_name="notes.txt",
                content=b"\xff\xfePRIVATE SOURCE TEXT",
                document_format=DocumentFormat.TXT,
            )

        self.assertEqual(error.exception.safe_error_class, "invalid_txt_utf8")
        self.assertNotIn("PRIVATE SOURCE TEXT", str(error.exception))

    def test_rejects_docx_that_is_not_a_readable_zip(self):
        with self.assertRaises(DocumentContentRejectedError) as error:
            validate_document_content(
                file_name="book.docx",
                content=b"plain text masquerading as docx",
                document_format=DocumentFormat.DOCX,
            )

        self.assertEqual(error.exception.safe_error_class, "zip_invalid_signature")

    def test_rejects_corrupt_zip_with_valid_local_header_signature(self):
        with self.assertRaises(DocumentContentRejectedError) as error:
            validate_document_content(
                file_name="book.docx",
                content=b"PK\x03\x04corrupt zip body",
                document_format=DocumentFormat.DOCX,
            )

        self.assertEqual(error.exception.safe_error_class, "zip_corrupt")
        self.assertTrue(error.exception.container_failed)

    def test_rejects_docx_missing_expected_document_part(self):
        with self.assertRaises(DocumentContentRejectedError) as error:
            validate_document_content(
                file_name="book.docx",
                content=_make_zip({"word/styles.xml": b"<w:styles />"}),
                document_format=DocumentFormat.DOCX,
            )

        self.assertEqual(error.exception.safe_error_class, "docx_missing_document")

    def test_rejects_archive_traversal_and_absolute_paths(self):
        cases = (
            (
                DocumentFormat.DOCX,
                "book.docx",
                {"word/document.xml": b"<w:document />"},
            ),
            (
                DocumentFormat.EPUB,
                "book.epub",
                {
                    "mimetype": b"application/epub+zip",
                    "META-INF/container.xml": b"<container />",
                },
            ),
        )
        for document_format, file_name, required_members in cases:
            for member_name in ("../evil.txt", "/absolute/evil.txt", "C:/evil.txt"):
                members = dict(required_members)
                members[member_name] = b"unsafe"
                with self.subTest(
                    document_format=document_format.value,
                    member_name=member_name,
                ):
                    with self.assertRaises(DocumentContentRejectedError) as error:
                        validate_document_content(
                            file_name=file_name,
                            content=_make_zip(members),
                            document_format=document_format,
                        )

                    self.assertEqual(
                        error.exception.safe_error_class,
                        "unsafe_archive_path",
                    )
                    self.assertNotIn(member_name, str(error.exception))

    def test_rejects_executable_looking_embedded_archive_members(self):
        cases = (
            (
                DocumentFormat.DOCX,
                "book.docx",
                {
                    "word/document.xml": b"<w:document />",
                    "word/media/payload.exe": b"MZ",
                },
                "word/media/payload.exe",
            ),
            (
                DocumentFormat.EPUB,
                "book.epub",
                {
                    "mimetype": b"application/epub+zip",
                    "META-INF/container.xml": b"<container />",
                    "OPS/scripts/install.bat": b"echo unsafe",
                },
                "OPS/scripts/install.bat",
            ),
        )

        for document_format, file_name, members, unsafe_member in cases:
            with self.subTest(document_format=document_format.value):
                with self.assertRaises(DocumentContentRejectedError) as error:
                    validate_document_content(
                        file_name=file_name,
                        content=_make_zip(members),
                        document_format=document_format,
                    )

                self.assertEqual(
                    error.exception.safe_error_class,
                    "executable_archive_member",
                )
                self.assertNotIn(unsafe_member, str(error.exception))

    def test_rejects_extension_content_mismatch(self):
        epub_content = _make_zip(
            {
                "mimetype": b"application/epub+zip",
                "META-INF/container.xml": b"<container />",
                "OPS/chapter.xhtml": b"<html><body><p>Text.</p></body></html>",
            }
        )

        with self.assertRaises(DocumentContentRejectedError) as error:
            validate_document_content(
                file_name="book.docx",
                content=epub_content,
                document_format=DocumentFormat.DOCX,
            )

        self.assertEqual(error.exception.safe_error_class, "docx_missing_document")

        docx_content = _make_zip({"word/document.xml": b"<w:document />"})
        with self.assertRaises(DocumentContentRejectedError) as error:
            validate_document_content(
                file_name="book.epub",
                content=docx_content,
                document_format=DocumentFormat.EPUB,
            )

        self.assertEqual(error.exception.safe_error_class, "epub_missing_mimetype")

    def test_rejects_archives_with_too_many_entries(self):
        content = _make_zip(
            {f"word/extra-{index}.xml": b"<x />" for index in range(513)}
            | {"word/document.xml": b"<w:document />"}
        )

        with self.assertRaises(DocumentContentRejectedError) as error:
            validate_document_content(
                file_name="book.docx",
                content=content,
                document_format=DocumentFormat.DOCX,
            )

        self.assertEqual(error.exception.safe_error_class, "archive_too_many_entries")

    def test_rejects_oversized_member_and_total_uncompressed_content(self):
        with patch.object(documents, "MAX_ARCHIVE_MEMBER_BYTES", 10):
            with self.assertRaises(DocumentContentRejectedError) as error:
                validate_document_content(
                    file_name="book.docx",
                    content=_make_zip({"word/document.xml": b"x" * 11}),
                    document_format=DocumentFormat.DOCX,
                )

        self.assertEqual(error.exception.safe_error_class, "archive_member_too_large")

        with patch.object(documents, "MAX_ARCHIVE_UNCOMPRESSED_BYTES", 20):
            with self.assertRaises(DocumentContentRejectedError) as error:
                validate_document_content(
                    file_name="book.docx",
                    content=_make_zip(
                        {
                            "word/document.xml": b"x" * 11,
                            "word/header1.xml": b"x" * 10,
                        }
                    ),
                    document_format=DocumentFormat.DOCX,
                )

        self.assertEqual(
            error.exception.safe_error_class,
            "archive_uncompressed_too_large",
        )

    def test_rejects_zip_bomb_like_high_compression_ratio(self):
        cases = (
            (
                DocumentFormat.DOCX,
                "book.docx",
                {"word/document.xml": b"x" * 1000},
            ),
            (
                DocumentFormat.EPUB,
                "book.epub",
                {
                    "mimetype": b"application/epub+zip",
                    "META-INF/container.xml": b"<container />",
                    "OPS/chapter.xhtml": b"x" * 1000,
                },
            ),
        )
        with patch.object(documents, "MAX_ARCHIVE_COMPRESSION_RATIO", 2):
            for document_format, file_name, members in cases:
                with self.subTest(document_format=document_format.value):
                    with self.assertRaises(DocumentContentRejectedError) as error:
                        validate_document_content(
                            file_name=file_name,
                            content=_make_zip(
                                members,
                                compression=zipfile.ZIP_DEFLATED,
                            ),
                            document_format=document_format,
                        )

                    self.assertEqual(
                        error.exception.safe_error_class,
                        "archive_compression_ratio",
                    )

    def test_rejects_epub_missing_expected_structure(self):
        with self.assertRaises(DocumentContentRejectedError) as error:
            validate_document_content(
                file_name="book.epub",
                content=_make_zip({"OPS/chapter.xhtml": b"<html />"}),
                document_format=DocumentFormat.EPUB,
            )

        self.assertEqual(error.exception.safe_error_class, "epub_missing_mimetype")


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


def _make_zip(
    members: dict[str, bytes],
    *,
    compression: int = zipfile.ZIP_STORED,
) -> bytes:
    archive = BytesIO()
    with zipfile.ZipFile(archive, "w", compression=compression) as zip_file:
        for name, content in members.items():
            zip_file.writestr(name, content)
    return archive.getvalue()


if __name__ == "__main__":
    unittest.main()
