import unittest

from translator_service.languages import (
    SUPPORTED_TARGET_LANGUAGES,
    find_language_by_button_text,
)


class LanguagesTest(unittest.TestCase):
    def test_supported_target_languages_are_the_requested_five(self):
        self.assertEqual(
            [(language.code, language.button_text) for language in SUPPORTED_TARGET_LANGUAGES],
            [
                ("ru", "Русский"),
                ("uk", "Українська"),
                ("fr", "Français"),
                ("es", "Español"),
                ("en", "English"),
            ],
        )

    def test_finds_language_by_button_text_case_insensitively(self):
        language = find_language_by_button_text(" english ")

        self.assertEqual(language.code, "en")
        self.assertEqual(language.name, "English")

    def test_returns_none_for_unknown_language_button(self):
        self.assertIsNone(find_language_by_button_text("Deutsch"))


if __name__ == "__main__":
    unittest.main()
