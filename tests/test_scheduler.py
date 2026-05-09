from datetime import UTC, datetime, timedelta
from typing import get_type_hints
import unittest

from translator_service.scheduler import (
    RetryDecision,
    SchedulerClaim,
    SchedulerJobStatus,
    SchedulerLimits,
    SchedulerRepository,
    SchedulerWorkUnitStatus,
    WorkUnitFailureKind,
    calculate_retry_decision,
)
from translator_service.persistent_jobs import SQLiteTranslationJobStore


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

    def test_scheduler_limits_have_safe_defaults(self):
        limits = SchedulerLimits()

        self.assertEqual(limits.max_active_units_per_job, 1)
        self.assertEqual(limits.max_active_jobs_per_user, 1)
        self.assertEqual(limits.max_active_units_per_user, 1)
        self.assertEqual(limits.max_active_units_global, 2)
        self.assertEqual(limits.max_attempts_per_unit, 3)
        self.assertEqual(limits.priority_aging_seconds, 1800)

    def test_sqlite_store_exposes_scheduler_repository_methods(self):
        self.assertTrue(callable(SQLiteTranslationJobStore.claim_next_scheduled_work_unit))
        self.assertTrue(callable(SQLiteTranslationJobStore.complete_claimed_work_unit))
        self.assertTrue(callable(SQLiteTranslationJobStore.fail_claimed_work_unit))

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
