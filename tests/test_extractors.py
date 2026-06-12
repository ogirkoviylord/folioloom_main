import unittest
import warnings
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from translator_service.extractors import (
    TextExtractionError,
    MAX_ARCHIVE_ENTRY_COUNT,
    MAX_ARCHIVE_UNCOMPRESSED_BYTES,
    MAX_EPUB_TEXT_BLOCKS,
    MAX_XML_BYTES,
    MAX_XML_DEPTH,
    MAX_XML_ELEMENT_COUNT,
    extract_text_from_docx,
    extract_text_from_epub,
    extract_text_from_txt,
)


TEST_SAMPLES_DIR = Path(__file__).resolve().parents[1] / "test_samples"


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

    def test_extracts_docx_text_from_headers_footers_notes_and_comments(self):
        content = _make_docx(
            """
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body><w:p><w:r><w:t>Основной текст</w:t></w:r></w:p></w:body>
            </w:document>
            """,
            extra_parts={
                "word/header1.xml": _docx_part_xml("Колонтитул сверху"),
                "word/footer1.xml": _docx_part_xml("Колонтитул снизу"),
                "word/footnotes.xml": _docx_part_xml("Текст сноски"),
                "word/endnotes.xml": _docx_part_xml("Текст endnote"),
                "word/comments.xml": _docx_part_xml("Текст комментария"),
            },
        )

        text = extract_text_from_docx(content)

        self.assertEqual(
            text,
            "Основной текст\n\n"
            "Колонтитул сверху\n\n"
            "Колонтитул снизу\n\n"
            "Текст сноски\n\n"
            "Текст endnote\n\n"
            "Текст комментария",
        )

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

    def test_rejects_docx_with_excessive_uncompressed_size(self):
        archive = BytesIO()
        with ZipFile(archive, "w", compression=ZIP_DEFLATED) as docx:
            docx.writestr("word/document.xml", b"x" * (MAX_ARCHIVE_UNCOMPRESSED_BYTES + 1))

        with self.assertRaises(TextExtractionError):
            extract_text_from_docx(archive.getvalue())

    def test_rejects_docx_with_too_many_archive_entries(self):
        archive = BytesIO()
        with ZipFile(archive, "w") as docx:
            docx.writestr("word/document.xml", _docx_part_xml("Text"))
            for index in range(MAX_ARCHIVE_ENTRY_COUNT):
                docx.writestr(f"word/header{index}.xml", _docx_part_xml("Header"))

        with self.assertRaises(TextExtractionError):
            extract_text_from_docx(archive.getvalue())

    def test_rejects_docx_xml_part_above_xml_limit(self):
        archive = BytesIO()
        with ZipFile(archive, "w", compression=ZIP_DEFLATED) as docx:
            docx.writestr(
                "word/document.xml",
                b"<w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\">"
                + b" " * MAX_XML_BYTES
                + b"</w:document>",
            )

        with self.assertRaisesRegex(TextExtractionError, "XML part is too large"):
            extract_text_from_docx(archive.getvalue())

    def test_rejects_docx_xml_with_excessive_depth(self):
        content = _make_docx(_deep_docx_xml(MAX_XML_DEPTH + 1))

        with self.assertRaisesRegex(TextExtractionError, "XML nesting is too deep"):
            extract_text_from_docx(content)

    def test_rejects_docx_xml_entities_before_parsing(self):
        content = _make_docx(
            """
            <!DOCTYPE document [<!ENTITY injected "boom">]>
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body><w:p><w:r><w:t>&injected;</w:t></w:r></w:p></w:body>
            </w:document>
            """
        )

        with self.assertRaisesRegex(TextExtractionError, "XML entities are not supported"):
            extract_text_from_docx(content)

    def test_rejects_docx_xml_with_too_many_elements(self):
        repeated_runs = "<w:r><w:t>x</w:t></w:r>" * (MAX_XML_ELEMENT_COUNT // 2)
        content = _make_docx(
            f"""
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body><w:p>{repeated_runs}</w:p></w:body>
            </w:document>
            """
        )

        with self.assertRaisesRegex(TextExtractionError, "too many elements"):
            extract_text_from_docx(content)

    def test_extracts_russian_profile_regression_docx_sample(self):
        content = (TEST_SAMPLES_DIR / "russian_profile_regression.en-ru.docx").read_bytes()

        text = extract_text_from_docx(content)

        self.assertIn("Russian Profile Regression", text)
        self.assertIn("He made a decision after a high-level overview", text)
        self.assertIn("Set the API endpoint", text)
        self.assertIn("English: The endpoint failed", text)
        self.assertIn("Maria Johnson visited Baker Street", text)
        self.assertIn("${API_TOKEN}", text)
        self.assertIn("Russian profile regression header", text)
        self.assertIn("Footnote: preserve API endpoint terminology.", text)


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

    def test_extracts_legacy_epub_xhtml_with_doctype_and_html_entities(self):
        content = _make_epub(
            {
                "OPS/chapter.xhtml": """
                <!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN"
                  "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
                <html xmlns="http://www.w3.org/1999/xhtml">
                  <body><p>First&nbsp;&mdash;&nbsp;second.</p></body>
                </html>
                """
            }
        )

        text = extract_text_from_epub(content)

        self.assertEqual(text, "First — second.")

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

    def test_rejects_epub_with_malformed_container_xml(self):
        archive = BytesIO()
        with ZipFile(archive, "w") as epub:
            epub.writestr("mimetype", "application/epub+zip")
            epub.writestr("META-INF/container.xml", "<container")
            epub.writestr(
                "OPS/chapter.xhtml",
                """
                <html xmlns="http://www.w3.org/1999/xhtml">
                  <body><p>Chapter text.</p></body>
                </html>
                """,
            )

        with self.assertRaisesRegex(
            TextExtractionError,
            "EPUB container XML is not readable",
        ):
            extract_text_from_epub(archive.getvalue())

    def test_rejects_epub_with_malformed_opf_xml(self):
        archive = BytesIO()
        with ZipFile(archive, "w") as epub:
            epub.writestr("mimetype", "application/epub+zip")
            epub.writestr(
                "META-INF/container.xml",
                """
                <container>
                  <rootfiles>
                    <rootfile full-path="OPS/content.opf" />
                  </rootfiles>
                </container>
                """,
            )
            epub.writestr("OPS/content.opf", "<package")
            epub.writestr(
                "OPS/chapter.xhtml",
                """
                <html xmlns="http://www.w3.org/1999/xhtml">
                  <body><p>Chapter text.</p></body>
                </html>
                """,
            )

        with self.assertRaisesRegex(
            TextExtractionError,
            "EPUB package XML is not readable",
        ):
            extract_text_from_epub(archive.getvalue())

    def test_rejects_epub_with_duplicate_archive_member_names(self):
        archive = BytesIO()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with ZipFile(archive, "w") as epub:
                epub.writestr("mimetype", "application/epub+zip")
                epub.writestr("META-INF/container.xml", "<container />")
                epub.writestr("OPS/toc.ncx", "<ncx><text>One</text></ncx>")
                epub.writestr("OPS/toc.ncx", "<ncx><text>Two</text></ncx>")
                epub.writestr(
                    "OPS/chapter.xhtml",
                    """
                    <html xmlns="http://www.w3.org/1999/xhtml">
                      <body><p>Chapter text.</p></body>
                    </html>
                    """,
                )

        with self.assertRaisesRegex(
            TextExtractionError,
            "Document archive contains duplicate file names",
        ):
            extract_text_from_epub(archive.getvalue())

    def test_rejects_epub_with_excessive_uncompressed_size(self):
        archive = BytesIO()
        with ZipFile(archive, "w", compression=ZIP_DEFLATED) as epub:
            epub.writestr("META-INF/container.xml", b"x" * (MAX_ARCHIVE_UNCOMPRESSED_BYTES + 1))

        with self.assertRaises(TextExtractionError):
            extract_text_from_epub(archive.getvalue())

    def test_rejects_epub_with_too_many_text_blocks(self):
        paragraphs = "".join(
            f"<p>Paragraph {index}</p>" for index in range(MAX_EPUB_TEXT_BLOCKS + 1)
        )
        content = _make_epub(
            {
                "OPS/chapter.xhtml": (
                    '<html xmlns="http://www.w3.org/1999/xhtml">'
                    f"<body>{paragraphs}</body>"
                    "</html>"
                )
            }
        )

        with self.assertRaisesRegex(TextExtractionError, "too many text blocks"):
            extract_text_from_epub(content)

    def test_extracts_russian_profile_regression_epub_sample_in_spine_order(self):
        content = (TEST_SAMPLES_DIR / "russian_profile_regression.en-ru.epub").read_bytes()

        text = extract_text_from_epub(content)

        self.assertIn("Russian Profile Regression", text)
        self.assertIn("The room held its breath", text)
        self.assertIn("Set the API endpoint", text)
        self.assertIn("English: The endpoint failed", text)
        self.assertIn("Zażółć gęślą jaźń", text)
        self.assertIn("https://example.com/v1/items", text)
        self.assertLess(
            text.index("Russian Profile Regression"),
            text.index("Mixed, Named Entities, And Protected Text"),
        )

    def test_extracts_pg78824_real_book_epub_samples_without_embedding_text(self):
        sample_names = (
            "pg78824-images-3.en-ru.epub",
            "pg78824-images-3.en-uk.epub",
        )

        extracted_lengths = []
        for sample_name in sample_names:
            content = (TEST_SAMPLES_DIR / sample_name).read_bytes()

            text = extract_text_from_epub(content)

            extracted_lengths.append(len(text))

        self.assertEqual(extracted_lengths, [357401, 357401])


def _make_docx(document_xml: str, extra_parts: dict[str, str] | None = None) -> bytes:
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


def _deep_docx_xml(nesting_depth: int) -> str:
    wrappers = "".join("<w:proofErr />" for _ in range(1))
    open_tags = "<w:sdt>" * nesting_depth
    close_tags = "</w:sdt>" * nesting_depth
    return f"""
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body>{wrappers}{open_tags}<w:p><w:r><w:t>Deep text</w:t></w:r></w:p>{close_tags}</w:body>
    </w:document>
    """


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
