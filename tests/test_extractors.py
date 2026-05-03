import unittest
from io import BytesIO
from zipfile import ZipFile

from translator_service.extractors import (
    TextExtractionError,
    extract_text_from_docx,
    extract_text_from_txt,
)


class TxtExtractionTest(unittest.TestCase):
    def test_extracts_utf8_text_from_txt_bytes(self):
        text = extract_text_from_txt("Привет\nмир".encode("utf-8"))

        self.assertEqual(text, "Привет\nмир")

    def test_removes_utf8_byte_order_mark(self):
        text = extract_text_from_txt(b"\xef\xbb\xbfHello")

        self.assertEqual(text, "Hello")

    def test_rejects_bytes_that_are_not_utf8_text(self):
        with self.assertRaises(TextExtractionError):
            extract_text_from_txt(b"\xff\xfe\x00\x00")

    def test_rejects_empty_text_after_decoding(self):
        with self.assertRaises(TextExtractionError):
            extract_text_from_txt(" \n\t ".encode("utf-8"))


if __name__ == "__main__":
    unittest.main()


class DocxExtractionTest(unittest.TestCase):
    def test_extracts_paragraph_text_from_docx_bytes(self):
        content = _make_docx(
            """
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body>
                <w:p><w:r><w:t>Первый</w:t></w:r><w:r><w:t> абзац</w:t></w:r></w:p>
                <w:p><w:r><w:t>Второй абзац</w:t></w:r></w:p>
              </w:body>
            </w:document>
            """
        )

        text = extract_text_from_docx(content)

        self.assertEqual(text, "Первый абзац\n\nВторой абзац")

    def test_rejects_docx_without_document_xml(self):
        archive = BytesIO()
        with ZipFile(archive, "w") as docx:
            docx.writestr("[Content_Types].xml", "<Types />")

        with self.assertRaises(TextExtractionError):
            extract_text_from_docx(archive.getvalue())

    def test_rejects_docx_without_translatable_text(self):
        content = _make_docx(
            """
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body><w:p><w:r><w:t>   </w:t></w:r></w:p></w:body>
            </w:document>
            """
        )

        with self.assertRaises(TextExtractionError):
            extract_text_from_docx(content)

    def test_rejects_invalid_docx_archive(self):
        with self.assertRaises(TextExtractionError):
            extract_text_from_docx(b"not a zip")


def _make_docx(document_xml: str) -> bytes:
    archive = BytesIO()
    with ZipFile(archive, "w") as docx:
        docx.writestr("word/document.xml", document_xml)
    return archive.getvalue()
