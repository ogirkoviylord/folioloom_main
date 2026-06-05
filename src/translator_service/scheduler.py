from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol


class SchedulerJobStatus(StrEnum):
    QUEUED = "queued"
    TRANSLATING = "translating"
    ASSEMBLING = "assembling"
    PARTIAL = "partial"
    READY = "ready"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"
    FAILED = "failed"
    EXPIRED = "expired"


class SchedulerWorkUnitStatus(StrEnum):
    PENDING = "pending"
    TRANSLATING = "translating"
    TRANSLATED = "translated"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_TERMINAL = "failed_terminal"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"
    CACHED = "cached"


class WorkUnitFailureKind(StrEnum):
    RETRYABLE_PROVIDER = "retryable_provider"
    MALFORMED_PROVIDER_OUTPUT = "malformed_provider_output"
    LEASE_EXPIRED = "lease_expired"
    MISSING_SOURCE_OBJECT = "missing_source_object"
    UNSUPPORTED_CONTRACT = "unsupported_contract"
    ASSEMBLY_MAPPING_FAILED = "assembly_mapping_failed"


class ProviderSlotLeaseStatus(StrEnum):
    ACTIVE = "active"
    RELEASED = "released"
    EXPIRED = "expired"


class ProviderCapacityCapScope(StrEnum):
    ACCOUNT = "account"
    MODEL = "model"


class ProviderCapacitySlotDiagnosticStatus(StrEnum):
    DISABLED = "disabled"
    FREE = "free"
    LEASED = "leased"
    EXPIRED_ACTIVE = "expired_active"
    CAP_DENIED = "cap_denied"


@dataclass(frozen=True)
class SchedulerLimits:
    max_active_units_per_job: int = 1
    max_active_jobs_per_user: int = 1
    max_active_units_per_user: int = 1
    max_active_units_global: int = 2
    max_attempts_per_unit: int = 3
    priority_aging_seconds: int = 1800


@dataclass(frozen=True)
class SchedulerClaim:
    job_id: str
    work_unit_id: str
    worker_id: str
    claim_token: str
    lease_until: datetime
    attempt_number: int
    source_object_key: str | None


@dataclass(frozen=True)
class ProviderSlot:
    provider_id: str
    channel_id: str
    slot_index: int
    capacity_source: str | None
    enabled: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ProviderSlotInventoryItem:
    provider_id: str
    channel_id: str
    max_parallel_requests: int
    capacity_source: str | None = None


@dataclass(frozen=True)
class ProviderCapacityCap:
    provider_id: str
    cap_id: str
    scope: ProviderCapacityCapScope
    max_parallel_requests: int
    channel_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProviderSlotLease:
    lease_id: str
    lease_token: str
    provider_id: str
    channel_id: str
    slot_index: int
    job_id: str
    work_unit_id: str
    worker_id: str
    work_unit_claim_token: str
    status: ProviderSlotLeaseStatus
    acquired_at: datetime
    lease_until: datetime
    released_at: datetime | None
    release_reason: str | None


@dataclass(frozen=True)
class ProviderCapacitySlotDiagnostic:
    provider_id: str
    channel_id: str
    slot_index: int
    capacity_source: str | None
    enabled: bool
    status: ProviderCapacitySlotDiagnosticStatus
    leased_by_job_id: str | None = None
    leased_by_work_unit_id: str | None = None
    leased_by_worker_id: str | None = None
    acquired_at: datetime | None = None
    lease_until: datetime | None = None
    lease_age_seconds: float | None = None
    lease_expires_in_seconds: float | None = None


@dataclass(frozen=True)
class ProviderCapacityCapDiagnostic:
    provider_id: str
    cap_id: str
    scope: ProviderCapacityCapScope
    max_parallel_requests: int
    active_leases: int
    available_capacity: int
    at_limit: bool
    channel_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProviderCapacityDiagnostics:
    provider_id: str
    generated_at: datetime
    capacity_state: str
    total_slots: int
    enabled_slots: int
    disabled_slots: int
    active_leases: int
    free_slots: int
    cap_denied_slots: int
    expired_active_leases: int
    recovered_expired_leases: int
    released_leases: int
    slots: tuple[ProviderCapacitySlotDiagnostic, ...]
    caps: tuple[ProviderCapacityCapDiagnostic, ...]
    diagnostic_scope: str = "provider_capacity_only"


@dataclass(frozen=True)
class RetryDecision:
    retryable: bool
    next_status: SchedulerWorkUnitStatus
    available_at: datetime
    terminal_job_status: SchedulerJobStatus | None


def utc_now() -> datetime:
    return datetime.now(UTC)


def build_provider_capacity_diagnostics(
    *,
    provider_id: str,
    slots: list[ProviderSlot] | tuple[ProviderSlot, ...],
    leases: list[ProviderSlotLease] | tuple[ProviderSlotLease, ...],
    capacity_caps: list[ProviderCapacityCap] | tuple[ProviderCapacityCap, ...] = (),
    now: datetime | None = None,
    released_lease_count: int | None = None,
    recovered_expired_lease_count: int | None = None,
) -> ProviderCapacityDiagnostics:
    current_time = _aware_utc(now or utc_now())
    provider_slots = tuple(slot for slot in slots if slot.provider_id == provider_id)
    provider_leases = tuple(
        lease for lease in leases if lease.provider_id == provider_id
    )
    active_leases = tuple(
        lease
        for lease in provider_leases
        if lease.status is ProviderSlotLeaseStatus.ACTIVE
    )
    active_lease_by_slot = {
        (lease.channel_id, lease.slot_index): lease
        for lease in sorted(active_leases, key=lambda item: item.acquired_at)
    }
    safe_caps = _provider_capacity_caps_for_diagnostics(
        capacity_caps,
        provider_id=provider_id,
    )
    cap_diagnostics = tuple(
        _provider_capacity_cap_diagnostic(
            cap,
            active_leases=active_leases,
        )
        for cap in safe_caps
    )
    slot_diagnostics = tuple(
        _provider_capacity_slot_diagnostic(
            slot,
            active_lease=active_lease_by_slot.get((slot.channel_id, slot.slot_index)),
            capacity_caps=safe_caps,
            active_leases=active_leases,
            now=current_time,
        )
        for slot in provider_slots
    )
    enabled_slots = sum(1 for slot in provider_slots if slot.enabled)
    free_slots = sum(
        1
        for slot in slot_diagnostics
        if slot.status is ProviderCapacitySlotDiagnosticStatus.FREE
    )
    cap_denied_slots = sum(
        1
        for slot in slot_diagnostics
        if slot.status is ProviderCapacitySlotDiagnosticStatus.CAP_DENIED
    )
    expired_active_leases = sum(
        1
        for slot in slot_diagnostics
        if slot.status is ProviderCapacitySlotDiagnosticStatus.EXPIRED_ACTIVE
    )
    released_count = (
        released_lease_count
        if released_lease_count is not None
        else sum(
            1
            for lease in provider_leases
            if lease.status is ProviderSlotLeaseStatus.RELEASED
        )
    )
    recovered_count = (
        recovered_expired_lease_count
        if recovered_expired_lease_count is not None
        else sum(
            1
            for lease in provider_leases
            if lease.status is ProviderSlotLeaseStatus.EXPIRED
            and lease.release_reason == "lease_expired"
        )
    )
    return ProviderCapacityDiagnostics(
        provider_id=_safe_provider_diagnostic_text(provider_id),
        generated_at=current_time,
        capacity_state=_provider_capacity_state(
            total_slots=len(provider_slots),
            enabled_slots=enabled_slots,
            active_leases=len(active_leases),
            free_slots=free_slots,
            cap_denied_slots=cap_denied_slots,
            expired_active_leases=expired_active_leases,
        ),
        total_slots=len(provider_slots),
        enabled_slots=enabled_slots,
        disabled_slots=len(provider_slots) - enabled_slots,
        active_leases=len(active_leases),
        free_slots=free_slots,
        cap_denied_slots=cap_denied_slots,
        expired_active_leases=expired_active_leases,
        recovered_expired_leases=max(0, int(recovered_count)),
        released_leases=max(0, int(released_count)),
        slots=slot_diagnostics,
        caps=cap_diagnostics,
    )


def _provider_capacity_caps_for_diagnostics(
    capacity_caps: list[ProviderCapacityCap] | tuple[ProviderCapacityCap, ...],
    *,
    provider_id: str,
) -> tuple[ProviderCapacityCap, ...]:
    caps = []
    for cap in capacity_caps:
        if cap.provider_id != provider_id:
            continue
        channel_ids = tuple(
            sorted({channel_id for channel_id in cap.channel_ids if channel_id})
        )
        caps.append(
            ProviderCapacityCap(
                provider_id=provider_id,
                cap_id=cap.cap_id,
                scope=cap.scope,
                max_parallel_requests=max(0, int(cap.max_parallel_requests)),
                channel_ids=channel_ids,
            )
        )
    return tuple(caps)


def _provider_capacity_cap_diagnostic(
    cap: ProviderCapacityCap,
    *,
    active_leases: tuple[ProviderSlotLease, ...],
) -> ProviderCapacityCapDiagnostic:
    active_count = _provider_capacity_cap_active_count(cap, active_leases)
    available_capacity = max(0, cap.max_parallel_requests - active_count)
    return ProviderCapacityCapDiagnostic(
        provider_id=_safe_provider_diagnostic_text(cap.provider_id),
        cap_id=_safe_provider_diagnostic_text(cap.cap_id),
        scope=cap.scope,
        max_parallel_requests=cap.max_parallel_requests,
        active_leases=active_count,
        available_capacity=available_capacity,
        at_limit=cap.max_parallel_requests <= 0
        or active_count >= cap.max_parallel_requests,
        channel_ids=tuple(
            _safe_provider_diagnostic_text(channel_id)
            for channel_id in cap.channel_ids
        ),
    )


def _provider_capacity_slot_diagnostic(
    slot: ProviderSlot,
    *,
    active_lease: ProviderSlotLease | None,
    capacity_caps: tuple[ProviderCapacityCap, ...],
    active_leases: tuple[ProviderSlotLease, ...],
    now: datetime,
) -> ProviderCapacitySlotDiagnostic:
    status = ProviderCapacitySlotDiagnosticStatus.FREE
    if not slot.enabled:
        status = ProviderCapacitySlotDiagnosticStatus.DISABLED
    elif active_lease is not None:
        status = (
            ProviderCapacitySlotDiagnosticStatus.EXPIRED_ACTIVE
            if _aware_utc(active_lease.lease_until) <= now
            else ProviderCapacitySlotDiagnosticStatus.LEASED
        )
    elif _provider_capacity_caps_block_slot(
        slot,
        capacity_caps=capacity_caps,
        active_leases=active_leases,
    ):
        status = ProviderCapacitySlotDiagnosticStatus.CAP_DENIED

    lease_age_seconds = None
    lease_expires_in_seconds = None
    if active_lease is not None:
        lease_age_seconds = max(
            0.0,
            (now - _aware_utc(active_lease.acquired_at)).total_seconds(),
        )
        lease_expires_in_seconds = (
            _aware_utc(active_lease.lease_until) - now
        ).total_seconds()

    return ProviderCapacitySlotDiagnostic(
        provider_id=_safe_provider_diagnostic_text(slot.provider_id),
        channel_id=_safe_provider_diagnostic_text(slot.channel_id),
        slot_index=slot.slot_index,
        capacity_source=(
            _safe_provider_diagnostic_text(slot.capacity_source)
            if slot.capacity_source is not None
            else None
        ),
        enabled=slot.enabled,
        status=status,
        leased_by_job_id=active_lease.job_id if active_lease is not None else None,
        leased_by_work_unit_id=(
            active_lease.work_unit_id if active_lease is not None else None
        ),
        leased_by_worker_id=(
            active_lease.worker_id if active_lease is not None else None
        ),
        acquired_at=active_lease.acquired_at if active_lease is not None else None,
        lease_until=active_lease.lease_until if active_lease is not None else None,
        lease_age_seconds=lease_age_seconds,
        lease_expires_in_seconds=lease_expires_in_seconds,
    )


def _provider_capacity_caps_block_slot(
    slot: ProviderSlot,
    *,
    capacity_caps: tuple[ProviderCapacityCap, ...],
    active_leases: tuple[ProviderSlotLease, ...],
) -> bool:
    for cap in capacity_caps:
        if cap.channel_ids and slot.channel_id not in cap.channel_ids:
            continue
        active_count = _provider_capacity_cap_active_count(cap, active_leases)
        if cap.max_parallel_requests <= 0 or active_count >= cap.max_parallel_requests:
            return True
    return False


def _provider_capacity_cap_active_count(
    cap: ProviderCapacityCap,
    active_leases: tuple[ProviderSlotLease, ...],
) -> int:
    return sum(
        1
        for lease in active_leases
        if lease.provider_id == cap.provider_id
        and (not cap.channel_ids or lease.channel_id in cap.channel_ids)
    )


def _provider_capacity_state(
    *,
    total_slots: int,
    enabled_slots: int,
    active_leases: int,
    free_slots: int,
    cap_denied_slots: int,
    expired_active_leases: int,
) -> str:
    if total_slots <= 0:
        return "no_inventory"
    if enabled_slots <= 0:
        return "disabled"
    if expired_active_leases > 0:
        return "recovering_expired_leases"
    if active_leases >= enabled_slots:
        return "fully_leased"
    if cap_denied_slots > 0 and free_slots == 0:
        return "cap_denied"
    if free_slots > 0 and active_leases == 0:
        return "idle"
    if free_slots > 0:
        return "available"
    return "constrained"


def _safe_provider_diagnostic_text(value: str) -> str:
    lowered = value.lower()
    unsafe_markers = (
        ".api_keys.",
        "api_key",
        "authorization",
        "bearer ",
        "password",
        "secret",
        "sk-",
        "token",
        "traceback",
    )
    if any(marker in lowered for marker in unsafe_markers):
        return "[redacted]"
    if "/" in value or "\\" in value:
        return "[redacted]"
    return value


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def calculate_retry_decision(
    *,
    failure_kind: WorkUnitFailureKind,
    attempt_count: int,
    max_attempts: int,
    now: datetime,
    base_delay_seconds: int,
    max_delay_seconds: int,
) -> RetryDecision:
    terminal_failures = {
        WorkUnitFailureKind.MISSING_SOURCE_OBJECT,
        WorkUnitFailureKind.UNSUPPORTED_CONTRACT,
        WorkUnitFailureKind.ASSEMBLY_MAPPING_FAILED,
    }
    if failure_kind in terminal_failures or attempt_count >= max_attempts:
        return RetryDecision(
            retryable=False,
            next_status=SchedulerWorkUnitStatus.FAILED_TERMINAL,
            available_at=now,
            terminal_job_status=SchedulerJobStatus.INTERRUPTED,
        )

    delay = min(base_delay_seconds * (2 ** max(0, attempt_count - 1)), max_delay_seconds)
    return RetryDecision(
        retryable=True,
        next_status=SchedulerWorkUnitStatus.FAILED_RETRYABLE,
        available_at=now + timedelta(seconds=delay),
        terminal_job_status=None,
    )


class SchedulerRepository(Protocol):
    def claim_next_scheduled_work_unit(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
        limits: SchedulerLimits,
    ) -> SchedulerClaim | None:
        pass

    def complete_claimed_work_unit(
        self,
        *,
        work_unit_id: str,
        claim_token: str,
        translated_text: str,
        prompt_tokens: int,
        completion_tokens: int,
        cache_hit_tokens: int,
        cache_miss_tokens: int,
    ) -> object:
        pass

    def fail_claimed_work_unit(
        self,
        *,
        work_unit_id: str,
        claim_token: str,
        failure_kind: WorkUnitFailureKind,
        error_message: str,
        retry_base_delay_seconds: int,
        retry_max_delay_seconds: int,
        provider_failure_diagnostic: object | None = None,
    ) -> object:
        pass
