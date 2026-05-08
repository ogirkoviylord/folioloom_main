import os
import unittest
from concurrent.futures import ThreadPoolExecutor

from translator_service.persistent_jobs import (
    JobUsageSummary,
    PersistentTranslationJobStatus,
    PersistentWorkUnitStatus,
    WorkUnitPlan,
)
from translator_service.postgres_jobs import PostgreSQLTranslationJobStore


@unittest.skipUnless(os.getenv("TEST_POSTGRES_DSN"), "TEST_POSTGRES_DSN is not set")
class PostgreSQLTranslationJobStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = PostgreSQLTranslationJobStore(os.environ["TEST_POSTGRES_DSN"])
        self.addCleanup(self.store.close)
        self.store.reset_schema_for_tests()

    def test_creates_claims_completes_and_summarizes_job(self):
        job = _job_with_units(self.store)

        claimed = self.store.claim_next_work_unit(job.id, worker_id="worker-a")
        self.assertEqual(claimed.sequence, 1)
        self.assertEqual(claimed.status, PersistentWorkUnitStatus.TRANSLATING)
        self.assertEqual(claimed.worker_id, "worker-a")

        completed = self.store.complete_work_unit(
            claimed.id,
            translated_text="Привіт",
            prompt_tokens=10,
            completion_tokens=5,
            cache_hit_tokens=2,
            cache_miss_tokens=8,
        )

        self.assertEqual(completed.status, PersistentWorkUnitStatus.TRANSLATED)
        self.assertEqual(completed.translated_text, "Привіт")
        self.assertEqual(
            self.store.get_job(job.id).status,
            PersistentTranslationJobStatus.TRANSLATING,
        )
        self.assertEqual(
            self.store.get_usage_summary(job.id),
            JobUsageSummary(
                job_id=job.id,
                translated_units=1,
                prompt_tokens=10,
                completion_tokens=5,
                cache_hit_tokens=2,
                cache_miss_tokens=8,
                total_tokens=15,
            ),
        )

        second = self.store.claim_next_work_unit(job.id, worker_id="worker-a")
        self.store.complete_work_unit(
            second.id,
            translated_text="Світ",
            prompt_tokens=7,
            completion_tokens=4,
            cache_hit_tokens=1,
            cache_miss_tokens=6,
        )
        self.assertEqual(
            self.store.get_job(job.id).status,
            PersistentTranslationJobStatus.READY,
        )

    def test_claim_next_work_unit_is_ordered_and_single_active_per_job(self):
        job = _job_with_units(self.store)

        def claim(worker_id):
            store = PostgreSQLTranslationJobStore(os.environ["TEST_POSTGRES_DSN"])
            try:
                return store.claim_next_work_unit(job.id, worker_id=worker_id)
            finally:
                store.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(claim, ["worker-a", "worker-b"]))

        claimed = [unit for unit in results if unit is not None]
        missed = [unit for unit in results if unit is None]

        self.assertEqual(len(claimed), 1)
        self.assertEqual(len(missed), 1)
        self.assertEqual(claimed[0].sequence, 1)
        self.assertEqual(claimed[0].status, PersistentWorkUnitStatus.TRANSLATING)

    def test_list_claimable_jobs_returns_queued_translating_and_interrupted_jobs(self):
        queued = _job_with_units(self.store)
        translating = _job_with_units(self.store)
        interrupted = _job_with_units(self.store)
        ready = _job_with_units(self.store)
        cancelled = _job_with_units(self.store)

        self.store.claim_next_work_unit(translating.id, worker_id="worker-a")
        failed_unit = self.store.claim_next_work_unit(
            interrupted.id,
            worker_id="worker-a",
        )
        self.store.fail_work_unit(
            failed_unit.id,
            error_message="provider read timeout",
            retry_count=1,
        )
        for unit in self.store.list_work_units(ready.id):
            claimed = self.store.claim_next_work_unit(ready.id, worker_id="worker-a")
            self.store.complete_work_unit(
                claimed.id,
                translated_text=f"Done {unit.sequence}",
                prompt_tokens=1,
                completion_tokens=1,
                cache_hit_tokens=0,
                cache_miss_tokens=1,
            )
        self.store.cancel_job(cancelled.id)

        claimable = self.store.list_claimable_jobs()

        self.assertEqual(
            [job.id for job in claimable],
            [queued.id, translating.id, interrupted.id],
        )
        self.assertEqual(
            [job.status for job in claimable],
            [
                PersistentTranslationJobStatus.QUEUED,
                PersistentTranslationJobStatus.TRANSLATING,
                PersistentTranslationJobStatus.INTERRUPTED,
            ],
        )

    def test_cancel_and_resume_preserve_completed_work_and_retry_failed_units(self):
        job = _job_with_units(self.store)
        first = self.store.claim_next_work_unit(job.id, worker_id="worker-a")
        self.store.complete_work_unit(
            first.id,
            translated_text="Привіт",
            prompt_tokens=10,
            completion_tokens=5,
            cache_hit_tokens=0,
            cache_miss_tokens=10,
        )

        cancelled = self.store.cancel_job(job.id)
        self.assertEqual(cancelled.status, PersistentTranslationJobStatus.CANCELLED)
        self.assertEqual(
            [unit.status for unit in self.store.list_work_units(job.id)],
            [PersistentWorkUnitStatus.TRANSLATED, PersistentWorkUnitStatus.PENDING],
        )

        resumed = self.store.resume_job(job.id)
        second = self.store.claim_next_work_unit(job.id, worker_id="worker-b")
        failed = self.store.fail_work_unit(
            second.id,
            error_message="provider read timeout",
            retry_count=3,
        )
        retried = self.store.resume_job(job.id)
        claimed_again = self.store.claim_next_work_unit(job.id, worker_id="worker-c")

        self.assertEqual(resumed.status, PersistentTranslationJobStatus.QUEUED)
        self.assertEqual(failed.status, PersistentWorkUnitStatus.FAILED)
        self.assertEqual(failed.last_error, "provider read timeout")
        self.assertEqual(retried.status, PersistentTranslationJobStatus.QUEUED)
        self.assertEqual(claimed_again.id, second.id)
        self.assertEqual(claimed_again.status, PersistentWorkUnitStatus.TRANSLATING)

    def test_reclaims_expired_translating_unit_after_worker_crash(self):
        job = _job_with_units(self.store)
        first = self.store.claim_next_work_unit(job.id, worker_id="worker-a")

        reclaimed = self.store.reclaim_stale_work_units(
            lease_seconds=0,
            worker_id="worker-b",
        )
        reclaimed_unit = self.store.list_work_units(job.id)[0]
        reclaimed_job = self.store.get_job(job.id)
        second = self.store.claim_next_work_unit(job.id, worker_id="worker-b")

        self.assertEqual(reclaimed, 1)
        self.assertEqual(reclaimed_unit.status, PersistentWorkUnitStatus.PENDING)
        self.assertIsNone(reclaimed_unit.worker_id)
        self.assertEqual(reclaimed_job.status, PersistentTranslationJobStatus.QUEUED)
        self.assertEqual(first.id, second.id)
        self.assertEqual(second.worker_id, "worker-b")
        self.assertEqual(
            self.store.get_job(job.id).status,
            PersistentTranslationJobStatus.TRANSLATING,
        )

    def test_stale_worker_cannot_complete_reclaimed_unit(self):
        job = _job_with_units(self.store)
        first = self.store.claim_next_work_unit(job.id, worker_id="worker-a")
        self.store.reclaim_stale_work_units(lease_seconds=0, worker_id="worker-b")
        claimed_by_new_worker = self.store.claim_next_work_unit(
            job.id,
            worker_id="worker-b",
        )

        stale_result = self.store.complete_work_unit(
            first.id,
            translated_text="stale result",
            prompt_tokens=1,
            completion_tokens=1,
            cache_hit_tokens=0,
            cache_miss_tokens=1,
            worker_id="worker-a",
        )
        final_result = self.store.complete_work_unit(
            claimed_by_new_worker.id,
            translated_text="fresh result",
            prompt_tokens=2,
            completion_tokens=2,
            cache_hit_tokens=0,
            cache_miss_tokens=2,
            worker_id="worker-b",
        )

        self.assertEqual(stale_result.status, PersistentWorkUnitStatus.TRANSLATING)
        self.assertEqual(stale_result.worker_id, "worker-b")
        self.assertIsNone(stale_result.translated_text)
        self.assertEqual(final_result.status, PersistentWorkUnitStatus.TRANSLATED)
        self.assertEqual(final_result.translated_text, "fresh result")

    def test_stale_worker_cannot_fail_reclaimed_unit(self):
        job = _job_with_units(self.store)
        first = self.store.claim_next_work_unit(job.id, worker_id="worker-a")
        self.store.reclaim_stale_work_units(lease_seconds=0, worker_id="worker-b")
        self.store.claim_next_work_unit(job.id, worker_id="worker-b")

        stale_result = self.store.fail_work_unit(
            first.id,
            error_message="old timeout",
            retry_count=1,
            worker_id="worker-a",
        )

        self.assertEqual(stale_result.status, PersistentWorkUnitStatus.TRANSLATING)
        self.assertEqual(stale_result.worker_id, "worker-b")
        self.assertIsNone(stale_result.last_error)
        self.assertEqual(
            self.store.get_job(job.id).status,
            PersistentTranslationJobStatus.TRANSLATING,
        )

    def test_reclaim_does_not_reopen_terminal_job(self):
        job = _job_with_units(self.store)
        active = self.store.claim_next_work_unit(job.id, worker_id="worker-a")
        self.store.cancel_job(job.id)
        with self.store._connection.transaction():
            self.store._connection.execute(
                """
                UPDATE work_units
                SET status = %s, worker_id = %s
                WHERE id = %s
                """,
                (
                    PersistentWorkUnitStatus.TRANSLATING.value,
                    "worker-a",
                    active.id,
                ),
            )

        reclaimed = self.store.reclaim_stale_work_units(
            lease_seconds=0,
            worker_id="worker-b",
        )

        self.assertEqual(reclaimed, 0)
        self.assertEqual(
            self.store.get_job(job.id).status,
            PersistentTranslationJobStatus.CANCELLED,
        )

    def test_attach_output_and_timestamps_are_timezone_aware(self):
        job = _job_with_units(self.store)

        partial = self.store.attach_job_output(
            job.id,
            partial_object_key="partial/job-1-book.partial.txt",
        )
        final = self.store.attach_job_output(
            job.id,
            final_object_key="final/job-1-book.txt",
        )
        unit = self.store.claim_next_work_unit(job.id, worker_id="worker-a")

        self.assertEqual(partial.partial_object_key, "partial/job-1-book.partial.txt")
        self.assertIsNone(partial.final_object_key)
        self.assertEqual(final.partial_object_key, "partial/job-1-book.partial.txt")
        self.assertEqual(final.final_object_key, "final/job-1-book.txt")
        self.assertIsNotNone(final.created_at.tzinfo)
        self.assertIsNotNone(unit.created_at.tzinfo)
        self.assertIsNotNone(unit.started_at.tzinfo)


def _job_with_units(store: PostgreSQLTranslationJobStore):
    job = store.create_job(
        order_id="order-1",
        user_id="user-42",
        file_id="file-1",
        file_name="book.epub",
        document_kind="epub",
        source_language="auto",
        target_language="uk",
        adapter_version="epub-v1",
        prompt_version="plain-v1",
        pricing_snapshot_id="pricing-1",
        source_object_key="original/file-1.epub",
    )
    store.add_work_units(
        job.id,
        [
            WorkUnitPlan(
                sequence=1,
                source_block_ids=("chapter-1:p1",),
                source_text_hash="hash-1",
                prompt_tier="plain",
                source_language="en",
                target_language="uk",
                source_object_key="intermediate/job-1/unit-1.txt",
            ),
            WorkUnitPlan(
                sequence=2,
                source_block_ids=("chapter-1:p2",),
                source_text_hash="hash-2",
                prompt_tier="plain",
                source_language="en",
                target_language="uk",
                source_object_key="intermediate/job-1/unit-2.txt",
            ),
        ],
    )
    return job


if __name__ == "__main__":
    unittest.main()
