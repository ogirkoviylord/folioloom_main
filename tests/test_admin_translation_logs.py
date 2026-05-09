from __future__ import annotations

import unittest
from tempfile import TemporaryDirectory

from translator_service.admin.translation_logs import (
    get_translation_run_details,
    list_translation_run_summaries,
)
from translator_service.translation_run_logs import (
    TranslationFragmentLog,
    TranslationRunLogger,
    TranslationRunMetadata,
)


class AdminTranslationLogsTest(unittest.TestCase):
    def test_lists_translation_runs_without_document_text(self):
        with TemporaryDirectory() as temp_dir:
            ready = TranslationRunLogger.start(
                root=temp_dir,
                metadata=TranslationRunMetadata(
                    job_id="job-ready",
                    order_id="order-1",
                    user_id="telegram:42",
                    file_name="novel.txt",
                    document_kind="txt",
                    source_language="en",
                    target_language="ru",
                    translator_model="deepseek",
                ),
            )
            ready.finish(status="ready", result_file_name="novel.ru.txt")
            failed = TranslationRunLogger.start(
                root=temp_dir,
                metadata=TranslationRunMetadata(
                    job_id="job-failed",
                    order_id=None,
                    user_id="telegram:77",
                    file_name="contract.docx",
                    document_kind="docx",
                    source_language="en",
                    target_language="uk",
                ),
            )
            failed.finish(status="failed", error_message="provider timeout")

            rows = list_translation_run_summaries(temp_dir)

        self.assertEqual([row.job_id for row in rows], ["job-failed", "job-ready"])
        self.assertEqual(rows[0].status, "failed")
        self.assertEqual(rows[0].file_name, "contract.docx")
        self.assertEqual(rows[0].error_message, "provider timeout")
        self.assertIsNone(rows[0].order_id)
        self.assertEqual(rows[1].result_file_name, "novel.ru.txt")
        self.assertNotIn("source_text", repr(rows))
        self.assertNotIn("translated_text", repr(rows))

    def test_filters_by_status_and_date_range(self):
        with TemporaryDirectory() as temp_dir:
            first = TranslationRunLogger.start(
                root=temp_dir,
                metadata=TranslationRunMetadata(
                    job_id="job-ready",
                    order_id=None,
                    user_id=None,
                    file_name="first.txt",
                    document_kind="txt",
                    source_language="en",
                    target_language="ru",
                ),
            )
            first.finish(status="ready")
            second = TranslationRunLogger.start(
                root=temp_dir,
                metadata=TranslationRunMetadata(
                    job_id="job-failed",
                    order_id=None,
                    user_id=None,
                    file_name="second.txt",
                    document_kind="txt",
                    source_language="en",
                    target_language="ru",
                ),
            )
            second.finish(status="failed")

            ready_rows = list_translation_run_summaries(temp_dir, status="ready")
            failed_day = second.run_dir.name[:10]
            failed_rows = list_translation_run_summaries(
                temp_dir,
                status="failed",
                date_from=failed_day,
                date_to=failed_day,
            )

        self.assertEqual([row.job_id for row in ready_rows], ["job-ready"])
        self.assertEqual([row.job_id for row in failed_rows], ["job-failed"])

    def test_missing_log_root_returns_empty_list(self):
        rows = list_translation_run_summaries("/tmp/does-not-exist-folioloom")

        self.assertEqual(rows, ())

    def test_loads_translation_run_details_without_document_text(self):
        with TemporaryDirectory() as temp_dir:
            logger = TranslationRunLogger.start(
                root=temp_dir,
                metadata=TranslationRunMetadata(
                    job_id="job-detail",
                    order_id="order-42",
                    user_id="telegram:42",
                    file_name="novel.epub",
                    document_kind="epub",
                    source_language="en",
                    target_language="uk",
                    translator_model="deepseek-test",
                    prompt_version="prompt-v2",
                    adapter_version="epub-adapter-v3",
                    translation_policy="policy-v1",
                    translation_quality_route="ukrainian-literary",
                    translation_stack={
                        "schema_version": "stack-v1",
                        "adapter": {
                            "name": "epub",
                            "version": "epub-adapter-v3",
                        },
                        "language_profiles": {
                            "target_language": {"signature": "uk-profile-v1"},
                            "source_pair": {"signature": "en-uk-v1"},
                            "quality_track": {"signature": "literary-v1"},
                        },
                    },
                ),
            )
            logger.record_fragment(
                TranslationFragmentLog(
                    sequence=1,
                    source_text="Original paragraph",
                    translated_text="Перекладений абзац",
                    status="ready",
                    elapsed_seconds=1.25,
                    prompt_tokens=100,
                    completion_tokens=70,
                    total_tokens=170,
                    source_block_ids=("chapter-1",),
                    prompt_tier="literary",
                    retry_count=1,
                )
            )
            logger.finish(status="ready", result_file_name="novel.uk.epub")

            details = get_translation_run_details(temp_dir, logger.run_dir.name)

        self.assertIsNotNone(details)
        assert details is not None
        self.assertEqual(details.summary.job_id, "job-detail")
        self.assertEqual(details.summary.status, "ready")
        self.assertEqual(details.totals["total_tokens"], 170)
        self.assertEqual(details.metadata["prompt_version"], "prompt-v2")
        self.assertEqual(details.metadata["adapter_version"], "epub-adapter-v3")
        self.assertEqual(details.translation_stack["schema_version"], "stack-v1")
        self.assertEqual(details.fragments[0].sequence, 1)
        self.assertEqual(details.fragments[0].source_text_chars, 18)
        self.assertEqual(details.fragments[0].translated_text_chars, 18)
        self.assertEqual(details.fragments[0].source_block_ids, ("chapter-1",))
        self.assertIn("run_started", [event.event_type for event in details.events])
        self.assertNotIn("Original paragraph", repr(details))
        self.assertNotIn("Перекладений абзац", repr(details))


if __name__ == "__main__":
    unittest.main()
