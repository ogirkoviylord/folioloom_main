import unittest

from translator_service.russian_quality import RussianQualityTrack
from translator_service.russian_regression_samples import russian_regression_samples
from translator_service.translation_eval import (
    ExternalMetricResult,
    OptionalMetricDisabledError,
    build_russian_eval_rubric,
    build_translation_eval_report,
    evaluate_russian_translation,
    run_optional_metric,
)


class TranslationEvalTest(unittest.TestCase):
    def test_literary_and_precision_rubrics_weight_different_quality_dimensions(self):
        literary = build_russian_eval_rubric(RussianQualityTrack.LITERARY)
        precision = build_russian_eval_rubric(RussianQualityTrack.PRECISION)

        literary_weights = {criterion.name: criterion.weight for criterion in literary.criteria}
        precision_weights = {criterion.name: criterion.weight for criterion in precision.criteria}

        self.assertGreater(
            literary_weights["fluency"]
            + literary_weights["style"]
            + literary_weights["voice"],
            literary_weights["terminology"] + literary_weights["structure"],
        )
        self.assertGreater(
            precision_weights["accuracy"]
            + precision_weights["terminology"]
            + precision_weights["structure"],
            precision_weights["style"] + precision_weights["voice"],
        )
        self.assertEqual(literary.version, "russian-mqm-rubric-v1")
        self.assertEqual(precision.version, "russian-mqm-rubric-v1")

    def test_evaluate_russian_translation_maps_deterministic_qa_to_mqm_issues(self):
        result = evaluate_russian_translation(
            sample_id="sample-1",
            source_text="Send ROW-001 to https://example.com/callback with ${API_TOKEN}.",
            translated_text="Отправьте строку в callback с токеном.",
            source_language="en",
            target_language="ru",
            quality_track=RussianQualityTrack.PRECISION,
        )

        self.assertFalse(result.passed)
        self.assertLess(result.score, 85)
        self.assertEqual(
            [issue.category for issue in result.issues],
            ["protected_content", "protected_content", "protected_content"],
        )
        self.assertEqual(
            [issue.code for issue in result.issues],
            ["missing_url", "missing_placeholder", "missing_identifier"],
        )

    def test_evaluate_russian_translation_passes_clean_precision_translation(self):
        result = evaluate_russian_translation(
            sample_id="sample-2",
            source_text=(
                "Acme B.V. shall deliver order ORD-2026-05 by 15 March 2026 "
                "for 1,234.50 € via https://example.com/v1/items/${API_TOKEN}."
            ),
            translated_text=(
                "Acme B.V. должна доставить заказ ORD-2026-05 до 15 марта 2026 "
                "на сумму 1 234,50 € через https://example.com/v1/items/${API_TOKEN}."
            ),
            source_language="en",
            target_language="ru",
            quality_track=RussianQualityTrack.PRECISION,
        )

        self.assertTrue(result.passed)
        self.assertEqual(result.score, 100.0)
        self.assertEqual(result.issues, ())

    def test_translation_eval_report_aggregates_scores_and_issue_counts(self):
        clean = evaluate_russian_translation(
            sample_id="clean",
            source_text="The room held its breath.",
            translated_text="Комната затаила дыхание.",
            source_language="en",
            target_language="ru",
            quality_track=RussianQualityTrack.LITERARY,
        )
        failing = evaluate_russian_translation(
            sample_id="failing",
            source_text="Українська: Вона тихо зачинила двері, і дім знову навчився мовчати.",
            translated_text="Вона тихо зачинила двері, і дім знову навчився мовчати.",
            source_language="uk",
            target_language="ru",
            quality_track=RussianQualityTrack.LITERARY,
        )

        report = build_translation_eval_report([clean, failing])

        self.assertEqual(report.sample_count, 2)
        self.assertEqual(report.passed_count, 1)
        self.assertEqual(report.failed_count, 1)
        self.assertEqual(report.issue_counts, {"untranslated_text": 1})
        self.assertEqual(report.worst_sample_ids, ("failing",))
        self.assertLess(report.average_score, 100.0)

    def test_optional_metric_adapter_requires_explicit_opt_in(self):
        adapter = _FakeMetricAdapter()

        with self.assertRaises(OptionalMetricDisabledError):
            run_optional_metric(
                adapter,
                source_text="The room held its breath.",
                translated_text="Комната затаила дыхание.",
                reference_translation="Комната словно затаила дыхание.",
                opt_in=False,
            )

        result = run_optional_metric(
            adapter,
            source_text="The room held its breath.",
            translated_text="Комната затаила дыхание.",
            reference_translation="Комната словно затаила дыхание.",
            opt_in=True,
        )

        self.assertEqual(result.metric_name, "fake-chrf")
        self.assertEqual(result.score, 0.82)
        self.assertEqual(result.metric_version, "fake-chrf-v1")

    def test_russian_reference_corpus_passes_deterministic_eval(self):
        evaluated = [
            evaluate_russian_translation(
                sample_id=sample.sample_id,
                source_text=sample.source_text,
                translated_text=sample.reference_translation,
                source_language=sample.source_language,
                target_language=sample.target_language,
                quality_track=sample.quality_track,
            )
            for sample in russian_regression_samples()
            if sample.reference_translation is not None
        ]

        self.assertGreaterEqual(len(evaluated), 5)
        self.assertTrue(all(result.passed for result in evaluated))


class _FakeMetricAdapter:
    def score(
        self,
        *,
        source_text: str,
        translated_text: str,
        reference_translation: str | None = None,
    ) -> ExternalMetricResult:
        return ExternalMetricResult(
            metric_name="fake-chrf",
            metric_version="fake-chrf-v1",
            score=0.82,
            metadata={"reference_used": bool(reference_translation)},
        )


if __name__ == "__main__":
    unittest.main()
