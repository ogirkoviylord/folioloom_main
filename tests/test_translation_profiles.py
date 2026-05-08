import unittest

from translator_service.text_analysis import TextType
from translator_service.russian_quality import RussianQualityTrack
from translator_service.translation_profiles import (
    build_target_language_profile_prompt,
    get_target_language_profile,
    target_language_policy_signature,
)


class TranslationProfilesTest(unittest.TestCase):
    def test_returns_russian_target_language_profile(self):
        profile = get_target_language_profile("ru")

        self.assertIsNotNone(profile)
        assert profile is not None
        self.assertEqual(profile.language_code, "ru")
        self.assertEqual(profile.version, "russian-v2")
        term_examples = " ".join(profile.term_examples)
        self.assertIn("плейсхолдер", term_examples)
        self.assertIn("endpoint", term_examples)

    def test_returns_ukrainian_target_language_profile(self):
        profile = get_target_language_profile("uk")

        self.assertIsNotNone(profile)
        assert profile is not None
        self.assertEqual(profile.language_code, "uk")
        self.assertEqual(profile.version, "ukrainian-v1")
        term_examples = " ".join(profile.term_examples)
        self.assertIn("параметри запиту", term_examples)
        self.assertIn("заповнювач", term_examples)
        self.assertIn("плейсхолдер", term_examples)
        self.assertIn("endpoint", term_examples)

    def test_returns_ukrainian_profile_for_regional_language_tag(self):
        profile = get_target_language_profile("uk-UA")

        self.assertIsNotNone(profile)
        assert profile is not None
        self.assertEqual(profile.language_code, "uk")

    def test_returns_no_profile_for_language_without_specific_rules_yet(self):
        self.assertIsNone(get_target_language_profile("en"))

    def test_returns_stable_policy_signature_for_cache_keys(self):
        self.assertEqual(
            target_language_policy_signature("ru"),
            "target-profile:ru:russian-v2",
        )
        self.assertEqual(
            target_language_policy_signature("en"),
            "target-profile:default-v1",
        )

    def test_returns_stable_ukrainian_policy_signature_for_cache_keys(self):
        self.assertEqual(
            target_language_policy_signature("uk"),
            "target-profile:uk:ukrainian-v1",
        )
        self.assertEqual(
            target_language_policy_signature("uk-UA"),
            "target-profile:uk:ukrainian-v1",
        )

    def test_builds_russian_prompt_with_text_type_specific_rules(self):
        prompt = build_target_language_profile_prompt(
            target_language="ru",
            text_type=TextType.TECHNICAL,
            quality_track=RussianQualityTrack.PRECISION,
        )

        self.assertIn("Russian target-language profile", prompt)
        self.assertIn("natural modern Russian", prompt)
        self.assertIn("avoid English word order", prompt)
        self.assertIn("technical documentation", prompt)
        self.assertIn("preserve code identifiers", prompt)
        self.assertIn("API names", prompt)
        self.assertIn("Transliterate ordinary personal names", prompt)
        self.assertIn("placeholder", prompt)
        self.assertIn("плейсхолдер", prompt)
        self.assertIn("Precision Russian quality track", prompt)
        self.assertIn("dates, numbers, legal obligations", prompt)

    def test_builds_ukrainian_prompt_with_text_type_specific_rules(self):
        prompt = build_target_language_profile_prompt(
            target_language="uk",
            text_type=TextType.TECHNICAL,
            quality_track=RussianQualityTrack.PRECISION,
        )

        self.assertIn("Ukrainian target-language profile", prompt)
        self.assertIn("standard Ukrainian", prompt)
        self.assertIn("Avoid Russian calques", prompt)
        self.assertIn("technical documentation", prompt)
        self.assertIn("preserve code identifiers", prompt)
        self.assertIn("API names", prompt)
        self.assertIn("Transcribe ordinary personal names", prompt)
        self.assertIn("placeholder", prompt)
        self.assertIn("заповнювач", prompt)
        self.assertIn("Precision Ukrainian quality track", prompt)
        self.assertIn("dates, numbers, legal obligations", prompt)

    def test_russian_prompt_includes_naturalness_and_protected_grammar_examples(self):
        prompt = build_target_language_profile_prompt(
            target_language="ru",
            text_type=TextType.GENERAL,
            quality_track=RussianQualityTrack.LITERARY,
        )

        self.assertIn("Do not translate made a decision as сделал решение", prompt)
        self.assertIn("prefer решил or принял решение", prompt)
        self.assertIn("high-level overview", prompt)
        self.assertIn("общее описание", prompt)
        self.assertIn("модуль FastAPI", prompt)
        self.assertIn("пакет requests", prompt)
        self.assertIn("callback-функцию", prompt)
        self.assertIn("Literary Russian quality track", prompt)
        self.assertIn("voice, rhythm, dialogue, imagery", prompt)

    def test_ukrainian_prompt_includes_naturalness_and_protected_grammar_examples(self):
        prompt = build_target_language_profile_prompt(
            target_language="uk",
            text_type=TextType.GENERAL,
            quality_track=RussianQualityTrack.LITERARY,
        )

        self.assertIn("Do not translate made a decision as зробив рішення", prompt)
        self.assertIn("prefer вирішив or ухвалив рішення", prompt)
        self.assertIn("приймати участь", prompt)
        self.assertIn("брати участь", prompt)
        self.assertIn("на протязі", prompt)
        self.assertIn("протягом", prompt)
        self.assertIn("модуль FastAPI", prompt)
        self.assertIn("пакет requests", prompt)
        self.assertIn("змінна PATH", prompt)
        self.assertIn("Literary Ukrainian quality track", prompt)
        self.assertIn("voice, rhythm, dialogue, imagery", prompt)

    def test_ukrainian_prompt_includes_quote_typography_rule(self):
        prompt = build_target_language_profile_prompt(
            target_language="uk",
            text_type=TextType.LITERARY_FICTION,
            quality_track=RussianQualityTrack.LITERARY,
        )

        self.assertIn("Use Ukrainian guillemets", prompt)
        self.assertIn("«...»", prompt)

    def test_omits_profile_prompt_when_language_has_no_profile(self):
        prompt = build_target_language_profile_prompt(
            target_language="en",
            text_type=TextType.GENERAL,
            quality_track=None,
        )

        self.assertEqual(prompt, "")


if __name__ == "__main__":
    unittest.main()
