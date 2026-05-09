import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from translator_service.admin.quality import build_quality_run_summary
from translator_service.admin.quality_runner import write_quality_run


class _FakeTranslator:
    def translate(
        self,
        *,
        text: str,
        source_language: str,
        target_language: str,
    ) -> str:
        return f"[{target_language}] {source_language}: {text}"


class _FailingTranslator:
    def translate(
        self,
        *,
        text: str,
        source_language: str,
        target_language: str,
    ) -> str:
        raise RuntimeError("provider secret sk-raw-secret failed")


class AdminQualityTest(unittest.TestCase):
    def test_missing_quality_run_returns_privacy_safe_empty_summary(self):
        summary = build_quality_run_summary("/tmp/folioloom-missing-quality-run.jsonl")

        self.assertFalse(summary.found)
        self.assertEqual(summary.scored_samples, 0)
        self.assertGreaterEqual(summary.total_reference_samples, 5)
        self.assertIsNone(summary.average_meteor)
        self.assertIsNone(summary.average_chrf)
        self.assertTrue(all(row.status == "missing" for row in summary.rows))
        target_languages = [
            group.target_language for group in summary.language_groups
        ]
        self.assertIn("ru", target_languages)
        self.assertIn("uk", target_languages)
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
                        json.dumps(
                            {
                                "sample_id": "uk-ordinary-calque-decision-overview",
                                "translated_text": (
                                    "Він ухвалив рішення після загального огляду "
                                    "системи."
                                ),
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
        self.assertEqual(summary.scored_samples, 3)
        self.assertEqual(summary.extra_candidates, 1)
        self.assertGreater(summary.missing_samples, 0)
        self.assertEqual(summary.average_meteor, 1.0)
        self.assertEqual(summary.average_chrf, 1.0)
        scored = [row for row in summary.rows if row.status == "scored"]
        self.assertEqual(len(scored), 3)
        self.assertTrue(all(row.meteor == 1.0 for row in scored))
        self.assertTrue(all(row.chrf == 1.0 for row in scored))
        language_counts = {
            group.target_language: group.total_reference_samples
            for group in summary.language_groups
        }
        self.assertGreaterEqual(language_counts["ru"], 5)
        self.assertGreaterEqual(language_counts["uk"], 4)

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

    def test_quality_runner_writes_candidates_without_source_text(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "latest.jsonl"

            result = write_quality_run(path, translator=_FakeTranslator())

            payloads = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
            ]
        self.assertTrue(result.translated_samples)
        self.assertEqual(result.failed_samples, 0)
        self.assertTrue(all("sample_id" in payload for payload in payloads))
        self.assertTrue(all("translated_text" in payload for payload in payloads))
        self.assertTrue(all("source_text" not in payload for payload in payloads))
        self.assertNotIn("source_text", repr(result))

    def test_quality_runner_records_redacted_sample_errors(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "latest.jsonl"

            result = write_quality_run(path, translator=_FailingTranslator())
            summary = build_quality_run_summary(path)

        self.assertEqual(result.translated_samples, 0)
        self.assertGreater(result.failed_samples, 0)
        self.assertEqual(summary.scored_samples, 0)
        self.assertGreater(
            len([row for row in summary.rows if row.status == "error"]),
            0,
        )
        self.assertNotIn("sk-raw-secret", repr(result))
        self.assertNotIn("sk-raw-secret", repr(summary))


if __name__ == "__main__":
    unittest.main()
