import unittest

from translator_service.languages import (
    SUPPORTED_TARGET_LANGUAGES,
    find_language_by_button_text,
    language_name_for_code,
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

    def test_returns_none_for_missing_message_text(self):
        self.assertIsNone(find_language_by_button_text(None))

    def test_resolves_language_names_for_prompts(self):
        self.assertEqual(language_name_for_code("uk"), "Ukrainian")
        self.assertEqual(language_name_for_code("en"), "English")
        self.assertEqual(language_name_for_code("auto"), "all detected source languages")
        self.assertEqual(language_name_for_code("de"), "German")


if __name__ == "__main__":
    unittest.main()
