import unittest

from translator_service.translation_jobs import (
    FragmentTranslation,
    TranslationJobResult,
    translate_text_fragments,
)


class RecordingTranslator:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, str]] = []

    def translate(self, *, text: str, source_language: str, target_language: str) -> str:
        self.requests.append((text, source_language, target_language))
        return f"[{target_language}] {text}"


class TranslationJobsTest(unittest.TestCase):
    def test_translates_fragments_in_order_and_assembles_text(self):
        translator = RecordingTranslator()

        result = translate_text_fragments(
            fragments=["Первый абзац.", "Второй абзац."],
            source_language="ru",
            target_language="en",
            translator=translator,
        )

        self.assertEqual(
            result,
            TranslationJobResult(
                fragments=[
                    FragmentTranslation(
                        index=0,
                        source_text="Первый абзац.",
                        translated_text="[en] Первый абзац.",
                    ),
                    FragmentTranslation(
                        index=1,
                        source_text="Второй абзац.",
                        translated_text="[en] Второй абзац.",
                    ),
                ],
                assembled_text="[en] Первый абзац.\n\n[en] Второй абзац.",
            ),
        )
        self.assertEqual(
            translator.requests,
            [
                ("Первый абзац.", "ru", "en"),
                ("Второй абзац.", "ru", "en"),
            ],
        )

    def test_skips_blank_fragments(self):
        translator = RecordingTranslator()

        result = translate_text_fragments(
            fragments=["Первый абзац.", "   ", "Второй абзац."],
            source_language="ru",
            target_language="en",
            translator=translator,
        )

        self.assertEqual(len(result.fragments), 2)
        self.assertEqual(result.assembled_text, "[en] Первый абзац.\n\n[en] Второй абзац.")

    def test_reports_progress_after_each_translated_fragment(self):
        progress_updates: list[tuple[int, int]] = []

        translate_text_fragments(
            fragments=["One", "Two", "Three"],
            source_language="en",
            target_language="uk",
            translator=RecordingTranslator(),
            progress_callback=progress_updates.append,
        )

        self.assertEqual(progress_updates, [(1, 3), (2, 3), (3, 3)])


if __name__ == "__main__":
    unittest.main()
