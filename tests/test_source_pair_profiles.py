import unittest

from translator_service.source_pair_profiles import (
    build_source_pair_profile_prompt,
    source_pair_profile_signature,
)


class SourcePairProfilesTest(unittest.TestCase):
    def test_builds_english_to_russian_guidance(self):
        prompt = build_source_pair_profile_prompt("en", "ru")

        self.assertIn("English to Russian source-pair profile", prompt)
        self.assertIn("articles", prompt)
        self.assertIn("phrasal verbs", prompt)
        self.assertIn("avoid English word order", prompt)

    def test_builds_ukrainian_to_russian_guidance(self):
        prompt = build_source_pair_profile_prompt("uk", "ru")

        self.assertIn("Ukrainian to Russian source-pair profile", prompt)
        self.assertIn("false friends", prompt)
        self.assertIn("і, ї, є, ґ", prompt)
        self.assertIn("not transliterate Ukrainian words", prompt)

    def test_builds_polish_to_russian_guidance(self):
        prompt = build_source_pair_profile_prompt("pl", "ru")

        self.assertIn("Polish to Russian source-pair profile", prompt)
        self.assertIn("Polish diacritics", prompt)
        self.assertIn("pan/pani", prompt)
        self.assertIn("false friends", prompt)

    def test_builds_dutch_to_russian_guidance(self):
        prompt = build_source_pair_profile_prompt("nl", "ru")

        self.assertIn("Dutch to Russian source-pair profile", prompt)
        self.assertIn("separable verbs", prompt)
        self.assertIn("B.V.", prompt)
        self.assertIn("afspraak", prompt)

    def test_builds_german_to_russian_guidance(self):
        prompt = build_source_pair_profile_prompt("de", "ru")

        self.assertIn("German to Russian source-pair profile", prompt)
        self.assertIn("compound nouns", prompt)
        self.assertIn("verb-final clauses", prompt)
        self.assertIn("GmbH", prompt)

    def test_builds_french_to_russian_guidance(self):
        prompt = build_source_pair_profile_prompt("fr", "ru")

        self.assertIn("French to Russian source-pair profile", prompt)
        self.assertIn("ne pas", prompt)
        self.assertIn("false friends", prompt)
        self.assertIn("French quotation", prompt)

    def test_builds_spanish_to_russian_guidance(self):
        prompt = build_source_pair_profile_prompt("es", "ru")

        self.assertIn("Spanish to Russian source-pair profile", prompt)
        self.assertIn("ser/estar", prompt)
        self.assertIn("inverted punctuation", prompt)
        self.assertIn("false friends", prompt)

    def test_builds_mixed_auto_to_russian_guidance(self):
        prompt = build_source_pair_profile_prompt("auto", "ru")

        self.assertIn("Mixed-source to Russian source-pair profile", prompt)
        self.assertIn("source_language hints", prompt)
        self.assertIn("do not assume English", prompt)
        self.assertIn("translate every human-language span", prompt)

    def test_builds_english_to_ukrainian_guidance(self):
        prompt = build_source_pair_profile_prompt("en", "uk")

        self.assertIn("English to Ukrainian source-pair profile", prompt)
        self.assertIn("English word order", prompt)
        self.assertIn("phrasal verbs", prompt)
        self.assertIn("false friends", prompt)
        self.assertIn("Title Case", prompt)

    def test_builds_russian_to_ukrainian_guidance(self):
        prompt = build_source_pair_profile_prompt("ru", "uk")

        self.assertIn("Russian to Ukrainian source-pair profile", prompt)
        self.assertIn("standard Ukrainian", prompt)
        self.assertIn("not word-by-word replacement", prompt)
        self.assertIn("surzhyk", prompt)
        self.assertIn("приймати участь", prompt)

    def test_builds_mixed_auto_to_ukrainian_guidance(self):
        prompt = build_source_pair_profile_prompt("auto", "uk")

        self.assertIn("Mixed-source to Ukrainian source-pair profile", prompt)
        self.assertIn("source_language hints", prompt)
        self.assertIn("do not assume English", prompt)
        self.assertIn("translate every human-language span", prompt)
        self.assertIn("Ukrainian", prompt)

    def test_language_pair_without_profile_has_no_source_pair_guidance(self):
        self.assertEqual(build_source_pair_profile_prompt("en", "fr"), "")
        self.assertEqual(source_pair_profile_signature("en", "fr"), "source-pair:none")

    def test_source_pair_signature_is_stable(self):
        self.assertEqual(
            source_pair_profile_signature("en-US", "ru"),
            "source-pair:en-ru:v1",
        )
        self.assertEqual(
            source_pair_profile_signature("auto", "ru"),
            "source-pair:auto-ru:v1",
        )

    def test_ukrainian_source_pair_signature_is_stable(self):
        self.assertEqual(
            source_pair_profile_signature("en-US", "uk-UA"),
            "source-pair:en-uk:v1",
        )
        self.assertEqual(
            source_pair_profile_signature("ru", "uk"),
            "source-pair:ru-uk:v1",
        )
        self.assertEqual(
            source_pair_profile_signature("auto", "uk"),
            "source-pair:auto-uk:v1",
        )


if __name__ == "__main__":
    unittest.main()
