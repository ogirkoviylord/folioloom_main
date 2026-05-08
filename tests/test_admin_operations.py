import unittest
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from translator_service.admin.operations import (
    JOB_STATE_CANCELLED,
    JOB_STATE_FAILED,
    JOB_STATE_QUEUED,
    JOB_STATE_RUNNING,
    JOB_STATE_SUCCEEDED,
    build_operations_overview,
    summarize_job,
    summarize_worker,
)


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
