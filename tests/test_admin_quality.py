import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from translator_service.admin.quality import build_quality_run_summary


class AdminQualityTest(unittest.TestCase):
    def test_missing_quality_run_returns_privacy_safe_empty_summary(self):
        summary = build_quality_run_summary("/tmp/folioloom-missing-quality-run.jsonl")

        self.assertFalse(summary.found)
        self.assertEqual(summary.scored_samples, 0)
        self.assertGreaterEqual(summary.total_reference_samples, 5)
        self.assertIsNone(summary.average_meteor)
        self.assertIsNone(summary.average_chrf)
        self.assertTrue(all(row.status == "missing" for row in summary.rows))
        self.assertNotIn("translated_text", repr(summary))
        self.assertNotIn("reference_translation", repr(summary))
        self.assertNotIn("source_text", repr(summary))

    def test_scores_jsonl_candidates_against_reference_samples(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "latest.jsonl"
            path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "sample_id": "ru-ordinary-calque-decision-overview",
                                "translated_text": (
                                    "Он принял решение после общего описания системы."
                                ),
                            },
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            {
                                "sample_id": "ru-literary-rain-window",
                                "translated_text": (
                                    "Комната словно затаила дыхание, пока дождь "
                                    "чертил серебряные линии на стекле."
                                ),
                            },
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            {
                                "sample_id": "unknown-sample",
                                "translated_text": "Extra candidate.",
                            },
                            ensure_ascii=False,
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            summary = build_quality_run_summary(path)

        self.assertTrue(summary.found)
        self.assertEqual(summary.scored_samples, 2)
        self.assertEqual(summary.extra_candidates, 1)
        self.assertGreater(summary.missing_samples, 0)
        self.assertEqual(summary.average_meteor, 1.0)
        self.assertEqual(summary.average_chrf, 1.0)
        scored = [row for row in summary.rows if row.status == "scored"]
        self.assertEqual(len(scored), 2)
        self.assertTrue(all(row.meteor == 1.0 for row in scored))
        self.assertTrue(all(row.chrf == 1.0 for row in scored))

    def test_malformed_jsonl_lines_are_reported_without_raw_text(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "latest.jsonl"
            path.write_text(
                '{"sample_id":"ru-ordinary-calque-decision-overview"}\n'
                "{not-json}\n",
                encoding="utf-8",
            )

            summary = build_quality_run_summary(path)

        error_rows = [row for row in summary.rows if row.status == "error"]
        self.assertEqual(len(error_rows), 1)
        self.assertEqual(
            error_rows[0].sample_id,
            "ru-ordinary-calque-decision-overview",
        )
        self.assertIn("translated_text", error_rows[0].error or "")
        self.assertEqual(summary.malformed_candidates, 1)
        self.assertNotIn("{not-json}", repr(summary))


if __name__ == "__main__":
    unittest.main()
