import io
import unittest
from zipfile import ZIP_DEFLATED, ZipFile

from scripts.generate_sample_documents import _zip_writestr
from scripts.generate_sample_documents import (
    _russian_regression_docx_document_xml,
    _russian_regression_epub_chapters,
)


class SampleDocumentGeneratorTest(unittest.TestCase):
    def test_zip_entries_use_stable_timestamps(self):
        archive_bytes = io.BytesIO()

        with ZipFile(archive_bytes, "w") as archive:
            _zip_writestr(
                archive,
                "word/document.xml",
                "<document />",
                compress_type=ZIP_DEFLATED,
            )

        with ZipFile(io.BytesIO(archive_bytes.getvalue())) as archive:
            info = archive.getinfo("word/document.xml")

        self.assertEqual(info.date_time, (2026, 1, 1, 0, 0, 0))

    def test_russian_regression_docx_xml_contains_rich_format_cases(self):
        document_xml = _russian_regression_docx_document_xml()

        self.assertIn("Russian Profile Regression", document_xml)
        self.assertIn("He made a decision after a high-level overview", document_xml)
        self.assertIn("Set the API endpoint", document_xml)
        self.assertIn("Maria Johnson visited Baker Street", document_xml)
        self.assertIn("${API_TOKEN}", document_xml)
        self.assertIn("<w:tbl>", document_xml)

    def test_russian_regression_epub_chapters_cover_mixed_and_protected_cases(self):
        chapters = _russian_regression_epub_chapters()

        self.assertEqual(set(chapters), {"OPS/ru-profile-1.xhtml", "OPS/ru-profile-2.xhtml"})
        combined = "\n".join(chapters.values())
        self.assertIn("Russian Profile Regression", combined)
        self.assertIn("The room held its breath", combined)
        self.assertIn("English: The endpoint failed", combined)
        self.assertIn("Zażółć gęślą jaźń", combined)
        self.assertIn("https://example.com/v1/items", combined)
        self.assertIn("<strong>API endpoint</strong>", combined)


if __name__ == "__main__":
    unittest.main()
