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


@dataclass(frozen=True)
class SchedulerLimits:
    max_active_units_per_job: int = 1
    max_active_jobs_per_user: int = 1
    max_active_units_per_user: int = 2
    max_active_units_global: int = 8
    max_attempts_per_unit: int = 3


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
class RetryDecision:
    retryable: bool
    next_status: SchedulerWorkUnitStatus
    available_at: datetime
    terminal_job_status: SchedulerJobStatus | None


def utc_now() -> datetime:
    return datetime.now(UTC)


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
    ) -> object:
        pass
