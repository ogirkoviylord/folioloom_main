import unittest

from translator_service.language_detection import (
    DetectedLanguage,
    detect_language_from_text,
    detect_languages_from_text,
    format_detected_source_language,
    format_detected_source_languages,
)


class LanguageDetectionTest(unittest.TestCase):
    def test_detects_russian_from_cyrillic_text(self):
        detected = detect_language_from_text("Это русский текст про книгу и перевод.")

        self.assertEqual(detected, DetectedLanguage(code="ru", name="Russian"))

    def test_detects_ukrainian_from_unique_letters(self):
        detected = detect_language_from_text("Це український текст про книгу і переклад.")

        self.assertEqual(detected, DetectedLanguage(code="uk", name="Ukrainian"))

    def test_detects_english_from_common_words(self):
        detected = detect_language_from_text("This is a short English document.")

        self.assertEqual(detected, DetectedLanguage(code="en", name="English"))

    def test_detects_french_from_common_words(self):
        detected = detect_language_from_text("Ceci est un document français avec le texte.")

        self.assertEqual(detected, DetectedLanguage(code="fr", name="French"))

    def test_detects_spanish_from_common_words(self):
        detected = detect_language_from_text("Este es un documento español con el texto.")

        self.assertEqual(detected, DetectedLanguage(code="es", name="Spanish"))

    def test_detects_mixed_language_stress_text_languages(self):
        detected = detect_languages_from_text(
            "Русский текст. "
            "Nederlands: Ik fiets vandaag naar Zwolle. "
            "English: The quick brown fox jumps over the lazy dog. "
            "Deutsch: Falsches Üben quält jeden größeren Zwerg. "
            "Español: El pingüino tomó café. "
            "Polski: Zażółć gęślą jaźń. "
            "עברית: שלום עולם. "
            "العربية: مرحبا بالعالم. "
            "中文: 这是一个中文句子。"
            "日本語: これは日本語の文です。"
            "한국어: 이것은 한국어 문장입니다."
        )

        self.assertEqual(
            [(language.code, language.name) for language in detected],
            [
                ("ru", "Russian"),
                ("en", "English"),
                ("es", "Spanish"),
                ("pl", "Polish"),
                ("nl", "Dutch"),
                ("de", "German"),
                ("he", "Hebrew"),
                ("ar", "Arabic"),
                ("zh", "Chinese"),
                ("ja", "Japanese"),
                ("ko", "Korean"),
            ],
        )

    def test_spanish_diacritics_do_not_look_polish(self):
        detected = detect_languages_from_text("Español: El pingüino tomó café.")

        self.assertEqual(detected, [DetectedLanguage(code="es", name="Spanish")])

    def test_detects_ukrainian_without_false_russian_in_mixed_detector(self):
        detected = detect_languages_from_text("Це український текст про книгу і переклад.")

        self.assertEqual(detected, [DetectedLanguage(code="uk", name="Ukrainian")])

    def test_returns_none_when_text_is_too_ambiguous(self):
        self.assertIsNone(detect_language_from_text("12345 !!!"))

    def test_formats_auto_source_language_for_user(self):
        self.assertEqual(
            format_detected_source_language(
                requested_source_language="auto",
                detected_language=DetectedLanguage(code="en", name="English"),
            ),
            "English",
        )

    def test_formats_mixed_auto_source_language_with_primary_and_admixtures(self):
        self.assertEqual(
            format_detected_source_languages(
                requested_source_language="auto",
                detected_languages=[
                    DetectedLanguage(code="ru", name="Russian"),
                    DetectedLanguage(code="en", name="English"),
                    DetectedLanguage(code="nl", name="Dutch"),
                ],
                primary_language=DetectedLanguage(code="ru", name="Russian"),
            ),
            "Russian (admixtures: English, Dutch)",
        )

    def test_formats_unknown_auto_source_language_for_user(self):
        self.assertEqual(
            format_detected_source_language(
                requested_source_language="auto",
                detected_language=None,
            ),
            "auto (unknown)",
        )

    def test_keeps_explicit_source_language_unchanged(self):
        self.assertEqual(
            format_detected_source_language(
                requested_source_language="ru",
                detected_language=DetectedLanguage(code="en", name="English"),
            ),
            "ru",
        )


if __name__ == "__main__":
    unittest.main()
