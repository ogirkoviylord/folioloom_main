from __future__ import annotations

import unittest
from dataclasses import dataclass
from datetime import UTC, datetime
from tempfile import TemporaryDirectory

from translator_service.admin.operations import JOB_STATE_RUNNING
from translator_service.admin.translation_logs import list_translation_run_summaries
from translator_service.admin.translation_progress import (
    build_durable_translation_progress_snapshot,
)
from translator_service.translation_run_logs import (
    TranslationRunLogger,
    TranslationRunMetadata,
)


class AdminTranslationProgressTest(unittest.TestCase):
    def test_snapshot_uses_durable_units_when_run_log_progress_is_stale_zero(self):
        with TemporaryDirectory() as temp_dir:
            TranslationRunLogger.start(
                root=temp_dir,
                metadata=TranslationRunMetadata(
                    job_id="job-progress",
                    order_id="order-1",
                    user_id="telegram:42",
                    file_name="book.epub",
                    document_kind="epub",
                    source_language="en",
                    target_language="ru",
                    total_fragment_count=0,
                ),
            )
            [run] = list_translation_run_summaries(temp_dir)

        store = _FakeProgressStore(
            job=_Row(
                id="job-progress",
                status="translating",
                created_at=_time(0),
                updated_at=_time(10),
            ),
            units=(
                _Row(
                    status="translated",
                    prompt_tokens=100,
                    completion_tokens=30,
                    cache_hit_tokens=25,
                    cache_miss_tokens=75,
                    retry_count=0,
                    translated_text="private translated text",
                    started_at=_time(1),
                    completed_at=_time(2),
                ),
                _Row(
                    status="cached",
                    prompt_tokens=80,
                    completion_tokens=20,
                    cache_hit_tokens=80,
                    cache_miss_tokens=0,
                    retry_count=0,
                    translated_text="private cached text",
                    started_at=_time(2),
                    completed_at=_time(3),
                ),
                _Row(status="pending"),
                _Row(status="translating", worker_id="worker-b", started_at=_time(9)),
                _Row(
                    status="failed_retryable",
                    prompt_tokens=12,
                    completion_tokens=4,
                    retry_count=2,
                    last_error="Authorization: Bearer secret-token private source",
                ),
            ),
        )

        snapshot = build_durable_translation_progress_snapshot(
            "job-progress",
            store=store,
            now=_time(11),
        )

        self.assertEqual(run.fragment_count, 0)
        self.assertTrue(snapshot.available)
        self.assertEqual(snapshot.job_id, "job-progress")
        self.assertEqual(snapshot.status, "translating")
        self.assertEqual(snapshot.state, JOB_STATE_RUNNING)
        self.assertEqual(snapshot.completed_units, 2)
        self.assertEqual(snapshot.total_units, 5)
        self.assertEqual(snapshot.failed_units, 1)
        self.assertEqual(snapshot.active_units, 1)
        self.assertEqual(snapshot.pending_units, 1)
        self.assertEqual(snapshot.prompt_tokens, 192)
        self.assertEqual(snapshot.completion_tokens, 54)
        self.assertEqual(snapshot.cache_hit_tokens, 105)
        self.assertEqual(snapshot.cache_miss_tokens, 75)
        self.assertEqual(snapshot.total_tokens, 246)
        self.assertEqual(snapshot.retry_count, 2)
        self.assertEqual(snapshot.active_worker_ids, ("worker-b",))
        self.assertEqual(snapshot.progress_percent, 40.0)
        self.assertEqual(snapshot.eta_seconds, 900.0)
        self.assertEqual(snapshot.started_at, _time(1))
        self.assertEqual(snapshot.completed_at, _time(3))

        snapshot_repr = repr(snapshot)
        self.assertNotIn("private translated text", snapshot_repr)
        self.assertNotIn("private cached text", snapshot_repr)
        self.assertNotIn("private source", snapshot_repr)
        self.assertNotIn("secret-token", snapshot_repr)

    def test_snapshot_handles_missing_store_and_job_without_leaking_exceptions(self):
        no_store = build_durable_translation_progress_snapshot(
            "job-missing-store",
            store=None,
        )
        missing_job = build_durable_translation_progress_snapshot(
            "job-missing",
            store=_FakeProgressStore(job=None),
        )
        store_error = build_durable_translation_progress_snapshot(
            "job-error",
            store=_FakeProgressStore(error=RuntimeError("private stack text")),
        )

        self.assertFalse(no_store.available)
        self.assertEqual(no_store.unavailable_reason, "store_unavailable")
        self.assertFalse(missing_job.available)
        self.assertEqual(missing_job.unavailable_reason, "job_not_found")
        self.assertFalse(store_error.available)
        self.assertEqual(store_error.unavailable_reason, "store_error")
        self.assertNotIn("private stack text", repr(store_error))


@dataclass(frozen=True)
class _Row:
    id: str | None = None
    status: str | None = None
    worker_id: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_hit_tokens: int = 0
    cache_miss_tokens: int = 0
    retry_count: int = 0
    translated_text: str | None = None
    last_error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class _FakeProgressStore:
    def __init__(
        self,
        *,
        job: _Row | None = None,
        units: tuple[_Row, ...] = (),
        error: Exception | None = None,
    ) -> None:
        self._job = job
        self._units = units
        self._error = error

    def get_job(self, job_id: str) -> _Row | None:
        if self._error is not None:
            raise self._error
        return self._job

    def list_work_units(self, job_id: str) -> tuple[_Row, ...]:
        if self._error is not None:
            raise self._error
        return self._units


def _time(minutes: int) -> datetime:
    return datetime(2026, 6, 6, 12, minutes, tzinfo=UTC)


if __name__ == "__main__":
    unittest.main()
