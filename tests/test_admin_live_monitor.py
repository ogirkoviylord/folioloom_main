from __future__ import annotations

import unittest
from tempfile import TemporaryDirectory

from translator_service.admin.live import build_live_monitor_snapshot
from translator_service.translation_run_logs import (
    TranslationFragmentLog,
    TranslationRunLogger,
    TranslationRunMetadata,
)


class AdminLiveMonitorTest(unittest.TestCase):
    def test_builds_privacy_safe_live_snapshot_from_translation_runs(self):
        with TemporaryDirectory() as temp_dir:
            running = TranslationRunLogger.start(
                root=temp_dir,
                metadata=TranslationRunMetadata(
                    job_id="job-running",
                    order_id="order-1",
                    user_id="telegram:42",
                    file_name="active-book.txt",
                    document_kind="txt",
                    source_language="en",
                    target_language="ru",
                ),
            )
            running.record_fragment(
                TranslationFragmentLog(
                    sequence=1,
                    source_text="private source",
                    translated_text="private target",
                    status="translated",
                    elapsed_seconds=1.0,
                    prompt_tokens=100,
                    completion_tokens=40,
                    total_tokens=140,
                )
            )
            failed = TranslationRunLogger.start(
                root=temp_dir,
                metadata=TranslationRunMetadata(
                    job_id="job-failed",
                    order_id=None,
                    user_id="telegram:77",
                    file_name="failed-book.docx",
                    document_kind="docx",
                    source_language="en",
                    target_language="uk",
                ),
            )
            failed.finish(status="failed", error_message="provider timeout")

            snapshot = build_live_monitor_snapshot(temp_dir)

        self.assertEqual(snapshot.active_translations, 1)
        self.assertEqual(snapshot.failed_today, 1)
        self.assertEqual(snapshot.tokens_today, 140)
        self.assertEqual(snapshot.tokens_last_hour, 140)
        self.assertEqual(snapshot.recent_runs[0].job_id, "job-failed")
        self.assertEqual(snapshot.recent_runs[1].job_id, "job-running")
        self.assertFalse(snapshot.server.available)
        self.assertNotIn("private source", repr(snapshot))
        self.assertNotIn("private target", repr(snapshot))


if __name__ == "__main__":
    unittest.main()
