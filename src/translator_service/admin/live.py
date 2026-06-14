from __future__ import annotations

import logging
import shutil
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from translator_service.admin.operations import OperationsOverview
from translator_service.admin.translation_logs import (
    TranslationRunSummary,
    list_translation_run_summaries,
)
from translator_service.admin.translation_progress import (
    DurableTranslationProgressSnapshot,
    overlay_translation_run_summaries,
)

logger = logging.getLogger(__name__)

_ACTIVE_STATUSES = {
    "active",
    "cancel_requested",
    "in_progress",
    "processing",
    "running",
    "started",
    "translating",
}
_FAILED_STATUSES = {"failed", "interrupted", "error"}
_TERMINAL_OPERATION_STATES = {"succeeded", "failed", "cancelled"}
_TERMINAL_OPERATION_STATUSES = {
    "canceled",
    "cancelled",
    "cached",
    "complete",
    "completed",
    "deleted",
    "expired",
    "failed",
    "failed_terminal",
    "interrupted",
    "partial",
    "ready",
    "skipped",
    "success",
    "succeeded",
    "translated",
}
_AUTO_PSUTIL = object()


@dataclass(frozen=True)
class ServerHealthSnapshot:
    available: bool = False
    cpu_percent: float | None = None
    memory_percent: float | None = None
    memory_used_mb: float | None = None
    memory_total_mb: float | None = None
    disk_percent: float | None = None
    disk_used_gb: float | None = None
    disk_total_gb: float | None = None
    uptime_seconds: float | None = None


@dataclass(frozen=True)
class LiveMonitorSnapshot:
    generated_at: datetime
    active_translations: int
    queued_translations: int
    failed_today: int
    tokens_today: int
    tokens_last_hour: int
    recent_runs: tuple[TranslationRunSummary, ...]
    server: ServerHealthSnapshot


def build_live_monitor_snapshot(
    translation_run_log_root: str | Path,
    *,
    operations: OperationsOverview | None = None,
    progress_snapshots: dict[str, DurableTranslationProgressSnapshot] | None = None,
    runtime_statuses: tuple[Any, ...] = (),
    now: datetime | None = None,
    recent_limit: int = 8,
    server: ServerHealthSnapshot | None = None,
) -> LiveMonitorSnapshot:
    current_time = _aware_utc(now or datetime.now(UTC))
    runs = list_translation_run_summaries(
        translation_run_log_root,
        limit=200,
        now=current_time,
    )
    today = current_time.date()
    one_hour_ago = current_time - timedelta(hours=1)
    queued = 0
    running_job_ids: set[str] = set()
    terminal_job_ids: set[str] = set()
    if operations is not None:
        queued = operations.job_counts_by_state.get("queued", 0)
        running_job_ids = {
            job.id for job in operations.jobs if job.state in _ACTIVE_STATUSES
        }
        terminal_job_ids = {
            job.id for job in operations.jobs if _is_terminal_operation_job(job)
        }
    live_runs = tuple(
        run
        for run in runs
        if run.status in _ACTIVE_STATUSES and run.job_id not in terminal_job_ids
    )
    active_run_job_ids = {
        run.job_id for run in live_runs if run.job_id
    }
    active_runs_without_job_id = sum(
        1 for run in live_runs if not run.job_id
    )
    recent_runs = _recent_live_runs(
        live_runs,
        operations=operations,
        logged_job_ids=active_run_job_ids,
        limit=max(1, int(recent_limit)),
        now=current_time,
    )
    recent_runs = overlay_translation_run_summaries(
        recent_runs,
        operations=None,
        progress_snapshots=progress_snapshots,
        now=current_time,
    )
    resource_usage = _resource_usage_from_runtime_statuses(runtime_statuses)
    recent_runs = tuple(
        replace(run, resource_usage=resource_usage) for run in recent_runs
    )

    return LiveMonitorSnapshot(
        generated_at=current_time,
        active_translations=len(active_run_job_ids | running_job_ids)
        + active_runs_without_job_id,
        queued_translations=queued,
        failed_today=sum(
            1
            for run in runs
            if run.status in _FAILED_STATUSES and _run_date(run.started_at) == today
        ),
        tokens_today=sum(
            run.total_tokens for run in runs if _run_date(run.started_at) == today
        ),
        tokens_last_hour=sum(
            run.total_tokens
            for run in runs
            if run.started_at is not None and _aware_utc(run.started_at) >= one_hour_ago
        ),
        recent_runs=recent_runs,
        server=server if server is not None else collect_local_server_health(),
    )


def _recent_live_runs(
    live_runs: tuple[TranslationRunSummary, ...],
    *,
    operations: OperationsOverview | None,
    logged_job_ids: set[str],
    limit: int,
    now: datetime,
) -> tuple[TranslationRunSummary, ...]:
    operation_summaries_by_job_id: dict[str, TranslationRunSummary] = {}
    operation_runs = ()
    if operations is not None:
        operation_summaries = tuple(
            _summary_from_operation_job(job, now=now)
            for job in operations.jobs
            if job.state in _ACTIVE_STATUSES
        )
        operation_summaries_by_job_id = {
            summary.job_id: summary for summary in operation_summaries if summary.job_id
        }
        live_runs = tuple(
            _merge_run_with_operation_progress(
                run,
                operation_summaries_by_job_id.get(run.job_id),
            )
            for run in live_runs
        )
        operation_runs = tuple(
            summary
            for summary in operation_summaries
            if summary.job_id not in logged_job_ids
        )

    rows = (*live_runs, *operation_runs)
    rows = tuple(
        sorted(
            rows,
            key=lambda run: run.last_event_at or run.started_at or datetime.min,
            reverse=True,
        )
    )
    return rows[:limit]


def _merge_run_with_operation_progress(
    run: TranslationRunSummary,
    operation: TranslationRunSummary | None,
) -> TranslationRunSummary:
    if operation is None:
        return run
    if operation.total_fragment_count <= 0 and operation.fragment_count <= 0:
        return run
    return replace(
        run,
        status=operation.status or run.status,
        fragment_count=operation.fragment_count,
        total_fragment_count=max(
            run.total_fragment_count,
            operation.total_fragment_count,
        ),
        progress_percent=operation.progress_percent,
        eta_seconds=operation.eta_seconds,
        current_stage=operation.current_stage or run.current_stage,
        last_event_at=operation.last_event_at or run.last_event_at,
        total_tokens=max(run.total_tokens, operation.total_tokens),
        error_message=operation.error_message or run.error_message,
    )


def _is_terminal_operation_job(job: Any) -> bool:
    return _status_text(getattr(job, "state", None)) in _TERMINAL_OPERATION_STATES or (
        _status_text(getattr(job, "raw_status", None)) in _TERMINAL_OPERATION_STATUSES
    )


def _summary_from_operation_job(
    job,
    *,
    now: datetime | None = None,
) -> TranslationRunSummary:
    total_units = max(0, int(job.total_units))
    completed_units = max(0, int(job.completed_units))
    total_tokens = max(0, int(job.total_tokens))
    started_at = job.started_at or job.created_at
    status = _status_text(job.raw_status or job.state)
    return TranslationRunSummary(
        job_id=job.id,
        status=status,
        started_at=started_at,
        finished_at=job.completed_at,
        order_id=job.order_id,
        user_id=None,
        file_name=job.file_name,
        document_kind=job.document_kind,
        source_language=job.source_language,
        target_language=job.target_language,
        translator_model=None,
        result_file_name=None,
        error_message=job.error_excerpt,
        fragment_count=completed_units,
        total_fragment_count=total_units,
        progress_percent=_operation_progress_percent(completed_units, total_units),
        eta_seconds=_operation_eta_seconds(
            status=status,
            completed=completed_units,
            total=total_units,
            started_at=started_at,
            now=now,
        ),
        current_stage=status,
        last_event_at=job.updated_at,
        total_tokens=total_tokens,
        elapsed_seconds=0.0,
        run_dir="",
    )


def _resource_usage_from_runtime_statuses(
    runtime_statuses: tuple[Any, ...],
) -> dict[str, Any]:
    status = next(
        (
            item
            for item in runtime_statuses
            if getattr(item, "provider_id", None) == "deepseek"
        ),
        None,
    )
    if status is None:
        return {}
    channels = tuple(getattr(status, "active_channels", ()) or ())
    provider_state = getattr(status, "provider_state", None)
    parallel_capacity = sum(
        max(1, int(getattr(channel, "max_parallel_requests", 1) or 1))
        for channel in channels
    )
    active_requests = sum(
        max(0, int(getattr(channel, "active_requests", 0) or 0))
        for channel in channels
    )
    return {
        "provider": "deepseek",
        "active_key_channels": len(channels),
        "active_requests": active_requests,
        "parallel_capacity": parallel_capacity,
        "busy_channels": sum(
            1
            for channel in channels
            if int(getattr(channel, "active_requests", 0) or 0)
            >= int(getattr(channel, "max_parallel_requests", 1) or 1)
        ),
        "cooling_down_channels": sum(
            1
            for channel in channels
            if str(getattr(channel, "health", "")).lower() == "cooling_down"
        ),
        "degraded_channels": sum(
            1
            for channel in channels
            if str(getattr(channel, "health", "")).lower()
            in {"cooling_down", "degraded"}
        ),
        "unsafe_model_output_failures": sum(
            max(0, int(getattr(channel, "total_unsafe_model_output_failures", 0) or 0))
            for channel in channels
        ),
        "available_provider_slots": (
            max(0, int(getattr(provider_state, "available_slots", 0) or 0))
            if provider_state is not None
            else None
        ),
        "adaptive_current_limit": (
            max(0, int(getattr(provider_state, "current_limit", 0) or 0))
            if provider_state is not None
            else None
        ),
        "adaptive_max_capacity": (
            max(0, int(getattr(provider_state, "max_capacity", 0) or 0))
            if provider_state is not None
            else None
        ),
    }


def collect_local_server_health(
    *,
    disk_path: str | Path = "/",
    disk_usage: Callable[[str | Path], Any] = shutil.disk_usage,
    psutil_module: Any = _AUTO_PSUTIL,
    now: Callable[[], datetime] | None = None,
) -> ServerHealthSnapshot:
    psutil = _load_psutil() if psutil_module is _AUTO_PSUTIL else psutil_module
    cpu_percent = None
    memory_percent = None
    memory_used_mb = None
    memory_total_mb = None
    uptime_seconds = None
    disk_percent = None
    disk_used_gb = None
    disk_total_gb = None

    if psutil is not None:
        try:
            cpu_percent = _round_metric(psutil.cpu_percent(interval=None))
        except Exception:
            logger.debug("Failed to read CPU percent", exc_info=True)
            cpu_percent = None
        try:
            memory = psutil.virtual_memory()
            memory_percent = _round_metric(memory.percent)
            memory_used_mb = _bytes_to_mb(memory.used)
            memory_total_mb = _bytes_to_mb(memory.total)
        except Exception:
            logger.debug("Failed to read memory metrics", exc_info=True)
            memory_percent = None
            memory_used_mb = None
            memory_total_mb = None
        try:
            current_time = now() if now is not None else datetime.now(UTC)
            boot_time = datetime.fromtimestamp(float(psutil.boot_time()), tz=UTC)
            uptime_seconds = max(
                0.0,
                (_aware_utc(current_time) - boot_time).total_seconds(),
            )
        except Exception:
            logger.debug("Failed to read uptime", exc_info=True)
            uptime_seconds = None

    try:
        disk = disk_usage(disk_path)
        disk_percent = _round_metric((float(disk.used) / float(disk.total)) * 100)
        disk_used_gb = _bytes_to_gb(disk.used)
        disk_total_gb = _bytes_to_gb(disk.total)
    except Exception:
        logger.debug("Failed to read disk metrics", exc_info=True)
        disk_percent = None
        disk_used_gb = None
        disk_total_gb = None

    return ServerHealthSnapshot(
        available=any(
            value is not None
            for value in (
                cpu_percent,
                memory_percent,
                memory_used_mb,
                memory_total_mb,
                disk_percent,
                disk_used_gb,
                disk_total_gb,
                uptime_seconds,
            )
        ),
        cpu_percent=cpu_percent,
        memory_percent=memory_percent,
        memory_used_mb=memory_used_mb,
        memory_total_mb=memory_total_mb,
        disk_percent=disk_percent,
        disk_used_gb=disk_used_gb,
        disk_total_gb=disk_total_gb,
        uptime_seconds=uptime_seconds,
    )


def _run_date(value: datetime | None):
    if value is None:
        return None
    return _aware_utc(value).date()


def _operation_progress_percent(completed: int, total: int) -> float | None:
    if total <= 0:
        return None
    return round((completed / total) * 100, 1)


def _operation_eta_seconds(
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


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _load_psutil() -> Any:
    try:
        import psutil
    except ImportError:
        return None
    return psutil


def _round_metric(value: Any) -> float:
    return round(float(value), 1)


def _bytes_to_mb(value: Any) -> float:
    return round(float(value) / 1024 / 1024, 1)


def _bytes_to_gb(value: Any) -> float:
    return round(float(value) / 1024 / 1024 / 1024, 1)
