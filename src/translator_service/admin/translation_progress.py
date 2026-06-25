from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from translator_service.admin.operations import (
    JOB_STATE_FAILED,
    JOB_STATE_QUEUED,
    JOB_STATE_RUNNING,
    JOB_STATE_SUCCEEDED,
    JOB_STATE_UNKNOWN,
    OperationsOverview,
    normalize_job_state,
)
from translator_service.admin.translation_logs import (
    TranslationRunDetails,
    TranslationRunSummary,
)

_ACTIVE_STATUSES = {
    "active",
    "cancel_requested",
    "in_progress",
    "processing",
    "running",
    "started",
    "translating",
}


@dataclass(frozen=True)
class DurableTranslationProgressSnapshot:
    job_id: str
    available: bool = False
    unavailable_reason: str | None = None
    status: str = "unknown"
    state: str = JOB_STATE_UNKNOWN
    completed_units: int = 0
    total_units: int = 0
    failed_units: int = 0
    active_units: int = 0
    pending_units: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_hit_tokens: int = 0
    cache_miss_tokens: int = 0
    cache_hit_units: int = 0
    total_tokens: int = 0
    retry_count: int = 0
    active_worker_ids: tuple[str, ...] = ()
    created_at: datetime | None = None
    updated_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    progress_percent: float | None = None
    eta_seconds: float | None = None


def build_durable_translation_progress_snapshot(
    job_id: str,
    *,
    store: Any | None,
    now: datetime | None = None,
) -> DurableTranslationProgressSnapshot:
    safe_job_id = str(job_id or "")
    if not safe_job_id:
        return _unavailable_progress_snapshot("", "missing_job_id")
    if store is None:
        return _unavailable_progress_snapshot(safe_job_id, "store_unavailable")

    try:
        job = store.get_job(safe_job_id)
    except Exception:
        return _unavailable_progress_snapshot(safe_job_id, "store_error")
    if job is None:
        return _unavailable_progress_snapshot(safe_job_id, "job_not_found")

    try:
        units = tuple(store.list_work_units(safe_job_id))
    except Exception:
        return _unavailable_progress_snapshot(
            safe_job_id,
            "work_units_unavailable",
        )

    status = _status_text(_read_value(job, "status", "state"))
    state = normalize_job_state(status)
    unit_states = tuple(
        normalize_job_state(_read_value(unit, "status")) for unit in units
    )
    completed_units = _count_unit_states(unit_states, JOB_STATE_SUCCEEDED)
    failed_units = _count_unit_states(unit_states, JOB_STATE_FAILED)
    active_units = _count_unit_states(unit_states, JOB_STATE_RUNNING)
    pending_units = _count_unit_states(unit_states, JOB_STATE_QUEUED)
    prompt_tokens = _sum_unit_field(units, "prompt_tokens")
    completion_tokens = _sum_unit_field(units, "completion_tokens")
    cache_hit_tokens = _sum_unit_field(units, "cache_hit_tokens")
    cache_miss_tokens = _sum_unit_field(units, "cache_miss_tokens")
    total_units = max(
        _nonnegative_int(_read_value(job, "total_units", "unit_count")),
        len(units),
    )
    started_at = (
        _optional_datetime(_read_value(job, "started_at"))
        or _first_datetime(tuple(_read_value(unit, "started_at") for unit in units))
        or _optional_datetime(_read_value(job, "created_at"))
    )
    completed_at = _last_datetime(
        (
            _read_value(job, "completed_at"),
            *(_read_value(unit, "completed_at") for unit in units),
        )
    )

    return DurableTranslationProgressSnapshot(
        job_id=safe_job_id,
        available=True,
        status=status,
        state=state,
        completed_units=completed_units,
        total_units=total_units,
        failed_units=failed_units,
        active_units=active_units,
        pending_units=pending_units,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cache_hit_tokens=cache_hit_tokens,
        cache_miss_tokens=cache_miss_tokens,
        cache_hit_units=_count_positive_unit_field(units, "cache_hit_tokens"),
        total_tokens=prompt_tokens + completion_tokens,
        retry_count=max(
            _nonnegative_int(_read_value(job, "retry_count", "retries")),
            _sum_unit_field(units, "retry_count"),
        ),
        active_worker_ids=_active_worker_ids(units, unit_states),
        created_at=_optional_datetime(_read_value(job, "created_at")),
        updated_at=_optional_datetime(_read_value(job, "updated_at")),
        started_at=started_at,
        completed_at=completed_at,
        progress_percent=_progress_percent(completed_units, total_units),
        eta_seconds=_eta_seconds(
            status=state,
            completed=completed_units,
            total=total_units,
            started_at=started_at,
            now=now,
        ),
    )


def overlay_translation_run_summaries(
    summaries: tuple[TranslationRunSummary, ...],
    *,
    operations: OperationsOverview | None,
    progress_snapshots: Mapping[str, DurableTranslationProgressSnapshot] | None = None,
    now: datetime | None = None,
) -> tuple[TranslationRunSummary, ...]:
    if operations is None and progress_snapshots is None:
        return summaries
    jobs_by_id = _jobs_by_id(operations) if operations is not None else {}
    snapshots_by_id = progress_snapshots or {}
    return tuple(
        _overlay_summary_with_progress_snapshot(
            _overlay_summary(summary, jobs_by_id.get(summary.job_id), now=now),
            snapshots_by_id.get(summary.job_id),
            now=now,
        )
        for summary in summaries
    )


def overlay_translation_run_details(
    details: TranslationRunDetails,
    *,
    operations: OperationsOverview | None,
    progress_snapshots: Mapping[str, DurableTranslationProgressSnapshot] | None = None,
    now: datetime | None = None,
) -> TranslationRunDetails:
    if operations is None and progress_snapshots is None:
        return details
    job = _jobs_by_id(operations).get(details.summary.job_id) if operations else None
    snapshot = (progress_snapshots or {}).get(details.summary.job_id)
    if job is None and (snapshot is None or not snapshot.available):
        return details
    summary = _overlay_summary(details.summary, job, now=now)
    summary = _overlay_summary_with_progress_snapshot(summary, snapshot, now=now)
    totals = _overlay_totals(details.totals, job) if job is not None else details.totals
    totals = _overlay_totals_with_progress_snapshot(totals, snapshot)
    if summary == details.summary and totals == details.totals:
        return details
    return replace(details, summary=summary, totals=totals)


def overlay_operations_overview_progress(
    operations: OperationsOverview,
    *,
    progress_snapshots: Mapping[str, DurableTranslationProgressSnapshot] | None,
) -> OperationsOverview:
    if not progress_snapshots:
        return operations
    updated_jobs = tuple(
        _overlay_operation_job_with_progress_snapshot(
            job,
            progress_snapshots.get(job.id),
        )
        for job in operations.jobs
    )
    if updated_jobs == operations.jobs:
        return operations
    return replace(operations, jobs=updated_jobs)


def _overlay_summary(
    summary: TranslationRunSummary,
    job: Any | None,
    *,
    now: datetime | None,
) -> TranslationRunSummary:
    if job is None:
        return summary
    completed_units = _nonnegative_int(getattr(job, "completed_units", 0))
    total_units = _nonnegative_int(getattr(job, "total_units", 0))
    total_tokens = _nonnegative_int(getattr(job, "total_tokens", 0))
    if completed_units <= 0 and total_units <= 0 and total_tokens <= 0:
        return summary

    status = _status_text(
        getattr(job, "raw_status", None) or getattr(job, "state", None)
    )
    displayed_completed = max(summary.fragment_count, completed_units)
    displayed_total = max(
        summary.total_fragment_count,
        total_units,
        displayed_completed,
    )
    return replace(
        summary,
        status=status if status != "unknown" else summary.status,
        fragment_count=displayed_completed,
        total_fragment_count=displayed_total,
        progress_percent=_progress_percent(displayed_completed, displayed_total),
        eta_seconds=_eta_seconds(
            status=status,
            completed=displayed_completed,
            total=displayed_total,
            started_at=getattr(job, "started_at", None)
            or getattr(job, "created_at", None)
            or summary.started_at,
            now=now,
        ),
        current_stage=status if status != "unknown" else summary.current_stage,
        last_event_at=getattr(job, "updated_at", None) or summary.last_event_at,
        total_tokens=max(summary.total_tokens, total_tokens),
        error_message=getattr(job, "error_excerpt", None) or summary.error_message,
    )


def _overlay_summary_with_progress_snapshot(
    summary: TranslationRunSummary,
    snapshot: DurableTranslationProgressSnapshot | None,
    *,
    now: datetime | None,
) -> TranslationRunSummary:
    if snapshot is None or not snapshot.available:
        return summary
    if (
        snapshot.completed_units <= 0
        and snapshot.total_units <= 0
        and snapshot.total_tokens <= 0
    ):
        return summary

    displayed_completed = snapshot.completed_units
    displayed_total = max(snapshot.total_units, displayed_completed)
    status = snapshot.status if snapshot.status != "unknown" else summary.status
    return replace(
        summary,
        status=status,
        fragment_count=displayed_completed,
        total_fragment_count=displayed_total,
        progress_percent=_progress_percent(displayed_completed, displayed_total),
        eta_seconds=(
            snapshot.eta_seconds
            if snapshot.eta_seconds is not None
            else _eta_seconds(
                status=snapshot.state,
                completed=displayed_completed,
                total=displayed_total,
                started_at=snapshot.started_at or summary.started_at,
                now=now,
            )
        ),
        current_stage=status or summary.current_stage,
        last_event_at=snapshot.updated_at or summary.last_event_at,
        total_tokens=snapshot.total_tokens,
    )


def _overlay_totals(totals: dict[str, Any], job: Any) -> dict[str, Any]:
    updated = dict(totals)
    prompt_tokens = _nonnegative_int(getattr(job, "prompt_tokens", 0))
    completion_tokens = _nonnegative_int(getattr(job, "completion_tokens", 0))
    total_tokens = _nonnegative_int(getattr(job, "total_tokens", 0))
    _set_max(updated, "prompt_tokens", prompt_tokens)
    _set_max(updated, "completion_tokens", completion_tokens)
    _set_max(updated, "total_tokens", total_tokens)
    return updated


def _overlay_totals_with_progress_snapshot(
    totals: dict[str, Any],
    snapshot: DurableTranslationProgressSnapshot | None,
) -> dict[str, Any]:
    if snapshot is None or not snapshot.available:
        return totals
    updated = dict(totals)
    updated["prompt_tokens"] = snapshot.prompt_tokens
    updated["completion_tokens"] = snapshot.completion_tokens
    updated["total_tokens"] = snapshot.total_tokens
    updated["prompt_cache_hit_tokens"] = snapshot.cache_hit_tokens
    updated["prompt_cache_miss_tokens"] = snapshot.cache_miss_tokens
    updated["cache_hits"] = snapshot.cache_hit_units
    updated["retry_count"] = snapshot.retry_count
    return updated


def _overlay_operation_job_with_progress_snapshot(
    job: Any,
    snapshot: DurableTranslationProgressSnapshot | None,
) -> Any:
    if snapshot is None or not snapshot.available:
        return job
    return replace(
        job,
        state=snapshot.state,
        raw_status=snapshot.status,
        updated_at=snapshot.updated_at or getattr(job, "updated_at", None),
        started_at=snapshot.started_at or getattr(job, "started_at", None),
        completed_at=snapshot.completed_at or getattr(job, "completed_at", None),
        total_units=snapshot.total_units,
        completed_units=snapshot.completed_units,
        failed_units=snapshot.failed_units,
        prompt_tokens=snapshot.prompt_tokens,
        completion_tokens=snapshot.completion_tokens,
        total_tokens=snapshot.total_tokens,
        retry_count=snapshot.retry_count,
        active_worker_ids=snapshot.active_worker_ids,
    )


def _jobs_by_id(operations: OperationsOverview) -> dict[str, Any]:
    return {job.id: job for job in operations.jobs if getattr(job, "id", "")}


def _unavailable_progress_snapshot(
    job_id: str,
    reason: str,
) -> DurableTranslationProgressSnapshot:
    return DurableTranslationProgressSnapshot(
        job_id=job_id,
        available=False,
        unavailable_reason=reason,
    )


def _active_worker_ids(
    units: tuple[Any, ...],
    unit_states: tuple[str, ...],
) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                worker_id
                for unit, unit_state in zip(units, unit_states, strict=True)
                if unit_state == JOB_STATE_RUNNING
                for worker_id in (_optional_string(_read_value(unit, "worker_id")),)
                if worker_id
            }
        )
    )


def _count_unit_states(unit_states: tuple[str, ...], state: str) -> int:
    return sum(1 for unit_state in unit_states if unit_state == state)


def _sum_unit_field(units: tuple[Any, ...], field_name: str) -> int:
    return sum(_nonnegative_int(_read_value(unit, field_name)) for unit in units)


def _count_positive_unit_field(units: tuple[Any, ...], field_name: str) -> int:
    return sum(
        1
        for unit in units
        if _nonnegative_int(_read_value(unit, field_name)) > 0
    )


def _read_value(row: Any, *names: str) -> Any:
    for name in names:
        if isinstance(row, Mapping) and name in row:
            return row[name]
        keys = getattr(row, "keys", None)
        if keys is not None and name in keys():
            return row[name]
        if hasattr(row, name):
            return getattr(row, name)
    return None


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "value"):
        value = value.value
    return str(value)


def _optional_datetime(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return None


def _first_datetime(values: tuple[Any, ...]) -> datetime | None:
    datetimes = tuple(
        value
        for value in (_optional_datetime(value) for value in values)
        if value is not None
    )
    return min(datetimes) if datetimes else None


def _last_datetime(values: tuple[Any, ...]) -> datetime | None:
    datetimes = tuple(
        value
        for value in (_optional_datetime(value) for value in values)
        if value is not None
    )
    return max(datetimes) if datetimes else None


def _set_max(values: dict[str, Any], key: str, candidate: int) -> None:
    values[key] = max(_nonnegative_int(values.get(key, 0)), candidate)


def _progress_percent(completed: int, total: int) -> float | None:
    if total <= 0:
        return None
    return round(min(100.0, completed / total * 100), 1)


def _eta_seconds(
    *,
    status: str,
    completed: int,
    total: int,
    started_at: datetime | None,
    now: datetime | None,
) -> float | None:
    if status not in _ACTIVE_STATUSES or total <= 0 or completed <= 0:
        return None
    if completed >= total:
        return 0.0
    if started_at is None or now is None:
        return None
    elapsed_seconds = max(
        0.0,
        (_aware_utc(now) - _aware_utc(started_at)).total_seconds(),
    )
    if elapsed_seconds <= 0:
        return None
    return round((elapsed_seconds / completed) * (total - completed), 1)


def _status_text(value: Any) -> str:
    if value is None:
        return "unknown"
    if hasattr(value, "value"):
        value = value.value
    return str(value).strip().lower() or "unknown"


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
