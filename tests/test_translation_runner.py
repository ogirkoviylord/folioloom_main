import unittest

from translator_service.translation_runner import TranslatedDocument, translate_txt_document


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


if __name__ == "__main__":
    unittest.main()
