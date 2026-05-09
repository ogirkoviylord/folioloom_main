import unittest

from translator_service.translation_metrics import (
    score_chrf,
    score_meteor_core,
    score_reference_translation,
)


class TranslationMetricsTest(unittest.TestCase):
    def test_meteor_core_exact_match_scores_one(self):
        result = score_meteor_core(
            "Комната словно затаила дыхание.",
            "Комната словно затаила дыхание.",
        )

        self.assertEqual(result.name, "meteor_core")
        self.assertEqual(result.version, "meteor-core-v1")
        self.assertEqual(result.score, 1.0)

    def test_meteor_core_penalizes_fragmented_word_order(self):
        fluent = score_meteor_core(
            "Он принял решение после общего описания системы.",
            "Он принял решение после общего описания системы.",
        )
        fragmented = score_meteor_core(
            "системы описания общего после решение принял Он",
            "Он принял решение после общего описания системы.",
        )

        self.assertLess(fragmented.score, fluent.score)
        self.assertGreater(fragmented.score, 0.0)

    def test_metrics_handle_empty_inputs(self):
        self.assertEqual(score_meteor_core("", "Reference").score, 0.0)
        self.assertEqual(score_meteor_core("Candidate", "").score, 0.0)
        self.assertEqual(score_chrf("", "Reference").score, 0.0)
        self.assertEqual(score_chrf("Candidate", "").score, 0.0)

    def test_chrf_exact_match_scores_one_and_unrelated_text_scores_lower(self):
        exact = score_chrf(
            "Укажите API endpoint.",
            "Укажите API endpoint.",
        )
        unrelated = score_chrf(
            "Совершенно другой текст.",
            "Укажите API endpoint.",
        )

        self.assertEqual(exact.name, "chrf")
        self.assertEqual(exact.version, "chrf-v1")
        self.assertEqual(exact.score, 1.0)
        self.assertLess(unrelated.score, 0.5)

    def test_reference_translation_returns_both_metrics(self):
        scores = score_reference_translation(
            candidate="Acme B.V. обязуется предоставить материалы.",
            reference="Acme B.V. обязуется предоставить материалы.",
        )

        self.assertEqual([score.name for score in scores], ["meteor_core", "chrf"])
        self.assertEqual([score.score for score in scores], [1.0, 1.0])


if __name__ == "__main__":
    unittest.main()
