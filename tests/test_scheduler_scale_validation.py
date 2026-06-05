import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Lock
from uuid import uuid4

from translator_service.provider_failure_diagnostics import (
    ProviderFailureCategory,
    build_provider_failure_diagnostic,
)
from translator_service.scheduler import (
    ProviderCapacityCap,
    ProviderCapacityCapScope,
    ProviderSlot,
    ProviderSlotLease,
    ProviderSlotLeaseStatus,
    SchedulerBackpressureState,
    build_provider_capacity_diagnostics,
    build_scheduler_backpressure_diagnostics,
    build_scheduler_queue_policy_diagnostics,
)


class SchedulerScaleValidationTest(unittest.TestCase):
    def test_eight_keys_two_slots_do_not_oversubscribe_across_workers(self):
        ledger = _FakeProviderSlotLedger(key_count=8, slots_per_key=2)

        with ThreadPoolExecutor(max_workers=32) as pool:
            leases = list(pool.map(ledger.acquire_for_worker, range(64)))

        active_leases = [lease for lease in leases if lease is not None]
        leased_slots = {
            (lease.channel_id, lease.slot_index) for lease in active_leases
        }
        self.assertEqual(len(active_leases), 16)
        self.assertEqual(len(leased_slots), 16)
        self.assertEqual(ledger.max_active_observed, 16)
        self.assertEqual(ledger.denied_acquires, 48)

    def test_account_cap_limits_effective_capacity_below_theoretical_slots(self):
        ledger = _FakeProviderSlotLedger(
            key_count=8,
            slots_per_key=2,
            account_cap=10,
        )

        with ThreadPoolExecutor(max_workers=32) as pool:
            leases = list(pool.map(ledger.acquire_for_worker, range(64)))

        active_leases = [lease for lease in leases if lease is not None]
        diagnostics = ledger.provider_capacity_diagnostics()

        self.assertEqual(len(active_leases), 10)
        self.assertLess(len(active_leases), ledger.theoretical_slots)
        self.assertEqual(ledger.max_active_observed, 10)
        self.assertEqual(diagnostics.total_slots, 16)
        self.assertEqual(diagnostics.active_leases, 10)
        self.assertEqual(diagnostics.free_slots, 0)
        self.assertEqual(diagnostics.cap_denied_slots, 6)
        self.assertEqual(diagnostics.capacity_state, "cap_denied")

    def test_throttle_pressure_is_input_not_provider_capacity_truth(self):
        ledger = _FakeProviderSlotLedger(key_count=8, slots_per_key=2)
        capacity = ledger.provider_capacity_diagnostics()

        diagnostics = build_scheduler_backpressure_diagnostics(
            queue_depth_units=12,
            eligible_waiting_units=12,
            delayed_retry_units=0,
            active_work_units=0,
            retry_pressure_units=0,
            expired_work_unit_leases=0,
            provider_capacity=capacity,
            throttle_available_slots=0,
            throttle_circuit_state="open",
            recent_completed_units=4,
            throughput_window_seconds=120,
        )

        self.assertEqual(
            diagnostics.backpressure_state,
            SchedulerBackpressureState.THROTTLE_PRESSURE,
        )
        self.assertEqual(diagnostics.provider_free_slots, 16)
        self.assertIn("adaptive_throttle_pressure", diagnostics.pressure_reasons)
        self.assertEqual(diagnostics.eta.unknown_reason, "adaptive_throttle_pressure")

    def test_provider_failure_categories_are_safe_under_simulated_load(self):
        cases = {
            "HTTP 429 rate limit for sk-secret": ProviderFailureCategory.RATE_LIMITED,
            "provider read timeout token=secret": ProviderFailureCategory.TIMEOUT,
            "HTTP 503 unavailable provider payload": (
                ProviderFailureCategory.UNAVAILABLE_5XX
            ),
            "invalid json response contained raw text": (
                ProviderFailureCategory.MALFORMED_RESPONSE
            ),
            "unsafe_model_output prompt disclosure": (
                ProviderFailureCategory.UNSAFE_MODEL_OUTPUT
            ),
        }

        for message, expected_category in cases.items():
            with self.subTest(expected_category=expected_category.value):
                diagnostic = build_provider_failure_diagnostic(RuntimeError(message))
                payload_json = json.dumps(
                    diagnostic.to_safe_payload(attempt_number=1),
                    sort_keys=True,
                )

                self.assertEqual(diagnostic.failure_category, expected_category)
                self.assertIn(expected_category.value, payload_json)
                self.assertNotIn("sk-secret", payload_json)
                self.assertNotIn("token=secret", payload_json)
                self.assertNotIn("raw text", payload_json)
                self.assertNotIn("prompt disclosure", payload_json)

    def test_expired_lease_recovery_does_not_preempt_active_call(self):
        now = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
        ledger = _FakeProviderSlotLedger(key_count=1, slots_per_key=1)
        lease = ledger.acquire_for_worker(1, lease_seconds=1, now=now)
        ledger.mark_call_active(lease.work_unit_id)

        recovered_while_active = ledger.recover_expired(
            now=lease.lease_until + timedelta(seconds=1)
        )
        ledger.mark_call_finished(lease.work_unit_id)
        recovered_after_finish = ledger.recover_expired(
            now=lease.lease_until + timedelta(seconds=2)
        )

        self.assertEqual(recovered_while_active, 0)
        self.assertEqual(recovered_after_finish, 1)
        self.assertEqual(
            ledger.leases[lease.lease_token].status,
            ProviderSlotLeaseStatus.EXPIRED,
        )

    def test_diagnostics_explain_capacity_cap_throttle_and_fairness_under_load(self):
        ledger = _FakeProviderSlotLedger(
            key_count=8,
            slots_per_key=2,
            account_cap=10,
        )
        for worker_index in range(10):
            ledger.acquire_for_worker(worker_index)

        capacity = ledger.provider_capacity_diagnostics()
        backpressure = build_scheduler_backpressure_diagnostics(
            queue_depth_units=20,
            eligible_waiting_units=10,
            delayed_retry_units=2,
            active_work_units=10,
            retry_pressure_units=2,
            expired_work_unit_leases=0,
            provider_capacity=capacity,
            throttle_available_slots=0,
            throttle_circuit_state="open",
        )
        queue_policy = build_scheduler_queue_policy_diagnostics(
            active_user_units_before_claim=1,
            active_user_jobs_before_claim=1,
            active_job_units_before_claim=0,
            max_active_units_per_job=2,
            max_active_units_per_user=4,
            max_active_jobs_per_user=2,
            priority_aging_seconds=1800,
        )

        self.assertEqual(backpressure.provider_cap_denied_slots, 6)
        self.assertIn("account_model_cap_pressure", backpressure.pressure_reasons)
        self.assertIn("adaptive_throttle_pressure", backpressure.pressure_reasons)
        self.assertIn("provider_failure_retry_pressure", backpressure.pressure_reasons)
        self.assertEqual(queue_policy["active_user_units_before_claim"], 1)
        self.assertIn("active_user_units_asc", queue_policy["ordering"])


class _FakeProviderSlotLedger:
    def __init__(
        self,
        *,
        key_count: int,
        slots_per_key: int,
        account_cap: int | None = None,
    ) -> None:
        self.provider_id = "deepseek"
        self.slots = tuple(
            ProviderSlot(
                provider_id=self.provider_id,
                channel_id=f"chan_{key_index}",
                slot_index=slot_index,
                capacity_source="scale-test",
                enabled=True,
                created_at=datetime(2026, 6, 5, 12, 0, tzinfo=UTC),
                updated_at=datetime(2026, 6, 5, 12, 0, tzinfo=UTC),
            )
            for key_index in range(key_count)
            for slot_index in range(slots_per_key)
        )
        self.account_cap = account_cap
        self.leases: dict[str, ProviderSlotLease] = {}
        self.max_active_observed = 0
        self.denied_acquires = 0
        self._active_calls: set[str] = set()
        self._lock = Lock()

    @property
    def theoretical_slots(self) -> int:
        return len(self.slots)

    def acquire_for_worker(
        self,
        worker_index: int,
        *,
        lease_seconds: int = 300,
        now: datetime | None = None,
    ) -> ProviderSlotLease | None:
        acquired_at = now or datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
        with self._lock:
            active_leases = self._active_leases()
            effective_cap = (
                self.theoretical_slots if self.account_cap is None else self.account_cap
            )
            if len(active_leases) >= effective_cap:
                self.denied_acquires += 1
                return None
            active_slots = {
                (lease.channel_id, lease.slot_index) for lease in active_leases
            }
            slot = next(
                (
                    candidate
                    for candidate in self.slots
                    if (candidate.channel_id, candidate.slot_index) not in active_slots
                ),
                None,
            )
            if slot is None:
                self.denied_acquires += 1
                return None
            lease_token = f"lease-token-{uuid4().hex}"
            lease = ProviderSlotLease(
                lease_id=f"lease-{uuid4().hex}",
                lease_token=lease_token,
                provider_id=self.provider_id,
                channel_id=slot.channel_id,
                slot_index=slot.slot_index,
                job_id=f"job-{worker_index}",
                work_unit_id=f"job-{worker_index}:unit-1",
                worker_id=f"worker-{worker_index}",
                work_unit_claim_token=f"claim-{worker_index}",
                status=ProviderSlotLeaseStatus.ACTIVE,
                acquired_at=acquired_at,
                lease_until=acquired_at + timedelta(seconds=max(1, lease_seconds)),
                released_at=None,
                release_reason=None,
            )
            self.leases[lease_token] = lease
            self.max_active_observed = max(
                self.max_active_observed,
                len(self._active_leases()),
            )
            return lease

    def mark_call_active(self, work_unit_id: str) -> None:
        with self._lock:
            self._active_calls.add(work_unit_id)

    def mark_call_finished(self, work_unit_id: str) -> None:
        with self._lock:
            self._active_calls.discard(work_unit_id)

    def recover_expired(self, *, now: datetime) -> int:
        recovered = 0
        with self._lock:
            for lease_token, lease in list(self.leases.items()):
                if lease.status is not ProviderSlotLeaseStatus.ACTIVE:
                    continue
                if lease.lease_until > now:
                    continue
                if lease.work_unit_id in self._active_calls:
                    continue
                self.leases[lease_token] = replace(
                    lease,
                    status=ProviderSlotLeaseStatus.EXPIRED,
                    released_at=now,
                    release_reason="lease_expired",
                )
                recovered += 1
        return recovered

    def provider_capacity_diagnostics(self):
        caps = ()
        if self.account_cap is not None:
            caps = (
                ProviderCapacityCap(
                    provider_id=self.provider_id,
                    cap_id="deepseek-account-scale-test",
                    scope=ProviderCapacityCapScope.ACCOUNT,
                    max_parallel_requests=self.account_cap,
                ),
            )
        return build_provider_capacity_diagnostics(
            provider_id=self.provider_id,
            slots=self.slots,
            leases=tuple(self.leases.values()),
            capacity_caps=caps,
            now=datetime(2026, 6, 5, 12, 0, tzinfo=UTC),
        )

    def _active_leases(self) -> list[ProviderSlotLease]:
        return [
            lease
            for lease in self.leases.values()
            if lease.status is ProviderSlotLeaseStatus.ACTIVE
        ]


if __name__ == "__main__":
    unittest.main()
