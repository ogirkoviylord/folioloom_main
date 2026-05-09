import unittest

from translator_service.russian_quality import RussianQualityTrack
from translator_service.source_pair_profiles import build_source_pair_profile_prompt
from translator_service.text_analysis import detect_text_type
from translator_service.translation_profiles import build_target_language_profile_prompt
from translator_service.ukrainian_quality_checks import check_ukrainian_translation_quality
from translator_service.ukrainian_regression_samples import (
    REQUIRED_UKRAINIAN_SAMPLE_CATEGORIES,
    REQUIRED_UKRAINIAN_SOURCE_LANGUAGES,
    format_ukrainian_regression_sample_pack,
    ukrainian_regression_samples,
)


class UkrainianRegressionSamplesTest(unittest.TestCase):
    def test_sample_pack_covers_required_ukrainian_profile_categories(self):
        samples = ukrainian_regression_samples()
        categories = {sample.category for sample in samples}
        sample_ids = [sample.sample_id for sample in samples]

        self.assertEqual(len(sample_ids), len(set(sample_ids)))
        self.assertTrue(REQUIRED_UKRAINIAN_SAMPLE_CATEGORIES <= categories)

    def test_sample_pack_covers_required_source_languages_and_tracks(self):
        samples = ukrainian_regression_samples()
        source_languages = {sample.source_language for sample in samples}
        quality_tracks = {sample.quality_track for sample in samples}

        self.assertTrue(REQUIRED_UKRAINIAN_SOURCE_LANGUAGES <= source_languages)
        self.assertIn(RussianQualityTrack.LITERARY, quality_tracks)
        self.assertIn(RussianQualityTrack.PRECISION, quality_tracks)

    def test_samples_have_expected_text_type_and_prompt_terms(self):
        for sample in ukrainian_regression_samples():
            with self.subTest(sample=sample.sample_id):
                self.assertEqual(sample.target_language, "uk")
                self.assertIn(sample.source_language, REQUIRED_UKRAINIAN_SOURCE_LANGUAGES)
                self.assertIsInstance(sample.quality_track, RussianQualityTrack)
                self.assertEqual(
                    detect_text_type(sample.source_text),
                    sample.expected_text_type,
                )
                self.assertTrue(sample.expected_behavior)
                self.assertTrue(sample.banned_outputs)
                self.assertTrue(sample.required_preservations)

                prompt = build_target_language_profile_prompt(
                    target_language=sample.target_language,
                    text_type=sample.expected_text_type,
                    quality_track=sample.quality_track,
                )
                for term in sample.required_prompt_terms:
                    self.assertIn(term, prompt)

                source_pair_prompt = build_source_pair_profile_prompt(
                    sample.source_language,
                    sample.target_language,
                )
                for term in sample.required_source_pair_terms:
                    self.assertIn(term, source_pair_prompt)

    def test_core_banned_outputs_are_detected_by_ukrainian_quality_checks(self):
        samples = ukrainian_regression_samples()
        calque_samples = [
            sample for sample in samples
            if sample.category in {"ordinary_prose", "russian_calque"}
        ]

        self.assertGreaterEqual(len(calque_samples), 2)
        for sample in calque_samples:
            for banned in sample.banned_outputs:
                with self.subTest(sample=sample.sample_id, banned=banned):
                    result = check_ukrainian_translation_quality(
                        source_text=sample.source_text,
                        translated_text=f"Це тестовий переклад: {banned}.",
                        source_language=sample.source_language,
                        target_language=sample.target_language,
                        quality_track=sample.quality_track,
                    )
                    self.assertIn(
                        "ukrainian_calque",
                        [issue.code for issue in result.issues],
                    )

    def test_corpus_contains_reference_translations_for_core_samples(self):
        referenced_samples = [
            sample for sample in ukrainian_regression_samples()
            if sample.reference_translation is not None
        ]

        self.assertGreaterEqual(len(referenced_samples), 4)
        for sample in referenced_samples:
            with self.subTest(sample=sample.sample_id):
                assert sample.reference_translation is not None
                self.assertIn(" ", sample.reference_translation)

    def test_formats_sample_pack_for_manual_qa(self):
        formatted = format_ukrainian_regression_sample_pack()

        self.assertIn("Ukrainian Translation Regression Sample Pack", formatted)
        self.assertIn("Target language: uk", formatted)
        self.assertIn("## uk-ordinary-calque-decision-overview", formatted)
        self.assertIn("Category: ordinary_prose", formatted)
        self.assertIn("Source language: en", formatted)
        self.assertIn("Quality track: precision", formatted)
        self.assertIn("Expected text type: general", formatted)
        self.assertIn("Source:", formatted)
        self.assertIn("Expected behavior:", formatted)
        self.assertIn("Banned outputs:", formatted)
        self.assertIn("Required preservations:", formatted)
        self.assertIn("Reference translation:", formatted)
        self.assertIn("Required prompt terms:", formatted)
        self.assertIn("He made a decision after a high-level overview", formatted)
        self.assertIn("Он принял участие", formatted)
        self.assertIn("${API_TOKEN}", formatted)


if __name__ == "__main__":
    unittest.main()
