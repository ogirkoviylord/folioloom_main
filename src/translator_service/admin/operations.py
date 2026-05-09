from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from translator_service.admin.translation_logs import list_translation_run_summaries
from translator_service.persistent_job_store import (
    open_persistent_job_store,
    sqlite_store_exists,
)
from translator_service.persistent_jobs import (
    PersistentTranslationJobStatus,
)

JOB_STATE_QUEUED = "queued"
JOB_STATE_RUNNING = "running"
JOB_STATE_PAUSED = "paused"
JOB_STATE_SUCCEEDED = "succeeded"
JOB_STATE_FAILED = "failed"
JOB_STATE_CANCELLED = "cancelled"
JOB_STATE_UNKNOWN = "unknown"

WORKER_HEALTH_HEALTHY = "healthy"
WORKER_HEALTH_STALE = "stale"
WORKER_HEALTH_OFFLINE = "offline"
WORKER_HEALTH_UNKNOWN = "unknown"

_QUEUED_STATUSES = {"new", "pending", "queued", "scheduled"}
_RUNNING_STATUSES = {
    "active",
    "assembling",
    "cancel_requested",
    "in_progress",
    "processing",
    "running",
    "started",
    "translating",
}
_PAUSED_STATUSES = {"paused"}
_SUCCEEDED_STATUSES = {
    "cached",
    "complete",
    "completed",
    "partial",
    "ready",
    "skipped",
    "success",
    "succeeded",
    "translated",
}
_FAILED_STATUSES = {
    "error",
    "expired",
    "failed",
    "failed_retryable",
    "failed_terminal",
    "interrupted",
}
_CANCELLED_STATUSES = {"canceled", "cancelled"}

_HEALTHY_WORKER_STATUSES = {"active", "idle", "ok", "ready", "running"}
_OFFLINE_WORKER_STATUSES = {"dead", "offline", "stopped", "terminated"}
_UNKNOWN_WORKER_STATUSES = {"", "unknown"}

_SECRET_PATTERNS = (
    re.compile(r"(?i)authorization:\s*bearer\s+[a-z0-9._~+/=-]+"),
    re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)\bsk-[a-z0-9_-]{8,}"),
    re.compile(r"(?i)\bapi[-_ ]?key[-_: =]+[a-z0-9._-]{4,}"),
)


@dataclass(frozen=True)
class AdminJobSummary:
    id: str
    state: str
    raw_status: str | None = None
    order_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    total_units: int = 0
    completed_units: int = 0
    failed_units: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    retry_count: int = 0
    active_worker_ids: tuple[str, ...] = ()
    retryable: bool = False
    cancellable: bool = False
    pausable: bool = False
    deletable: bool = False
    error_excerpt: str | None = None
    log_href: str | None = None


@dataclass(frozen=True)
class AdminWorkerSummary:
    id: str
    health: str
    raw_status: str | None = None
    queue_name: str | None = None
    current_job_id: str | None = None
    active_work_unit_id: str | None = None
    last_heartbeat_at: datetime | None = None
    queue_depth: int | None = None


@dataclass(frozen=True)
class OperationsOverview:
    jobs: tuple[AdminJobSummary, ...]
    workers: tuple[AdminWorkerSummary, ...]
    job_counts_by_state: dict[str, int] = field(default_factory=dict)
    worker_counts_by_health: dict[str, int] = field(default_factory=dict)
    queue_depths: dict[str, int] = field(default_factory=dict)
    total_queue_depth: int = 0


def normalize_job_state(status: Any) -> str:
    normalized = _normalize_status(status)
    if normalized in _QUEUED_STATUSES:
        return JOB_STATE_QUEUED
    if normalized in _RUNNING_STATUSES:
        return JOB_STATE_RUNNING
    if normalized in _PAUSED_STATUSES:
        return JOB_STATE_PAUSED
    if normalized in _SUCCEEDED_STATUSES:
        return JOB_STATE_SUCCEEDED
    if normalized in _FAILED_STATUSES:
        return JOB_STATE_FAILED
    if normalized in _CANCELLED_STATUSES:
        return JOB_STATE_CANCELLED
    return JOB_STATE_UNKNOWN


def summarize_job(
    row: Any,
    *,
    work_units: Iterable[Any] | None = None,
    log_href: str | None = None,
    max_error_chars: int = 160,
) -> AdminJobSummary:
    raw_status = _optional_string(_read(row, "status", "state"))
    state = normalize_job_state(raw_status)
    units = tuple(work_units or ())
    completed_units = _count_units(units, JOB_STATE_SUCCEEDED)
    failed_units = _count_units(units, JOB_STATE_FAILED)
    active_worker_ids = _active_worker_ids(units)
    prompt_tokens = _optional_int(
        _read(row, "prompt_tokens"),
        _sum_unit_ints(units, "prompt_tokens"),
    )
    completion_tokens = _optional_int(
        _read(row, "completion_tokens"),
        _sum_unit_ints(units, "completion_tokens"),
    )
    total_tokens = _optional_int(
        _read(row, "total_tokens"),
        prompt_tokens + completion_tokens,
    )
    started_at = _optional_datetime(_read(row, "started_at")) or _first_unit_datetime(
        units,
        "started_at",
    )

    return AdminJobSummary(
        id=_required_string(row, "id", "job_id"),
        state=state,
        raw_status=raw_status,
        order_id=_optional_string(_read(row, "order_id")),
        created_at=_optional_datetime(_read(row, "created_at")),
        updated_at=_optional_datetime(_read(row, "updated_at")),
        started_at=started_at,
        completed_at=_optional_datetime(_read(row, "completed_at")),
        total_units=_optional_int(_read(row, "total_units", "unit_count"), len(units)),
        completed_units=_optional_int(
            _read(row, "completed_units", "translated_units"),
            completed_units,
        ),
        failed_units=_optional_int(_read(row, "failed_units"), failed_units),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        retry_count=_optional_int(_read(row, "retry_count", "retries"), 0),
        active_worker_ids=active_worker_ids,
        retryable=state == JOB_STATE_FAILED,
        cancellable=state in {JOB_STATE_QUEUED, JOB_STATE_RUNNING},
        pausable=state in {JOB_STATE_QUEUED, JOB_STATE_RUNNING},
        deletable=state in {JOB_STATE_QUEUED, JOB_STATE_RUNNING, JOB_STATE_PAUSED},
        error_excerpt=_safe_error_excerpt(
            _first_present(
                _read(row, "error_excerpt", "last_error", "error_message", "error"),
                _first_unit_error(units),
            ),
            max_chars=max_error_chars,
        ),
        log_href=log_href,
    )


def summarize_worker(
    row: Any,
    *,
    now: datetime | None = None,
    stale_after: timedelta = timedelta(minutes=5),
    queue_depth: int | None = None,
) -> AdminWorkerSummary:
    raw_status = _optional_string(_read(row, "status", "state"))
    last_heartbeat_at = _optional_datetime(
        _read(row, "last_heartbeat_at", "heartbeat_at", "updated_at")
    )
    queue_name = _optional_string(_read(row, "queue_name", "queue"))

    return AdminWorkerSummary(
        id=_required_string(row, "id", "worker_id"),
        health=_worker_health(
            raw_status,
            last_heartbeat_at=last_heartbeat_at,
            now=now,
            stale_after=stale_after,
        ),
        raw_status=raw_status,
        queue_name=queue_name,
        current_job_id=_optional_string(_read(row, "current_job_id", "job_id")),
        active_work_unit_id=_optional_string(
            _read(row, "active_work_unit_id", "work_unit_id")
        ),
        last_heartbeat_at=last_heartbeat_at,
        queue_depth=queue_depth,
    )


def build_operations_overview(
    *,
    jobs: Iterable[Any] = (),
    workers: Iterable[Any] = (),
    queue_depths: Mapping[str, int] | None = None,
    work_units_by_job_id: Mapping[str, Iterable[Any]] | None = None,
    job_log_hrefs: Mapping[str, str] | None = None,
    now: datetime | None = None,
    stale_after: timedelta = timedelta(minutes=5),
) -> OperationsOverview:
    normalized_queue_depths = {
        str(queue_name): int(depth)
        for queue_name, depth in (queue_depths or {}).items()
    }
    normalized_work_units = work_units_by_job_id or {}
    normalized_log_hrefs = job_log_hrefs or {}
    job_summaries = tuple(
        summarize_job(
            job,
            work_units=normalized_work_units.get(_job_mapping_key(job), ()),
            log_href=normalized_log_hrefs.get(_job_mapping_key(job)),
        )
        for job in jobs
    )
    worker_summaries = tuple(
        summarize_worker(
            worker,
            now=now,
            stale_after=stale_after,
            queue_depth=_queue_depth_for(worker, normalized_queue_depths),
        )
        for worker in workers
    )

    return OperationsOverview(
        jobs=job_summaries,
        workers=worker_summaries,
        job_counts_by_state=_counts(
            (job.state for job in job_summaries),
            (
                JOB_STATE_QUEUED,
                JOB_STATE_RUNNING,
                JOB_STATE_SUCCEEDED,
                JOB_STATE_FAILED,
                JOB_STATE_CANCELLED,
                JOB_STATE_UNKNOWN,
            ),
        ),
        worker_counts_by_health=_counts(
            (worker.health for worker in worker_summaries),
            (
                WORKER_HEALTH_HEALTHY,
                WORKER_HEALTH_STALE,
                WORKER_HEALTH_OFFLINE,
                WORKER_HEALTH_UNKNOWN,
            ),
        ),
        queue_depths=normalized_queue_depths,
        total_queue_depth=sum(normalized_queue_depths.values()),
    )


def build_persistent_operations_overview(
    db_path: str | Path,
    log_root: str | Path,
    *,
    limit_per_status: int = 25,
    scheduler_backend: str = "sqlite",
    postgres_dsn: str = "postgresql://translator:translator@localhost:5432/translator",
) -> OperationsOverview:
    if scheduler_backend == "sqlite":
        if not sqlite_store_exists(db_path):
            return build_operations_overview()

    store = open_persistent_job_store(
        _OperationStoreSettings(
            scheduler_backend=scheduler_backend,
            persistent_jobs_db_path=str(db_path),
            postgres_dsn=postgres_dsn,
        )
    )
    try:
        jobs = []
        work_units_by_job_id: dict[str, tuple[Any, ...]] = {}
        for status in _PERSISTENT_OPERATION_STATUSES:
            for job in store.list_jobs_by_status(status, limit=limit_per_status):
                jobs.append(job)
                job_id = _job_mapping_key(job)
                work_units_by_job_id[job_id] = tuple(store.list_work_units(job_id))
    finally:
        store.close()

    job_log_hrefs = {
        summary.job_id: f"/admin/logs/{Path(summary.run_dir).name}"
        for summary in list_translation_run_summaries(log_root, limit=500)
        if summary.job_id
    }
    return build_operations_overview(
        jobs=jobs,
        work_units_by_job_id=work_units_by_job_id,
        job_log_hrefs=job_log_hrefs,
    )


_PERSISTENT_OPERATION_STATUSES = (
    PersistentTranslationJobStatus.QUEUED,
    PersistentTranslationJobStatus.TRANSLATING,
    PersistentTranslationJobStatus.ASSEMBLING,
    PersistentTranslationJobStatus.PAUSED,
    PersistentTranslationJobStatus.CANCEL_REQUESTED,
    PersistentTranslationJobStatus.CANCELLED,
    PersistentTranslationJobStatus.EXPIRED,
    PersistentTranslationJobStatus.INTERRUPTED,
    PersistentTranslationJobStatus.FAILED,
    PersistentTranslationJobStatus.READY,
    PersistentTranslationJobStatus.PARTIAL,
)


@dataclass(frozen=True)
class _OperationStoreSettings:
    scheduler_backend: str
    persistent_jobs_db_path: str
    postgres_dsn: str


def _count_units(units: tuple[Any, ...], state: str) -> int:
    return sum(
        1 for unit in units if normalize_job_state(_read(unit, "status")) == state
    )


def _active_worker_ids(units: tuple[Any, ...]) -> tuple[str, ...]:
    worker_ids = {
        worker_id
        for unit in units
        if normalize_job_state(_read(unit, "status")) == JOB_STATE_RUNNING
        for worker_id in (_optional_string(_read(unit, "worker_id")),)
        if worker_id
    }
    return tuple(sorted(worker_ids))


def _first_unit_error(units: tuple[Any, ...]) -> Any:
    for unit in units:
        if normalize_job_state(_read(unit, "status")) == JOB_STATE_FAILED:
            error = _read(unit, "last_error", "error_message", "error")
            if error:
                return error
    return None


def _sum_unit_ints(units: tuple[Any, ...], field_name: str) -> int:
    return sum(_optional_int(_read(unit, field_name), 0) for unit in units)


def _first_unit_datetime(units: tuple[Any, ...], field_name: str) -> datetime | None:
    values = [
        value
        for value in (_optional_datetime(_read(unit, field_name)) for unit in units)
        if value is not None
    ]
    return min(values) if values else None


def _job_mapping_key(job: Any) -> str:
    return _required_string(job, "id", "job_id")


def _safe_error_excerpt(value: Any, *, max_chars: int) -> str | None:
    if value is None:
        return None

    excerpt = " ".join(str(value).split())
    for pattern in _SECRET_PATTERNS:
        excerpt = pattern.sub("[redacted]", excerpt)

    if len(excerpt) <= max_chars:
        return excerpt

    if max_chars <= 3:
        return "." * max_chars
    return excerpt[: max_chars - 3].rstrip() + "..."


def _worker_health(
    status: str | None,
    *,
    last_heartbeat_at: datetime | None,
    now: datetime | None,
    stale_after: timedelta,
) -> str:
    normalized = _normalize_status(status)
    if normalized in _OFFLINE_WORKER_STATUSES:
        return WORKER_HEALTH_OFFLINE
    if normalized in _UNKNOWN_WORKER_STATUSES:
        return WORKER_HEALTH_UNKNOWN
    if (
        last_heartbeat_at is not None
        and now is not None
        and _as_aware_utc(now) - _as_aware_utc(last_heartbeat_at) > stale_after
    ):
        return WORKER_HEALTH_STALE
    if normalized in _HEALTHY_WORKER_STATUSES:
        return WORKER_HEALTH_HEALTHY
    return WORKER_HEALTH_UNKNOWN


def _queue_depth_for(worker: Any, queue_depths: Mapping[str, int]) -> int | None:
    queue_name = _optional_string(_read(worker, "queue_name", "queue"))
    if queue_name is None:
        return None
    return queue_depths.get(queue_name)


def _counts(values: Iterable[str], known_values: Iterable[str]) -> dict[str, int]:
    counts = {value: 0 for value in known_values}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts


def _read(row: Any, *names: str) -> Any:
    for name in names:
        if isinstance(row, Mapping) and name in row:
            return row[name]

        keys = getattr(row, "keys", None)
        if keys is not None and name in keys():
            return row[name]

        if hasattr(row, name):
            return getattr(row, name)
    return None


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _required_string(row: Any, *names: str) -> str:
    value = _optional_string(_read(row, *names))
    if value is None:
        raise ValueError(f"Row is missing one of required fields: {', '.join(names)}")
    return value


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "value"):
        value = value.value
    return str(value)


def _optional_int(value: Any, default: int) -> int:
    if value is None:
        return default
    return int(value)


def _optional_datetime(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return None


def _normalize_status(status: Any) -> str:
    if status is None:
        return ""
    if hasattr(status, "value"):
        status = status.value
    return str(status).strip().lower().replace("-", "_").replace(" ", "_")


def _as_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
