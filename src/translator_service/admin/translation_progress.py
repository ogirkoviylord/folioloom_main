from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from translator_service.admin.operations import OperationsOverview
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


def overlay_translation_run_summaries(
    summaries: tuple[TranslationRunSummary, ...],
    *,
    operations: OperationsOverview | None,
    now: datetime | None = None,
) -> tuple[TranslationRunSummary, ...]:
    if operations is None:
        return summaries
    jobs_by_id = _jobs_by_id(operations)
    return tuple(
        _overlay_summary(summary, jobs_by_id.get(summary.job_id), now=now)
        for summary in summaries
    )


def overlay_translation_run_details(
    details: TranslationRunDetails,
    *,
    operations: OperationsOverview | None,
    now: datetime | None = None,
) -> TranslationRunDetails:
    if operations is None:
        return details
    job = _jobs_by_id(operations).get(details.summary.job_id)
    if job is None:
        return details
    summary = _overlay_summary(details.summary, job, now=now)
    totals = _overlay_totals(details.totals, job)
    if summary == details.summary and totals == details.totals:
        return details
    return replace(details, summary=summary, totals=totals)


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
    displayed_total = max(summary.total_fragment_count, total_units, displayed_completed)
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


def _overlay_totals(totals: dict[str, Any], job: Any) -> dict[str, Any]:
    updated = dict(totals)
    prompt_tokens = _nonnegative_int(getattr(job, "prompt_tokens", 0))
    completion_tokens = _nonnegative_int(getattr(job, "completion_tokens", 0))
    total_tokens = _nonnegative_int(getattr(job, "total_tokens", 0))
    _set_max(updated, "prompt_tokens", prompt_tokens)
    _set_max(updated, "completion_tokens", completion_tokens)
    _set_max(updated, "total_tokens", total_tokens)
    return updated


def _jobs_by_id(operations: OperationsOverview) -> dict[str, Any]:
    return {job.id: job for job in operations.jobs if getattr(job, "id", "")}


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
