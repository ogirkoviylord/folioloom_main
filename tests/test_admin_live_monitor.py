from __future__ import annotations

import json
import unittest
from collections import namedtuple
from datetime import UTC, datetime
from tempfile import TemporaryDirectory

from translator_service.admin.live import (
    build_live_monitor_snapshot,
    collect_local_server_health,
)
from translator_service.admin.operations import build_operations_overview
from translator_service.admin.provider_runtime import (
    AIProviderRuntimeChannel,
    AIProviderRuntimeProviderState,
    AIProviderRuntimeStatus,
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
                    total_fragment_count=4,
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
            running.record_event(
                "work_unit_started",
                {"sequence": 2, "total_units": 4},
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
        self.assertEqual([run.job_id for run in snapshot.recent_runs], ["job-running"])
        self.assertEqual(snapshot.recent_runs[0].fragment_count, 1)
        self.assertEqual(snapshot.recent_runs[0].total_fragment_count, 4)
        self.assertEqual(snapshot.recent_runs[0].progress_percent, 25.0)
        self.assertEqual(snapshot.recent_runs[0].eta_seconds, 3.0)
        self.assertEqual(snapshot.recent_runs[0].current_stage, "work_unit_started")
        self.assertIsNotNone(snapshot.recent_runs[0].last_event_at)
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

    def test_active_translations_include_running_persistent_jobs_without_run_logs(self):
        with TemporaryDirectory() as temp_dir:
            operations = build_operations_overview(
                jobs=[
                    {"id": "job-running-without-log", "status": "translating"},
                    {"id": "job-queued", "status": "queued"},
                ],
            )

            snapshot = build_live_monitor_snapshot(
                temp_dir,
                operations=operations,
                now=datetime(2026, 5, 9, 12, 0, tzinfo=UTC),
                server=collect_local_server_health(
                    disk_usage=lambda path: (_ for _ in ()).throw(OSError("no disk")),
                    psutil_module=None,
                ),
            )

        self.assertEqual(snapshot.active_translations, 1)
        self.assertEqual(snapshot.queued_translations, 1)

    def test_operations_overview_reports_queue_depth_and_oldest_pending_age(self):
        operations = build_operations_overview(
            jobs=[
                {"id": "job-queued", "status": "queued"},
                {"id": "job-running", "status": "translating"},
            ],
            work_units_by_job_id={
                "job-queued": (
                    {
                        "status": "pending",
                        "available_at": datetime(2026, 5, 9, 11, 59, 30, tzinfo=UTC),
                    },
                    {
                        "status": "queued",
                        "created_at": datetime(2026, 5, 9, 11, 59, 45, tzinfo=UTC),
                    },
                ),
                "job-running": (
                    {
                        "status": "translating",
                        "created_at": datetime(2026, 5, 9, 11, 58, tzinfo=UTC),
                    },
                ),
            },
            now=datetime(2026, 5, 9, 12, 0, tzinfo=UTC),
        )

        self.assertEqual(operations.total_queue_depth, 2)
        self.assertEqual(operations.oldest_pending_age_seconds, 30.0)

    def test_recent_runs_include_running_persistent_jobs_without_run_logs(self):
        with TemporaryDirectory() as temp_dir:
            operations = build_operations_overview(
                jobs=[
                    {
                        "id": "job-running-without-log",
                        "status": "translating",
                        "order_id": "order-1",
                        "file_name": "new-upload.epub",
                        "document_kind": "epub",
                        "source_language": "en",
                        "target_language": "uk",
                        "created_at": datetime(2026, 5, 9, 11, 59, tzinfo=UTC),
                        "updated_at": datetime(2026, 5, 9, 12, 1, tzinfo=UTC),
                    }
                ],
                work_units_by_job_id={
                    "job-running-without-log": (
                        {"status": "translated", "prompt_tokens": 10},
                        {"status": "translating", "completion_tokens": 4},
                        {"status": "pending"},
                    )
                },
            )

            snapshot = build_live_monitor_snapshot(
                temp_dir,
                operations=operations,
                now=datetime(2026, 5, 9, 12, 0, tzinfo=UTC),
                server=collect_local_server_health(
                    disk_usage=lambda path: (_ for _ in ()).throw(OSError("no disk")),
                    psutil_module=None,
                ),
            )

        self.assertEqual(snapshot.active_translations, 1)
        self.assertEqual(
            [run.job_id for run in snapshot.recent_runs],
            ["job-running-without-log"],
        )
        self.assertEqual(snapshot.recent_runs[0].status, "translating")
        self.assertEqual(snapshot.recent_runs[0].file_name, "new-upload.epub")
        self.assertEqual(snapshot.recent_runs[0].source_language, "en")
        self.assertEqual(snapshot.recent_runs[0].target_language, "uk")
        self.assertEqual(snapshot.recent_runs[0].fragment_count, 1)
        self.assertEqual(snapshot.recent_runs[0].total_fragment_count, 3)
        self.assertEqual(snapshot.recent_runs[0].total_tokens, 14)
        self.assertEqual(snapshot.recent_runs[0].eta_seconds, 120.0)

    def test_recent_runs_merge_operation_progress_into_matching_run_log(self):
        with TemporaryDirectory() as temp_dir:
            run_logger = TranslationRunLogger.start(
                root=temp_dir,
                metadata=TranslationRunMetadata(
                    job_id="job-running-with-log",
                    order_id=None,
                    user_id="telegram:42",
                    file_name="logged-upload.epub",
                    document_kind="epub",
                    source_language="en",
                    target_language="ru",
                    total_fragment_count=3,
                ),
            )
            run_logger.record_event(
                "job_queued",
                {"job_id": "job-running-with-log", "fragment_count": 3},
            )
            operations = build_operations_overview(
                jobs=[
                    {
                        "id": "job-running-with-log",
                        "status": "translating",
                        "file_name": "logged-upload.epub",
                        "document_kind": "epub",
                        "source_language": "en",
                        "target_language": "ru",
                        "created_at": datetime(2026, 5, 9, 11, 59, tzinfo=UTC),
                        "updated_at": datetime(2026, 5, 9, 12, 1, tzinfo=UTC),
                    }
                ],
                work_units_by_job_id={
                    "job-running-with-log": (
                        {"status": "translated", "prompt_tokens": 10},
                        {"status": "translated", "completion_tokens": 8},
                        {"status": "translating"},
                    )
                },
            )

            snapshot = build_live_monitor_snapshot(
                temp_dir,
                operations=operations,
                now=datetime(2026, 5, 9, 12, 0, tzinfo=UTC),
                server=collect_local_server_health(
                    disk_usage=lambda path: (_ for _ in ()).throw(OSError("no disk")),
                    psutil_module=None,
                ),
            )

        self.assertEqual(snapshot.active_translations, 1)
        self.assertEqual(
            [run.job_id for run in snapshot.recent_runs],
            ["job-running-with-log"],
        )
        self.assertEqual(snapshot.recent_runs[0].fragment_count, 2)
        self.assertEqual(snapshot.recent_runs[0].total_fragment_count, 3)
        self.assertEqual(snapshot.recent_runs[0].progress_percent, 66.7)
        self.assertEqual(snapshot.recent_runs[0].total_tokens, 18)
        self.assertEqual(snapshot.recent_runs[0].run_dir, str(run_logger.run_dir))

    def test_recent_runs_include_current_resource_usage(self):
        with TemporaryDirectory() as temp_dir:
            running = TranslationRunLogger.start(
                root=temp_dir,
                metadata=TranslationRunMetadata(
                    job_id="job-running",
                    order_id=None,
                    user_id=None,
                    file_name="book.txt",
                    document_kind="txt",
                    source_language="en",
                    target_language="uk",
                    total_fragment_count=2,
                ),
            )
            running.record_event("work_unit_started", {"total_units": 2})
            runtime = AIProviderRuntimeStatus(
                provider_id="deepseek",
                source="bot",
                status="ok",
                reload_interval_seconds=30,
                last_reloaded_at=datetime(2026, 5, 9, 12, 0, tzinfo=UTC),
                active_channels=(
                    AIProviderRuntimeChannel(
                        label="key-a",
                        weight=1,
                        max_parallel_requests=2,
                        active_requests=1,
                    ),
                    AIProviderRuntimeChannel(
                        label="key-b",
                        weight=1,
                        max_parallel_requests=2,
                        active_requests=0,
                        health="cooling_down",
                        total_unsafe_model_output_failures=3,
                    ),
                ),
                provider_state=AIProviderRuntimeProviderState(
                    adaptive_enabled=True,
                    current_limit=3,
                    max_capacity=4,
                    active_requests=1,
                    available_slots=2,
                ),
            )

            snapshot = build_live_monitor_snapshot(
                temp_dir,
                runtime_statuses=(runtime,),
                server=collect_local_server_health(
                    disk_usage=lambda path: (_ for _ in ()).throw(OSError("no disk")),
                    psutil_module=None,
                ),
            )

        resources = snapshot.recent_runs[0].resource_usage
        self.assertEqual(resources["provider"], "deepseek")
        self.assertEqual(resources["active_key_channels"], 2)
        self.assertEqual(resources["active_requests"], 1)
        self.assertEqual(resources["parallel_capacity"], 4)
        self.assertEqual(resources["available_provider_slots"], 2)
        self.assertEqual(resources["cooling_down_channels"], 1)
        self.assertEqual(resources["unsafe_model_output_failures"], 3)

    def test_recent_runs_only_include_active_or_transitioning_runs(self):
        with TemporaryDirectory() as temp_dir:
            TranslationRunLogger.start(
                root=temp_dir,
                metadata=TranslationRunMetadata(
                    job_id="job-running",
                    order_id=None,
                    user_id=None,
                    file_name="running.txt",
                    document_kind="txt",
                    source_language="en",
                    target_language="ru",
                ),
            )
            ready = TranslationRunLogger.start(
                root=temp_dir,
                metadata=TranslationRunMetadata(
                    job_id="job-ready",
                    order_id=None,
                    user_id=None,
                    file_name="ready.txt",
                    document_kind="txt",
                    source_language="en",
                    target_language="ru",
                ),
            )
            ready.finish(status="ready")
            cancelled = TranslationRunLogger.start(
                root=temp_dir,
                metadata=TranslationRunMetadata(
                    job_id="job-cancelled",
                    order_id=None,
                    user_id=None,
                    file_name="cancelled.txt",
                    document_kind="txt",
                    source_language="en",
                    target_language="ru",
                ),
            )
            cancelled.finish(status="cancelled")
            cancelling = TranslationRunLogger.start(
                root=temp_dir,
                metadata=TranslationRunMetadata(
                    job_id="job-cancel-requested",
                    order_id=None,
                    user_id=None,
                    file_name="cancelling.txt",
                    document_kind="txt",
                    source_language="en",
                    target_language="ru",
                ),
            )
            _set_run_status(cancelling.run_dir, "cancel_requested")

            snapshot = build_live_monitor_snapshot(
                temp_dir,
                recent_limit=2,
                server=collect_local_server_health(
                    disk_usage=lambda path: (_ for _ in ()).throw(OSError("no disk")),
                    psutil_module=None,
                ),
            )

        self.assertEqual(
            [run.job_id for run in snapshot.recent_runs],
            ["job-cancel-requested", "job-running"],
        )
        self.assertEqual(
            {run.status for run in snapshot.recent_runs},
            {"cancel_requested", "running"},
        )


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


def _set_run_status(run_dir, status: str) -> None:
    run_json = run_dir / "run.json"
    snapshot = json.loads(run_json.read_text(encoding="utf-8"))
    snapshot["status"] = status
    run_json.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
