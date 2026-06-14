from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, tzinfo
from pathlib import Path
from typing import Any

from translator_service.json_utils import read_json_file


@dataclass(frozen=True)
class CostRates:
    input_usd_per_million: float = 0.28
    output_usd_per_million: float = 1.10


@dataclass(frozen=True)
class CostRunSummary:
    job_id: str
    order_id: str | None
    user_id: str | None
    file_name: str
    started_at: datetime | None
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: float
    log_href: str
    usage_available: bool = True


@dataclass(frozen=True)
class CostUsageTotals:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass(frozen=True)
class CostUserSummary:
    user_id: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: float


@dataclass(frozen=True)
class BetaSafetyCostSummary:
    global_daily_cap_usd: float | None
    global_monthly_cap_usd: float | None
    global_daily_reserved_usd: float
    global_daily_consumed_usd: float
    global_daily_remaining_usd: float | None
    global_monthly_reserved_usd: float
    global_monthly_consumed_usd: float
    global_monthly_remaining_usd: float | None
    translations_paused: bool
    warning: bool
    warning_reason: str


@dataclass(frozen=True)
class CostAnalytics:
    tokens_today: int
    tokens_last_7_days: int
    tokens_month_to_date: int
    estimated_cost_today_usd: float
    estimated_cost_last_7_days_usd: float
    estimated_cost_month_to_date_usd: float
    top_runs: tuple[CostRunSummary, ...]
    top_users: tuple[CostUserSummary, ...]
    beta_safety: BetaSafetyCostSummary | None = None
    unavailable_run_count: int = 0


def build_cost_analytics(
    log_root: str | Path,
    *,
    now: datetime | None = None,
    rates: CostRates | None = None,
    limit: int = 5,
    usage_lookup: Callable[[str], object | None] | None = None,
) -> CostAnalytics:
    current = _current_reporting_time(now)
    reporting_tz = current.tzinfo or UTC
    active_rates = rates or CostRates()
    today = current.date()
    last_7_start = today - timedelta(days=6)
    month = (today.year, today.month)
    all_runs = _read_runs(log_root, active_rates, usage_lookup=usage_lookup)
    runs = [run for run in all_runs if run.usage_available]
    run_dates = {
        run: _reporting_date(run.started_at, reporting_tz) for run in runs
    }

    today_runs = [
        run for run in runs if run_dates[run] and run_dates[run] == today
    ]
    last_7_runs = [
        run
        for run in runs
        if run_dates[run] and last_7_start <= run_dates[run] <= today
    ]
    month_runs = [
        run
        for run in runs
        if run_dates[run]
        and (run_dates[run].year, run_dates[run].month) == month
        and run_dates[run] <= today
    ]
    top_limit = max(0, int(limit))
    top_runs = sorted(
        runs,
        key=lambda run: (
            -run.estimated_cost_usd,
            -_sort_timestamp(run.started_at),
            run.job_id,
        ),
    )[:top_limit]
    top_users = _top_users(runs, limit=top_limit)
    return CostAnalytics(
        tokens_today=sum(run.total_tokens for run in today_runs),
        tokens_last_7_days=sum(run.total_tokens for run in last_7_runs),
        tokens_month_to_date=sum(run.total_tokens for run in month_runs),
        estimated_cost_today_usd=_round_cost(
            sum(run.estimated_cost_usd for run in today_runs)
        ),
        estimated_cost_last_7_days_usd=_round_cost(
            sum(run.estimated_cost_usd for run in last_7_runs)
        ),
        estimated_cost_month_to_date_usd=_round_cost(
            sum(run.estimated_cost_usd for run in month_runs)
        ),
        top_runs=tuple(top_runs),
        top_users=top_users,
        unavailable_run_count=len(all_runs) - len(runs),
    )


def build_beta_safety_cost_summary(summary, limits) -> BetaSafetyCostSummary:
    daily_remaining = summary.global_daily_remaining_usd(
        limits.global_daily_cost_cap_usd,
    )
    monthly_remaining = summary.global_monthly_remaining_usd(
        limits.global_monthly_cost_cap_usd,
    )
    warning_reason = _beta_safety_warning_reason(
        daily_total=summary.global_daily_total_usd,
        daily_cap=limits.global_daily_cost_cap_usd,
        monthly_total=summary.global_monthly_total_usd,
        monthly_cap=limits.global_monthly_cost_cap_usd,
        warning_fraction=limits.warning_fraction,
        paused=limits.translations_paused,
    )
    return BetaSafetyCostSummary(
        global_daily_cap_usd=limits.global_daily_cost_cap_usd,
        global_monthly_cap_usd=limits.global_monthly_cost_cap_usd,
        global_daily_reserved_usd=summary.global_daily_reserved_usd,
        global_daily_consumed_usd=summary.global_daily_consumed_usd,
        global_daily_remaining_usd=daily_remaining,
        global_monthly_reserved_usd=summary.global_monthly_reserved_usd,
        global_monthly_consumed_usd=summary.global_monthly_consumed_usd,
        global_monthly_remaining_usd=monthly_remaining,
        translations_paused=limits.translations_paused,
        warning=bool(warning_reason),
        warning_reason=warning_reason,
    )


def _beta_safety_warning_reason(
    *,
    daily_total: float,
    daily_cap: float | None,
    monthly_total: float,
    monthly_cap: float | None,
    warning_fraction: float,
    paused: bool,
) -> str:
    if paused:
        return "paused"
    fraction = min(1.0, max(0.0, warning_fraction))
    if _near_or_over_cap(daily_total, daily_cap, fraction):
        return "global_daily_cap"
    if _near_or_over_cap(monthly_total, monthly_cap, fraction):
        return "global_monthly_cap"
    return ""


def _near_or_over_cap(total: float, cap: float | None, fraction: float) -> bool:
    if cap is None:
        return False
    if cap <= 0:
        return True
    return total >= cap * fraction


def _read_runs(
    log_root: str | Path,
    rates: CostRates,
    *,
    usage_lookup: Callable[[str], object | None] | None,
) -> list[CostRunSummary]:
    root = Path(log_root)
    if not root.exists():
        return []
    runs: list[CostRunSummary] = []
    for run_json in root.glob("*/run.json"):
        run = _read_run(run_json, rates, usage_lookup=usage_lookup)
        if run is not None:
            runs.append(run)
    return runs


def _read_run(
    run_json: Path,
    rates: CostRates,
    *,
    usage_lookup: Callable[[str], object | None] | None,
) -> CostRunSummary | None:
    try:
        data = read_json_file(run_json)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    totals = data.get("totals")
    if not isinstance(totals, dict):
        totals = {}
    job_id = _string(data.get("job_id"), fallback=run_json.parent.name)
    prompt_tokens = _int(totals.get("prompt_tokens"))
    completion_tokens = _int(totals.get("completion_tokens"))
    total_tokens = _int(totals.get("total_tokens")) or (
        prompt_tokens + completion_tokens
    )
    usage = _lookup_usage(job_id, usage_lookup)
    if usage is not None and usage.total_tokens > 0:
        prompt_tokens = usage.prompt_tokens
        completion_tokens = usage.completion_tokens
        total_tokens = usage.total_tokens
    return CostRunSummary(
        job_id=job_id,
        order_id=_optional_string(data.get("order_id")),
        user_id=_optional_string(data.get("user_id")),
        file_name=_string(data.get("file_name"), fallback="unknown"),
        started_at=_parse_datetime(data.get("started_at")),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        estimated_cost_usd=_estimate_cost(prompt_tokens, completion_tokens, rates),
        log_href="/admin/logs",
        usage_available=total_tokens > 0,
    )


def _lookup_usage(
    job_id: str,
    usage_lookup: Callable[[str], object | None] | None,
) -> CostUsageTotals | None:
    if usage_lookup is None or not job_id:
        return None
    try:
        usage = usage_lookup(job_id)
    except (LookupError, ValueError):
        return None
    if usage is None:
        return None
    prompt_tokens = _int(getattr(usage, "prompt_tokens", None))
    completion_tokens = _int(getattr(usage, "completion_tokens", None))
    total_tokens = _int(getattr(usage, "total_tokens", None)) or (
        prompt_tokens + completion_tokens
    )
    return CostUsageTotals(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
    )


def _top_users(
    runs: list[CostRunSummary],
    *,
    limit: int,
) -> tuple[CostUserSummary, ...]:
    totals: dict[str, dict[str, float | int]] = {}
    for run in runs:
        if not run.user_id:
            continue
        row = totals.setdefault(
            run.user_id,
            {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "estimated_cost_usd": 0.0,
            },
        )
        row["prompt_tokens"] += run.prompt_tokens
        row["completion_tokens"] += run.completion_tokens
        row["total_tokens"] += run.total_tokens
        row["estimated_cost_usd"] += run.estimated_cost_usd
    users = [
        CostUserSummary(
            user_id=user_id,
            prompt_tokens=int(row["prompt_tokens"]),
            completion_tokens=int(row["completion_tokens"]),
            total_tokens=int(row["total_tokens"]),
            estimated_cost_usd=_round_cost(float(row["estimated_cost_usd"])),
        )
        for user_id, row in totals.items()
    ]
    users.sort(
        key=lambda user: (-user.total_tokens, -user.estimated_cost_usd, user.user_id)
    )
    return tuple(users[:limit])


def _estimate_cost(
    prompt_tokens: int,
    completion_tokens: int,
    rates: CostRates,
) -> float:
    return _round_cost(
        prompt_tokens / 1_000_000 * rates.input_usd_per_million
        + completion_tokens / 1_000_000 * rates.output_usd_per_million
    )


def _current_reporting_time(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(UTC)
    if now.tzinfo is None:
        return now.replace(tzinfo=UTC)
    return now


def _reporting_date(value: datetime | None, reporting_tz: tzinfo):
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=reporting_tz).date()
    return value.astimezone(reporting_tz).date()


def _sort_timestamp(value: datetime | None) -> float:
    if value is None:
        return 0.0
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC).timestamp()
    return value.timestamp()


def _round_cost(value: float) -> float:
    return round(value, 6)


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _string(value: Any, *, fallback: str) -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text or fallback


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0
