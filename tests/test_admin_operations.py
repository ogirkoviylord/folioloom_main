import unittest
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from translator_service.admin.operations import (
    JOB_STATE_CANCELLED,
    JOB_STATE_FAILED,
    JOB_STATE_QUEUED,
    JOB_STATE_RUNNING,
    JOB_STATE_SUCCEEDED,
    build_operations_overview,
    build_persistent_operations_overview,
    normalize_job_state,
    summarize_job,
    summarize_worker,
)
from translator_service.admin.views import operations_body


class AdminOperationsTest(unittest.TestCase):
    def test_failed_job_summary_is_retryable_not_cancellable(self):
        summary = summarize_job(
            {
                "id": "job-1",
                "status": "interrupted",
                "created_at": _time(0),
                "updated_at": _time(5),
                "last_error": "provider read timeout",
            },
            work_units=[
                {"status": "translated"},
                {"status": "failed", "last_error": "provider read timeout"},
            ],
        )

        self.assertEqual(summary.id, "job-1")
        self.assertEqual(summary.state, JOB_STATE_FAILED)
        self.assertTrue(summary.retryable)
        self.assertFalse(summary.cancellable)
        self.assertEqual(summary.total_units, 2)
        self.assertEqual(summary.completed_units, 1)
        self.assertEqual(summary.failed_units, 1)
        self.assertEqual(summary.error_excerpt, "provider read timeout")

    def test_queued_and_running_job_summaries_are_cancellable(self):
        queued = summarize_job({"id": "job-queued", "status": "pending"})
        running = summarize_job(
            {"id": "job-running", "status": "translating"},
            work_units=[
                {"status": "translating", "worker_id": "worker-a"},
                {"status": "pending"},
            ],
        )

        self.assertEqual(queued.state, JOB_STATE_QUEUED)
        self.assertTrue(queued.cancellable)
        self.assertFalse(queued.retryable)
        self.assertEqual(running.state, JOB_STATE_RUNNING)
        self.assertTrue(running.cancellable)
        self.assertFalse(running.retryable)
        self.assertEqual(running.active_worker_ids, ("worker-a",))

    def test_sanitizes_and_truncates_freeform_error_text(self):
        summary = summarize_job(
            {
                "id": "job-2",
                "status": "failed",
                "error_message": (
                    "DeepSeek failed with sk-live_51abcdefghijklmnopqrstuvwxyz "
                    "and Authorization: Bearer api-key-1234567890abcdef "
                    "while translating a very long chunk of user supplied text."
                ),
            },
            max_error_chars=80,
        )

        self.assertLessEqual(len(summary.error_excerpt), 80)
        self.assertIn("[redacted]", summary.error_excerpt)
        self.assertNotIn("sk-live", summary.error_excerpt)
        self.assertNotIn("api-key", summary.error_excerpt.lower())
        self.assertTrue(summary.error_excerpt.endswith("..."))

    def test_partial_status_is_succeeded(self):
        self.assertEqual(normalize_job_state("partial"), JOB_STATE_SUCCEEDED)

    def test_retryable_and_terminal_failed_units_count_as_failed(self):
        summary = summarize_job(
            {"id": "job-failed-units", "status": "failed"},
            work_units=[
                {"status": "failed_retryable", "last_error": "retryable timeout"},
                {"status": "failed_terminal", "last_error": "terminal policy error"},
                {"status": "translated"},
            ],
        )

        self.assertEqual(summary.failed_units, 2)
        self.assertEqual(summary.completed_units, 1)
        self.assertEqual(summary.error_excerpt, "retryable timeout")

    def test_persistent_overview_does_not_initialize_zero_byte_db(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "empty.sqlite3"
            db_path.touch()

            overview = build_persistent_operations_overview(db_path, temp_dir)

            self.assertEqual(overview.jobs, ())
            self.assertEqual(db_path.stat().st_size, 0)

    def test_overview_aggregates_job_counts_and_worker_health(self):
        now = _time(30)
        overview = build_operations_overview(
            jobs=[
                {"id": "job-queued", "status": "queued"},
                {"id": "job-running", "status": "translating"},
                {"id": "job-ready", "status": "ready"},
                {"id": "job-failed", "status": "failed"},
                {"id": "job-cancelled", "status": "cancelled"},
                {"id": "job-unknown", "status": "paused"},
            ],
            workers=[
                {"id": "worker-a", "status": "running", "queue_name": "default"},
                {
                    "id": "worker-b",
                    "status": "running",
                    "last_heartbeat_at": now - timedelta(minutes=10),
                },
                {"id": "worker-c", "status": "offline"},
            ],
            queue_depths={"default": 4, "priority": 1},
            now=now,
            stale_after=timedelta(minutes=5),
        )

        self.assertEqual(
            overview.job_counts_by_state,
            {
                JOB_STATE_QUEUED: 1,
                JOB_STATE_RUNNING: 1,
                JOB_STATE_SUCCEEDED: 1,
                JOB_STATE_FAILED: 1,
                JOB_STATE_CANCELLED: 1,
                "unknown": 1,
            },
        )
        self.assertEqual(
            overview.worker_counts_by_health,
            {"healthy": 1, "stale": 1, "offline": 1, "unknown": 0},
        )
        self.assertEqual(overview.queue_depths, {"default": 4, "priority": 1})
        self.assertEqual(overview.total_queue_depth, 5)

    def test_overview_rows_include_work_units_tokens_errors_and_log_links(self):
        overview = build_operations_overview(
            jobs=[
                {
                    "id": "job-queued",
                    "status": "queued",
                    "order_id": "order-queued",
                    "created_at": _time(1),
                    "updated_at": _time(2),
                },
                {
                    "id": "job-running",
                    "status": "translating",
                    "order_id": "order-running",
                    "created_at": _time(3),
                    "updated_at": _time(4),
                },
                {
                    "id": "job-failed",
                    "status": "failed",
                    "order_id": "order-failed",
                    "created_at": _time(5),
                    "updated_at": _time(6),
                    "last_error": (
                        "DeepSeek failed with sk-live_51abcdefghijklmnopqrstuvwxyz "
                        "while processing a long provider response that should not "
                        "be shown in full to operators. The upstream payload also "
                        "included several paragraphs of diagnostic context that must "
                        "stay summarized inside the operations table."
                    ),
                },
                {
                    "id": "job-ready",
                    "status": "ready",
                    "order_id": "order-ready",
                    "created_at": _time(7),
                    "updated_at": _time(8),
                },
            ],
            work_units_by_job_id={
                "job-queued": (
                    {"status": "pending", "prompt_tokens": 0, "completion_tokens": 0},
                    {"status": "pending", "prompt_tokens": 0, "completion_tokens": 0},
                ),
                "job-running": (
                    {
                        "status": "translated",
                        "prompt_tokens": 11,
                        "completion_tokens": 5,
                    },
                    {
                        "status": "translating",
                        "worker_id": "worker-a",
                        "prompt_tokens": 7,
                        "completion_tokens": 3,
                        "started_at": _time(4),
                    },
                ),
                "job-failed": (
                    {
                        "status": "failed",
                        "last_error": "Authorization: Bearer secret-token-123456",
                    },
                ),
                "job-ready": (
                    {
                        "status": "translated",
                        "prompt_tokens": 13,
                        "completion_tokens": 8,
                    },
                ),
            },
            job_log_hrefs={"job-ready": "/admin/logs"},
        )

        by_id = {job.id: job for job in overview.jobs}
        self.assertEqual(by_id["job-queued"].state, JOB_STATE_QUEUED)
        self.assertEqual(by_id["job-queued"].total_units, 2)
        self.assertEqual(by_id["job-running"].state, JOB_STATE_RUNNING)
        self.assertEqual(by_id["job-running"].completed_units, 1)
        self.assertEqual(by_id["job-running"].total_tokens, 26)
        self.assertEqual(by_id["job-running"].active_worker_ids, ("worker-a",))
        self.assertEqual(by_id["job-failed"].state, JOB_STATE_FAILED)
        self.assertIn("[redacted]", by_id["job-failed"].error_excerpt)
        self.assertNotIn("sk-live", by_id["job-failed"].error_excerpt)
        self.assertTrue(by_id["job-failed"].error_excerpt.endswith("..."))
        self.assertEqual(by_id["job-ready"].state, JOB_STATE_SUCCEEDED)
        self.assertEqual(by_id["job-ready"].log_href, "/admin/logs")

    def test_operations_body_renders_jobs_table_with_safe_actions_and_logs(self):
        overview = build_operations_overview(
            jobs=[
                {"id": "job-queued", "status": "queued", "order_id": "order-1"},
                {"id": "job-running", "status": "translating", "order_id": "order-2"},
                {
                    "id": "job-failed",
                    "status": "failed",
                    "order_id": "order-3",
                    "last_error": "<script>sk-live_abcdefghi</script>",
                },
                {"id": "job-ready", "status": "ready", "order_id": "order-4"},
            ],
            work_units_by_job_id={
                "job-running": (
                    {
                        "status": "translating",
                        "worker_id": "worker-a",
                        "prompt_tokens": 4,
                        "completion_tokens": 6,
                    },
                ),
            },
            job_log_hrefs={"job-ready": "/admin/logs"},
        )

        html = operations_body(overview)

        self.assertIn("<th>State</th>", html)
        self.assertIn("<th>Job id</th>", html)
        self.assertIn("order-1", html)
        self.assertIn("worker-a", html)
        self.assertIn("10", html)
        self.assertIn('href="/admin/logs"', html)
        self.assertIn(">Retry unavailable<", html)
        self.assertIn(">Cancel unavailable<", html)
        self.assertIn(">No action<", html)
        self.assertIn("&lt;script&gt;[redacted]&lt;/script&gt;", html)
        self.assertNotIn("<script>", html)
        self.assertNotIn("sk-live", html)

    def test_operations_body_rejects_unsafe_log_href(self):
        for unsafe_href in ("javascript:alert(1)", "https://example.test/logs"):
            with self.subTest(unsafe_href=unsafe_href):
                overview = build_operations_overview(
                    jobs=[
                        {
                            "id": "job-ready",
                            "status": "ready",
                            "order_id": "order-4",
                        }
                    ],
                    job_log_hrefs={"job-ready": unsafe_href},
                )

                html = operations_body(overview)

                self.assertNotIn(unsafe_href, html)
                self.assertIn('href="/admin/logs"', html)

    def test_accepts_object_rows_for_jobs_and_workers(self):
        job = _ObjectRow(id="job-3", status="ready", updated_at=_time(2))
        worker = _ObjectRow(
            id="worker-object",
            status="idle",
            queue_name="default",
            last_heartbeat_at=_time(3),
        )

        job_summary = summarize_job(job)
        worker_summary = summarize_worker(worker, now=_time(4))

        self.assertEqual(job_summary.state, JOB_STATE_SUCCEEDED)
        self.assertFalse(job_summary.retryable)
        self.assertFalse(job_summary.cancellable)
        self.assertEqual(worker_summary.id, "worker-object")
        self.assertEqual(worker_summary.health, "healthy")


@dataclass(frozen=True)
class _ObjectRow:
    id: str
    status: str
    updated_at: datetime | None = None
    queue_name: str | None = None
    last_heartbeat_at: datetime | None = None


def _time(minutes: int) -> datetime:
    return datetime(2026, 5, 8, 12, minutes, tzinfo=UTC)


if __name__ == "__main__":
    unittest.main()
