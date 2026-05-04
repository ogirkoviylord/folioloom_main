import unittest
from io import BytesIO
from zipfile import ZipFile

from translator_service.extractors import (
    TextExtractionError,
    extract_text_from_docx,
    extract_text_from_epub,
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


class EpubExtractionTest(unittest.TestCase):
    def test_extracts_visible_text_from_epub_xhtml_items(self):
        content = _make_epub(
            {
                "OPS/chapter1.xhtml": """
                <html xmlns="http://www.w3.org/1999/xhtml">
                  <head><title>Ignored title</title><style>.x { color: red; }</style></head>
                  <body>
                    <h1>Глава первая</h1>
                    <p>Первый абзац <em>книги</em>.</p>
                    <script>ignored()</script>
                  </body>
                </html>
                """,
                "OPS/chapter2.xhtml": """
                <html xmlns="http://www.w3.org/1999/xhtml">
                  <body><p>Второй абзац.</p></body>
                </html>
                """,
            }
        )

        text = extract_text_from_epub(content)

        self.assertEqual(text, "Глава первая\n\nПервый абзац книги.\n\nВторой абзац.")

    def test_extracts_epub_text_in_spine_order_not_archive_order(self):
        content = _make_epub(
            {
                "OPS/chapter2.xhtml": """
                <html xmlns="http://www.w3.org/1999/xhtml">
                  <body><p>Second chapter.</p></body>
                </html>
                """,
                "OPS/chapter1.xhtml": """
                <html xmlns="http://www.w3.org/1999/xhtml">
                  <body><p>First chapter.</p></body>
                </html>
                """,
            },
            spine=["OPS/chapter1.xhtml", "OPS/chapter2.xhtml"],
        )

        text = extract_text_from_epub(content)

        self.assertEqual(text, "First chapter.\n\nSecond chapter.")

    def test_rejects_epub_without_translatable_text(self):
        content = _make_epub(
            {
                "OPS/chapter.xhtml": """
                <html xmlns="http://www.w3.org/1999/xhtml">
                  <body><p>   </p><script>ignored()</script></body>
                </html>
                """,
            }
        )

        with self.assertRaises(TextExtractionError):
            extract_text_from_epub(content)

    def test_rejects_invalid_epub_archive(self):
        with self.assertRaises(TextExtractionError):
            extract_text_from_epub(b"not a zip")


def _make_docx(document_xml: str) -> bytes:
    archive = BytesIO()
    with ZipFile(archive, "w") as docx:
        docx.writestr("word/document.xml", document_xml)
    return archive.getvalue()


def _make_epub(xhtml_items: dict[str, str], spine: list[str] | None = None) -> bytes:
    archive = BytesIO()
    spine = spine or list(xhtml_items)
    manifest_items = "\n".join(
        f'<item id="item{index}" href="{file_name}" media-type="application/xhtml+xml" />'
        for index, file_name in enumerate(xhtml_items)
    )
    spine_items = "\n".join(
        f'<itemref idref="item{list(xhtml_items).index(file_name)}" />'
        for file_name in spine
    )
    with ZipFile(archive, "w") as epub:
        epub.writestr("mimetype", "application/epub+zip")
        epub.writestr(
            "META-INF/container.xml",
            """
            <container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
              <rootfiles>
                <rootfile full-path="OPS/content.opf" media-type="application/oebps-package+xml" />
              </rootfiles>
            </container>
            """,
        )
        epub.writestr(
            "OPS/content.opf",
            f"""
            <package xmlns="http://www.idpf.org/2007/opf">
              <manifest>{manifest_items}</manifest>
              <spine>{spine_items}</spine>
            </package>
            """,
        )
        for file_name, content in xhtml_items.items():
            epub.writestr(file_name, content)
        epub.writestr("OPS/style.css", "body { font-family: serif; }")
    return archive.getvalue()
