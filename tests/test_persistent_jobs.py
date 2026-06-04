import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from translator_service.persistent_jobs import (
    JobUsageSummary,
    PersistentTranslationJobStatus,
    PersistentWorkUnitStatus,
    SQLiteTranslationJobStore,
    WorkUnitPlan,
)


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
                translation_policy='{"target_language_policy":"target-profile:ru:russian-v1"}',
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
            self.assertEqual(
                persisted_job.translation_policy,
                '{"target_language_policy":"target-profile:ru:russian-v1"}',
            )
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

    def test_claim_next_work_unit_allows_configured_active_units_per_job(self):
        store = self._memory_store()
        job = _job_with_units(store)

        first = store.claim_next_work_unit(
            job.id,
            worker_id="worker-a",
            max_active_units_per_job=2,
        )
        second = store.claim_next_work_unit(
            job.id,
            worker_id="worker-b",
            max_active_units_per_job=2,
        )
        third = store.claim_next_work_unit(
            job.id,
            worker_id="worker-c",
            max_active_units_per_job=2,
        )

        self.assertEqual(first.sequence, 1)
        self.assertEqual(second.sequence, 2)
        self.assertIsNone(third)
        self.assertEqual(first.status, PersistentWorkUnitStatus.TRANSLATING)
        self.assertEqual(second.status, PersistentWorkUnitStatus.TRANSLATING)

    def test_scheduler_claim_sets_token_lease_and_attempt_count(self):
        from translator_service.scheduler import SchedulerLimits

        store = self._memory_store()
        job = _job_with_units(store)

        claim = store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=SchedulerLimits(max_active_units_global=4),
        )
        claimed_unit = store.list_work_units(job.id)[0]

        self.assertEqual(claim.job_id, job.id)
        self.assertEqual(claim.work_unit_id, claimed_unit.id)
        self.assertEqual(claim.worker_id, "worker-a")
        self.assertTrue(claim.claim_token)
        self.assertEqual(claim.attempt_number, 1)
        self.assertEqual(claimed_unit.worker_id, "worker-a")
        self.assertEqual(claimed_unit.claim_token, claim.claim_token)
        self.assertIsNotNone(claimed_unit.lease_until)
        self.assertEqual(claimed_unit.attempt_count, 1)

    def test_scheduler_claim_does_not_overwrite_lost_candidate(self):
        from translator_service.scheduler import SchedulerLimits

        store = self._memory_store()
        job = _job_with_units(store)
        store._connection = _ClaimRaceConnection(store._connection)

        claim = store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=SchedulerLimits(max_active_units_global=4),
        )
        claimed_unit = store.list_work_units(job.id)[0]

        self.assertIsNone(claim)
        self.assertEqual(claimed_unit.worker_id, "worker-race")
        self.assertEqual(claimed_unit.claim_token, "race-token")
        self.assertEqual(claimed_unit.attempt_count, 1)

    def test_completion_requires_matching_claim_token(self):
        from translator_service.scheduler import SchedulerLimits

        store = self._memory_store()
        job = _job_with_units(store)
        claim = store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=SchedulerLimits(),
        )

        with self.assertRaises(ValueError):
            store.complete_claimed_work_unit(
                work_unit_id=claim.work_unit_id,
                claim_token="stale-token",
                translated_text="stale completion",
                prompt_tokens=1,
                completion_tokens=1,
                cache_hit_tokens=0,
                cache_miss_tokens=1,
            )

        store.complete_claimed_work_unit(
            work_unit_id=claim.work_unit_id,
            claim_token=claim.claim_token,
            translated_text="valid completion",
            prompt_tokens=1,
            completion_tokens=1,
            cache_hit_tokens=0,
            cache_miss_tokens=1,
        )

        first_unit = store.list_work_units(job.id)[0]
        self.assertEqual(first_unit.translated_text, "valid completion")

    def test_stale_completion_cannot_overwrite_newer_claim(self):
        from datetime import timedelta

        from translator_service.scheduler import SchedulerLimits

        store = self._memory_store()
        job = _job_with_units(store)
        old_claim = store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=1,
            limits=SchedulerLimits(),
        )
        store.recover_expired_leases(
            now=old_claim.lease_until + timedelta(seconds=1),
            retry_base_delay_seconds=0,
            retry_max_delay_seconds=0,
        )
        new_claim = store.claim_next_scheduled_work_unit(
            worker_id="worker-b",
            lease_seconds=300,
            limits=SchedulerLimits(),
        )

        with self.assertRaises(ValueError):
            store.complete_claimed_work_unit(
                work_unit_id=old_claim.work_unit_id,
                claim_token=old_claim.claim_token,
                translated_text="stale completion",
                prompt_tokens=1,
                completion_tokens=1,
                cache_hit_tokens=0,
                cache_miss_tokens=1,
            )

        first_unit = store.list_work_units(job.id)[0]
        self.assertEqual(first_unit.status, PersistentWorkUnitStatus.TRANSLATING)
        self.assertEqual(first_unit.claim_token, new_claim.claim_token)
        self.assertIsNone(first_unit.translated_text)

    def test_scheduled_claim_allows_later_unit_when_job_active_limit_permits(self):
        from translator_service.scheduler import SchedulerLimits

        store = self._memory_store()
        job = _job_with_units(store)

        first = store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=SchedulerLimits(
                max_active_units_per_job=2,
                max_active_units_per_user=2,
                max_active_units_global=10,
            ),
        )
        second = store.claim_next_scheduled_work_unit(
            worker_id="worker-b",
            lease_seconds=300,
            limits=SchedulerLimits(
                max_active_units_per_job=2,
                max_active_units_per_user=2,
                max_active_units_global=10,
            ),
        )
        third = store.claim_next_scheduled_work_unit(
            worker_id="worker-c",
            lease_seconds=300,
            limits=SchedulerLimits(
                max_active_units_per_job=2,
                max_active_units_per_user=2,
                max_active_units_global=10,
            ),
        )

        self.assertEqual(first.work_unit_id, f"{job.id}:unit-1")
        self.assertEqual(second.work_unit_id, f"{job.id}:unit-2")
        self.assertIsNone(third)

    def test_scheduled_claim_preserves_single_active_ordering_by_default(self):
        from translator_service.scheduler import SchedulerLimits

        store = self._memory_store()
        job = _job_with_units(store)

        first = store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=SchedulerLimits(max_active_units_per_job=1),
        )
        second = store.claim_next_scheduled_work_unit(
            worker_id="worker-b",
            lease_seconds=300,
            limits=SchedulerLimits(max_active_units_per_job=1),
        )

        self.assertEqual(first.work_unit_id, f"{job.id}:unit-1")
        self.assertIsNone(second)

    def test_scheduled_claim_user_unit_cap_blocks_second_job_for_same_user(self):
        from translator_service.scheduler import SchedulerLimits

        store = self._memory_store()
        first_job = _job_with_units(
            store,
            order_id="order-1",
            user_id="user-42",
            file_id="file-1",
        )
        _job_with_units(
            store,
            order_id="order-2",
            user_id="user-42",
            file_id="file-2",
        )
        limits = SchedulerLimits(
            max_active_units_global=10,
            max_active_units_per_job=1,
            max_active_units_per_user=1,
            max_active_jobs_per_user=2,
        )

        first = store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=limits,
        )
        second = store.claim_next_scheduled_work_unit(
            worker_id="worker-b",
            lease_seconds=300,
            limits=limits,
        )

        self.assertEqual(first.job_id, first_job.id)
        self.assertIsNone(second)

    def test_scheduled_claim_prefers_user_with_lower_active_load(self):
        from translator_service.scheduler import SchedulerLimits

        store = self._memory_store()
        first_user_first_job = _job_with_units(
            store,
            order_id="order-1",
            user_id="user-42",
            file_id="file-1",
        )
        _job_with_units(
            store,
            order_id="order-2",
            user_id="user-42",
            file_id="file-2",
        )
        other_user_job = _job_with_units(
            store,
            order_id="order-3",
            user_id="user-100",
            file_id="file-3",
        )
        limits = SchedulerLimits(
            max_active_units_global=10,
            max_active_units_per_job=1,
            max_active_units_per_user=2,
            max_active_jobs_per_user=2,
        )

        first = store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=limits,
        )
        second = store.claim_next_scheduled_work_unit(
            worker_id="worker-b",
            lease_seconds=300,
            limits=limits,
        )

        self.assertEqual(first.job_id, first_user_first_job.id)
        self.assertEqual(second.job_id, other_user_job.id)

    def test_scheduled_claim_priority_aging_prevents_old_job_starvation(self):
        from translator_service.scheduler import SchedulerLimits

        store = self._memory_store()
        old_low_priority = _job_with_units(
            store,
            order_id="order-old",
            user_id="user-old",
            file_id="file-old",
        )
        new_high_priority = _job_with_units(
            store,
            order_id="order-new",
            user_id="user-new",
            file_id="file-new",
        )
        now = datetime.now(UTC)
        with store._connection:
            store._connection.execute(
                """
                UPDATE translation_jobs
                SET priority = ?, created_at = ?
                WHERE id = ?
                """,
                (
                    0,
                    (now - timedelta(minutes=3)).isoformat(),
                    old_low_priority.id,
                ),
            )
            store._connection.execute(
                """
                UPDATE translation_jobs
                SET priority = ?, created_at = ?
                WHERE id = ?
                """,
                (1, now.isoformat(), new_high_priority.id),
            )

        claimed = store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=SchedulerLimits(
                max_active_units_global=10,
                max_active_units_per_job=1,
                max_active_units_per_user=1,
                max_active_jobs_per_user=1,
                priority_aging_seconds=60,
            ),
        )

        self.assertEqual(claimed.job_id, old_low_priority.id)

    def test_retryable_failure_records_attempt_and_delays_reclaim(self):
        from translator_service.scheduler import (
            SchedulerLimits,
            WorkUnitFailureKind,
        )

        store = self._memory_store()
        _job_with_units(store)
        claim = store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=SchedulerLimits(),
        )

        failed = store.fail_claimed_work_unit(
            work_unit_id=claim.work_unit_id,
            claim_token=claim.claim_token,
            failure_kind=WorkUnitFailureKind.RETRYABLE_PROVIDER,
            error_message="provider timeout",
            retry_base_delay_seconds=60,
            retry_max_delay_seconds=600,
        )
        immediate = store.claim_next_scheduled_work_unit(
            worker_id="worker-b",
            lease_seconds=300,
            limits=SchedulerLimits(),
        )
        attempts = store.list_work_unit_attempts(claim.work_unit_id)

        self.assertEqual(failed.status, PersistentWorkUnitStatus.FAILED_RETRYABLE)
        self.assertIsNone(immediate)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0].error_message, "provider timeout")

    def test_provider_failure_diagnostic_is_persisted_on_attempt_and_event(self):
        from translator_service.provider_failure_diagnostics import (
            ProviderFailureCategory,
            ProviderFailureDiagnostic,
        )
        from translator_service.scheduler import (
            SchedulerLimits,
            WorkUnitFailureKind,
        )

        store = self._memory_store()
        job = _job_with_units(store)
        claim = store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=SchedulerLimits(),
        )
        diagnostic = ProviderFailureDiagnostic(
            failure_category=ProviderFailureCategory.TIMEOUT,
            http_status_bucket=None,
            provider_id="deepseek",
            channel_fingerprint="chan_123456789abc",
            latency_ms=842.0,
            adaptive_circuit_snapshot={"circuit_state": "closed"},
        )

        failed = store.fail_claimed_work_unit(
            work_unit_id=claim.work_unit_id,
            claim_token=claim.claim_token,
            failure_kind=WorkUnitFailureKind.RETRYABLE_PROVIDER,
            error_message="retryable provider failure",
            retry_base_delay_seconds=60,
            retry_max_delay_seconds=600,
            provider_failure_diagnostic=diagnostic,
        )

        attempts = store.list_work_unit_attempts(claim.work_unit_id)
        events = store.list_scheduler_events(job.id)
        latest_payload = json.loads(events[-1].payload_json)

        self.assertEqual(failed.status, PersistentWorkUnitStatus.FAILED_RETRYABLE)
        self.assertEqual(attempts[0].error_code, "timeout")
        self.assertEqual(attempts[0].error_message, "provider failure: timeout")
        self.assertEqual(latest_payload["failure_kind"], "retryable_provider")
        self.assertEqual(latest_payload["provider_failure"]["failure_category"], "timeout")
        self.assertEqual(latest_payload["provider_failure"]["provider_id"], "deepseek")
        self.assertEqual(latest_payload["provider_failure"]["latency_ms"], 842.0)
        self.assertEqual(latest_payload["terminal_reason"], None)

    def test_terminal_provider_failure_records_max_attempts_reason(self):
        from translator_service.provider_failure_diagnostics import (
            ProviderFailureCategory,
            ProviderFailureDiagnostic,
        )
        from translator_service.scheduler import (
            SchedulerLimits,
            WorkUnitFailureKind,
        )

        store = self._memory_store()
        job = _job_with_units(store)
        store._connection.execute(
            "UPDATE work_units SET max_attempts = 1 WHERE job_id = ?",
            (job.id,),
        )
        claim = store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=SchedulerLimits(),
        )

        failed = store.fail_claimed_work_unit(
            work_unit_id=claim.work_unit_id,
            claim_token=claim.claim_token,
            failure_kind=WorkUnitFailureKind.RETRYABLE_PROVIDER,
            error_message="retryable provider failure",
            retry_base_delay_seconds=60,
            retry_max_delay_seconds=600,
            provider_failure_diagnostic=ProviderFailureDiagnostic(
                failure_category=ProviderFailureCategory.RATE_LIMITED,
                http_status_bucket="429",
                provider_id="deepseek",
            ),
        )

        events = store.list_scheduler_events(job.id)
        latest_payload = json.loads(events[-1].payload_json)

        self.assertEqual(failed.status, PersistentWorkUnitStatus.FAILED_TERMINAL)
        self.assertEqual(latest_payload["provider_failure"]["failure_category"], "rate_limited")
        self.assertEqual(latest_payload["terminal_reason"], "max_attempts_reached")

    def test_expired_lease_is_recovered_for_retry(self):
        from datetime import timedelta

        from translator_service.scheduler import SchedulerLimits

        store = self._memory_store()
        _job_with_units(store)
        claim = store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=1,
            limits=SchedulerLimits(),
        )

        recovered = store.recover_expired_leases(
            now=claim.lease_until + timedelta(seconds=1),
            retry_base_delay_seconds=0,
            retry_max_delay_seconds=0,
        )
        reclaimed = store.claim_next_scheduled_work_unit(
            worker_id="worker-b",
            lease_seconds=300,
            limits=SchedulerLimits(),
        )

        self.assertEqual(recovered, 1)
        self.assertEqual(reclaimed.work_unit_id, claim.work_unit_id)
        self.assertNotEqual(reclaimed.claim_token, claim.claim_token)

    def test_scheduler_events_capture_claim_complete_and_retry(self):
        from translator_service.scheduler import SchedulerLimits, WorkUnitFailureKind

        store = self._memory_store()
        job = _job_with_units(store)
        claim = store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=SchedulerLimits(),
        )
        store.fail_claimed_work_unit(
            work_unit_id=claim.work_unit_id,
            claim_token=claim.claim_token,
            failure_kind=WorkUnitFailureKind.RETRYABLE_PROVIDER,
            error_message="provider timeout",
            retry_base_delay_seconds=60,
            retry_max_delay_seconds=600,
        )

        events = store.list_scheduler_events(job.id)

        self.assertEqual(
            [event.event_type for event in events],
            ["work_unit_claimed", "work_unit_retry_scheduled"],
        )
        self.assertEqual(events[0].job_id, job.id)
        self.assertEqual(events[0].work_unit_id, claim.work_unit_id)

    def test_worker_heartbeat_is_upserted(self):
        store = self._memory_store()

        store.record_worker_heartbeat(
            worker_id="worker-a",
            worker_kind="translation",
            status="idle",
            active_job_id=None,
            active_work_unit_id=None,
        )
        store.record_worker_heartbeat(
            worker_id="worker-a",
            worker_kind="translation",
            status="busy",
            active_job_id="job-1",
            active_work_unit_id="job-1:unit-1",
        )

        heartbeat = store.get_worker_heartbeat("worker-a")

        self.assertEqual(heartbeat.worker_id, "worker-a")
        self.assertEqual(heartbeat.status, "busy")
        self.assertEqual(heartbeat.active_job_id, "job-1")

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

    def test_pause_job_stops_new_claims_and_can_be_resumed(self):
        store = self._memory_store()
        job = _job_with_units(store)
        claimed = store.claim_next_work_unit(job.id, worker_id="worker-a")

        paused = store.pause_job(job.id)
        no_claim = store.claim_next_work_unit(job.id, worker_id="worker-b")
        resumed = store.resume_job(job.id)
        next_claim = store.claim_next_work_unit(job.id, worker_id="worker-c")

        self.assertEqual(paused.status, PersistentTranslationJobStatus.PAUSED)
        self.assertIsNone(no_claim)
        self.assertEqual(resumed.status, PersistentTranslationJobStatus.QUEUED)
        self.assertEqual(next_claim.id, claimed.id)

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

    def test_lists_jobs_for_user_with_most_recent_first(self):
        store = self._memory_store()
        first = store.create_job(
            order_id="order-1",
            user_id="telegram:42",
            file_id="file-1",
            file_name="first.epub",
            document_kind="epub",
            source_language="en",
            target_language="uk",
            adapter_version="epub-v1",
            prompt_version="plain-v1",
            pricing_snapshot_id="pricing-1",
            source_object_key="original/first.epub",
        )
        second = store.create_job(
            order_id="order-2",
            user_id="telegram:42",
            file_id="file-2",
            file_name="second.docx",
            document_kind="docx",
            source_language="en",
            target_language="ru",
            adapter_version="docx-v1",
            prompt_version="plain-v1",
            pricing_snapshot_id="pricing-1",
            source_object_key="original/second.docx",
        )
        store.create_job(
            order_id="order-3",
            user_id="telegram:100",
            file_id="file-3",
            file_name="other.txt",
            document_kind="txt",
            source_language="en",
            target_language="fr",
            adapter_version="txt-v1",
            prompt_version="plain-v1",
            pricing_snapshot_id="pricing-1",
            source_object_key="original/other.txt",
        )

        jobs = store.list_jobs_for_user("telegram:42", limit=5)

        self.assertEqual([job.id for job in jobs], [second.id, first.id])
        self.assertEqual([job.file_name for job in jobs], ["second.docx", "first.epub"])

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


def _job_with_units(
    store: SQLiteTranslationJobStore,
    *,
    order_id: str = "order-1",
    user_id: str = "user-42",
    file_id: str = "file-1",
):
    job = store.create_job(
        order_id=order_id,
        user_id=user_id,
        file_id=file_id,
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


class _ClaimRaceConnection:
    def __init__(self, connection):
        self._connection = connection
        self._armed = True

    def execute(self, sql, parameters=()):
        cursor = self._connection.execute(sql, parameters)
        if self._armed and "SELECT wu.*" in sql:
            self._armed = False
            return _ClaimRaceCursor(self._connection, cursor)
        return cursor

    def executemany(self, *args, **kwargs):
        return self._connection.executemany(*args, **kwargs)

    def __enter__(self):
        self._connection.__enter__()
        return self

    def __exit__(self, *args):
        return self._connection.__exit__(*args)

    def close(self):
        return self._connection.close()


class _ClaimRaceCursor:
    def __init__(self, connection, cursor):
        self._connection = connection
        self._cursor = cursor

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is not None:
            self._connection.execute(
                """
                UPDATE work_units
                SET status = ?, worker_id = ?, claim_token = ?,
                    attempt_count = attempt_count + 1
                WHERE id = ?
                """,
                (
                    PersistentWorkUnitStatus.TRANSLATING.value,
                    "worker-race",
                    "race-token",
                    row["id"],
                ),
            )
        return row


if __name__ == "__main__":
    unittest.main()
