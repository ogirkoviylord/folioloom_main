import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory

from translator_service.job_store import TranslationJobStore
from translator_service.persistent_jobs import (
    JobUsageSummary,
    PersistentTranslationJobStatus,
    PersistentWorkUnitStatus,
    SQLiteTranslationJobStore,
    WorkUnitPlan,
)


class JobStoreProtocolTests(unittest.TestCase):
    def test_sqlite_store_satisfies_translation_job_store_protocol(self):
        store: TranslationJobStore = SQLiteTranslationJobStore(":memory:")
        self.addCleanup(store.close)

        job = store.create_job(
            order_id="order-1",
            user_id="user-1",
            file_id="file-1",
            file_name="book.txt",
            document_kind="txt",
            source_language="en",
            target_language="uk",
            adapter_version="txt-v1",
            prompt_version="prompt-v1",
            pricing_snapshot_id="price-v1",
            source_object_key="original/file-1.txt",
        )

        self.assertEqual(store.get_job(job.id).id, job.id)


class SQLiteTranslationJobStoreTest(unittest.TestCase):
    def test_job_and_work_units_survive_store_reopen(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "jobs.sqlite3"
            store = SQLiteTranslationJobStore(db_path)
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
                source_object_key="original/abc-book.epub",
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
                        source_block_ids=("chapter-1:p2", "chapter-1:p3"),
                        source_text_hash="hash-2",
                        prompt_tier="structured",
                        source_language="en",
                        target_language="uk",
                        source_object_key="intermediate/job-1/unit-2.txt",
                    ),
                ],
            )
            store.close()

            reopened = SQLiteTranslationJobStore(db_path)
            self.addCleanup(reopened.close)
            persisted_job = reopened.get_job(job.id)
            work_units = reopened.list_work_units(job.id)

            self.assertEqual(
                persisted_job.status,
                PersistentTranslationJobStatus.QUEUED,
            )
            self.assertEqual(persisted_job.file_name, "book.epub")
            self.assertEqual(persisted_job.source_object_key, "original/abc-book.epub")
            self.assertEqual(len(work_units), 2)
            self.assertEqual(work_units[0].status, PersistentWorkUnitStatus.PENDING)
            self.assertEqual(work_units[0].source_block_ids, ("chapter-1:p1",))
            self.assertEqual(
                work_units[0].source_object_key,
                "intermediate/job-1/unit-1.txt",
            )
            self.assertEqual(
                work_units[1].source_block_ids,
                ("chapter-1:p2", "chapter-1:p3"),
            )
            self.assertEqual(
                work_units[1].source_object_key,
                "intermediate/job-1/unit-2.txt",
            )

    def test_claim_next_work_unit_is_ordered_and_single_active_per_job(self):
        store = self._memory_store()
        job = _job_with_units(store)

        claimed = store.claim_next_work_unit(job.id, worker_id="worker-a")
        second_claim = store.claim_next_work_unit(job.id, worker_id="worker-b")
        persisted_job = store.get_job(job.id)

        self.assertEqual(claimed.sequence, 1)
        self.assertEqual(claimed.status, PersistentWorkUnitStatus.TRANSLATING)
        self.assertEqual(claimed.worker_id, "worker-a")
        self.assertIsNone(second_claim)
        self.assertEqual(
            persisted_job.status,
            PersistentTranslationJobStatus.TRANSLATING,
        )

    def test_list_claimable_jobs_returns_queued_translating_and_interrupted_jobs(self):
        store = self._memory_store()
        queued = _job_with_units(store)
        translating = _job_with_units(store)
        interrupted = _job_with_units(store)
        ready = _job_with_units(store)
        cancelled = _job_with_units(store)

        store.claim_next_work_unit(translating.id, worker_id="worker-a")
        failed_unit = store.claim_next_work_unit(interrupted.id, worker_id="worker-a")
        store.fail_work_unit(
            failed_unit.id,
            error_message="provider read timeout",
            retry_count=1,
        )
        for unit in store.list_work_units(ready.id):
            claimed = store.claim_next_work_unit(ready.id, worker_id="worker-a")
            store.complete_work_unit(
                claimed.id,
                translated_text=f"Done {unit.sequence}",
                prompt_tokens=1,
                completion_tokens=1,
                cache_hit_tokens=0,
                cache_miss_tokens=1,
            )
        store.cancel_job(cancelled.id)

        claimable = store.list_claimable_jobs()

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

    def test_complete_work_units_stores_usage_and_marks_job_ready(self):
        store = self._memory_store()
        job = _job_with_units(store)

        first = store.claim_next_work_unit(job.id, worker_id="worker-a")
        completed_first = store.complete_work_unit(
            first.id,
            translated_text="Перший абзац.",
            prompt_tokens=100,
            completion_tokens=20,
            cache_hit_tokens=30,
            cache_miss_tokens=70,
        )
        second = store.claim_next_work_unit(job.id, worker_id="worker-a")
        store.complete_work_unit(
            second.id,
            translated_text="Другий абзац.",
            prompt_tokens=80,
            completion_tokens=16,
            cache_hit_tokens=0,
            cache_miss_tokens=80,
        )

        persisted_job = store.get_job(job.id)
        work_units = store.list_work_units(job.id)

        self.assertEqual(completed_first.status, PersistentWorkUnitStatus.TRANSLATED)
        self.assertEqual(completed_first.translated_text, "Перший абзац.")
        self.assertEqual(completed_first.prompt_tokens, 100)
        self.assertEqual(completed_first.completion_tokens, 20)
        self.assertEqual(completed_first.cache_hit_tokens, 30)
        self.assertEqual(completed_first.cache_miss_tokens, 70)
        self.assertEqual(persisted_job.status, PersistentTranslationJobStatus.READY)
        self.assertEqual(
            [unit.status for unit in work_units],
            [
                PersistentWorkUnitStatus.TRANSLATED,
                PersistentWorkUnitStatus.TRANSLATED,
            ],
        )

    def test_cancel_job_preserves_completed_work_and_pending_resume_units(self):
        store = self._memory_store()
        job = _job_with_units(store)
        first = store.claim_next_work_unit(job.id, worker_id="worker-a")
        store.complete_work_unit(
            first.id,
            translated_text="Перший абзац.",
            prompt_tokens=10,
            completion_tokens=5,
            cache_hit_tokens=0,
            cache_miss_tokens=10,
        )

        cancelled = store.cancel_job(job.id)
        work_units = store.list_work_units(job.id)

        self.assertEqual(cancelled.status, PersistentTranslationJobStatus.CANCELLED)
        self.assertEqual(work_units[0].status, PersistentWorkUnitStatus.TRANSLATED)
        self.assertEqual(work_units[0].translated_text, "Перший абзац.")
        self.assertEqual(work_units[1].status, PersistentWorkUnitStatus.PENDING)

    def test_resume_after_reopen_claims_first_pending_unit_after_completed_work(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "jobs.sqlite3"
            store = SQLiteTranslationJobStore(db_path)
            job = _job_with_units(store)
            first = store.claim_next_work_unit(job.id, worker_id="worker-a")
            store.complete_work_unit(
                first.id,
                translated_text="Перший абзац.",
                prompt_tokens=10,
                completion_tokens=5,
                cache_hit_tokens=0,
                cache_miss_tokens=10,
            )
            store.cancel_job(job.id)
            store.close()

            reopened = SQLiteTranslationJobStore(db_path)
            self.addCleanup(reopened.close)
            resumed = reopened.resume_job(job.id)
            next_unit = reopened.claim_next_work_unit(job.id, worker_id="worker-b")

            self.assertEqual(resumed.status, PersistentTranslationJobStatus.QUEUED)
            self.assertEqual(next_unit.sequence, 2)
            self.assertEqual(next_unit.status, PersistentWorkUnitStatus.TRANSLATING)

    def test_failed_work_unit_interrupts_job_and_can_be_resumed(self):
        store = self._memory_store()
        job = _job_with_units(store)
        first = store.claim_next_work_unit(job.id, worker_id="worker-a")

        failed = store.fail_work_unit(
            first.id,
            error_message="provider read timeout",
            retry_count=3,
        )
        interrupted = store.get_job(job.id)
        resumed = store.resume_job(job.id)
        retried = store.claim_next_work_unit(job.id, worker_id="worker-b")

        self.assertEqual(failed.status, PersistentWorkUnitStatus.FAILED)
        self.assertEqual(failed.last_error, "provider read timeout")
        self.assertEqual(failed.retry_count, 3)
        self.assertEqual(interrupted.status, PersistentTranslationJobStatus.INTERRUPTED)
        self.assertEqual(resumed.status, PersistentTranslationJobStatus.QUEUED)
        self.assertEqual(retried.id, first.id)
        self.assertEqual(retried.status, PersistentWorkUnitStatus.TRANSLATING)

    def test_reclaims_expired_translating_unit_after_worker_crash(self):
        store = self._memory_store()
        job = _job_with_units(store)
        first = store.claim_next_work_unit(job.id, worker_id="worker-a")

        reclaimed = store.reclaim_stale_work_units(
            lease_seconds=0,
            worker_id="worker-b",
        )
        reclaimed_unit = store.list_work_units(job.id)[0]
        reclaimed_job = store.get_job(job.id)
        second = store.claim_next_work_unit(job.id, worker_id="worker-b")

        self.assertEqual(reclaimed, 1)
        self.assertEqual(reclaimed_unit.status, PersistentWorkUnitStatus.PENDING)
        self.assertIsNone(reclaimed_unit.worker_id)
        self.assertEqual(reclaimed_job.status, PersistentTranslationJobStatus.QUEUED)
        self.assertEqual(first.id, second.id)
        self.assertEqual(second.worker_id, "worker-b")
        self.assertEqual(
            store.get_job(job.id).status,
            PersistentTranslationJobStatus.TRANSLATING,
        )

    def test_stale_worker_cannot_complete_reclaimed_unit(self):
        store = self._memory_store()
        job = _job_with_units(store)
        first = store.claim_next_work_unit(job.id, worker_id="worker-a")
        store.reclaim_stale_work_units(lease_seconds=0, worker_id="worker-b")
        claimed_by_new_worker = store.claim_next_work_unit(
            job.id,
            worker_id="worker-b",
        )

        stale_result = store.complete_work_unit(
            first.id,
            translated_text="stale result",
            prompt_tokens=1,
            completion_tokens=1,
            cache_hit_tokens=0,
            cache_miss_tokens=1,
            worker_id="worker-a",
        )
        final_result = store.complete_work_unit(
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
        store = self._memory_store()
        job = _job_with_units(store)
        first = store.claim_next_work_unit(job.id, worker_id="worker-a")
        store.reclaim_stale_work_units(lease_seconds=0, worker_id="worker-b")
        store.claim_next_work_unit(job.id, worker_id="worker-b")

        stale_result = store.fail_work_unit(
            first.id,
            error_message="old timeout",
            retry_count=1,
            worker_id="worker-a",
        )

        self.assertEqual(stale_result.status, PersistentWorkUnitStatus.TRANSLATING)
        self.assertEqual(stale_result.worker_id, "worker-b")
        self.assertIsNone(stale_result.last_error)
        self.assertEqual(
            store.get_job(job.id).status,
            PersistentTranslationJobStatus.TRANSLATING,
        )

    def test_reclaim_does_not_reopen_terminal_job(self):
        store = self._memory_store()
        job = _job_with_units(store)
        active = store.claim_next_work_unit(job.id, worker_id="worker-a")
        store.cancel_job(job.id)
        with store._connection:
            store._connection.execute(
                """
                UPDATE work_units
                SET status = ?, worker_id = ?
                WHERE id = ?
                """,
                (
                    PersistentWorkUnitStatus.TRANSLATING.value,
                    "worker-a",
                    active.id,
                ),
            )

        reclaimed = store.reclaim_stale_work_units(
            lease_seconds=0,
            worker_id="worker-b",
        )

        self.assertEqual(reclaimed, 0)
        self.assertEqual(
            store.get_job(job.id).status,
            PersistentTranslationJobStatus.CANCELLED,
        )

    def test_usage_summary_sums_completed_work_units(self):
        store = self._memory_store()
        job = _job_with_units(store)

        first = store.claim_next_work_unit(job.id, worker_id="worker-a")
        store.complete_work_unit(
            first.id,
            translated_text="Перший абзац.",
            prompt_tokens=100,
            completion_tokens=20,
            cache_hit_tokens=30,
            cache_miss_tokens=70,
        )
        second = store.claim_next_work_unit(job.id, worker_id="worker-a")
        store.complete_work_unit(
            second.id,
            translated_text="Другий абзац.",
            prompt_tokens=80,
            completion_tokens=16,
            cache_hit_tokens=5,
            cache_miss_tokens=75,
        )

        summary = store.get_usage_summary(job.id)

        self.assertEqual(
            summary,
            JobUsageSummary(
                job_id=job.id,
                translated_units=2,
                prompt_tokens=180,
                completion_tokens=36,
                cache_hit_tokens=35,
                cache_miss_tokens=145,
                total_tokens=216,
            ),
        )

    def test_attaches_partial_and_final_output_object_keys_to_job(self):
        store = self._memory_store()
        job = _job_with_units(store)

        partial = store.attach_job_output(
            job.id,
            partial_object_key="partial/job-1-book.partial.txt",
        )
        final = store.attach_job_output(
            job.id,
            final_object_key="final/job-1-book.txt",
        )

        self.assertEqual(partial.partial_object_key, "partial/job-1-book.partial.txt")
        self.assertIsNone(partial.final_object_key)
        self.assertEqual(final.partial_object_key, "partial/job-1-book.partial.txt")
        self.assertEqual(final.final_object_key, "final/job-1-book.txt")

    def test_store_can_be_used_from_worker_thread(self):
        with TemporaryDirectory() as temp_dir:
            store = SQLiteTranslationJobStore(Path(temp_dir) / "jobs.sqlite3")
            self.addCleanup(store.close)
            job = _job_with_units(store)

            def claim_in_worker():
                return store.claim_next_work_unit(job.id, worker_id="worker-a")

            with ThreadPoolExecutor(max_workers=1) as pool:
                claimed = pool.submit(claim_in_worker).result(timeout=5)

            self.assertEqual(claimed.sequence, 1)
            self.assertEqual(claimed.status, PersistentWorkUnitStatus.TRANSLATING)

    def test_store_creates_parent_directory_for_file_database(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "var" / "jobs.sqlite3"

            store = SQLiteTranslationJobStore(db_path)
            self.addCleanup(store.close)

            self.assertTrue(db_path.exists())

    def _memory_store(self) -> SQLiteTranslationJobStore:
        store = SQLiteTranslationJobStore(":memory:")
        self.addCleanup(store.close)
        return store


def _job_with_units(store: SQLiteTranslationJobStore):
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
