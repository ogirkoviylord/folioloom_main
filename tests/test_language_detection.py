import unittest

from translator_service.language_detection import (
    DetectedLanguage,
    detect_language_from_text,
    format_detected_source_language,
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

    def test_returns_none_when_text_is_too_ambiguous(self):
        self.assertIsNone(detect_language_from_text("12345 !!!"))

    def test_formats_auto_source_language_for_user(self):
        self.assertEqual(
            format_detected_source_language(
                requested_source_language="auto",
                detected_language=DetectedLanguage(code="en", name="English"),
            ),
            "auto (English)",
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
