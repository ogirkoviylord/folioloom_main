import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from translator_service.persistent_jobs import (
    GLOSSARY_APPROVAL_SCHEMA_VERSION,
    GLOSSARY_SNAPSHOT_SCHEMA_VERSION,
    JobUsageSummary,
    PersistentTranslationJobStatus,
    PersistentWorkUnitStatus,
    SQLiteTranslationJobStore,
    StrictDocxAdmissionRequest,
    WorkUnitPlan,
)
from translator_service.scheduler import (
    SCHEDULER_FAIR_QUEUE_POLICY,
    SchedulerBackpressureState,
    SchedulerLimits,
    WorkUnitFailureKind,
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

    def test_request_cancel_job_stops_legacy_claims(self):
        store = self._memory_store()
        job = _job_with_units(store)

        store.request_cancel_job(job.id)

        self.assertEqual(
            store.get_job(job.id).status,
            PersistentTranslationJobStatus.CANCELLED,
        )
        self.assertIsNone(store.claim_next_work_unit(job.id, worker_id="worker-a"))

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
        events = store.list_scheduler_events(job.id)
        payload = json.loads(events[-1].payload_json)
        self.assertEqual(payload["queue_policy"], SCHEDULER_FAIR_QUEUE_POLICY)
        diagnostics = payload["queue_policy_diagnostics"]
        self.assertEqual(diagnostics["active_user_units_before_claim"], 0)
        self.assertEqual(diagnostics["active_user_jobs_before_claim"], 0)
        self.assertEqual(diagnostics["active_job_units_before_claim"], 0)
        self.assertEqual(diagnostics["max_active_units_per_job"], 1)
        self.assertEqual(diagnostics["max_active_units_per_user"], 1)
        self.assertEqual(diagnostics["max_active_jobs_per_user"], 1)

    def test_backpressure_diagnostics_empty_queue_are_idle(self):
        store = self._memory_store()

        diagnostics = store.get_scheduler_backpressure_diagnostics()

        self.assertEqual(
            diagnostics.backpressure_state,
            SchedulerBackpressureState.IDLE,
        )
        self.assertEqual(diagnostics.queue_depth_units, 0)
        self.assertEqual(diagnostics.eligible_waiting_units, 0)
        self.assertEqual(diagnostics.pressure_reasons, ("no_eligible_work",))
        self.assertEqual(diagnostics.eta.unknown_reason, "no_eligible_work")

    def test_backpressure_diagnostics_count_mixed_jobs_from_durable_queue(self):
        store = self._memory_store()
        _job_with_unit_count(
            store,
            order_id="order-large",
            user_id="user-large",
            file_id="file-large",
            unit_count=3,
        )
        _job_with_unit_count(
            store,
            order_id="order-small",
            user_id="user-small",
            file_id="file-small",
            unit_count=1,
        )

        diagnostics = store.get_scheduler_backpressure_diagnostics()

        self.assertEqual(
            diagnostics.backpressure_state,
            SchedulerBackpressureState.CAPACITY_WAIT,
        )
        self.assertEqual(diagnostics.queue_depth_units, 4)
        self.assertEqual(diagnostics.eligible_waiting_units, 2)
        self.assertEqual(diagnostics.active_work_units, 0)
        self.assertIn("provider_capacity_unknown", diagnostics.pressure_reasons)

    def test_backpressure_diagnostics_report_retry_and_expired_lease_pressure(self):
        from translator_service.scheduler import SchedulerLimits, WorkUnitFailureKind

        store = self._memory_store()
        retry_job = _job_with_unit_count(
            store,
            order_id="order-retry",
            user_id="user-retry",
            file_id="file-retry",
            unit_count=1,
        )
        retry_claim = store.claim_next_scheduled_work_unit(
            worker_id="worker-retry",
            lease_seconds=300,
            limits=SchedulerLimits(max_active_units_global=2),
        )
        store.fail_claimed_work_unit(
            work_unit_id=retry_claim.work_unit_id,
            claim_token=retry_claim.claim_token,
            failure_kind=WorkUnitFailureKind.RETRYABLE_PROVIDER,
            error_message="provider timeout",
            retry_base_delay_seconds=60,
            retry_max_delay_seconds=60,
        )
        expired_job = _job_with_unit_count(
            store,
            order_id="order-expired",
            user_id="user-expired",
            file_id="file-expired",
            unit_count=1,
        )
        expired_claim = store.claim_next_scheduled_work_unit(
            worker_id="worker-expired",
            lease_seconds=1,
            limits=SchedulerLimits(max_active_units_global=2),
        )

        diagnostics = store.get_scheduler_backpressure_diagnostics(
            now=expired_claim.lease_until + timedelta(seconds=1),
        )

        self.assertEqual(
            diagnostics.backpressure_state,
            SchedulerBackpressureState.RECOVERY_NEEDED,
        )
        self.assertEqual(diagnostics.queue_depth_units, 1)
        self.assertEqual(diagnostics.delayed_retry_units, 1)
        self.assertEqual(diagnostics.retry_pressure_units, 1)
        self.assertEqual(diagnostics.active_work_units, 1)
        self.assertEqual(diagnostics.expired_work_unit_leases, 1)
        self.assertIn("lease_expiry_recovery", diagnostics.pressure_reasons)
        self.assertIn("provider_failure_retry_pressure", diagnostics.pressure_reasons)
        self.assertEqual(
            store.get_job(retry_job.id).status,
            PersistentTranslationJobStatus.TRANSLATING,
        )
        self.assertEqual(
            store.get_job(expired_job.id).status,
            PersistentTranslationJobStatus.TRANSLATING,
        )

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

    def test_scheduled_fair_queue_prevents_large_job_from_monopolizing_slots(self):
        from translator_service.scheduler import SchedulerLimits

        store = self._memory_store()
        large_job = _job_with_unit_count(
            store,
            order_id="order-large",
            user_id="user-large",
            file_id="file-large",
            unit_count=4,
        )
        small_a = _job_with_unit_count(
            store,
            order_id="order-small-a",
            user_id="user-small-a",
            file_id="file-small-a",
            unit_count=1,
        )
        small_b = _job_with_unit_count(
            store,
            order_id="order-small-b",
            user_id="user-small-b",
            file_id="file-small-b",
            unit_count=1,
        )
        limits = SchedulerLimits(
            max_active_units_global=3,
            max_active_units_per_job=3,
            max_active_units_per_user=3,
            max_active_jobs_per_user=3,
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
        third = store.claim_next_scheduled_work_unit(
            worker_id="worker-c",
            lease_seconds=300,
            limits=limits,
        )

        self.assertEqual(first.job_id, large_job.id)
        self.assertEqual({second.job_id, third.job_id}, {small_a.id, small_b.id})
        self.assertNotIn(large_job.id, {second.job_id, third.job_id})

    def test_scheduled_fair_queue_allows_same_user_rotation_when_caps_allow(self):
        from translator_service.scheduler import SchedulerLimits

        store = self._memory_store()
        first_job = _job_with_unit_count(
            store,
            order_id="order-1",
            user_id="user-42",
            file_id="file-1",
            unit_count=2,
        )
        second_job = _job_with_unit_count(
            store,
            order_id="order-2",
            user_id="user-42",
            file_id="file-2",
            unit_count=1,
        )
        limits = SchedulerLimits(
            max_active_units_global=2,
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

        self.assertEqual(first.job_id, first_job.id)
        self.assertEqual(second.job_id, second_job.id)
        self.assertNotEqual(first.work_unit_id, second.work_unit_id)
        second_events = store.list_scheduler_events(second_job.id)
        second_payload = json.loads(second_events[-1].payload_json)
        diagnostics = second_payload["queue_policy_diagnostics"]
        self.assertEqual(diagnostics["active_user_units_before_claim"], 1)
        self.assertEqual(diagnostics["active_user_jobs_before_claim"], 1)
        self.assertEqual(diagnostics["active_job_units_before_claim"], 0)

    def test_scheduled_fair_queue_moves_past_retryable_failure_backoff(self):
        from translator_service.scheduler import SchedulerLimits, WorkUnitFailureKind

        store = self._memory_store()
        retrying_job = _job_with_unit_count(
            store,
            order_id="order-retry",
            user_id="user-retry",
            file_id="file-retry",
            unit_count=1,
        )
        ready_job = _job_with_unit_count(
            store,
            order_id="order-ready",
            user_id="user-ready",
            file_id="file-ready",
            unit_count=1,
        )
        limits = SchedulerLimits(
            max_active_units_global=1,
            max_active_units_per_job=1,
            max_active_units_per_user=1,
            max_active_jobs_per_user=1,
        )
        claim = store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=limits,
        )

        failed = store.fail_claimed_work_unit(
            work_unit_id=claim.work_unit_id,
            claim_token=claim.claim_token,
            failure_kind=WorkUnitFailureKind.RETRYABLE_PROVIDER,
            error_message="provider timeout",
            retry_base_delay_seconds=60,
            retry_max_delay_seconds=60,
        )
        next_claim = store.claim_next_scheduled_work_unit(
            worker_id="worker-b",
            lease_seconds=300,
            limits=limits,
        )

        self.assertEqual(claim.job_id, retrying_job.id)
        self.assertEqual(failed.status, PersistentWorkUnitStatus.FAILED_RETRYABLE)
        self.assertEqual(next_claim.job_id, ready_job.id)

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
        self.assertEqual(
            latest_payload["provider_failure"]["failure_category"],
            "timeout",
        )
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
        self.assertEqual(
            latest_payload["provider_failure"]["failure_category"],
            "rate_limited",
        )
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

    def test_cancel_requested_job_waits_for_active_claims_then_cancels(self):
        from translator_service.scheduler import SchedulerLimits

        store = self._memory_store()
        job = _job_with_units(store)
        limits = SchedulerLimits(
            max_active_units_per_job=2,
            max_active_units_per_user=2,
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
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)

        store.request_cancel_job(job.id)
        store.complete_claimed_work_unit(
            work_unit_id=first.work_unit_id,
            claim_token=first.claim_token,
            translated_text="Перший абзац.",
            prompt_tokens=10,
            completion_tokens=5,
            cache_hit_tokens=0,
            cache_miss_tokens=10,
        )
        after_first = store.get_job(job.id)
        store.complete_claimed_work_unit(
            work_unit_id=second.work_unit_id,
            claim_token=second.claim_token,
            translated_text="Другий абзац.",
            prompt_tokens=10,
            completion_tokens=5,
            cache_hit_tokens=0,
            cache_miss_tokens=10,
        )
        after_second = store.get_job(job.id)

        self.assertEqual(
            after_first.status,
            PersistentTranslationJobStatus.CANCEL_REQUESTED,
        )
        self.assertEqual(
            after_second.status,
            PersistentTranslationJobStatus.CANCELLED,
        )

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

    def test_resume_job_retries_terminal_failed_work_unit_after_partial_result(self):
        store = self._memory_store()
        job = _job_with_units(store)
        with store._connection:
            store._connection.execute(
                "UPDATE work_units SET max_attempts = 1 WHERE job_id = ?",
                (job.id,),
            )
        first = store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=SchedulerLimits(),
        )
        store.complete_claimed_work_unit(
            work_unit_id=first.work_unit_id,
            claim_token=first.claim_token,
            translated_text="Перший абзац.",
            prompt_tokens=10,
            completion_tokens=5,
            cache_hit_tokens=0,
            cache_miss_tokens=10,
        )
        terminal = store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=SchedulerLimits(),
        )
        store.fail_claimed_work_unit(
            work_unit_id=terminal.work_unit_id,
            claim_token=terminal.claim_token,
            failure_kind=WorkUnitFailureKind.MALFORMED_PROVIDER_OUTPUT,
            error_message="provider failure: malformed_response",
            retry_base_delay_seconds=0,
            retry_max_delay_seconds=0,
        )
        store.attach_job_output(
            job.id,
            partial_object_key="partial/job-1-book.partial.epub",
        )
        store.mark_job_assembled(job.id, partial=True)

        resumed = store.resume_job(job.id)
        retried = store.claim_next_scheduled_work_unit(
            worker_id="worker-b",
            lease_seconds=300,
            limits=SchedulerLimits(),
        )

        self.assertEqual(resumed.status, PersistentTranslationJobStatus.QUEUED)
        self.assertIsNone(resumed.partial_object_key)
        self.assertEqual(retried.work_unit_id, terminal.work_unit_id)
        retried_unit = store.get_work_unit(retried.work_unit_id)
        self.assertEqual(retried_unit.status, PersistentWorkUnitStatus.TRANSLATING)

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

    def test_strict_admission_binds_approved_custody_without_payload_leak(self):
        store = self._memory_store()
        payload = b'{"terms":["private-term"]}'
        approval = store.create_glossary_approval(
            snapshot_payload=payload,
            snapshot_digest=__import__("hashlib").sha256(payload).hexdigest(),
            snapshot_schema_version=GLOSSARY_SNAPSHOT_SCHEMA_VERSION,
            approval_schema_version=GLOSSARY_APPROVAL_SCHEMA_VERSION,
        )

        result = store.admit_strict_docx_job(
            StrictDocxAdmissionRequest(
                approval_id=approval.approval_id,
                order_id="order-strict",
                user_id="user-42",
                file_id="original/book.docx",
                file_name="book.docx",
                document_kind="docx",
                source_object_key="original/book.docx",
                source_language="en",
                target_language="uk",
                adapter_version="docx-v1",
                prompt_version="plain-v1",
                pricing_snapshot_id="pricing-1",
                translation_policy='{"mode":"strict"}',
                work_units=[
                    WorkUnitPlan(
                        sequence=1,
                        source_block_ids=("docx:1",),
                        source_text_hash="hash-1",
                        prompt_tier="plain",
                        source_language="en",
                        target_language="uk",
                        source_object_key="original/book.docx",
                    )
                ],
            )
        )

        self.assertTrue(result.admitted)
        self.assertIsNotNone(result.job)
        self.assertEqual(result.work_units[0].source_object_key, "original/book.docx")
        binding = store._connection.execute(
            "SELECT * FROM strict_job_glossary_bindings WHERE job_id = ?",
            (result.job.id,),
        ).fetchone()
        self.assertEqual(binding["approval_id"], approval.approval_id)
        rows = store._connection.execute(
            "SELECT translation_policy FROM translation_jobs"
        ).fetchall()
        self.assertNotIn("private-term", repr(rows))
        approved_snapshot = store.read_approved_glossary_snapshot(
            approval_id=approval.approval_id
        )
        if approved_snapshot is None:
            self.fail("approved snapshot was not readable")
        self.assertEqual(approved_snapshot.snapshot_payload, payload)

    def test_revoked_or_missing_approval_denies_without_job_state(self):
        store = self._memory_store()
        payload = b"snapshot"
        approval = store.create_glossary_approval(
            snapshot_payload=payload,
            snapshot_digest=__import__("hashlib").sha256(payload).hexdigest(),
            snapshot_schema_version=GLOSSARY_SNAPSHOT_SCHEMA_VERSION,
            approval_schema_version=GLOSSARY_APPROVAL_SCHEMA_VERSION,
        )
        store.revoke_glossary_approval(approval_id=approval.approval_id)
        request = _strict_request(approval.approval_id)

        result = store.admit_strict_docx_job(request)

        self.assertEqual(result.denial_code, "approval_revoked")
        job_count = store._connection.execute(
            "SELECT COUNT(*) FROM translation_jobs"
        ).fetchone()[0]
        binding_count = store._connection.execute(
            "SELECT COUNT(*) FROM strict_job_glossary_bindings"
        ).fetchone()[0]
        self.assertEqual(job_count, 0)
        self.assertEqual(binding_count, 0)

    def _memory_store(self) -> SQLiteTranslationJobStore:
        store = SQLiteTranslationJobStore(":memory:")
        self.addCleanup(store.close)
        return store


def _strict_request(approval_id: str) -> StrictDocxAdmissionRequest:
    return StrictDocxAdmissionRequest(
        approval_id=approval_id,
        order_id="order-strict",
        user_id="user-42",
        file_id="original/book.docx",
        file_name="book.docx",
        document_kind="docx",
        source_object_key="original/book.docx",
        source_language="en",
        target_language="uk",
        adapter_version="docx-v1",
        prompt_version="plain-v1",
        pricing_snapshot_id="pricing-1",
        translation_policy=None,
        work_units=[
            WorkUnitPlan(
                sequence=1,
                source_block_ids=("docx:1",),
                source_text_hash="hash-1",
                prompt_tier="plain",
                source_language="en",
                target_language="uk",
                source_object_key="original/book.docx",
            )
        ],
    )


def _job_with_units(
    store: SQLiteTranslationJobStore,
    *,
    order_id: str = "order-1",
    user_id: str = "user-42",
    file_id: str = "file-1",
):
    return _job_with_unit_count(
        store,
        order_id=order_id,
        user_id=user_id,
        file_id=file_id,
        unit_count=2,
    )


def _job_with_unit_count(
    store: SQLiteTranslationJobStore,
    *,
    order_id: str,
    user_id: str,
    file_id: str,
    unit_count: int,
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
                sequence=sequence,
                source_block_ids=(f"chapter-1:p{sequence}",),
                source_text_hash=f"hash-{sequence}",
                prompt_tier="plain",
                source_language="en",
                target_language="uk",
                source_object_key=f"intermediate/{file_id}/unit-{sequence}.txt",
            )
            for sequence in range(1, max(1, unit_count) + 1)
        ],
    )
    return job


class _ClaimRaceConnection:
    def __init__(self, connection):
        self._connection = connection
        self._armed = True

    def execute(self, sql, parameters=()):
        cursor = self._connection.execute(sql, parameters)
        if (
            self._armed
            and "FROM work_units wu" in sql
            and "ORDER BY" in sql
            and "LIMIT 1" in sql
        ):
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
