from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from translator_service.admin.operations import OperationsOverview
from translator_service.admin.translation_logs import (
    TranslationRunSummary,
    list_translation_run_summaries,
)

_ACTIVE_STATUSES = {"running", "active", "translating", "processing"}
_FAILED_STATUSES = {"failed", "interrupted", "error"}


@dataclass(frozen=True)
class ServerHealthSnapshot:
    available: bool = False
    cpu_percent: float | None = None
    memory_percent: float | None = None
    memory_used_mb: float | None = None
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
    now: datetime | None = None,
    recent_limit: int = 8,
) -> LiveMonitorSnapshot:
    current_time = _aware_utc(now or datetime.now(UTC))
    runs = list_translation_run_summaries(translation_run_log_root, limit=200)
    today = current_time.date()
    one_hour_ago = current_time - timedelta(hours=1)
    queued = 0
    if operations is not None:
        queued = operations.job_counts_by_state.get("queued", 0)

    return LiveMonitorSnapshot(
        generated_at=current_time,
        active_translations=sum(1 for run in runs if run.status in _ACTIVE_STATUSES),
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
        recent_runs=tuple(runs[: max(1, int(recent_limit))]),
        server=ServerHealthSnapshot(),
    )


def _run_date(value: datetime | None):
    if value is None:
        return None
    return _aware_utc(value).date()


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
