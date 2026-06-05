import json
import os
import threading
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from translator_service.file_storage import LocalObjectStorage, StoredFileKind
from translator_service.format_adapters import TXT_ADAPTER_VERSION
from translator_service.persistent_jobs import (
    PersistentTranslationJobStatus,
    WorkUnitPlan,
)
from translator_service.postgres_scheduler import (
    PostgresSchedulerStore,
    initialize_postgres_scheduler_schema,
)
from translator_service.provider_failure_diagnostics import (
    ProviderFailureCategory,
    ProviderFailureDiagnostic,
)
from translator_service.scheduler import (
    SCHEDULER_FAIR_QUEUE_POLICY,
    ProviderCapacityCap,
    ProviderCapacityCapScope,
    ProviderCapacitySlotDiagnosticStatus,
    ProviderSlotInventoryItem,
    ProviderSlotLeaseStatus,
    SchedulerLimits,
    WorkUnitFailureKind,
)

POSTGRES_DSN = os.getenv("TEST_POSTGRES_DSN")


class PostgresSchedulerContractTest(unittest.TestCase):
    def test_store_exposes_scheduler_runtime_methods(self):
        expected_methods = [
            "complete_claimed_work_unit",
            "fail_claimed_work_unit",
            "defer_claimed_work_unit_for_provider_capacity",
            "attach_job_output",
            "list_jobs_by_status",
            "list_jobs_for_user",
            "cancel_job",
            "resume_job",
            "delete_job",
            "mark_job_interrupted",
            "get_usage_summary",
            "mark_job_assembled",
            "list_work_unit_attempts",
            "list_scheduler_events",
            "record_worker_heartbeat",
            "get_worker_heartbeat",
            "recover_expired_leases",
            "upsert_provider_slot_inventory",
            "list_provider_slots",
            "acquire_provider_slot_lease",
            "release_provider_slot_lease",
            "recover_expired_provider_slot_leases",
            "list_provider_slot_leases",
            "get_provider_capacity_diagnostics",
        ]

        for method_name in expected_methods:
            self.assertTrue(
                callable(getattr(PostgresSchedulerStore, method_name, None)),
                method_name,
            )


@unittest.skipUnless(POSTGRES_DSN, "TEST_POSTGRES_DSN is not set")
class PostgresSchedulerStoreTest(unittest.TestCase):
    def setUp(self):
        self.store = PostgresSchedulerStore(POSTGRES_DSN)
        initialize_postgres_scheduler_schema(self.store.connection)
        self.store.clear_for_tests()

    def tearDown(self):
        self.store.close()

    def _create_txt_job_with_unit(
        self,
        *,
        order_id="order-1",
        file_id="file-1",
        user_id="telegram:42",
    ):
        job = self.store.create_job(
            order_id=order_id,
            user_id=user_id,
            file_id=file_id,
            file_name="notes.txt",
            document_kind="txt",
            source_language="en",
            target_language="uk",
            adapter_version=TXT_ADAPTER_VERSION,
            prompt_version="plain-v1",
            pricing_snapshot_id="pricing-1",
            source_object_key="intermediate/job-1/unit-1.txt",
        )
        self.store.add_work_units(
            job.id,
            [
                WorkUnitPlan(
                    sequence=1,
                    source_block_ids=("txt:0",),
                    source_text_hash="hash-1",
                    prompt_tier="plain",
                    source_language="en",
                    target_language="uk",
                    source_object_key="intermediate/job-1/unit-1.txt",
                )
            ],
        )
        return job

    def _claim_txt_job(
        self,
        *,
        order_id="order-1",
        file_id="file-1",
        user_id="telegram:42",
        worker_id="worker-a",
    ):
        job = self._create_txt_job_with_unit(
            order_id=order_id,
            file_id=file_id,
            user_id=user_id,
        )
        claim = self.store.claim_next_scheduled_work_unit(
            worker_id=worker_id,
            lease_seconds=300,
            limits=SchedulerLimits(
                max_active_units_global=10,
                max_active_units_per_job=1,
                max_active_units_per_user=1,
                max_active_jobs_per_user=1,
            ),
        )
        self.assertIsNotNone(claim)
        self.assertEqual(claim.job_id, job.id)
        return job, claim

    def _create_txt_job_with_units(
        self,
        *,
        unit_count=3,
        order_id="order-1",
        file_id="file-1",
        user_id="telegram:42",
    ):
        job = self._create_txt_job_with_unit(
            order_id=order_id,
            file_id=file_id,
            user_id=user_id,
        )
        if unit_count <= 1:
            return job
        self.store.add_work_units(
            job.id,
            [
                WorkUnitPlan(
                    sequence=sequence,
                    source_block_ids=(f"txt:{sequence - 1}",),
                    source_text_hash=f"hash-{sequence}",
                    prompt_tier="plain",
                    source_language="en",
                    target_language="uk",
                    source_object_key=f"intermediate/job-1/unit-{sequence}.txt",
                )
                for sequence in range(2, unit_count + 1)
            ],
        )
        return job

    def test_two_workers_do_not_claim_same_unit(self):
        self._create_txt_job_with_unit()

        first = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=SchedulerLimits(),
        )
        second = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-b",
            lease_seconds=300,
            limits=SchedulerLimits(),
        )

        self.assertIsNotNone(first)
        self.assertIsNone(second)

    def test_provider_slot_inventory_expands_key_capacity(self):
        slots = self.store.upsert_provider_slot_inventory(
            provider_id="deepseek",
            channel_id="chan_abcdef123456",
            max_parallel_requests=2,
            capacity_source="admin",
        )

        self.assertEqual([slot.slot_index for slot in slots], [0, 1])
        self.assertEqual([slot.enabled for slot in slots], [True, True])
        self.assertEqual({slot.capacity_source for slot in slots}, {"admin"})

        reduced = self.store.upsert_provider_slot_inventory(
            provider_id="deepseek",
            channel_id="chan_abcdef123456",
            max_parallel_requests=1,
            capacity_source="admin",
        )

        self.assertEqual([slot.slot_index for slot in reduced], [0, 1])
        self.assertEqual([slot.enabled for slot in reduced], [True, False])

    def test_provider_slot_acquire_does_not_double_lease_same_slot(self):
        _, first_claim = self._claim_txt_job(
            order_id="order-1",
            file_id="file-1",
            user_id="telegram:42",
            worker_id="worker-a",
        )
        _, second_claim = self._claim_txt_job(
            order_id="order-2",
            file_id="file-2",
            user_id="telegram:100",
            worker_id="worker-b",
        )
        self.store.upsert_provider_slot_inventory(
            provider_id="deepseek",
            channel_id="chan_abcdef123456",
            max_parallel_requests=1,
            capacity_source="admin",
        )

        first_lease = self.store.acquire_provider_slot_lease(
            provider_id="deepseek",
            channel_id="chan_abcdef123456",
            job_id=first_claim.job_id,
            work_unit_id=first_claim.work_unit_id,
            worker_id=first_claim.worker_id,
            work_unit_claim_token=first_claim.claim_token,
            lease_seconds=300,
        )
        second_lease = self.store.acquire_provider_slot_lease(
            provider_id="deepseek",
            channel_id="chan_abcdef123456",
            job_id=second_claim.job_id,
            work_unit_id=second_claim.work_unit_id,
            worker_id=second_claim.worker_id,
            work_unit_claim_token=second_claim.claim_token,
            lease_seconds=300,
        )

        self.assertIsNotNone(first_lease)
        self.assertEqual(first_lease.status, ProviderSlotLeaseStatus.ACTIVE)
        self.assertIsNone(second_lease)

    def test_provider_slot_account_cap_limits_one_key_with_multiple_slots(self):
        _, first_claim = self._claim_txt_job(
            order_id="order-1",
            file_id="file-1",
            user_id="telegram:42",
            worker_id="worker-a",
        )
        _, second_claim = self._claim_txt_job(
            order_id="order-2",
            file_id="file-2",
            user_id="telegram:100",
            worker_id="worker-b",
        )
        self.store.upsert_provider_slot_inventory(
            provider_id="deepseek",
            channel_id="chan_shared",
            max_parallel_requests=2,
            capacity_source="admin",
        )
        cap = _provider_capacity_cap(
            cap_id="deepseek-account-shared",
            max_parallel_requests=1,
            channel_ids=("chan_shared",),
        )

        first_lease = self.store.acquire_provider_slot_lease(
            provider_id="deepseek",
            job_id=first_claim.job_id,
            work_unit_id=first_claim.work_unit_id,
            worker_id=first_claim.worker_id,
            work_unit_claim_token=first_claim.claim_token,
            lease_seconds=300,
            capacity_caps=[cap],
        )
        second_lease = self.store.acquire_provider_slot_lease(
            provider_id="deepseek",
            job_id=second_claim.job_id,
            work_unit_id=second_claim.work_unit_id,
            worker_id=second_claim.worker_id,
            work_unit_claim_token=second_claim.claim_token,
            lease_seconds=300,
            capacity_caps=[cap],
        )

        self.assertIsNotNone(first_lease)
        self.assertIsNone(second_lease)

    def test_provider_slot_model_cap_limits_one_key_with_multiple_slots(self):
        _, first_claim = self._claim_txt_job(
            order_id="order-1",
            file_id="file-1",
            user_id="telegram:42",
            worker_id="worker-a",
        )
        _, second_claim = self._claim_txt_job(
            order_id="order-2",
            file_id="file-2",
            user_id="telegram:100",
            worker_id="worker-b",
        )
        self.store.upsert_provider_slot_inventory(
            provider_id="deepseek",
            channel_id="chan_model",
            max_parallel_requests=2,
            capacity_source="admin",
        )
        cap = _provider_capacity_cap(
            cap_id="deepseek-model-shared",
            scope=ProviderCapacityCapScope.MODEL,
            max_parallel_requests=1,
            channel_ids=("chan_model",),
        )

        first_lease = self.store.acquire_provider_slot_lease(
            provider_id="deepseek",
            job_id=first_claim.job_id,
            work_unit_id=first_claim.work_unit_id,
            worker_id=first_claim.worker_id,
            work_unit_claim_token=first_claim.claim_token,
            lease_seconds=300,
            capacity_caps=[cap],
        )
        second_lease = self.store.acquire_provider_slot_lease(
            provider_id="deepseek",
            job_id=second_claim.job_id,
            work_unit_id=second_claim.work_unit_id,
            worker_id=second_claim.worker_id,
            work_unit_claim_token=second_claim.claim_token,
            lease_seconds=300,
            capacity_caps=[cap],
        )

        self.assertIsNotNone(first_lease)
        self.assertIsNone(second_lease)

    def test_provider_slot_account_cap_limits_multiple_keys_in_one_group(self):
        _, first_claim = self._claim_txt_job(
            order_id="order-1",
            file_id="file-1",
            user_id="telegram:42",
            worker_id="worker-a",
        )
        _, second_claim = self._claim_txt_job(
            order_id="order-2",
            file_id="file-2",
            user_id="telegram:100",
            worker_id="worker-b",
        )
        for channel_id in ("chan_a", "chan_b"):
            self.store.upsert_provider_slot_inventory(
                provider_id="deepseek",
                channel_id=channel_id,
                max_parallel_requests=1,
                capacity_source="admin",
            )
        cap = _provider_capacity_cap(
            cap_id="deepseek-account-shared",
            max_parallel_requests=1,
            channel_ids=("chan_a", "chan_b"),
        )

        first_lease = self.store.acquire_provider_slot_lease(
            provider_id="deepseek",
            job_id=first_claim.job_id,
            work_unit_id=first_claim.work_unit_id,
            worker_id=first_claim.worker_id,
            work_unit_claim_token=first_claim.claim_token,
            lease_seconds=300,
            capacity_caps=[cap],
        )
        second_lease = self.store.acquire_provider_slot_lease(
            provider_id="deepseek",
            job_id=second_claim.job_id,
            work_unit_id=second_claim.work_unit_id,
            worker_id=second_claim.worker_id,
            work_unit_claim_token=second_claim.claim_token,
            lease_seconds=300,
            capacity_caps=[cap],
        )
        self.store.release_provider_slot_lease(
            lease_token=first_lease.lease_token,
            work_unit_claim_token=first_claim.claim_token,
            release_reason="completed",
        )
        second_after_release = self.store.acquire_provider_slot_lease(
            provider_id="deepseek",
            job_id=second_claim.job_id,
            work_unit_id=second_claim.work_unit_id,
            worker_id=second_claim.worker_id,
            work_unit_claim_token=second_claim.claim_token,
            lease_seconds=300,
            capacity_caps=[cap],
        )

        self.assertIsNotNone(first_lease)
        self.assertEqual(first_lease.channel_id, "chan_a")
        self.assertIsNone(second_lease)
        self.assertIsNotNone(second_after_release)

    def test_provider_slot_account_cap_serializes_concurrent_workers(self):
        _, first_claim = self._claim_txt_job(
            order_id="order-1",
            file_id="file-1",
            user_id="telegram:42",
            worker_id="worker-a",
        )
        _, second_claim = self._claim_txt_job(
            order_id="order-2",
            file_id="file-2",
            user_id="telegram:100",
            worker_id="worker-b",
        )
        for channel_id in ("chan_a", "chan_b"):
            self.store.upsert_provider_slot_inventory(
                provider_id="deepseek",
                channel_id=channel_id,
                max_parallel_requests=1,
                capacity_source="admin",
            )
        cap = _provider_capacity_cap(
            cap_id="deepseek-account-shared",
            max_parallel_requests=1,
            channel_ids=("chan_a", "chan_b"),
        )
        other_store = PostgresSchedulerStore(POSTGRES_DSN)
        self.addCleanup(other_store.close)
        barrier = threading.Barrier(2)
        results = []

        def acquire(store, claim):
            barrier.wait(timeout=5)
            results.append(
                store.acquire_provider_slot_lease(
                    provider_id="deepseek",
                    job_id=claim.job_id,
                    work_unit_id=claim.work_unit_id,
                    worker_id=claim.worker_id,
                    work_unit_claim_token=claim.claim_token,
                    lease_seconds=300,
                    capacity_caps=[cap],
                )
            )

        first_thread = threading.Thread(target=acquire, args=(self.store, first_claim))
        second_thread = threading.Thread(
            target=acquire,
            args=(other_store, second_claim),
        )
        first_thread.start()
        second_thread.start()
        first_thread.join(timeout=5)
        second_thread.join(timeout=5)

        self.assertFalse(first_thread.is_alive())
        self.assertFalse(second_thread.is_alive())
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(sum(result is None for result in results), 1)

    def test_provider_capacity_diagnostics_show_cap_denied_free_slot(self):
        _, first_claim = self._claim_txt_job(
            order_id="order-1",
            file_id="file-1",
            user_id="telegram:42",
            worker_id="worker-a",
        )
        self.store.upsert_provider_slot_inventory(
            provider_id="deepseek",
            channel_id="chan_shared",
            max_parallel_requests=2,
            capacity_source="admin",
        )
        cap = _provider_capacity_cap(
            cap_id="deepseek-account-shared",
            max_parallel_requests=1,
            channel_ids=("chan_shared",),
        )
        self.store.acquire_provider_slot_lease(
            provider_id="deepseek",
            job_id=first_claim.job_id,
            work_unit_id=first_claim.work_unit_id,
            worker_id=first_claim.worker_id,
            work_unit_claim_token=first_claim.claim_token,
            lease_seconds=300,
            capacity_caps=[cap],
        )

        diagnostic = self.store.get_provider_capacity_diagnostics(
            provider_id="deepseek",
            capacity_caps=[cap],
        )

        self.assertEqual(diagnostic.capacity_state, "cap_denied")
        self.assertEqual(diagnostic.total_slots, 2)
        self.assertEqual(diagnostic.active_leases, 1)
        self.assertEqual(diagnostic.free_slots, 0)
        self.assertEqual(diagnostic.cap_denied_slots, 1)
        self.assertEqual(
            [slot.status for slot in diagnostic.slots],
            [
                ProviderCapacitySlotDiagnosticStatus.LEASED,
                ProviderCapacitySlotDiagnosticStatus.CAP_DENIED,
            ],
        )
        self.assertEqual(diagnostic.caps[0].active_leases, 1)
        self.assertTrue(diagnostic.caps[0].at_limit)

    def test_provider_slot_release_is_claim_scoped_and_idempotent(self):
        _, claim = self._claim_txt_job()
        self.store.upsert_provider_slot_inventory(
            provider_id="deepseek",
            channel_id="chan_abcdef123456",
            max_parallel_requests=1,
            capacity_source="admin",
        )
        lease = self.store.acquire_provider_slot_lease(
            provider_id="deepseek",
            channel_id="chan_abcdef123456",
            job_id=claim.job_id,
            work_unit_id=claim.work_unit_id,
            worker_id=claim.worker_id,
            work_unit_claim_token=claim.claim_token,
            lease_seconds=300,
        )

        wrong_claim_release = self.store.release_provider_slot_lease(
            lease_token=lease.lease_token,
            work_unit_claim_token="wrong-claim-token",
            release_reason="completed",
        )
        first_release = self.store.release_provider_slot_lease(
            lease_token=lease.lease_token,
            work_unit_claim_token=claim.claim_token,
            release_reason="completed",
        )
        second_release = self.store.release_provider_slot_lease(
            lease_token=lease.lease_token,
            work_unit_claim_token=claim.claim_token,
            release_reason="raw unsafe text should not persist",
        )

        self.assertIsNone(wrong_claim_release)
        self.assertEqual(first_release.status, ProviderSlotLeaseStatus.RELEASED)
        self.assertEqual(first_release.release_reason, "completed")
        self.assertEqual(second_release.status, ProviderSlotLeaseStatus.RELEASED)
        self.assertEqual(second_release.release_reason, "completed")

    def test_provider_slot_expiry_does_not_recover_active_work_unit_claim(self):
        _, claim = self._claim_txt_job()
        self.store.upsert_provider_slot_inventory(
            provider_id="deepseek",
            channel_id="chan_abcdef123456",
            max_parallel_requests=1,
            capacity_source="admin",
        )
        lease = self.store.acquire_provider_slot_lease(
            provider_id="deepseek",
            channel_id="chan_abcdef123456",
            job_id=claim.job_id,
            work_unit_id=claim.work_unit_id,
            worker_id=claim.worker_id,
            work_unit_claim_token=claim.claim_token,
            lease_seconds=1,
        )

        recovered = self.store.recover_expired_provider_slot_leases(
            now=lease.lease_until + timedelta(seconds=1),
        )
        active = self.store.list_provider_slot_leases(
            status=ProviderSlotLeaseStatus.ACTIVE,
        )
        work_unit = self.store.get_work_unit(claim.work_unit_id)

        self.assertEqual(recovered, 0)
        self.assertEqual([item.lease_token for item in active], [lease.lease_token])
        self.assertEqual(work_unit.status.value, "translating")
        self.assertEqual(work_unit.claim_token, claim.claim_token)

    def test_provider_capacity_diagnostics_show_expired_active_lease(self):
        _, claim = self._claim_txt_job()
        self.store.upsert_provider_slot_inventory(
            provider_id="deepseek",
            channel_id="chan_abcdef123456",
            max_parallel_requests=1,
            capacity_source="admin",
        )
        lease = self.store.acquire_provider_slot_lease(
            provider_id="deepseek",
            channel_id="chan_abcdef123456",
            job_id=claim.job_id,
            work_unit_id=claim.work_unit_id,
            worker_id=claim.worker_id,
            work_unit_claim_token=claim.claim_token,
            lease_seconds=1,
        )

        diagnostic = self.store.get_provider_capacity_diagnostics(
            provider_id="deepseek",
            now=lease.lease_until + timedelta(seconds=1),
        )

        self.assertEqual(diagnostic.capacity_state, "recovering_expired_leases")
        self.assertEqual(diagnostic.expired_active_leases, 1)
        self.assertEqual(
            diagnostic.slots[0].status,
            ProviderCapacitySlotDiagnosticStatus.EXPIRED_ACTIVE,
        )

    def test_provider_slot_expiry_recovers_after_work_unit_lease_is_stale(self):
        _, claim = self._claim_txt_job()
        self.store.upsert_provider_slot_inventory(
            provider_id="deepseek",
            channel_id="chan_abcdef123456",
            max_parallel_requests=1,
            capacity_source="admin",
        )
        lease = self.store.acquire_provider_slot_lease(
            provider_id="deepseek",
            channel_id="chan_abcdef123456",
            job_id=claim.job_id,
            work_unit_id=claim.work_unit_id,
            worker_id=claim.worker_id,
            work_unit_claim_token=claim.claim_token,
            lease_seconds=1,
        )

        recovered = self.store.recover_expired_provider_slot_leases(
            now=claim.lease_until + timedelta(seconds=1),
        )
        [expired] = self.store.list_provider_slot_leases(
            status=ProviderSlotLeaseStatus.EXPIRED,
        )

        self.assertEqual(recovered, 1)
        self.assertEqual(expired.lease_token, lease.lease_token)
        self.assertEqual(expired.release_reason, "lease_expired")

    def test_delete_job_removes_provider_slot_leases_first(self):
        job, claim = self._claim_txt_job()
        self.store.upsert_provider_slot_inventory(
            provider_id="deepseek",
            channel_id="chan_abcdef123456",
            max_parallel_requests=1,
            capacity_source="admin",
        )
        self.store.acquire_provider_slot_lease(
            provider_id="deepseek",
            channel_id="chan_abcdef123456",
            job_id=claim.job_id,
            work_unit_id=claim.work_unit_id,
            worker_id=claim.worker_id,
            work_unit_claim_token=claim.claim_token,
            lease_seconds=300,
        )

        deleted = self.store.delete_job(job.id)

        self.assertTrue(deleted)
        self.assertEqual(self.store.list_provider_slot_leases(), [])
        self.assertIsNone(self.store.get_job(job.id))

    def test_provider_slot_lease_schema_has_safe_metadata_columns(self):
        columns = {
            row["column_name"]
            for row in self.store.connection.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'provider_slot_leases'
                """
            ).fetchall()
        }

        self.assertIn("lease_token", columns)
        self.assertIn("work_unit_claim_token", columns)
        self.assertNotIn("api_key", columns)
        self.assertNotIn("source_text", columns)
        self.assertNotIn("translated_text", columns)
        self.assertNotIn("prompt", columns)
        self.assertNotIn("provider_payload", columns)
        self.assertNotIn("stack_trace", columns)

    def test_defer_claimed_unit_for_provider_capacity_returns_pending_without_attempt(
        self,
    ):
        _, claim = self._claim_txt_job()

        deferred = self.store.defer_claimed_work_unit_for_provider_capacity(
            work_unit_id=claim.work_unit_id,
            claim_token=claim.claim_token,
        )

        attempts = self.store.list_work_unit_attempts(claim.work_unit_id)
        events = self.store.list_scheduler_events(claim.job_id)
        next_claim = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-b",
            lease_seconds=300,
            limits=SchedulerLimits(),
        )

        self.assertIsNotNone(deferred)
        self.assertEqual(deferred.status.value, "pending")
        self.assertIsNone(deferred.worker_id)
        self.assertIsNone(deferred.claim_token)
        self.assertIsNone(deferred.lease_until)
        self.assertEqual(deferred.attempt_count, 0)
        self.assertEqual(attempts, [])
        self.assertEqual(
            events[-1].event_type,
            "work_unit_provider_capacity_deferred",
        )
        self.assertEqual(next_claim.work_unit_id, claim.work_unit_id)

    def test_per_job_limit_of_one_preserves_unit_ordering(self):
        job = self._create_txt_job_with_units()

        first = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=SchedulerLimits(max_active_units_per_job=1),
        )
        second = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-b",
            lease_seconds=300,
            limits=SchedulerLimits(max_active_units_per_job=1),
        )

        self.assertEqual(first.work_unit_id, f"{job.id}:unit-1")
        self.assertIsNone(second)

    def test_per_job_limit_allows_later_units_up_to_limit(self):
        job = self._create_txt_job_with_units()
        limits = SchedulerLimits(
            max_active_units_per_job=2,
            max_active_units_per_user=2,
            max_active_units_global=10,
        )

        first = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=limits,
        )
        second = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-b",
            lease_seconds=300,
            limits=limits,
        )
        third = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-c",
            lease_seconds=300,
            limits=limits,
        )

        self.assertEqual(first.work_unit_id, f"{job.id}:unit-1")
        self.assertEqual(second.work_unit_id, f"{job.id}:unit-2")
        self.assertIsNone(third)

    def test_global_limit_blocks_second_job_sequentially(self):
        first_job = self._create_txt_job_with_unit(order_id="order-1", file_id="file-1")
        self._create_txt_job_with_unit(order_id="order-2", file_id="file-2")
        limits = SchedulerLimits(max_active_units_global=1)

        first = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=limits,
        )
        second = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-b",
            lease_seconds=300,
            limits=limits,
        )

        self.assertEqual(first.job_id, first_job.id)
        self.assertIsNone(second)

    def test_user_unit_cap_blocks_second_job_for_same_user(self):
        first_job = self._create_txt_job_with_unit(
            order_id="order-1",
            file_id="file-1",
            user_id="telegram:42",
        )
        self._create_txt_job_with_unit(
            order_id="order-2",
            file_id="file-2",
            user_id="telegram:42",
        )
        limits = SchedulerLimits(
            max_active_units_global=10,
            max_active_units_per_job=1,
            max_active_units_per_user=1,
            max_active_jobs_per_user=2,
        )

        first = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=limits,
        )
        second = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-b",
            lease_seconds=300,
            limits=limits,
        )

        self.assertEqual(first.job_id, first_job.id)
        self.assertIsNone(second)

    def test_claim_prefers_user_with_lower_active_load(self):
        first_user_first_job = self._create_txt_job_with_unit(
            order_id="order-1",
            file_id="file-1",
            user_id="telegram:42",
        )
        self._create_txt_job_with_unit(
            order_id="order-2",
            file_id="file-2",
            user_id="telegram:42",
        )
        other_user_job = self._create_txt_job_with_unit(
            order_id="order-3",
            file_id="file-3",
            user_id="telegram:100",
        )
        limits = SchedulerLimits(
            max_active_units_global=10,
            max_active_units_per_job=1,
            max_active_units_per_user=2,
            max_active_jobs_per_user=2,
        )

        first = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=limits,
        )
        second = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-b",
            lease_seconds=300,
            limits=limits,
        )

        self.assertEqual(first.job_id, first_user_first_job.id)
        self.assertEqual(second.job_id, other_user_job.id)

    def test_claim_fair_queue_prevents_large_job_from_monopolizing_slots(self):
        large_job = self._create_txt_job_with_units(
            order_id="order-large",
            file_id="file-large",
            user_id="telegram:42",
            unit_count=4,
        )
        small_a = self._create_txt_job_with_units(
            order_id="order-small-a",
            file_id="file-small-a",
            user_id="telegram:100",
            unit_count=1,
        )
        small_b = self._create_txt_job_with_units(
            order_id="order-small-b",
            file_id="file-small-b",
            user_id="telegram:200",
            unit_count=1,
        )
        limits = SchedulerLimits(
            max_active_units_global=3,
            max_active_units_per_job=3,
            max_active_units_per_user=3,
            max_active_jobs_per_user=3,
        )

        first = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=limits,
        )
        second = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-b",
            lease_seconds=300,
            limits=limits,
        )
        third = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-c",
            lease_seconds=300,
            limits=limits,
        )

        self.assertEqual(first.job_id, large_job.id)
        self.assertEqual({second.job_id, third.job_id}, {small_a.id, small_b.id})
        self.assertNotIn(large_job.id, {second.job_id, third.job_id})

    def test_claim_priority_aging_prevents_old_job_starvation(self):
        old_low_priority = self._create_txt_job_with_unit(
            order_id="order-old",
            file_id="file-old",
            user_id="telegram:42",
        )
        new_high_priority = self._create_txt_job_with_unit(
            order_id="order-new",
            file_id="file-new",
            user_id="telegram:100",
        )
        now = datetime.now(UTC)
        with self.store.connection.transaction():
            self.store.connection.execute(
                """
                UPDATE translation_jobs
                SET priority = %(priority)s, created_at = %(created_at)s
                WHERE id = %(job_id)s
                """,
                {
                    "priority": 0,
                    "created_at": now - timedelta(minutes=3),
                    "job_id": old_low_priority.id,
                },
            )
            self.store.connection.execute(
                """
                UPDATE translation_jobs
                SET priority = %(priority)s, created_at = %(created_at)s
                WHERE id = %(job_id)s
                """,
                {
                    "priority": 1,
                    "created_at": now,
                    "job_id": new_high_priority.id,
                },
            )

        claimed = self.store.claim_next_scheduled_work_unit(
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

    def test_legacy_failed_unit_is_retryable_for_claiming(self):
        job = self._create_txt_job_with_unit()
        with self.store.connection.transaction():
            self.store.connection.execute(
                """
                UPDATE work_units
                SET status = 'failed', available_at = now() - interval '1 second'
                WHERE id = %(work_unit_id)s
                """,
                {"work_unit_id": f"{job.id}:unit-1"},
            )

        claim = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=SchedulerLimits(),
        )

        self.assertIsNotNone(claim)
        self.assertEqual(claim.work_unit_id, f"{job.id}:unit-1")

    def test_complete_claimed_unit_moves_job_to_assembling(self):
        job = self._create_txt_job_with_unit()
        claim = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=SchedulerLimits(),
        )

        completed = self.store.complete_claimed_work_unit(
            work_unit_id=claim.work_unit_id,
            claim_token=claim.claim_token,
            translated_text="[uk] First paragraph",
            prompt_tokens=10,
            completion_tokens=5,
            cache_hit_tokens=1,
            cache_miss_tokens=9,
        )

        persisted_job = self.store.get_job(job.id)
        events = self.store.list_scheduler_events(job.id)
        claim_payload = json.loads(events[0].payload_json)
        self.assertEqual(completed.status.value, "translated")
        self.assertEqual(persisted_job.status, PersistentTranslationJobStatus.ASSEMBLING)
        self.assertEqual(
            claim_payload["queue_policy"],
            SCHEDULER_FAIR_QUEUE_POLICY,
        )
        self.assertEqual(events[-1].event_type, "work_unit_completed")

    def test_retryable_failure_records_attempt_and_releases_claim(self):
        job = self._create_txt_job_with_unit()
        claim = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=SchedulerLimits(),
        )

        failed = self.store.fail_claimed_work_unit(
            work_unit_id=claim.work_unit_id,
            claim_token=claim.claim_token,
            failure_kind=WorkUnitFailureKind.RETRYABLE_PROVIDER,
            error_message="provider timeout",
            retry_base_delay_seconds=30,
            retry_max_delay_seconds=600,
        )

        attempts = self.store.list_work_unit_attempts(claim.work_unit_id)
        events = self.store.list_scheduler_events(job.id)
        self.assertEqual(failed.status.value, "failed_retryable")
        self.assertIsNone(failed.claim_token)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(events[-1].event_type, "work_unit_retry_scheduled")

    def test_provider_failure_diagnostic_is_persisted_on_attempt_and_event(self):
        job = self._create_txt_job_with_unit()
        claim = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=SchedulerLimits(),
        )

        self.store.fail_claimed_work_unit(
            work_unit_id=claim.work_unit_id,
            claim_token=claim.claim_token,
            failure_kind=WorkUnitFailureKind.RETRYABLE_PROVIDER,
            error_message="retryable provider failure",
            retry_base_delay_seconds=30,
            retry_max_delay_seconds=600,
            provider_failure_diagnostic=ProviderFailureDiagnostic(
                failure_category=ProviderFailureCategory.AUTH,
                http_status_bucket="4xx",
                provider_id="deepseek",
                channel_fingerprint="chan_abcdef123456",
            ),
        )

        attempts = self.store.list_work_unit_attempts(claim.work_unit_id)
        events = self.store.list_scheduler_events(job.id)
        payload = json.loads(events[-1].payload_json)

        self.assertEqual(attempts[0].error_code, "auth")
        self.assertEqual(attempts[0].error_message, "provider failure: auth")
        self.assertEqual(payload["provider_failure"]["failure_category"], "auth")
        self.assertEqual(payload["provider_failure"]["http_status_bucket"], "4xx")

    def test_stale_completion_with_wrong_token_leaves_claim_intact(self):
        self._create_txt_job_with_unit()
        claim = self.store.claim_next_scheduled_work_unit(
            worker_id="worker-a",
            lease_seconds=300,
            limits=SchedulerLimits(),
        )

        with self.assertRaises(ValueError):
            self.store.complete_claimed_work_unit(
                work_unit_id=claim.work_unit_id,
                claim_token="wrong-token",
                translated_text="[uk] stale",
                prompt_tokens=1,
                completion_tokens=1,
                cache_hit_tokens=0,
                cache_miss_tokens=1,
            )

        work_unit = self.store.get_work_unit(claim.work_unit_id)
        self.assertEqual(work_unit.claim_token, claim.claim_token)
        self.assertEqual(work_unit.status.value, "translating")

    def test_worker_heartbeat_is_upserted(self):
        self.store.record_worker_heartbeat(
            worker_id="worker-a",
            worker_kind="translation",
            status="idle",
            active_job_id=None,
            active_work_unit_id=None,
        )
        self.store.record_worker_heartbeat(
            worker_id="worker-a",
            worker_kind="translation",
            status="busy",
            active_job_id="job-1",
            active_work_unit_id="job-1:unit-1",
        )

        heartbeat = self.store.get_worker_heartbeat("worker-a")

        self.assertEqual(heartbeat.worker_id, "worker-a")
        self.assertEqual(heartbeat.status, "busy")
        self.assertEqual(heartbeat.active_job_id, "job-1")

    def test_scheduler_runner_translates_and_assembles_txt_job(self):
        from translator_service.scheduler_runner import run_scheduler_once

        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir))
            original = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="notes.txt",
                content_type="text/plain; charset=utf-8",
                content=b"First paragraph",
            )
            source = storage.put_bytes(
                kind=StoredFileKind.INTERMEDIATE,
                file_name="unit-1.txt",
                content_type="text/plain; charset=utf-8",
                content=b"First paragraph",
            )
            job = self.store.create_job(
                order_id="order-runtime-smoke",
                user_id="telegram:42",
                file_id="file-runtime-smoke",
                file_name="notes.txt",
                document_kind="txt",
                source_language="en",
                target_language="uk",
                adapter_version=TXT_ADAPTER_VERSION,
                prompt_version="plain-v1",
                pricing_snapshot_id="pricing-1",
                source_object_key=original.object_key,
            )
            self.store.add_work_units(
                job.id,
                [
                    WorkUnitPlan(
                        sequence=1,
                        source_block_ids=("txt:segment:1",),
                        source_text_hash="hash-runtime-smoke",
                        prompt_tier="plain",
                        source_language="en",
                        target_language="uk",
                        source_object_key=source.object_key,
                    )
                ],
            )
            translator = PostgresSmokeTranslator()

            summary = run_scheduler_once(
                store=self.store,
                storage=storage,
                worker_id="postgres-smoke-worker",
                translator=translator,
                limits=SchedulerLimits(),
                lease_seconds=300,
            )

            persisted_job = self.store.get_job(job.id)
            events = self.store.list_scheduler_events(job.id)
            leases = self.store.list_provider_slot_leases()
            self.assertEqual(summary.completed_units, 1)
            self.assertEqual(summary.failed_units, 0)
            self.assertEqual(summary.assembled_jobs, 1)
            self.assertEqual(persisted_job.status, PersistentTranslationJobStatus.READY)
            self.assertIsNotNone(persisted_job.final_object_key)
            self.assertEqual(
                storage.get_bytes(persisted_job.final_object_key).decode("utf-8"),
                "[uk] First paragraph",
            )
            self.assertEqual(
                [event.event_type for event in events],
                ["work_unit_claimed", "work_unit_completed"],
            )
            self.assertEqual(len(leases), 1)
            self.assertEqual(leases[0].status, ProviderSlotLeaseStatus.RELEASED)
            self.assertEqual(leases[0].release_reason, "completed")
            self.assertEqual(translator.channel_contexts, ["deepseek-channel-1"])


class PostgresSmokeTranslator:
    provider_id = "deepseek"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.last_usage: _ProviderUsage | None = None
        self.channel_contexts: list[str] = []

    def provider_slot_inventory(self) -> list[ProviderSlotInventoryItem]:
        return [
            ProviderSlotInventoryItem(
                provider_id="deepseek",
                channel_id="deepseek-channel-1",
                max_parallel_requests=1,
                capacity_source="test",
            )
        ]

    def provider_slot_channel_lease(self, channel_id: str):
        class _Context:
            def __enter__(inner_self):
                self.channel_contexts.append(channel_id)

            def __exit__(inner_self, exc_type, exc_value, traceback):
                return False

        return _Context()

    def translate(
        self,
        *,
        text: str,
        source_language: str,
        target_language: str,
        translation_context=None,
    ) -> str:
        self.calls.append((text, source_language, target_language))
        self.last_usage = _ProviderUsage(
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            prompt_cache_hit_tokens=2,
            prompt_cache_miss_tokens=8,
        )
        return f"[{target_language}] {text}"


def _provider_capacity_cap(
    *,
    cap_id: str,
    max_parallel_requests: int,
    channel_ids: tuple[str, ...],
    scope: ProviderCapacityCapScope = ProviderCapacityCapScope.ACCOUNT,
) -> ProviderCapacityCap:
    return ProviderCapacityCap(
        provider_id="deepseek",
        cap_id=cap_id,
        scope=scope,
        max_parallel_requests=max_parallel_requests,
        channel_ids=channel_ids,
    )


class _ProviderUsage:
    def __init__(
        self,
        *,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        prompt_cache_hit_tokens: int,
        prompt_cache_miss_tokens: int,
    ) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = total_tokens
        self.prompt_cache_hit_tokens = prompt_cache_hit_tokens
        self.prompt_cache_miss_tokens = prompt_cache_miss_tokens


if __name__ == "__main__":
    unittest.main()
