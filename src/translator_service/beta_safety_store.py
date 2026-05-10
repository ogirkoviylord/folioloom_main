from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import RLock
from typing import Callable

from translator_service.beta_safety import (
    BETA_SAFETY_ALLOWED,
    BETA_SAFETY_GLOBAL_DAILY_CAP,
    BETA_SAFETY_GLOBAL_MONTHLY_CAP,
    BETA_SAFETY_KILL_SWITCH,
    BETA_SAFETY_RESERVATION_EXISTS,
    BetaSafetyDecision,
    BetaSafetyLimits,
    BetaSafetyRates,
    BudgetSnapshot,
    JobCostEstimate,
    decide_beta_safety,
    estimate_cost_usd,
)


RESERVATION_ACTIVE = "active"
RESERVATION_RELEASED = "released"
RESERVATION_CONSUMED = "consumed"


_SAFE_MESSAGES = {
    BETA_SAFETY_ALLOWED: "The translation can start.",
    BETA_SAFETY_KILL_SWITCH: "Translations are temporarily paused.",
    BETA_SAFETY_GLOBAL_DAILY_CAP: "Translations are temporarily limited for today.",
    BETA_SAFETY_GLOBAL_MONTHLY_CAP: "Translations are temporarily limited this month.",
    BETA_SAFETY_RESERVATION_EXISTS: "This translation is already reserved.",
}


@dataclass(frozen=True)
class BetaSafetyReservation:
    job_id: str
    user_id: str
    estimated_prompt_tokens: int
    estimated_completion_tokens: int
    estimated_cost_usd: float
    status: str
    reason: str | None
    reserved_at: datetime
    released_at: datetime | None
    consumed_at: datetime | None


@dataclass(frozen=True)
class BetaSafetyBudgetSummary:
    global_daily_reserved_usd: float = 0.0
    global_daily_consumed_usd: float = 0.0
    global_monthly_reserved_usd: float = 0.0
    global_monthly_consumed_usd: float = 0.0
    user_daily_reserved_usd: float = 0.0
    user_daily_consumed_usd: float = 0.0
    user_monthly_reserved_usd: float = 0.0
    user_monthly_consumed_usd: float = 0.0
    user_daily_active_jobs: int = 0
    user_daily_completed_work_units: int = 0

    @property
    def global_daily_total_usd(self) -> float:
        return round(
            self.global_daily_reserved_usd + self.global_daily_consumed_usd,
            6,
        )

    @property
    def global_monthly_total_usd(self) -> float:
        return round(
            self.global_monthly_reserved_usd + self.global_monthly_consumed_usd,
            6,
        )

    @property
    def user_daily_total_usd(self) -> float:
        return round(self.user_daily_reserved_usd + self.user_daily_consumed_usd, 6)

    @property
    def user_monthly_total_usd(self) -> float:
        return round(
            self.user_monthly_reserved_usd + self.user_monthly_consumed_usd,
            6,
        )

    def global_daily_remaining_usd(self, cap: float | None) -> float | None:
        return _remaining(cap, self.global_daily_total_usd)

    def global_monthly_remaining_usd(self, cap: float | None) -> float | None:
        return _remaining(cap, self.global_monthly_total_usd)

    def user_daily_remaining_usd(self, cap: float | None) -> float | None:
        return _remaining(cap, self.user_daily_total_usd)

    def user_monthly_remaining_usd(self, cap: float | None) -> float | None:
        return _remaining(cap, self.user_monthly_total_usd)


class SQLiteBetaSafetyStore:
    def __init__(self, db_path: str | Path) -> None:
        if str(db_path) != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._connection = sqlite3.connect(
            str(db_path),
            check_same_thread=False,
            isolation_level=None,
        )
        self._connection.row_factory = sqlite3.Row
        self._create_schema()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> SQLiteBetaSafetyStore:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def reserve_job(
        self,
        job_id: str,
        user_id: str,
        estimate: JobCostEstimate,
        limits: BetaSafetyLimits,
        rates: BetaSafetyRates,
        now: datetime | None = None,
    ) -> BetaSafetyDecision:
        del rates
        active_now = _utc_now(now)
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                exists = self._connection.execute(
                    """
                    SELECT 1
                    FROM beta_safety_reservations
                    WHERE job_id = ?
                    """,
                    (job_id,),
                ).fetchone()
                if exists is not None:
                    self._connection.execute("ROLLBACK")
                    return _decision(False, BETA_SAFETY_RESERVATION_EXISTS)

                budget = self._budget_snapshot_unlocked(
                    user_id=user_id,
                    now=active_now,
                )
                decision = decide_beta_safety(
                    estimate=estimate,
                    limits=limits,
                    budget=budget,
                )
                if not decision.allowed:
                    self._connection.execute("ROLLBACK")
                    return decision

                self._connection.execute(
                    """
                    INSERT INTO beta_safety_reservations (
                        job_id, user_id, estimated_prompt_tokens,
                        estimated_completion_tokens, estimated_cost_usd,
                        status, reason, reserved_at, released_at, consumed_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, NULL, ?, NULL, NULL)
                    """,
                    (
                        job_id,
                        user_id,
                        max(0, estimate.prompt_tokens),
                        max(0, estimate.completion_tokens),
                        max(0.0, estimate.estimated_cost_usd),
                        RESERVATION_ACTIVE,
                        _format_datetime(active_now),
                    ),
                )
                self._connection.execute("COMMIT")
                return decision
            except Exception:
                self._connection.execute("ROLLBACK")
                raise

    def release_job(
        self,
        job_id: str,
        reason: str,
        now: datetime | None = None,
    ) -> None:
        released_at = _format_datetime(_utc_now(now))
        with self._lock:
            self._connection.execute(
                """
                UPDATE beta_safety_reservations
                SET status = ?, reason = ?, released_at = ?
                WHERE job_id = ? AND status = ?
                """,
                (
                    RESERVATION_RELEASED,
                    reason,
                    released_at,
                    job_id,
                    RESERVATION_ACTIVE,
                ),
            )

    def record_work_unit_usage(
        self,
        job_id: str,
        user_id: str,
        work_unit_id: str,
        prompt_tokens: int,
        completion_tokens: int,
        rates: BetaSafetyRates,
        now: datetime | None = None,
    ) -> None:
        recorded_at = _format_datetime(_utc_now(now))
        cost_usd = estimate_cost_usd(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            rates=rates,
        )
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                self._connection.execute(
                    """
                    INSERT OR IGNORE INTO beta_safety_usage_events (
                        work_unit_id, job_id, user_id, prompt_tokens,
                        completion_tokens, cost_usd, recorded_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        work_unit_id,
                        job_id,
                        user_id,
                        max(0, prompt_tokens),
                        max(0, completion_tokens),
                        cost_usd,
                        recorded_at,
                    ),
                )
                self._connection.execute("COMMIT")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise

    def mark_job_consumed(
        self,
        job_id: str,
        now: datetime | None = None,
    ) -> None:
        consumed_at = _format_datetime(_utc_now(now))
        with self._lock:
            self._connection.execute(
                """
                UPDATE beta_safety_reservations
                SET status = ?, consumed_at = ?
                WHERE job_id = ? AND status = ?
                """,
                (
                    RESERVATION_CONSUMED,
                    consumed_at,
                    job_id,
                    RESERVATION_ACTIVE,
                ),
            )

    def get_reservation(self, job_id: str) -> BetaSafetyReservation | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT *
                FROM beta_safety_reservations
                WHERE job_id = ?
                """,
                (job_id,),
            ).fetchone()
        if row is None:
            return None
        return _reservation_from_row(row)

    def get_budget_summary(
        self,
        user_id: str | None = None,
        now: datetime | None = None,
    ) -> BetaSafetyBudgetSummary:
        with self._lock:
            return self._budget_summary_unlocked(user_id=user_id, now=_utc_now(now))

    def can_start_new_work(
        self,
        limits: BetaSafetyLimits,
        now: datetime | None = None,
    ) -> BetaSafetyDecision:
        if limits.translations_paused:
            return _decision(False, BETA_SAFETY_KILL_SWITCH)

        summary = self.get_budget_summary(now=now)
        if _cap_reached(summary.global_daily_total_usd, limits.global_daily_cost_cap_usd):
            return _decision(False, BETA_SAFETY_GLOBAL_DAILY_CAP)
        if _cap_reached(
            summary.global_monthly_total_usd,
            limits.global_monthly_cost_cap_usd,
        ):
            return _decision(False, BETA_SAFETY_GLOBAL_MONTHLY_CAP)
        return _decision(True, BETA_SAFETY_ALLOWED)

    def _create_schema(self) -> None:
        with self._lock:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS beta_safety_reservations (
                    job_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    estimated_prompt_tokens INTEGER NOT NULL,
                    estimated_completion_tokens INTEGER NOT NULL,
                    estimated_cost_usd REAL NOT NULL,
                    status TEXT NOT NULL,
                    reason TEXT,
                    reserved_at TEXT NOT NULL,
                    released_at TEXT,
                    consumed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS beta_safety_usage_events (
                    work_unit_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    prompt_tokens INTEGER NOT NULL,
                    completion_tokens INTEGER NOT NULL,
                    cost_usd REAL NOT NULL,
                    recorded_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_beta_safety_reservations_user_status
                    ON beta_safety_reservations(user_id, status, reserved_at);

                CREATE INDEX IF NOT EXISTS idx_beta_safety_usage_user_recorded
                    ON beta_safety_usage_events(user_id, recorded_at);
                """
            )

    def _budget_snapshot_unlocked(
        self,
        *,
        user_id: str,
        now: datetime,
    ) -> BudgetSnapshot:
        summary = self._budget_summary_unlocked(user_id=user_id, now=now)
        return BudgetSnapshot(
            global_daily_reserved_usd=summary.global_daily_reserved_usd,
            global_daily_consumed_usd=summary.global_daily_consumed_usd,
            global_monthly_reserved_usd=summary.global_monthly_reserved_usd,
            global_monthly_consumed_usd=summary.global_monthly_consumed_usd,
            user_daily_reserved_usd=summary.user_daily_reserved_usd,
            user_daily_consumed_usd=summary.user_daily_consumed_usd,
            user_monthly_reserved_usd=summary.user_monthly_reserved_usd,
            user_monthly_consumed_usd=summary.user_monthly_consumed_usd,
            user_daily_active_jobs=summary.user_daily_active_jobs,
        )

    def _budget_summary_unlocked(
        self,
        *,
        user_id: str | None,
        now: datetime,
    ) -> BetaSafetyBudgetSummary:
        day_start, day_end = _utc_day_range(now)
        month_start, month_end = _utc_month_range(now)

        global_daily_reserved = self._sum_reserved_unlocked(day_start, day_end)
        global_monthly_reserved = self._sum_reserved_unlocked(month_start, month_end)
        global_daily_consumed = self._sum_consumed_unlocked(day_start, day_end)
        global_monthly_consumed = self._sum_consumed_unlocked(month_start, month_end)

        if user_id is None:
            return BetaSafetyBudgetSummary(
                global_daily_reserved_usd=global_daily_reserved,
                global_daily_consumed_usd=global_daily_consumed,
                global_monthly_reserved_usd=global_monthly_reserved,
                global_monthly_consumed_usd=global_monthly_consumed,
            )

        return BetaSafetyBudgetSummary(
            global_daily_reserved_usd=global_daily_reserved,
            global_daily_consumed_usd=global_daily_consumed,
            global_monthly_reserved_usd=global_monthly_reserved,
            global_monthly_consumed_usd=global_monthly_consumed,
            user_daily_reserved_usd=self._sum_reserved_unlocked(
                day_start,
                day_end,
                user_id=user_id,
            ),
            user_daily_consumed_usd=self._sum_consumed_unlocked(
                day_start,
                day_end,
                user_id=user_id,
            ),
            user_monthly_reserved_usd=self._sum_reserved_unlocked(
                month_start,
                month_end,
                user_id=user_id,
            ),
            user_monthly_consumed_usd=self._sum_consumed_unlocked(
                month_start,
                month_end,
                user_id=user_id,
            ),
            user_daily_active_jobs=self._count_active_jobs_unlocked(
                day_start,
                day_end,
                user_id=user_id,
            ),
            user_daily_completed_work_units=self._count_work_units_unlocked(
                day_start,
                day_end,
                user_id=user_id,
            ),
        )

    def _sum_reserved_unlocked(
        self,
        start: datetime,
        end: datetime,
        *,
        user_id: str | None = None,
    ) -> float:
        where = [
            "status = ?",
            "reserved_at >= ?",
            "reserved_at < ?",
        ]
        params: list[object] = [
            RESERVATION_ACTIVE,
            _format_datetime(start),
            _format_datetime(end),
        ]
        if user_id is not None:
            where.append("user_id = ?")
            params.append(user_id)
        row = self._connection.execute(
            f"""
            SELECT COALESCE(SUM(estimated_cost_usd), 0.0) AS total
            FROM beta_safety_reservations
            WHERE {" AND ".join(where)}
            """,
            params,
        ).fetchone()
        return _rounded(row["total"])

    def _sum_consumed_unlocked(
        self,
        start: datetime,
        end: datetime,
        *,
        user_id: str | None = None,
    ) -> float:
        where = [
            "recorded_at >= ?",
            "recorded_at < ?",
        ]
        params: list[object] = [_format_datetime(start), _format_datetime(end)]
        if user_id is not None:
            where.append("user_id = ?")
            params.append(user_id)
        row = self._connection.execute(
            f"""
            SELECT COALESCE(SUM(cost_usd), 0.0) AS total
            FROM beta_safety_usage_events
            WHERE {" AND ".join(where)}
            """,
            params,
        ).fetchone()
        return _rounded(row["total"])

    def _count_active_jobs_unlocked(
        self,
        start: datetime,
        end: datetime,
        *,
        user_id: str,
    ) -> int:
        row = self._connection.execute(
            """
            SELECT COUNT(*) AS total
            FROM beta_safety_reservations
            WHERE user_id = ?
                AND status = ?
                AND reserved_at >= ?
                AND reserved_at < ?
            """,
            (
                user_id,
                RESERVATION_ACTIVE,
                _format_datetime(start),
                _format_datetime(end),
            ),
        ).fetchone()
        return int(row["total"])

    def _count_work_units_unlocked(
        self,
        start: datetime,
        end: datetime,
        *,
        user_id: str,
    ) -> int:
        row = self._connection.execute(
            """
            SELECT COUNT(*) AS total
            FROM beta_safety_usage_events
            WHERE user_id = ?
                AND recorded_at >= ?
                AND recorded_at < ?
            """,
            (user_id, _format_datetime(start), _format_datetime(end)),
        ).fetchone()
        return int(row["total"])


class ConfiguredBetaSafetyGuard:
    def __init__(
        self,
        *,
        store: SQLiteBetaSafetyStore,
        limits_loader: Callable[[], BetaSafetyLimits],
        rates_loader: Callable[[], BetaSafetyRates],
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._limits_loader = limits_loader
        self._rates_loader = rates_loader
        self._now_provider = now_provider

    def can_start_new_work(self) -> BetaSafetyDecision:
        return self._store.can_start_new_work(
            limits=self._limits_loader(),
            now=self._now(),
        )

    def reserve_job(
        self,
        *,
        job_id: str,
        user_id: str,
        estimate: JobCostEstimate,
    ) -> BetaSafetyDecision:
        return self._store.reserve_job(
            job_id=job_id,
            user_id=user_id,
            estimate=estimate,
            limits=self._limits_loader(),
            rates=self._rates_loader(),
            now=self._now(),
        )

    def release_job(self, *, job_id: str, reason: str) -> None:
        self._store.release_job(
            job_id=job_id,
            reason=reason,
            now=self._now(),
        )

    def record_work_unit_usage(
        self,
        *,
        job_id: str,
        user_id: str,
        work_unit_id: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> None:
        self._store.record_work_unit_usage(
            job_id=job_id,
            user_id=user_id,
            work_unit_id=work_unit_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            rates=self._rates_loader(),
            now=self._now(),
        )

    def _now(self) -> datetime | None:
        if self._now_provider is None:
            return None
        return self._now_provider()


def _reservation_from_row(row: sqlite3.Row) -> BetaSafetyReservation:
    return BetaSafetyReservation(
        job_id=row["job_id"],
        user_id=row["user_id"],
        estimated_prompt_tokens=row["estimated_prompt_tokens"],
        estimated_completion_tokens=row["estimated_completion_tokens"],
        estimated_cost_usd=row["estimated_cost_usd"],
        status=row["status"],
        reason=row["reason"],
        reserved_at=_parse_datetime(row["reserved_at"]),
        released_at=_parse_optional_datetime(row["released_at"]),
        consumed_at=_parse_optional_datetime(row["consumed_at"]),
    )


def _utc_now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(UTC)
    if now.tzinfo is None:
        return now.replace(tzinfo=UTC)
    return now.astimezone(UTC)


def _format_datetime(value: datetime) -> str:
    return _utc_now(value).isoformat()


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


def _parse_optional_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    return _parse_datetime(value)


def _utc_day_range(now: datetime) -> tuple[datetime, datetime]:
    start = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def _utc_month_range(now: datetime) -> tuple[datetime, datetime]:
    start = now.astimezone(UTC).replace(
        day=1,
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


def _decision(allowed: bool, reason_code: str) -> BetaSafetyDecision:
    return BetaSafetyDecision(
        allowed=allowed,
        reason_code=reason_code,
        safe_message=_SAFE_MESSAGES[reason_code],
    )


def _cap_reached(total: float, cap: float | None) -> bool:
    if cap is None:
        return False
    return total >= cap


def _remaining(cap: float | None, total: float) -> float | None:
    if cap is None:
        return None
    return round(max(0.0, cap - total), 6)


def _rounded(value: object) -> float:
    return round(float(value or 0.0), 6)
