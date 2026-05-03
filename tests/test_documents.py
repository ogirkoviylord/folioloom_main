import unittest

from translator_service.documents import (
    DocumentFormat,
    FileTooLargeError,
    EmptyDocumentError,
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


if __name__ == "__main__":
    unittest.main()
