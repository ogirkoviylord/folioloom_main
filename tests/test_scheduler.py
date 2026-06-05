import unittest
from datetime import UTC, datetime, timedelta
from typing import get_type_hints

from translator_service.persistent_jobs import SQLiteTranslationJobStore
from translator_service.scheduler import (
    SCHEDULER_FAIR_QUEUE_ORDERING,
    SCHEDULER_FAIR_QUEUE_POLICY,
    ProviderCapacityCap,
    ProviderCapacityCapScope,
    ProviderSlot,
    ProviderSlotLease,
    ProviderSlotLeaseStatus,
    RetryDecision,
    SchedulerBackpressureState,
    SchedulerClaim,
    SchedulerJobStatus,
    SchedulerLimits,
    SchedulerRepository,
    SchedulerWorkUnitStatus,
    WorkUnitFailureKind,
    build_provider_capacity_diagnostics,
    build_scheduler_backpressure_diagnostics,
    build_scheduler_queue_policy_diagnostics,
    calculate_retry_decision,
)


class SchedulerContractTest(unittest.TestCase):
    def test_status_values_are_persisted_contract_values(self):
        self.assertEqual(
            {status: status.value for status in SchedulerJobStatus},
            {
                SchedulerJobStatus.QUEUED: "queued",
                SchedulerJobStatus.TRANSLATING: "translating",
                SchedulerJobStatus.ASSEMBLING: "assembling",
                SchedulerJobStatus.PARTIAL: "partial",
                SchedulerJobStatus.READY: "ready",
                SchedulerJobStatus.CANCEL_REQUESTED: "cancel_requested",
                SchedulerJobStatus.CANCELLED: "cancelled",
                SchedulerJobStatus.INTERRUPTED: "interrupted",
                SchedulerJobStatus.FAILED: "failed",
                SchedulerJobStatus.EXPIRED: "expired",
            },
        )
        self.assertEqual(
            {status: status.value for status in SchedulerWorkUnitStatus},
            {
                SchedulerWorkUnitStatus.PENDING: "pending",
                SchedulerWorkUnitStatus.TRANSLATING: "translating",
                SchedulerWorkUnitStatus.TRANSLATED: "translated",
                SchedulerWorkUnitStatus.FAILED_RETRYABLE: "failed_retryable",
                SchedulerWorkUnitStatus.FAILED_TERMINAL: "failed_terminal",
                SchedulerWorkUnitStatus.CANCELLED: "cancelled",
                SchedulerWorkUnitStatus.SKIPPED: "skipped",
                SchedulerWorkUnitStatus.CACHED: "cached",
            },
        )

    def test_retry_decision_uses_exponential_backoff_with_cap(self):
        now = datetime(2026, 5, 8, 12, 0, tzinfo=UTC)

        decision = calculate_retry_decision(
            failure_kind=WorkUnitFailureKind.RETRYABLE_PROVIDER,
            attempt_count=2,
            max_attempts=5,
            now=now,
            base_delay_seconds=10,
            max_delay_seconds=120,
        )

        self.assertEqual(
            decision,
            RetryDecision(
                retryable=True,
                next_status=SchedulerWorkUnitStatus.FAILED_RETRYABLE,
                available_at=now + timedelta(seconds=20),
                terminal_job_status=None,
            ),
        )

    def test_retry_decision_interrupts_after_max_attempts(self):
        now = datetime(2026, 5, 8, 12, 0, tzinfo=UTC)

        decision = calculate_retry_decision(
            failure_kind=WorkUnitFailureKind.RETRYABLE_PROVIDER,
            attempt_count=5,
            max_attempts=5,
            now=now,
            base_delay_seconds=10,
            max_delay_seconds=120,
        )

        self.assertEqual(decision.retryable, False)
        self.assertEqual(decision.next_status, SchedulerWorkUnitStatus.FAILED_TERMINAL)
        self.assertEqual(decision.terminal_job_status, SchedulerJobStatus.INTERRUPTED)

    def test_scheduler_claim_carries_token_and_lease(self):
        lease_until = datetime(2026, 5, 8, 12, 5, tzinfo=UTC)

        claim = SchedulerClaim(
            job_id="job-1",
            work_unit_id="job-1:unit-1",
            worker_id="worker-a",
            claim_token="claim-token-1",
            lease_until=lease_until,
            attempt_number=1,
            source_object_key="intermediate/job-1/unit-1.txt",
        )

        self.assertEqual(claim.claim_token, "claim-token-1")
        self.assertEqual(claim.lease_until, lease_until)

    def test_provider_slot_lease_status_values_are_persisted_contract_values(self):
        self.assertEqual(
            {status: status.value for status in ProviderSlotLeaseStatus},
            {
                ProviderSlotLeaseStatus.ACTIVE: "active",
                ProviderSlotLeaseStatus.RELEASED: "released",
                ProviderSlotLeaseStatus.EXPIRED: "expired",
            },
        )

    def test_provider_slot_contract_carries_only_safe_metadata(self):
        acquired_at = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
        lease_until = acquired_at + timedelta(minutes=5)

        slot = ProviderSlot(
            provider_id="deepseek",
            channel_id="chan_abcdef123456",
            slot_index=1,
            capacity_source="admin",
            enabled=True,
            created_at=acquired_at,
            updated_at=acquired_at,
        )
        lease = ProviderSlotLease(
            lease_id="provider-slot-lease-1",
            lease_token="lease-token-1",
            provider_id=slot.provider_id,
            channel_id=slot.channel_id,
            slot_index=slot.slot_index,
            job_id="job-1",
            work_unit_id="job-1:unit-1",
            worker_id="worker-a",
            work_unit_claim_token="claim-token-1",
            status=ProviderSlotLeaseStatus.ACTIVE,
            acquired_at=acquired_at,
            lease_until=lease_until,
            released_at=None,
            release_reason=None,
        )

        self.assertEqual(lease.provider_id, "deepseek")
        self.assertEqual(lease.channel_id, "chan_abcdef123456")
        self.assertEqual(lease.slot_index, 1)
        self.assertEqual(lease.work_unit_claim_token, "claim-token-1")
        self.assertEqual(lease.status, ProviderSlotLeaseStatus.ACTIVE)

    def test_scheduler_limits_have_safe_defaults(self):
        limits = SchedulerLimits()

        self.assertEqual(limits.max_active_units_per_job, 1)
        self.assertEqual(limits.max_active_jobs_per_user, 1)
        self.assertEqual(limits.max_active_units_per_user, 1)
        self.assertEqual(limits.max_active_units_global, 2)
        self.assertEqual(limits.max_attempts_per_unit, 3)
        self.assertEqual(limits.priority_aging_seconds, 1800)

    def test_fair_queue_policy_id_is_stable_metadata(self):
        self.assertEqual(
            SCHEDULER_FAIR_QUEUE_POLICY,
            "least_active_user_job_v1",
        )
        self.assertIn("active_user_units_asc", SCHEDULER_FAIR_QUEUE_ORDERING)

    def test_fair_queue_policy_diagnostics_are_metadata_only(self):
        diagnostics = build_scheduler_queue_policy_diagnostics(
            active_user_units_before_claim=2,
            active_user_jobs_before_claim=1,
            active_job_units_before_claim=0,
            max_active_units_per_job=3,
            max_active_units_per_user=4,
            max_active_jobs_per_user=2,
            priority_aging_seconds=1800,
        )

        self.assertEqual(diagnostics["active_user_units_before_claim"], 2)
        self.assertEqual(diagnostics["active_user_jobs_before_claim"], 1)
        self.assertEqual(diagnostics["active_job_units_before_claim"], 0)
        self.assertEqual(diagnostics["max_active_units_per_job"], 3)
        self.assertEqual(diagnostics["max_active_units_per_user"], 4)
        self.assertEqual(diagnostics["max_active_jobs_per_user"], 2)
        self.assertEqual(diagnostics["priority_aging_seconds"], 1800)
        self.assertEqual(diagnostics["ordering"], list(SCHEDULER_FAIR_QUEUE_ORDERING))

    def test_backpressure_diagnostics_return_idle_unknown_for_empty_queue(self):
        diagnostics = build_scheduler_backpressure_diagnostics(
            queue_depth_units=0,
            eligible_waiting_units=0,
            delayed_retry_units=0,
            active_work_units=0,
            retry_pressure_units=0,
            expired_work_unit_leases=0,
        )

        self.assertEqual(diagnostics.backpressure_state, SchedulerBackpressureState.IDLE)
        self.assertEqual(diagnostics.pressure_reasons, ("no_eligible_work",))
        self.assertEqual(diagnostics.eta.state, "unknown")
        self.assertEqual(diagnostics.eta.unknown_reason, "no_eligible_work")

    def test_backpressure_diagnostics_report_pressure_without_user_data(self):
        now = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
        capacity = build_provider_capacity_diagnostics(
            provider_id="deepseek",
            slots=(
                ProviderSlot(
                    provider_id="deepseek",
                    channel_id="chan_a",
                    slot_index=0,
                    capacity_source="test",
                    enabled=True,
                    created_at=now,
                    updated_at=now,
                ),
                ProviderSlot(
                    provider_id="deepseek",
                    channel_id="chan_b",
                    slot_index=0,
                    capacity_source="test",
                    enabled=True,
                    created_at=now,
                    updated_at=now,
                ),
            ),
            leases=(
                ProviderSlotLease(
                    lease_id="lease-1",
                    lease_token="lease-token-1",
                    provider_id="deepseek",
                    channel_id="chan_a",
                    slot_index=0,
                    job_id="job-1",
                    work_unit_id="job-1:unit-1",
                    worker_id="worker-a",
                    work_unit_claim_token="claim-token",
                    status=ProviderSlotLeaseStatus.ACTIVE,
                    acquired_at=now - timedelta(seconds=10),
                    lease_until=now + timedelta(seconds=300),
                    released_at=None,
                    release_reason=None,
                ),
            ),
            capacity_caps=(
                ProviderCapacityCap(
                    provider_id="deepseek",
                    cap_id="account",
                    scope=ProviderCapacityCapScope.ACCOUNT,
                    max_parallel_requests=1,
                ),
            ),
            now=now,
        )

        diagnostics = build_scheduler_backpressure_diagnostics(
            queue_depth_units=5,
            eligible_waiting_units=3,
            delayed_retry_units=2,
            active_work_units=1,
            retry_pressure_units=2,
            expired_work_unit_leases=1,
            provider_capacity=capacity,
            throttle_available_slots=0,
            throttle_circuit_state="open",
            recent_completed_units=0,
            now=now,
        )

        self.assertEqual(
            diagnostics.backpressure_state,
            SchedulerBackpressureState.RECOVERY_NEEDED,
        )
        self.assertIn("account_model_cap_pressure", diagnostics.pressure_reasons)
        self.assertIn("adaptive_throttle_pressure", diagnostics.pressure_reasons)
        self.assertIn("provider_failure_retry_pressure", diagnostics.pressure_reasons)
        self.assertIn("lease_expiry_recovery", diagnostics.pressure_reasons)
        self.assertEqual(diagnostics.provider_cap_denied_slots, 1)
        self.assertEqual(diagnostics.throttle_circuit_state, "open")
        self.assertEqual(diagnostics.eta.state, "unknown")

    def test_backpressure_diagnostics_return_bounded_eta_from_throughput(self):
        now = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
        capacity = build_provider_capacity_diagnostics(
            provider_id="deepseek",
            slots=(
                ProviderSlot(
                    provider_id="deepseek",
                    channel_id="chan_a",
                    slot_index=0,
                    capacity_source="test",
                    enabled=True,
                    created_at=now,
                    updated_at=now,
                ),
            ),
            leases=(),
            now=now,
        )

        diagnostics = build_scheduler_backpressure_diagnostics(
            queue_depth_units=6,
            eligible_waiting_units=6,
            delayed_retry_units=0,
            active_work_units=2,
            retry_pressure_units=0,
            expired_work_unit_leases=0,
            provider_capacity=capacity,
            recent_completed_units=4,
            throughput_window_seconds=120,
            now=now,
        )

        self.assertEqual(diagnostics.backpressure_state, SchedulerBackpressureState.READY)
        self.assertEqual(diagnostics.eta.state, "bounded")
        self.assertEqual(diagnostics.eta.estimated_seconds_lower_bound, 120)
        self.assertEqual(diagnostics.eta.estimated_seconds_upper_bound, 480)

    def test_sqlite_store_exposes_scheduler_repository_methods(self):
        self.assertTrue(callable(SQLiteTranslationJobStore.claim_next_scheduled_work_unit))
        self.assertTrue(callable(SQLiteTranslationJobStore.complete_claimed_work_unit))
        self.assertTrue(callable(SQLiteTranslationJobStore.fail_claimed_work_unit))
        self.assertTrue(
            callable(SQLiteTranslationJobStore.get_scheduler_backpressure_diagnostics)
        )

    def test_scheduler_repository_allows_opaque_completion_results(self):
        class DummySchedulerRepository:
            def complete_claimed_work_unit(self, **kwargs):
                return {"work_unit_id": kwargs["work_unit_id"]}

            def fail_claimed_work_unit(self, **kwargs):
                return {"work_unit_id": kwargs["work_unit_id"]}

        complete_return = get_type_hints(
            SchedulerRepository.complete_claimed_work_unit
        )["return"]
        fail_return = get_type_hints(SchedulerRepository.fail_claimed_work_unit)[
            "return"
        ]
        repository = DummySchedulerRepository()

        self.assertIs(complete_return, object)
        self.assertIs(fail_return, object)
        self.assertEqual(
            repository.complete_claimed_work_unit(work_unit_id="unit-1"),
            {"work_unit_id": "unit-1"},
        )
        self.assertEqual(
            repository.fail_claimed_work_unit(work_unit_id="unit-2"),
            {"work_unit_id": "unit-2"},
        )


if __name__ == "__main__":
    unittest.main()
