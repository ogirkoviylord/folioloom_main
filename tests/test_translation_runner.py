import unittest
from io import BytesIO
from zipfile import ZipFile

from translator_service.extractors import extract_text_from_docx
from translator_service.extractors import extract_text_from_epub
from translator_service.translation_jobs import CancellationToken
from translator_service.translation_runner import (
    TranslatedDocument,
    translate_docx_document,
    translate_epub_document,
    translate_txt_document,
)


class RecordingTranslator:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, str]] = []

    def translate(self, *, text: str, source_language: str, target_language: str) -> str:
        self.requests.append((text, source_language, target_language))
        if "<translation_block" in text:
            return _translate_marked_blocks(text, target_language)
        return f"[{target_language}] {text}"


class TranslationRunnerTest(unittest.TestCase):
    def test_translates_txt_document_into_downloadable_txt_result(self):
        translator = RecordingTranslator()

        result = translate_txt_document(
            file_name="notes.txt",
            content="Первый абзац.\n\nВторой абзац.".encode("utf-8"),
            source_language="ru",
            target_language="en",
            max_fragment_chars=20,
            translator=translator,
        )

        self.assertEqual(
            result,
            TranslatedDocument(
                file_name="notes.en.txt",
                content_type="text/plain; charset=utf-8",
                content=b"[en] \xd0\x9f\xd0\xb5\xd1\x80\xd0\xb2\xd1\x8b\xd0\xb9 "
                b"\xd0\xb0\xd0\xb1\xd0\xb7\xd0\xb0\xd1\x86.\n\n[en] "
                b"\xd0\x92\xd1\x82\xd0\xbe\xd1\x80\xd0\xbe\xd0\xb9 "
                b"\xd0\xb0\xd0\xb1\xd0\xb7\xd0\xb0\xd1\x86.",
                fragment_count=2,
            ),
        )
        self.assertEqual(
            translator.requests,
            [
                ("Первый абзац.", "ru", "en"),
                ("Второй абзац.", "ru", "en"),
            ],
        )

    def test_translated_txt_file_name_handles_names_without_extension(self):
        translator = RecordingTranslator()

        result = translate_txt_document(
            file_name="notes",
            content=b"Hello",
            source_language="en",
            target_language="uk",
            max_fragment_chars=100,
            translator=translator,
        )

        self.assertEqual(result.file_name, "notes.uk.txt")

    def test_translates_docx_document_into_downloadable_docx_result(self):
        translator = RecordingTranslator()
        content = _make_docx(
            """
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body>
                <w:p><w:r><w:t>First paragraph</w:t></w:r></w:p>
                <w:p><w:r><w:t>Second</w:t></w:r><w:r><w:t> paragraph</w:t></w:r></w:p>
              </w:body>
            </w:document>
            """
        )

        result = translate_docx_document(
            file_name="contract.docx",
            content=content,
            source_language="en",
            target_language="fr",
            translator=translator,
        )

        self.assertEqual(result.file_name, "contract.fr.docx")
        self.assertEqual(
            result.content_type,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        self.assertEqual(result.fragment_count, 1)
        self.assertEqual(
            extract_text_from_docx(result.content),
            "[fr] First paragraph\n\n[fr] Second paragraph",
        )
        self.assertEqual(
            translator.requests,
            [
                (
                    "<translation_batch>\n"
                    '<translation_block id="0">First paragraph</translation_block>\n'
                    '<translation_block id="1">Second paragraph</translation_block>\n'
                    "</translation_batch>",
                    "en",
                    "fr",
                ),
            ],
        )

    def test_docx_translation_parses_marked_batch_without_leaking_xml(self):
        class XmlTranslator:
            def translate(self, *, text: str, source_language: str, target_language: str) -> str:
                return (
                    "<translation_batch>\n"
                    '<translation_block id="0">Глава 1</translation_block>\n'
                    '<translation_block id="1">Источник</translation_block>\n'
                    '<translation_block id="2">Цель</translation_block>\n'
                    "</translation_batch>"
                )

        content = _make_docx(
            """
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body>
                <w:p><w:r><w:t>Chapter 1</w:t></w:r></w:p>
                <w:p><w:r><w:t>Source</w:t></w:r></w:p>
                <w:p><w:r><w:t>Target</w:t></w:r></w:p>
              </w:body>
            </w:document>
            """
        )

        result = translate_docx_document(
            file_name="sample.docx",
            content=content,
            source_language="en",
            target_language="ru",
            translator=XmlTranslator(),
        )

        text = extract_text_from_docx(result.content)
        self.assertEqual(text, "Глава 1\n\nИсточник\n\nЦель")
        self.assertNotIn("translation_batch", text)

    def test_docx_translation_preserves_run_formatting_nodes(self):
        class XmlTranslator:
            def translate(self, *, text: str, source_language: str, target_language: str) -> str:
                return (
                    "<translation_batch>"
                    '<translation_block id="0">Обычный и жирный текст</translation_block>'
                    "</translation_batch>"
                )

        content = _make_docx(
            """
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body>
                <w:p>
                  <w:r><w:t>Plain and </w:t></w:r>
                  <w:r><w:rPr><w:b /></w:rPr><w:t>bold text</w:t></w:r>
                </w:p>
              </w:body>
            </w:document>
            """
        )

        result = translate_docx_document(
            file_name="sample.docx",
            content=content,
            source_language="en",
            target_language="ru",
            translator=XmlTranslator(),
        )

        with ZipFile(BytesIO(result.content)) as docx:
            document = _parse_xml(docx.read("word/document.xml"))
        namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        bold_runs = [
            run
            for run in document.findall(".//w:r", namespace)
            if run.find("w:rPr/w:b", namespace) is not None
        ]
        self.assertEqual(len(bold_runs), 1)
        bold_text = "".join(
            text_node.text or ""
            for text_node in bold_runs[0].findall(".//w:t", namespace)
        )
        self.assertIn("жирный", bold_text)

    def test_translates_epub_document_into_downloadable_epub_result(self):
        translator = RecordingTranslator()
        content = _make_epub(
            {
                "OPS/chapter1.xhtml": """
                <html xmlns="http://www.w3.org/1999/xhtml">
                  <body>
                    <h1>Chapter One</h1>
                    <p>First <em>paragraph</em>.</p>
                  </body>
                </html>
                """,
                "OPS/chapter2.xhtml": """
                <html xmlns="http://www.w3.org/1999/xhtml">
                  <body><p>Second paragraph.</p></body>
                </html>
                """,
            }
        )

        result = translate_epub_document(
            file_name="book.epub",
            content=content,
            source_language="en",
            target_language="uk",
            translator=translator,
        )

        self.assertEqual(result.file_name, "book.uk.epub")
        self.assertEqual(result.content_type, "application/epub+zip")
        self.assertEqual(result.fragment_count, 1)
        self.assertEqual(
            extract_text_from_epub(result.content),
            "[uk] Chapter One\n\n[uk] First paragraph.\n\n[uk] Second paragraph.",
        )
        with ZipFile(BytesIO(result.content)) as epub:
            self.assertEqual(epub.read("OPS/style.css"), b"body { font-family: serif; }")
        self.assertEqual(
            translator.requests,
            [
                (
                    "<translation_batch>\n"
                    '<translation_block id="0">Chapter One</translation_block>\n'
                    '<translation_block id="1">First paragraph.</translation_block>\n'
                    '<translation_block id="2">Second paragraph.</translation_block>\n'
                    "</translation_batch>",
                    "en",
                    "uk",
                ),
            ],
        )

    def test_translates_epub_div_text_without_duplicate_parent_blocks(self):
        translator = RecordingTranslator()
        content = _make_epub(
            {
                "OPS/chapter.xhtml": """
                <html xmlns="http://www.w3.org/1999/xhtml">
                  <body>
                    <section>
                      <h1>Chapter 1</h1>
                      <div class="body-text">This line is stored in a div.</div>
                      <div class="body-text">Another div paragraph with <span>inline text</span>.</div>
                    </section>
                  </body>
                </html>
                """,
            }
        )

        result = translate_epub_document(
            file_name="book.epub",
            content=content,
            source_language="en",
            target_language="uk",
            translator=translator,
        )

        self.assertEqual(result.fragment_count, 1)
        self.assertEqual(
            extract_text_from_epub(result.content),
            "[uk] Chapter 1\n\n"
            "[uk] This line is stored in a div.\n\n"
            "[uk] Another div paragraph with inline text.",
        )
        self.assertEqual(
            [request[0] for request in translator.requests],
            [
                "<translation_batch>\n"
                '<translation_block id="0">Chapter 1</translation_block>\n'
                '<translation_block id="1">This line is stored in a div.</translation_block>\n'
                '<translation_block id="2">Another div paragraph with inline text.</translation_block>\n'
                "</translation_batch>",
            ],
        )

    def test_epub_translation_preserves_inline_formatting_nodes(self):
        class XmlTranslator:
            def translate(self, *, text: str, source_language: str, target_language: str) -> str:
                return (
                    "<translation_batch>"
                    '<translation_block id="0">Обычный и выделенный текст.</translation_block>'
                    "</translation_batch>"
                )

        content = _make_epub(
            {
                "OPS/chapter.xhtml": """
                <html xmlns="http://www.w3.org/1999/xhtml">
                  <body><p>Plain and <strong>emphasized text</strong>.</p></body>
                </html>
                """,
            }
        )

        result = translate_epub_document(
            file_name="book.epub",
            content=content,
            source_language="en",
            target_language="ru",
            translator=XmlTranslator(),
        )

        with ZipFile(BytesIO(result.content)) as epub:
            chapter = epub.read("OPS/chapter.xhtml").decode("utf-8")
        self.assertIn("<html:strong", chapter)
        self.assertIn("Обычный и", chapter)
        self.assertIn("выделенный", chapter)

    def test_translated_epub_keeps_mimetype_as_first_archive_item(self):
        translator = RecordingTranslator()
        content = _make_epub(
            {
                "OPS/chapter.xhtml": """
                <html xmlns="http://www.w3.org/1999/xhtml">
                  <body><p>First paragraph.</p></body>
                </html>
                """,
            }
        )

        result = translate_epub_document(
            file_name="book.epub",
            content=content,
            source_language="en",
            target_language="uk",
            translator=translator,
        )

        with ZipFile(BytesIO(result.content)) as epub:
            self.assertEqual(epub.infolist()[0].filename, "mimetype")
            self.assertEqual(epub.read("mimetype"), b"application/epub+zip")

    def test_cancelled_epub_translation_returns_partial_epub_result(self):
        translator = RecordingTranslator()
        token = CancellationToken()
        content = _make_epub(
            {
                "OPS/chapter.xhtml": """
                <html xmlns="http://www.w3.org/1999/xhtml">
                  <body>
                    <p>First paragraph.</p>
                    <p>Second paragraph.</p>
                  </body>
                </html>
                """,
            }
        )

        def cancel_after_first(progress: tuple[int, int]) -> None:
            if progress == (1, 2):
                token.cancel()

        result = translate_epub_document(
            file_name="book.epub",
            content=content,
            source_language="en",
            target_language="uk",
            translator=translator,
            max_fragment_chars=30,
            progress_callback=cancel_after_first,
            cancellation_token=token,
        )

        self.assertEqual(result.file_name, "book.uk.partial.epub")
        self.assertTrue(result.is_partial)
        self.assertEqual(result.fragment_count, 1)
        self.assertEqual(
            extract_text_from_epub(result.content),
            "[uk] First paragraph.\n\nSecond paragraph.",
        )

    def test_cancelled_epub_translation_uses_spine_reading_order(self):
        translator = RecordingTranslator()
        token = CancellationToken()
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

        def cancel_after_first(progress: tuple[int, int]) -> None:
            if progress == (1, 2):
                token.cancel()

        result = translate_epub_document(
            file_name="book.epub",
            content=content,
            source_language="en",
            target_language="uk",
            translator=translator,
            max_fragment_chars=20,
            progress_callback=cancel_after_first,
            cancellation_token=token,
        )

        self.assertEqual(
            extract_text_from_epub(result.content),
            "[uk] First chapter.\n\nSecond chapter.",
        )

    def test_epub_translation_groups_blocks_by_max_fragment_chars(self):
        translator = RecordingTranslator()
        content = _make_epub(
            {
                "OPS/chapter.xhtml": """
                <html xmlns="http://www.w3.org/1999/xhtml">
                  <body>
                    <p>One short paragraph.</p>
                    <p>Two short paragraph.</p>
                    <p>Three short paragraph.</p>
                  </body>
                </html>
                """,
            }
        )

        result = translate_epub_document(
            file_name="book.epub",
            content=content,
            source_language="en",
            target_language="uk",
            max_fragment_chars=50,
            translator=translator,
        )

        self.assertEqual(result.fragment_count, 2)
        self.assertEqual(len(translator.requests), 2)


if __name__ == "__main__":
    unittest.main()


def _make_docx(document_xml: str) -> bytes:
    archive = BytesIO()
    with ZipFile(archive, "w") as docx:
        docx.writestr("word/document.xml", document_xml)
        docx.writestr("[Content_Types].xml", "<Types />")
    return archive.getvalue()


def _make_epub(xhtml_items: dict[str, str], spine: list[str] | None = None) -> bytes:
    archive = BytesIO()
    item_names = list(xhtml_items)
    spine = spine or item_names
    manifest_items = "\n".join(
        f'<item id="item{index}" href="{file_name}" media-type="application/xhtml+xml" />'
        for index, file_name in enumerate(item_names)
    )
    spine_items = "\n".join(
        f'<itemref idref="item{item_names.index(file_name)}" />'
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


def _translate_marked_blocks(text: str, target_language: str) -> str:
    from xml.etree import ElementTree

    document = ElementTree.fromstring(text)
    for block in document:
        block.text = f"[{target_language}] {block.text}"
    return ElementTree.tostring(document, encoding="unicode")


def _parse_xml(content: bytes):
    from xml.etree import ElementTree

    return ElementTree.fromstring(content)
