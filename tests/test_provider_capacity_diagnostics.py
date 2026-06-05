import json
import unittest
from datetime import UTC, datetime, timedelta

from translator_service.scheduler import (
    ProviderCapacityCap,
    ProviderCapacityCapScope,
    ProviderCapacitySlotDiagnosticStatus,
    ProviderSlot,
    ProviderSlotLease,
    ProviderSlotLeaseStatus,
    build_provider_capacity_diagnostics,
)


class ProviderCapacityDiagnosticsTest(unittest.TestCase):
    def test_builds_metadata_only_snapshot_with_redacted_channel_values(self):
        now = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
        slots = [
            _slot("deepseek", "deepseek-channel-1", 0),
            _slot("deepseek", "secret sk-live-provider-key", 0),
        ]
        leases = [
            _lease(
                provider_id="deepseek",
                channel_id="deepseek-channel-1",
                slot_index=0,
                acquired_at=now - timedelta(seconds=20),
                lease_until=now + timedelta(seconds=280),
            )
        ]
        caps = [
            ProviderCapacityCap(
                provider_id="deepseek",
                cap_id="deepseek-account-default",
                scope=ProviderCapacityCapScope.ACCOUNT,
                max_parallel_requests=1,
                channel_ids=("deepseek-channel-1", "secret sk-live-provider-key"),
            )
        ]

        diagnostic = build_provider_capacity_diagnostics(
            provider_id="deepseek",
            slots=slots,
            leases=leases,
            capacity_caps=caps,
            now=now,
        )
        serialized = json.dumps(diagnostic, default=str)

        self.assertEqual(diagnostic.capacity_state, "cap_denied")
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
        self.assertNotIn("sk-live-provider-key", serialized)
        self.assertNotIn("secret sk-live-provider-key", serialized)
        self.assertNotIn("lease-token", serialized)
        self.assertNotIn("claim-token", serialized)
        self.assertIn("job-1", serialized)
        self.assertIn("unit-1", serialized)
        self.assertIn("worker-1", serialized)

    def test_marks_expired_active_lease_as_recovering_without_releasing_it(self):
        now = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
        diagnostic = build_provider_capacity_diagnostics(
            provider_id="deepseek",
            slots=[_slot("deepseek", "deepseek-channel-1", 0)],
            leases=[
                _lease(
                    provider_id="deepseek",
                    channel_id="deepseek-channel-1",
                    slot_index=0,
                    acquired_at=now - timedelta(seconds=120),
                    lease_until=now - timedelta(seconds=30),
                )
            ],
            now=now,
        )

        self.assertEqual(diagnostic.capacity_state, "recovering_expired_leases")
        self.assertEqual(diagnostic.expired_active_leases, 1)
        self.assertEqual(
            diagnostic.slots[0].status,
            ProviderCapacitySlotDiagnosticStatus.EXPIRED_ACTIVE,
        )
        self.assertLess(diagnostic.slots[0].lease_expires_in_seconds, 0)


def _slot(
    provider_id: str,
    channel_id: str,
    slot_index: int,
    *,
    enabled: bool = True,
) -> ProviderSlot:
    now = datetime(2026, 6, 5, 11, 59, tzinfo=UTC)
    return ProviderSlot(
        provider_id=provider_id,
        channel_id=channel_id,
        slot_index=slot_index,
        capacity_source="test",
        enabled=enabled,
        created_at=now,
        updated_at=now,
    )


def _lease(
    *,
    provider_id: str,
    channel_id: str,
    slot_index: int,
    acquired_at: datetime,
    lease_until: datetime,
    status: ProviderSlotLeaseStatus = ProviderSlotLeaseStatus.ACTIVE,
) -> ProviderSlotLease:
    return ProviderSlotLease(
        lease_id="lease-1",
        lease_token="lease-token-secret",
        provider_id=provider_id,
        channel_id=channel_id,
        slot_index=slot_index,
        job_id="job-1",
        work_unit_id="unit-1",
        worker_id="worker-1",
        work_unit_claim_token="claim-token-secret",
        status=status,
        acquired_at=acquired_at,
        lease_until=lease_until,
        released_at=None,
        release_reason=None,
    )
