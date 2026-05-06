import unittest

from translator_service.text_analysis import detect_text_type
from translator_service.translation_profiles import build_target_language_profile_prompt
from translator_service.russian_regression_samples import (
    REQUIRED_RUSSIAN_SAMPLE_CATEGORIES,
    format_russian_regression_sample_pack,
    russian_regression_samples,
)


class RussianRegressionSamplesTest(unittest.TestCase):
    def test_sample_pack_covers_required_russian_profile_categories(self):
        samples = russian_regression_samples()
        categories = {sample.category for sample in samples}
        sample_ids = [sample.sample_id for sample in samples]

        self.assertEqual(len(sample_ids), len(set(sample_ids)))
        self.assertTrue(REQUIRED_RUSSIAN_SAMPLE_CATEGORIES <= categories)

    def test_samples_have_expected_text_type_and_prompt_terms(self):
        for sample in russian_regression_samples():
            with self.subTest(sample=sample.sample_id):
                self.assertEqual(sample.target_language, "ru")
                self.assertEqual(
                    detect_text_type(sample.source_text),
                    sample.expected_text_type,
                )
                self.assertTrue(sample.expected_behavior)

                prompt = build_target_language_profile_prompt(
                    target_language=sample.target_language,
                    text_type=sample.expected_text_type,
                )
                for term in sample.required_prompt_terms:
                    self.assertIn(term, prompt)

    def test_formats_sample_pack_for_manual_qa(self):
        formatted = format_russian_regression_sample_pack()

        self.assertIn("Russian Translation Regression Sample Pack", formatted)
        self.assertIn("Target language: ru", formatted)
        self.assertIn("## ru-ordinary-calque-decision-overview", formatted)
        self.assertIn("Category: ordinary_prose", formatted)
        self.assertIn("Expected text type: general", formatted)
        self.assertIn("Source:", formatted)
        self.assertIn("Expected behavior:", formatted)
        self.assertIn("Required prompt terms:", formatted)
        self.assertIn("He made a decision after a high-level overview", formatted)
        self.assertIn("callback handler", formatted)


if __name__ == "__main__":
    unittest.main()
