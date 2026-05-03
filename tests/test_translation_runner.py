import unittest
from io import BytesIO
from zipfile import ZipFile

from translator_service.extractors import extract_text_from_docx
from translator_service.extractors import extract_text_from_epub
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
        self.assertEqual(result.fragment_count, 2)
        self.assertEqual(
            extract_text_from_docx(result.content),
            "[fr] First paragraph\n\n[fr] Second paragraph",
        )
        self.assertEqual(
            translator.requests,
            [
                ("First paragraph", "en", "fr"),
                ("Second paragraph", "en", "fr"),
            ],
        )

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
        self.assertEqual(result.fragment_count, 3)
        self.assertEqual(
            extract_text_from_epub(result.content),
            "[uk] Chapter One\n\n[uk] First paragraph.\n\n[uk] Second paragraph.",
        )
        with ZipFile(BytesIO(result.content)) as epub:
            self.assertEqual(epub.read("OPS/style.css"), b"body { font-family: serif; }")
        self.assertEqual(
            translator.requests,
            [
                ("Chapter One", "en", "uk"),
                ("First paragraph.", "en", "uk"),
                ("Second paragraph.", "en", "uk"),
            ],
        )


if __name__ == "__main__":
    unittest.main()


def _make_docx(document_xml: str) -> bytes:
    archive = BytesIO()
    with ZipFile(archive, "w") as docx:
        docx.writestr("word/document.xml", document_xml)
        docx.writestr("[Content_Types].xml", "<Types />")
    return archive.getvalue()


def _make_epub(xhtml_items: dict[str, str]) -> bytes:
    archive = BytesIO()
    with ZipFile(archive, "w") as epub:
        epub.writestr("mimetype", "application/epub+zip")
        epub.writestr("META-INF/container.xml", "<container />")
        for file_name, content in xhtml_items.items():
            epub.writestr(file_name, content)
        epub.writestr("OPS/style.css", "body { font-family: serif; }")
    return archive.getvalue()
