from __future__ import annotations

import unittest
from collections import namedtuple
from datetime import UTC, datetime
from tempfile import TemporaryDirectory

from translator_service.admin.live import (
    build_live_monitor_snapshot,
    collect_local_server_health,
)
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

            snapshot = build_live_monitor_snapshot(
                temp_dir,
                server=collect_local_server_health(
                    disk_usage=_fake_disk_usage,
                    psutil_module=_FakePsutil(),
                    now=lambda: datetime(2026, 5, 9, 12, 0, tzinfo=UTC),
                ),
            )

        self.assertEqual(snapshot.active_translations, 1)
        self.assertEqual(snapshot.failed_today, 1)
        self.assertEqual(snapshot.tokens_today, 140)
        self.assertEqual(snapshot.tokens_last_hour, 140)
        self.assertEqual(snapshot.recent_runs[0].job_id, "job-failed")
        self.assertEqual(snapshot.recent_runs[1].job_id, "job-running")
        self.assertTrue(snapshot.server.available)
        self.assertEqual(snapshot.server.cpu_percent, 12.5)
        self.assertEqual(snapshot.server.memory_percent, 62.5)
        self.assertEqual(snapshot.server.disk_percent, 50.0)
        self.assertEqual(snapshot.server.uptime_seconds, 120.0)
        self.assertNotIn("private source", repr(snapshot))
        self.assertNotIn("private target", repr(snapshot))

    def test_local_server_health_degrades_when_metrics_are_unavailable(self):
        snapshot = collect_local_server_health(
            disk_usage=lambda path: (_ for _ in ()).throw(OSError("no disk")),
            psutil_module=None,
        )

        self.assertFalse(snapshot.available)
        self.assertIsNone(snapshot.cpu_percent)
        self.assertIsNone(snapshot.memory_percent)


_DiskUsage = namedtuple("_DiskUsage", ("total", "used", "free"))


def _fake_disk_usage(path):
    return _DiskUsage(
        total=100 * 1024 * 1024 * 1024,
        used=50 * 1024 * 1024 * 1024,
        free=50 * 1024 * 1024 * 1024,
    )


class _FakeMemory:
    percent = 62.5
    used = 640 * 1024 * 1024
    total = 1024 * 1024 * 1024


class _FakePsutil:
    def cpu_percent(self, interval=None):
        return 12.5

    def virtual_memory(self):
        return _FakeMemory()

    def boot_time(self):
        return datetime(2026, 5, 9, 11, 58, tzinfo=UTC).timestamp()


if __name__ == "__main__":
    unittest.main()
